"""Review bounded, editable evidence from one recorded synthetic recovery run.

No database connection or recovery command is made. The layout follows the
Backup Restore Drill reviewer: current evidence checks, recorded scenario,
selected proof, then an always-visible scope statement.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from html import escape


MAX_JSON = 1_048_576
MAX_LOG = 262_144
SUCCESS = "recovery_and_keyed_retry_passed_restart_readback_verified"
COMPONENT_COMMIT = "3ccd6a79cbc6c6a72b884d295ad314b75cdf3962"
PHASES = (
    "go-version", "postgres-version", "build-copied-server",
    "component-module-verify", "build-recovery-test", "example-module-verify",
    "copied-module-path", "initdb", "postgres-start", "createdb",
    "durability-settings", "TestDurableRecovery", "postgres-restart",
    "durable-row-readback", "postgres-stop",
)
FINAL_ROWS = (
    "after-outage|value:after-outage", "before-outage|value:before-outage",
    "lost-ack|value:lost-ack",
)
SCOPE = (
    "This review reads selected local receipt and stdout files only. It makes no "
    "live database connection. The historical evidence is editable and unauthenticated; "
    "matching hashes do not authenticate it. This synthetic network-fault rehearsal "
    "does not establish backup recovery, power-loss safety, general exactly-once "
    "delivery or production readiness."
)


def _path(path, directory=False):
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Paths must not contain parent traversal")
    path = path.absolute()
    for parent in reversed(path.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError("Path ancestors must be real directories, not symlinks")
    mode = path.lstat().st_mode
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(mode):
        raise ValueError("Evidence must use regular files and real directories, not symlinks or special files")
    return path


def _read(path, limit):
    path = _path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Evidence exceeds the regular-file review limit")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Evidence exceeds the bounded review limit")
    return raw


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON keys are invalid")
        value[key] = item
    return value


def _constant(_value):
    raise ValueError("Nonfinite JSON values are invalid")


def _bounded(value, depth=0):
    if depth > 32:
        raise ValueError("JSON nesting exceeds the review limit")
    if isinstance(value, str) and len(value) > 32_768:
        raise ValueError("JSON strings exceed the review limit")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON values are invalid")
    if isinstance(value, (dict, list)):
        if len(value) > 1024:
            raise ValueError("JSON collection exceeds the review limit")
        for item in value.values() if isinstance(value, dict) else value:
            _bounded(item, depth + 1)


def _typed(value, name, expected):
    if name in value and type(value[name]) is not expected:
        raise ValueError("Invalid type in recorded " + name)


def _safe_name(name):
    return (isinstance(name, str) and bool(name) and not PurePosixPath(name).is_absolute()
            and "\\" not in name and ":" not in name
            and all(part not in ("", ".", "..") for part in name.split("/"))
            and not any(ord(char) < 32 or ord(char) == 127 for char in name))


def _hashes(value):
    if type(value) is not dict:
        raise ValueError("Recorded source hashes must be an object")
    if any(not _safe_name(name) or not isinstance(digest, str)
           or not re.fullmatch("[a-f0-9]{64}", digest) for name, digest in value.items()):
        raise ValueError("Invalid recorded source path or SHA-256")


def _schema(saved):
    if type(saved) is not dict:
        raise ValueError("The receipt must be a JSON object")
    for name in ("status", "go_version", "postgres_version", "runtime_component", "upstream_commit"):
        _typed(saved, name, str)
    for name in ("synthetic_only", "cleanup_verified", "postgres_stopped", "socket_directory_removed"):
        _typed(saved, name, bool)
    for name in ("steps", "changed_protected_paths", "listeners_final", "public_changes", "provider_calls", "system_changes"):
        _typed(saved, name, list)
    for name in ("postgres_pid_before_restart", "postgres_pid_after_restart"):
        _typed(saved, name, int)
    if "durable_rows_after_restart" in saved:
        rows = saved["durable_rows_after_restart"]
        if type(rows) is not list or any(type(row) is not str for row in rows):
            raise ValueError("Recorded final rows must be an array of strings")
    for name in ("protected_hashes_before", "protected_hashes_after"):
        if name in saved:
            _hashes(saved[name])
    for name in ("changed_protected_paths",):
        if any(not _safe_name(item) for item in saved.get(name, [])):
            raise ValueError("Invalid recorded protected path")
    source = saved.get("source_verification_after", {})
    if type(source) is not dict:
        raise ValueError("Recorded source verification must be an object")
    for name, expected in (("status", str), ("component_files", int), ("adapted_files", int),
                           ("mode_check_enabled", bool), ("changed", list)):
        _typed(source, name, expected)
    steps = saved.get("steps", [])
    labels = set()
    for step in steps:
        if type(step) is not dict or type(step.get("label")) is not str:
            raise ValueError("Invalid recorded step")
        label = step["label"]
        if not _safe_name(label) or "/" in label or label in labels:
            raise ValueError("Recorded step labels must be unique safe basenames")
        labels.add(label)
        code = step.get("exit_code")
        if type(code) is not int and code != "timeout":
            raise ValueError("Invalid recorded step exit code")
        if type(code) is bool:
            raise ValueError("Boolean exit codes are invalid")
        elapsed = step.get("elapsed_seconds")
        if type(elapsed) not in (int, float) or elapsed < 0:
            raise ValueError("Invalid recorded step duration")
        if type(step.get("args")) is not list or any(type(arg) is not str for arg in step["args"]):
            raise ValueError("Invalid recorded step arguments")
        for name in ("stdout_sha256", "stderr_sha256"):
            if type(step.get(name)) is not str or not re.fullmatch("[a-f0-9]{64}", step[name]):
                raise ValueError("Invalid recorded step SHA-256")


def _duration(text):
    pieces = re.findall(r"(\d+(?:\.\d+)?)(ms|us|µs|ns|h|m|s)", text)
    if "".join(number + unit for number, unit in pieces) != text or not pieces:
        return None
    factors = {"h": 3600, "m": 60, "s": 1, "ms": .001, "us": .000001, "µs": .000001, "ns": .000000001}
    return sum(float(number) * factors[unit] for number, unit in pieces)


def _scenario(raw):
    text = raw.decode("utf-8", errors="strict")
    events = []
    for line in text.splitlines():
        match = re.match(r"\s+recovery_test\.go:\d+: (.*)$", line)
        if not match:
            continue
        message = match[1]
        if re.fullmatch(r"connection failed during outage: .+", message):
            events.append("connection_refused")
        elif re.fullmatch(r"write failed during outage: .+", message):
            events.append("write_refused")
        elif message.startswith("same pool recovered after "):
            duration = _duration(message.removeprefix("same pool recovered after "))
            events.append("pool_recovered" if duration is not None and duration < 5 else "invalid")
        elif re.fullmatch(r"write acknowledgement lost after [0-9.a-zµ]+: .*(?:timeout|deadline exceeded).*", message):
            events.append("ack_timeout")
        elif message == "same-key retry affected zero rows":
            events.append("retry_zero")
        elif message.startswith("row "):
            events.append({
                'row during-outage: count=0 payload=""': "during_count0",
                'row before-outage: count=1 payload="value:before-outage"': "before_count1",
                'row after-outage: count=1 payload="value:after-outage"': "after_count1",
                'row lost-ack: count=1 payload="value:lost-ack"': "lost_count1",
            }.get(message, "invalid"))
        else:
            events.append("invalid")
    expected = ["connection_refused", "write_refused", "during_count0", "pool_recovered",
                "before_count1", "after_count1", "ack_timeout", "lost_count1",
                "pool_recovered", "retry_zero", "lost_count1"]
    framed = (len(re.findall(r"^=== RUN   TestDurableRecovery$", text, re.M)) == 1
              and len(re.findall(r"^--- PASS: TestDurableRecovery \([0-9.]+s\)$", text, re.M)) == 1
              and len(re.findall(r"^PASS$", text, re.M)) == 1
              and not re.search(r"(?:^FAIL$|--- FAIL:|panic:)", text, re.M))
    return {"ordered_original_test_events": framed and events == expected,
            "refused_write_has_zero_rows": events[:3] == expected[:3],
            "lost_acknowledgement_has_one_row": events[6:8] == expected[6:8],
            "same_key_retry_changes_zero_rows": events[8:] == expected[8:],
            "go_test_pass_marker": framed}


def inspect_run(receipt: Path) -> dict:
    """Return scrubbed checks; malformed or unsafe input raises ValueError/OSError.

    A partial but well-formed failed receipt returns failed_or_mismatch. Only
    constant selected stdout basenames beside the receipt are opened.
    """
    receipt = _path(receipt)
    raw = _read(receipt, MAX_JSON)
    try:
        saved = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
        _bounded(saved)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("Invalid bounded UTF-8 JSON receipt") from error
    _schema(saved)
    by_label = {step["label"]: step for step in saved.get("steps", [])}
    logs, selected = {}, []
    for label in PHASES:
        step = by_label.get(label)
        current = None
        if step is not None:
            try:
                logs[label] = _read(receipt.parent / (label + ".stdout"), MAX_LOG)
                current = hashlib.sha256(logs[label]).hexdigest()
            except FileNotFoundError:
                pass
        selected.append({"phase": label, "recorded_exit_success": step is not None and type(step["exit_code"]) is int and step["exit_code"] == 0,
                         "recorded_stdout_sha256": step["stdout_sha256"] if step else None,
                         "current_stdout_sha256": current,
                         "stdout_matches": step is not None and current == step["stdout_sha256"]})
    scenario = _scenario(logs.get("TestDurableRecovery", b""))
    before, after = saved.get("protected_hashes_before", {}), saved.get("protected_hashes_after", {})
    source = saved.get("source_verification_after", {})
    go = logs.get("go-version", b"").decode("utf-8", errors="strict").strip()
    postgres = logs.get("postgres-version", b"").decode("utf-8", errors="strict").strip()
    checks = {
        "recorded_success_status": saved.get("status") == SUCCESS,
        "recorded_synthetic_scope": saved.get("synthetic_only") is True and all(saved.get(key) == [] for key in ("public_changes", "provider_calls", "system_changes")),
        "selected_phase_order_and_exits": tuple(by_label) == PHASES and all(item["recorded_exit_success"] for item in selected),
        "current_selected_stdout_hashes": all(item["stdout_matches"] for item in selected),
        "recorded_versions": bool(re.fullmatch(r"go version go1\.27\.2 linux/[a-z0-9]+", go)) and go == saved.get("go_version") and postgres == saved.get("postgres_version") == "pg_ctl (PostgreSQL) 18.6",
        "recorded_source_unchanged": len(before) == 95 and before == after and saved.get("changed_protected_paths") == [] and source.get("status") == "source_verified" and source.get("component_files") == 87 and source.get("adapted_files") == 8 and source.get("changed") == [] and saved.get("runtime_component") == "components/toxiproxy" and saved.get("upstream_commit") == COMPONENT_COMMIT,
        "recorded_durability_settings": logs.get("durability-settings") == b"on|on|on\n",
        "recorded_restart": type(saved.get("postgres_pid_before_restart")) is int and type(saved.get("postgres_pid_after_restart")) is int and saved["postgres_pid_before_restart"] > 0 and saved["postgres_pid_after_restart"] > 0 and saved["postgres_pid_before_restart"] != saved["postgres_pid_after_restart"],
        "recorded_exact_final_rows": saved.get("durable_rows_after_restart") == list(FINAL_ROWS) and logs.get("durable-row-readback") == ("\n".join(FINAL_ROWS) + "\n").encode(),
        "recorded_cleanup": all(saved.get(key) is True for key in ("cleanup_verified", "postgres_stopped", "socket_directory_removed")) and saved.get("listeners_final") == [],
        **scenario,
    }
    return {"schema_version": 1, "status": "corroborated" if all(checks.values()) else "failed_or_mismatch",
            "evidence_passed": all(checks.values()),
            "input_receipt_sha256": hashlib.sha256(raw).hexdigest(), "checks": checks,
            "scope": SCOPE, "proof": {"selected_stdout": selected,
                "scenario_checks": scenario, "expected_final_row_count": 3,
                "exact_expected_final_rows": checks["recorded_exact_final_rows"],
                "source_hash_entries_before": len(before), "source_hash_entries_after": len(after),
                "recorded_go_version": "Go 1.27.2" if checks["recorded_versions"] else "Not corroborated",
                "recorded_postgres_version": "PostgreSQL 18.6" if checks["recorded_versions"] else "Not corroborated"}}


def _render(review):
    passed = review["evidence_passed"]
    state = "Recorded success corroborated" if passed else "Recorded failure or evidence mismatch"
    scenario_label = "Corroborated" if passed else "Not corroborated"
    scenario_heading = "Recorded scenario" if passed else "Scenario acceptance conditions"
    scenario_intro = ("The recorded evidence corroborates these results. They are historical observations, not current database query results."
                      if passed else "The conditions below are required for acceptance. The available evidence does not corroborate the overall scenario.")
    scenarios = (
        ("Refused write", "The recorded write failed while the proxy was disabled. The direct read found zero rows for that attempt.",
         "Required: a write error while the proxy is disabled, followed by a direct read with zero rows for that attempt."),
        ("Lost acknowledgement", "The client timed out, but the recorded direct read found one committed row with the expected payload.",
         "Required: a client timeout followed by a direct read with one committed row and the expected payload."),
        ("Same-key retry", "The retry affected zero rows. The original row remained, and the recorded restart readback matched exactly three expected rows.",
         "Required: a retry that affects zero rows, preservation of the original row, and a restart readback matching exactly three expected rows."),
    )
    cards = "".join('<section><h3>' + escape(title) + '</h3><p class="scenario-state">' + scenario_label + '</p><p>'
                    + escape(observed if passed else required) + '</p></section>' for title, observed, required in scenarios)
    rows = "".join("<tr><th scope=\"row\">" + escape(name.replace("_", " ")) + "</th><td>" + ("Passed" if passed else "Failed / missing") + "</td></tr>" for name, passed in review["checks"].items())
    proof_rows = "".join("<tr><th scope=\"row\">" + escape(item["phase"]) + "</th><td>" + ("Passed" if item["recorded_exit_success"] else "Failed / missing") + "</td><td>" + ("Matches" if item["stdout_matches"] else "Differs / missing") + "</td></tr>" for item in review["proof"]["selected_stdout"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Recorded PostgreSQL recovery review</title><style>
body{{margin:0;font:16px/1.6 system-ui,sans-serif;background:#f4f7fb;color:#182736}}main{{max-width:76rem;margin:auto;padding:2rem 1rem}}h1{{line-height:1.2}}p{{max-width:78ch}}
.panel{{padding:1.5rem;border:1px solid #d1dce8;border-radius:.6rem;background:white;margin:1rem 0;overflow-wrap:anywhere}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}}.grid section{{background:#eaf1f8;padding:1rem}}.grid h3{{font-size:1rem;margin:0}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:40rem}}th,td{{text-align:left;padding:.7rem;border-bottom:1px solid #d1dce8;vertical-align:top}}thead{{background:#eaf1f8}}summary{{cursor:pointer;font-weight:600}}a{{color:#155b87}}:focus-visible{{outline:3px solid #155b87;outline-offset:2px}}code{{overflow-wrap:anywhere}}
@media(max-width:650px){{main{{padding:1rem .5rem}}.panel{{padding:1rem}}.grid{{grid-template-columns:1fr}}}}@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto}}}}@media print{{body{{background:white}}main{{max-width:none;padding:0}}.panel{{border:0;padding:0}}.scroll{{overflow:visible}}table{{min-width:0}}details>*{{display:block}}}}
</style></head><body><main><h1>Recorded PostgreSQL recovery review</h1><p>One recorded synthetic network-fault rehearsal. This reviewer reads local evidence and makes no database connection.</p>
<section class="panel"><h2>{escape(state)}</h2><p>A saved success status alone is insufficient. The verdict requires matching selected logs and corroborating recorded scenario, source and cleanup evidence.</p></section>
<section class="panel"><h2>{escape(scenario_heading)}</h2><p>{escape(scenario_intro)}</p><div class="grid">{cards}</div></section>
<details class="panel"><summary>Current evidence checks</summary><p>Current checks compare the selected stdout files with their saved SHA-256 values and inspect their recorded contents.</p><p>Receipt SHA-256: <code>{escape(review['input_receipt_sha256'])}</code></p>
<div class="scroll" tabindex="0" role="region" aria-label="Current evidence checks"><table><thead><tr><th scope="col">Check</th><th scope="col">Current review</th></tr></thead><tbody>{rows}</tbody></table></div></details>
<details class="panel"><summary>Selected evidence</summary><p>Only selected phase names, checks and hashes are exported. Paths, ports, credentials, database values and full logs are omitted.</p><div class="scroll" tabindex="0" role="region" aria-label="Selected recorded phases"><table><thead><tr><th scope="col">Phase</th><th scope="col">Recorded exit</th><th scope="col">Current stdout hash</th></tr></thead><tbody>{proof_rows}</tbody></table></div><p><a href="review.json">Review JSON</a> · <a href="selected-proof.json">Scrubbed selected proof</a></p></details>
<section class="panel"><h2>Scope and limits</h2><p>{escape(SCOPE)}</p><p>On a narrow screen, focus a table and use the arrow keys, or scroll it sideways. The scope remains visible when printed.</p></section></main></body></html>'''


def write_report(receipt: Path, output: Path) -> dict:
    """Create a new private report outside the original fixture/run directory."""
    receipt = _path(receipt)
    output = Path(output)
    if ".." in output.parts:
        raise ValueError("Output must not contain parent traversal")
    output = output.absolute()
    _path(output.parent, directory=True)
    try:
        output.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("Choose a new output directory; existing or dangling paths are not replaced")
    run_root = receipt.parent.parent
    if output.is_relative_to(run_root) or run_root.is_relative_to(output):
        raise ValueError("Output must be outside the receipt and original run, without overlap")
    review = inspect_run(receipt)
    output.mkdir(mode=0o700)
    values = {"review.json": {key: value for key, value in review.items() if key != "proof"},
              "selected-proof.json": review["proof"]}
    for name, value in values.items():
        with os.fdopen(os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600), "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
    with os.fdopen(os.open(output / "report.html", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600), "w", encoding="utf-8") as stream:
        stream.write(_render(review))
    return review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Exit 0: corroborated recorded success; 1: failure/mismatch; 2: invalid/unreadable input or output.")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the original run; parent must exist")
    args = parser.parse_args(argv)
    try:
        review = write_report(args.receipt, args.output)
    except (ValueError, OSError, UnicodeError) as error:
        # Do not echo raw paths, receipt values or OS error messages into a report.
        print("Review invalid or unreadable; no existing output was replaced. A partial new output may remain.", file=sys.stderr)
        return 2
    print(review["status"])
    return 0 if review["status"] == "corroborated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
