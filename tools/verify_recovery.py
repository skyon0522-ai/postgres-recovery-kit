"""Run the copied example's narrow recovery test on a new synthetic local cluster."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.request

from verify_source import verify

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--go", type=Path, required=True, help="Explicit Go 1.27.2 executable")
parser.add_argument("--pg-bin", type=Path, required=True, help="Explicit PostgreSQL 18.6 bin directory")
parser.add_argument("--output-parent", type=Path, required=True, help="Existing native Linux directory outside this repository")
parser.add_argument("--module-cache", type=Path, help="Optional existing checksum-verified Go module cache")
parser.add_argument("--offline", action="store_true", help="Use cached modules only; do not download dependencies")
options = parser.parse_args()
runtime, pgbin, output_parent = options.go.resolve(), options.pg_bin.resolve(), options.output_parent.resolve()
if os.name != "posix" or not runtime.is_file() or not os.access(runtime, os.X_OK):
    parser.error("Run on Linux with an executable --go path")
if not output_parent.is_dir() or output_parent == root or root in output_parent.parents:
    parser.error("--output-parent must be an existing native directory outside the repository")
for name in ("initdb", "pg_ctl", "createdb", "psql"):
    if not (pgbin / name).is_file() or not os.access(pgbin / name, os.X_OK):
        parser.error("--pg-bin must contain executable " + name)
if options.module_cache and not options.module_cache.resolve().is_dir():
    parser.error("--module-cache must be an existing directory")
manifest = json.loads((root / "source-copy-manifest.json").read_text())
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
fixture = output_parent / ("recovery-" + stamp)
fixture.mkdir(mode=0o700, exist_ok=False)
proof, build = fixture / "verification", fixture / "build"
proof.mkdir(mode=0o700)
build.mkdir(mode=0o700)
data = fixture / "data"
# Keep the private socket path below PostgreSQL's Unix socket length limit.
sockdir = Path("/tmp") / ("pg-recovery-" + stamp)
sockdir.mkdir(mode=0o700, exist_ok=False)
module_cache = options.module_cache.resolve() if options.module_cache else build / "modules"
env = {**os.environ, "GOTOOLCHAIN": "local", "GOWORK": "off", "GOFLAGS": "-mod=readonly",
       "GOMODCACHE": str(module_cache), "GOCACHE": str(build / "cache"),
       "GOPATH": str(build / "gopath"), "GOPROXY": "off" if options.offline else "https://proxy.golang.org,direct",
       "GOSUMDB": "sum.golang.org", "GONOSUMDB": "", "GONOPROXY": "", "GOPRIVATE": "", "CGO_ENABLED": "0"}
sha = lambda raw: hashlib.sha256(raw).hexdigest()
receipt = {"started_at_utc": stamp, "synthetic_only": True, "fixture": str(fixture),
           "upstream_commit": manifest["components"][0]["commit"], "steps": [], "public_changes": [], "provider_calls": [],
           "system_changes": [], "data_retained": True, "build": str(build),
           "module_cache_reused": bool(options.module_cache), "module_proxy": env["GOPROXY"],
           "fresh_dependency_download_verified": False}

def run(label, args, cwd=root / "recovery-improvement/example", timeout=60):
    started = time.monotonic()
    try:
        process = subprocess.run([str(x) for x in args], cwd=cwd, env=env, capture_output=True, timeout=timeout)
        out, err, code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        out, err, code = error.stdout or b"", error.stderr or b"", "timeout"
    (proof / (label + ".stdout")).write_bytes(out)
    (proof / (label + ".stderr")).write_bytes(err)
    item = {"label": label, "args": [str(x) for x in args], "exit_code": code,
            "elapsed_seconds": round(time.monotonic() - started, 3), "stdout_sha256": sha(out), "stderr_sha256": sha(err)}
    receipt["steps"].append(item)
    print(json.dumps(item), flush=True)
    if code != 0:
        raise RuntimeError(f"{label} failed: {code}; see preserved logs")
    return out

def protected_hashes():
    result = verify(root)
    if result["changed"]:
        raise RuntimeError("Source verification failed: " + json.dumps(result["changed"]))
    return result["hashes"]

def listeners():
    lines = subprocess.check_output(["ss", "-lntp"]).decode().splitlines()
    return [line for line in lines[1:] if any(line.split()[3].endswith(":" + str(port)) for port in ports)]

def api(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{apiport}" + path, timeout=2) as response:
        return json.load(response)

server = None
reservations = [socket.socket() for _ in range(3)]
for reservation in reservations:
    reservation.bind(("127.0.0.1", 0))
ports = [reservation.getsockname()[1] for reservation in reservations]
pgport, apiport, proxyport = ports
receipt["ports"] = {"postgres": pgport, "api": apiport, "proxy": proxyport}
env.update(RECOVERY_PG_ADDR=f"127.0.0.1:{pgport}", RECOVERY_TOXI_ADDR=f"127.0.0.1:{apiport}", RECOVERY_PROXY_ADDR=f"127.0.0.1:{proxyport}")
try:
    receipt["protected_hashes_before"] = protected_hashes()
    receipt["go_version"] = run("go-version", [runtime, "version"]).decode().strip()
    assert "go1.27.2 " in receipt["go_version"], "Use the tested Go 1.27.2 runtime"
    receipt["postgres_version"] = run("postgres-version", [pgbin / "pg_ctl", "--version"]).decode().strip()
    assert " 18.6" in receipt["postgres_version"], "Use the tested PostgreSQL 18.6 runtime"
    run("build-copied-server", [runtime, "build", "-trimpath", "-ldflags=-s -w", "-o", build / "toxiproxy-server", "./cmd/server"], cwd=root / "components/toxiproxy", timeout=180)
    run("component-module-verify", [runtime, "mod", "verify"], cwd=root / "components/toxiproxy")
    run("build-recovery-test", [runtime, "test", "-c", "-trimpath", "-o", build / "recovery.test", "."], timeout=120)
    run("example-module-verify", [runtime, "mod", "verify"])
    module = json.loads(run("copied-module-path", [runtime, "list", "-m", "-json", "github.com/Shopify/toxiproxy/v2"]))
    assert Path(module["Replace"]["Dir"]).resolve() == (root / "components/toxiproxy").resolve()
    receipt["runtime_component"] = "components/toxiproxy"
    run("initdb", [pgbin / "initdb", "-D", data, "--username=postgres", "--auth-local=trust", "--auth-host=trust", "--encoding=UTF8", "--locale=C"])
    (data / "pg_hba.conf").write_text("local all all trust\nhost all all 127.0.0.1/32 trust\n")
    with (data / "postgresql.conf").open("a") as config:
        config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {pgport}\nunix_socket_directories = '{sockdir}'\nfsync = on\nsynchronous_commit = on\nfull_page_writes = on\nlog_statement = 'all'\n")
    for reservation in reservations:
        reservation.close()
    assert listeners() == [], "Selected ports became occupied"
    run("postgres-start", [pgbin / "pg_ctl", "-D", data, "-l", fixture / "postgres.log", "-w", "-t", "30", "start"])
    receipt["postgres_pid_before_restart"] = int((data / "postmaster.pid").read_text().splitlines()[0])
    run("createdb", [pgbin / "createdb", "-h", "127.0.0.1", "-p", pgport, "-U", "postgres", "sample_test"])
    psql = [pgbin / "psql", "-X", "-h", "127.0.0.1", "-p", pgport, "-U", "postgres", "-d", "sample_test", "-v", "ON_ERROR_STOP=1", "-At", "-c"]
    run("durability-settings", psql + ["SELECT current_setting('fsync'), current_setting('synchronous_commit'), current_setting('full_page_writes');"])
    with (proof / "toxiproxy.stdout").open("wb") as out, (proof / "toxiproxy.stderr").open("wb") as err:
        server = subprocess.Popen([str(build / "toxiproxy-server"), "-host", "127.0.0.1", "-port", str(apiport)], stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        receipt["toxiproxy_pid"] = server.pid
        for _ in range(100):
            assert server.poll() is None, "Copied server exited before API startup"
            try:
                receipt["api_version"] = api("/version")
                break
            except (OSError, ValueError):
                time.sleep(0.05)
        else:
            raise RuntimeError("Copied server API startup timed out")
        assert api("/proxies") == {}
        run("TestDurableRecovery", [build / "recovery.test", "-test.v", "-test.run", "^TestDurableRecovery$", "-test.timeout", "30s"])
        receipt["proxies_after_test"] = api("/proxies")
        proxy = receipt["proxies_after_test"]["postgresql"]
        assert proxy["enabled"] and proxy["toxics"] == []
        receipt["listeners_running"] = listeners()
        assert len(receipt["listeners_running"]) == 3
        assert all("127.0.0.1:" in line for line in receipt["listeners_running"])
        run("postgres-restart", [pgbin / "pg_ctl", "-D", data, "-l", fixture / "postgres.log", "-w", "-t", "30", "restart"])
        receipt["postgres_pid_after_restart"] = int((data / "postmaster.pid").read_text().splitlines()[0])
        assert receipt["postgres_pid_before_restart"] != receipt["postgres_pid_after_restart"]
        rows = run("durable-row-readback", psql + ["SELECT operation_key, payload FROM recovery_writes ORDER BY operation_key;"])
        expected = b"after-outage|value:after-outage\nbefore-outage|value:before-outage\nlost-ack|value:lost-ack\n"
        assert rows == expected, "Rows after PostgreSQL restart did not match expected durable rows"
        receipt["durable_rows_after_restart"] = rows.decode().splitlines()
    receipt["status"] = "recovery_and_keyed_retry_passed_restart_readback_verified"
except Exception as error:
    receipt["status"], receipt["error"] = "failed_preserved", f"{type(error).__name__}: {error}"
finally:
    for reservation in reservations:
        reservation.close()
    if server is not None:
        if server.poll() is None:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        receipt["toxiproxy_exit_code"] = server.returncode
    # Only stop the unique cluster created by this runner; retain its data and logs.
    if data.joinpath("postmaster.pid").exists():
        try:
            run("postgres-stop", [pgbin / "pg_ctl", "-D", data, "-w", "-t", "30", "-m", "fast", "stop"])
        except Exception as error:
            receipt["cleanup_error"] = str(error)
    receipt["listeners_final"] = listeners()
    receipt["postgres_stopped"] = not data.joinpath("postmaster.pid").exists()
    if receipt["postgres_stopped"] and not any(sockdir.iterdir()):
        sockdir.rmdir()
    final_source = verify(root)
    receipt["source_verification_after"] = {key: value for key, value in final_source.items() if key != "hashes"}
    receipt["protected_hashes_after"] = final_source["hashes"]
    receipt["changed_protected_paths"] = [path for path, value in receipt.get("protected_hashes_before", {}).items() if receipt["protected_hashes_after"].get(path) != value]
    receipt["files_sha256"] = {str(path.relative_to(root)): sha(path.read_bytes()) for path in (root / "recovery-improvement/example").iterdir() if path.is_file()}
    receipt["binaries_sha256"] = {str(path): sha(path.read_bytes()) for path in (build / "toxiproxy-server", build / "recovery.test") if path.exists()}
    if (fixture / "postgres.log").exists():
        (proof / "postgres.log").write_bytes((fixture / "postgres.log").read_bytes())
    receipt["socket_directory_removed"] = not sockdir.exists()
    receipt["cleanup_verified"] = receipt["postgres_stopped"] and receipt["listeners_final"] == [] and not sockdir.exists() and (server is None or server.poll() is not None)
    if not receipt["cleanup_verified"] or receipt["changed_protected_paths"] or final_source["changed"]:
        receipt["status"] = "cleanup_or_protection_verification_failed"
    (proof / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(proof / "receipt.json"), "error": receipt.get("error"), "cleanup_verified": receipt["cleanup_verified"]}), flush=True)
if receipt["status"] != "recovery_and_keyed_retry_passed_restart_readback_verified":
    raise SystemExit(1)
