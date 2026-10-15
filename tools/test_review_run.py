"""Protocol unit fixtures only: these do not constitute native DB acceptance."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import review_run as reviewer


GO_LOG = b'''=== RUN   TestDurableRecovery
    recovery_test.go:81: connection failed during outage: synthetic error
    recovery_test.go:86: write failed during outage: synthetic error
    recovery_test.go:88: row during-outage: count=0 payload=""
    recovery_test.go:35: same pool recovered after 2ms
    recovery_test.go:95: row before-outage: count=1 payload="value:before-outage"
    recovery_test.go:96: row after-outage: count=1 payload="value:after-outage"
    recovery_test.go:111: write acknowledgement lost after 3s: synthetic i/o timeout
    recovery_test.go:113: row lost-ack: count=1 payload="value:lost-ack"
    recovery_test.go:35: same pool recovered after 2ms
    recovery_test.go:124: same-key retry affected zero rows
    recovery_test.go:125: row lost-ack: count=1 payload="value:lost-ack"
--- PASS: TestDurableRecovery (3.20s)
PASS
'''


class RecordedProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.proof = self.base / "run" / "verification"
        self.proof.mkdir(parents=True)
        self.receipt = self.proof / "receipt.json"
        self.logs = {label: b"" for label in reviewer.PHASES}
        self.logs.update({"go-version": b"go version go1.27.2 linux/amd64\n",
                          "postgres-version": b"pg_ctl (PostgreSQL) 18.6\n",
                          "durability-settings": b"on|on|on\n",
                          "TestDurableRecovery": GO_LOG,
                          "durable-row-readback": ("\n".join(reviewer.FINAL_ROWS) + "\n").encode()})
        hashes = {f"components/toxiproxy/protocol-fixture-{i}": "a" * 64 for i in range(95)}
        self.saved = {"status": reviewer.SUCCESS, "synthetic_only": True,
            "public_changes": [], "provider_calls": [], "system_changes": [],
            "go_version": "go version go1.27.2 linux/amd64", "postgres_version": "pg_ctl (PostgreSQL) 18.6",
            "upstream_commit": reviewer.COMPONENT_COMMIT, "runtime_component": "components/toxiproxy",
            "protected_hashes_before": hashes, "protected_hashes_after": copy.deepcopy(hashes),
            "source_verification_after": {"status": "source_verified", "component_files": 87, "adapted_files": 8, "mode_check_enabled": False, "changed": []},
            "changed_protected_paths": [], "cleanup_verified": True, "listeners_final": [],
            "postgres_stopped": True, "socket_directory_removed": True,
            "postgres_pid_before_restart": 100, "postgres_pid_after_restart": 101,
            "durable_rows_after_restart": list(reviewer.FINAL_ROWS),
            "fixture": "/untrusted/secret-directory", "ports": {"postgres": 54321},
            "error": "<script>credential-secret</script>",
            "steps": [{"label": label, "args": ["/untrusted/credential-secret", "54321"],
                       "exit_code": 0, "elapsed_seconds": .1,
                       "stdout_sha256": hashlib.sha256(raw).hexdigest(),
                       "stderr_sha256": hashlib.sha256(b"").hexdigest()}
                      for label, raw in self.logs.items()]}
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        for label, raw in self.logs.items():
            (self.proof / (label + ".stdout")).write_bytes(raw)
        self.receipt.write_text(json.dumps(self.saved), encoding="utf-8")

    def inspect(self):
        return reviewer.inspect_run(self.receipt)

    def replace_log(self, label, old, new, rehash=True):
        self.logs[label] = self.logs[label].replace(old, new)
        if rehash:
            next(item for item in self.saved["steps"] if item["label"] == label)["stdout_sha256"] = hashlib.sha256(self.logs[label]).hexdigest()
        self.save()

    def test_protocol_success_is_corroborated(self):
        self.assertEqual(self.inspect()["status"], "corroborated")

    def test_edit_without_rehash_is_mismatch(self):
        self.replace_log("TestDurableRecovery", b"2ms", b"3ms", rehash=False)
        self.assertFalse(self.inspect()["checks"]["current_selected_stdout_hashes"])

    def test_refused_write_cannot_be_a_committed_write(self):
        self.replace_log("TestDurableRecovery", b'row during-outage: count=0 payload=""', b'row during-outage: count=1 payload="value:during-outage"')
        self.assertEqual(self.inspect()["status"], "failed_or_mismatch")

    def test_lost_ack_requires_timeout_and_committed_row(self):
        for old, new in ((b"synthetic i/o timeout", b"synthetic connection refused"),
                         (b'row lost-ack: count=1 payload="value:lost-ack"', b'row lost-ack: count=0 payload=""')):
            with self.subTest(old=old):
                original = self.logs["TestDurableRecovery"]
                self.replace_log("TestDurableRecovery", old, new)
                self.assertFalse(self.inspect()["checks"]["ordered_original_test_events"])
                self.logs["TestDurableRecovery"] = original
                self.saved["steps"][11]["stdout_sha256"] = hashlib.sha256(original).hexdigest()
                self.save()

    def test_retry_cannot_insert_another_row(self):
        self.replace_log("TestDurableRecovery", b"same-key retry affected zero rows", b"same-key retry affected one row")
        self.assertFalse(self.inspect()["checks"]["same_key_retry_changes_zero_rows"])

    def test_order_and_deadline_are_checked(self):
        self.replace_log("TestDurableRecovery", b"same pool recovered after 2ms", b"same pool recovered after 5s")
        self.assertFalse(self.inspect()["checks"]["ordered_original_test_events"])

    def test_final_rows_check_payload_and_receipt_and_stdout(self):
        self.saved["durable_rows_after_restart"][0] = "after-outage|different"
        self.save()
        self.assertFalse(self.inspect()["checks"]["recorded_exact_final_rows"])

    def test_rehashed_extra_readback_row_is_rejected(self):
        self.replace_log("durable-row-readback", b"\n", b"\nextra|extra\n")
        self.assertFalse(self.inspect()["checks"]["recorded_exact_final_rows"])

    def test_status_alone_and_early_failure_have_failed_view(self):
        self.saved["status"] = "failed_preserved"
        self.saved["steps"] = self.saved["steps"][:3]
        self.saved["steps"][-1]["exit_code"] = 1
        for name in ("runtime_component", "go_version", "durable_rows_after_restart", "postgres_pid_after_restart"):
            self.saved.pop(name, None)
        self.save()
        review = reviewer.write_report(self.receipt, self.base / "failed-view")
        self.assertEqual(review["status"], "failed_or_mismatch")
        self.assertIn("Recorded failure", (self.base / "failed-view/report.html").read_text())

    def test_cleanup_and_source_mutations_block_success(self):
        for name, value in (("listeners_final", ["private listener"]), ("postgres_stopped", False),
                            ("socket_directory_removed", False), ("changed_protected_paths", ["components/toxiproxy/file"])):
            with self.subTest(name=name):
                original = self.saved[name]
                self.saved[name] = value
                self.save()
                self.assertEqual(self.inspect()["status"], "failed_or_mismatch")
                self.saved[name] = original
        self.saved["protected_hashes_after"][next(iter(self.saved["protected_hashes_after"]))] = "b" * 64
        self.save()
        self.assertFalse(self.inspect()["checks"]["recorded_source_unchanged"])

    def test_wrong_types_duplicate_keys_nonfinite_and_oversize(self):
        for raw in (b'{"status":"x","status":"y"}', b'{"elapsed":NaN}', b'{"elapsed":1e999}',
                    b'{"steps":true}', b'[]', b" " * (reviewer.MAX_JSON + 1)):
            with self.subTest(raw=raw[:30]):
                self.receipt.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_boolean_exit_is_invalid(self):
        self.saved["steps"][0]["exit_code"] = False
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_step_traversal_duplicate_and_protected_absolute_paths_invalid(self):
        for label in ("../secret", "/secret", "C:\\secret", "go-version"):
            with self.subTest(label=label):
                self.saved["steps"][1]["label"] = label
                self.save()
                with self.assertRaises(ValueError):
                    self.inspect()
        self.saved["steps"][1]["label"] = "postgres-version"
        self.saved["protected_hashes_before"] = {"/secret": "a" * 64}
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_missing_selected_file_is_failed_not_green(self):
        (self.proof / "TestDurableRecovery.stdout").unlink()
        self.assertEqual(self.inspect()["status"], "failed_or_mismatch")

    @unittest.skipUnless(os.name == "posix", "Linux symlink and FIFO boundary")
    def test_symlink_fifo_and_symlink_ancestor_rejected(self):
        path = self.proof / "TestDurableRecovery.stdout"
        path.unlink()
        path.symlink_to(self.receipt)
        with self.assertRaises(ValueError):
            self.inspect()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            self.inspect()
        path.unlink()
        path.write_bytes(GO_LOG)
        alias = self.base / "alias"
        alias.symlink_to(self.base / "run", target_is_directory=True)
        with self.assertRaises(ValueError):
            reviewer.inspect_run(alias / "verification/receipt.json")

    def test_oversized_selected_stdout_is_invalid(self):
        (self.proof / "TestDurableRecovery.stdout").write_bytes(b"x" * (reviewer.MAX_LOG + 1))
        with self.assertRaises(ValueError):
            self.inspect()

    def test_output_refuses_existing_overlap_traversal(self):
        for output in (self.base / "run/review", self.base / "run", self.base,
                       self.base / "run/../review"):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    reviewer.write_report(self.receipt, output)
        existing = self.base / "existing"
        existing.mkdir()
        with self.assertRaises(ValueError):
            reviewer.write_report(self.receipt, existing)

    @unittest.skipUnless(os.name == "posix", "Linux modes and dangling symlinks")
    def test_private_modes_and_dangling_output(self):
        output = self.base / "review"
        reviewer.write_report(self.receipt, output)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        for path in output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "missing")
        with self.assertRaises(ValueError):
            reviewer.write_report(self.receipt, dangling)

    def test_exports_only_scrubbed_static_proof(self):
        output = self.base / "review"
        review = reviewer.write_report(self.receipt, output)
        self.assertEqual(set(path.name for path in output.iterdir()), {"report.html", "review.json", "selected-proof.json"})
        exported = "\n".join(path.read_text() for path in output.iterdir())
        for forbidden in ("/untrusted", "credential-secret", "54321", "value:lost-ack", "<script>", "recovery_test.go:"):
            self.assertNotIn(forbidden, exported)
        html = (output / "report.html").read_text()
        self.assertIn('tabindex="0"', html)
        self.assertIn("@media print", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertNotIn("<script", html)
        self.assertEqual(html.count('<p class="scenario-state">Corroborated</p>'), 3)
        self.assertLess(html.index('<h3>Refused write</h3>'), html.index('<summary>Current evidence checks</summary>'))
        self.assertEqual(json.loads((output / "review.json").read_text())["checks"], review["checks"])

    def test_failed_view_labels_scenarios_as_uncorroborated_conditions(self):
        self.saved["status"] = "failed_preserved"
        self.save()
        review = reviewer.write_report(self.receipt, self.base / "failed-view")
        self.assertTrue(all(review["proof"]["scenario_checks"].values()))
        self.assertFalse(review["evidence_passed"])
        html = (self.base / "failed-view/report.html").read_text()
        self.assertIn("Scenario acceptance conditions", html)
        self.assertEqual(html.count('<p class="scenario-state">Not corroborated</p>'), 3)
        self.assertEqual(html.count('<p>Required:'), 3)
        self.assertNotIn('<p class="scenario-state">Corroborated</p>', html)
        self.assertNotIn("The recorded write failed", html)
        self.assertNotIn("The client timed out", html)

    def test_cli_exit_contract(self):
        self.assertEqual(reviewer.main(["--receipt", str(self.receipt), "--output", str(self.base / "good")]), 0)
        self.saved["status"] = "failed_preserved"
        self.save()
        self.assertEqual(reviewer.main(["--receipt", str(self.receipt), "--output", str(self.base / "bad")]), 1)
        self.receipt.write_text("{broken")
        self.assertEqual(reviewer.main(["--receipt", str(self.receipt), "--output", str(self.base / "invalid")]), 2)
        self.assertFalse((self.base / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
