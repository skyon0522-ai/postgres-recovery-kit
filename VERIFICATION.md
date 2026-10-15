# Observed verification

## Historical Linux stage: 2026-10-09

The portable stage was executed locally on Linux with task-local Go 1.27.2, PostgreSQL 18.6 and an existing checksum-verified dependency cache. Source verification preceded the run and followed cleanup. `GOTOOLCHAIN=local`, `GOWORK=off`, `GOFLAGS=-mod=readonly`, `GOSUMDB=sum.golang.org`, `CGO_ENABLED=0` and offline module access were scoped to the subprocesses. No global tools were installed.

## Historical baseline and review

The preserved candidate evidence executed the unedited copied PostgreSQL example, `TestSlowDBConnection` and `TestOutageResetPeer`; each exited 0. The raw copied Toxiproxy server and CLI were built, and selected stream/client contracts passed. These historical checks are separate from the new keyed recovery workload. They were not rerun for this public stage; no full upstream suite was run here.

An independent one-pass review accepted the bounded recovery demonstration and found one P3 defect in its five-second acceptance check: a successful Ping could return after the boundary. The correction gives each recovery wait one absolute context deadline and unconditionally checks elapsed time after success. A narrow independent closure marked that finding resolved after inspecting the dependency behavior and the writer's corrected selected rerun. A deliberately late-success boundary regression was not executed.

The stage retains the corrected 124-line `recovery_test.go`, SHA-256 `0e3a5d7bbcf572c80f15dd27f83e57c452e2fa85e1c9209c1ffd09cefc38414a`. The correction's earlier selected run and this portable stage run both passed. The five-second limit is an acceptance bound for each recovery wait, not a promise that the entire test or cleanup finishes within five seconds.

## Portable public procedure

The command in [README.md](README.md) was executed with explicit existing tool paths, a fresh native output parent and `--module-cache <existing verified cache> --offline`. The wrapper built a new server from `components/toxiproxy`, compiled the reviewed adapter, initialized a new synthetic cluster and selected only `TestDurableRecovery`.

| Executed stage | Observed result |
| --- | --- |
| Raw component and adapter verification | 87 component files and eight adapter files match their recorded bytes; no changed path |
| `go build -trimpath -ldflags='-s -w' -o <owned binary> ./cmd/server` in the component | Exit 0 |
| `go mod verify` in component and example modules | Both exit 0; all modules verified |
| `go test -c -trimpath -o <owned test binary> .` in the example | Exit 0 |
| `go list -m -json github.com/Shopify/toxiproxy/v2` | Local replacement resolves to the copied `components/toxiproxy` |
| `<owned test binary> -test.v -test.run '^TestDurableRecovery$' -test.timeout 30s` | Passed in 2.04 seconds |
| Clean `pg_ctl restart` and ordered SQL row readback | Different postmaster PID; all three exact key/payload pairs retained |
| Owned-service shutdown and source preservation | Server exit 0; PostgreSQL stopped; selected listeners empty; private socket directory removed; no changed source path |

The selected test observed the outage connection error and refused INSERT, zero `during-outage` rows through the direct observer, and same-pool recovery after about 1.012 seconds. The post-outage write inserted one matching row. A downstream timeout then produced a client I/O timeout after about 1.001 seconds while the direct observer found exactly one committed `lost-ack` row. After fault removal, the same pool recovered in about 2.7 milliseconds. Repeating the key affected zero rows and preserved its payload.

The test checked total count three. The runner separately compared the entire ordered post-restart readback to:

```text
after-outage|value:after-outage
before-outage|value:before-outage
lost-ack|value:lost-ack
```

The recorded durability settings were `on|on|on` for `fsync`, `synchronous_commit` and `full_page_writes`. API readback showed an enabled proxy and no remaining toxics. All three listeners were bound to `127.0.0.1`. The expected go-pg cancellation error during the disabled-proxy step was retained in stderr.

[verification-summary.json](verification-summary.json) contains the portable run's stable outcomes and hashes. Machine-specific commands/logs remain in separately retained local evidence. The run left all 95 staged source hashes and 182 protected original-source/fixture hashes unchanged; the original fixture stayed stopped. A separate native source-copy readback verifies all recorded Git/POSIX modes.

## Limits recorded for the 2026-10-09 stage

The stage run reused verified dependencies with `GOPROXY=off`; a fresh dependency download was not tested. The workflow configures raw-source/mode checks, server build and test compilation only. Remote CI has not run, and the database scenario is not claimed as a CI result. Importing from Windows must preserve the three upstream executable script modes recorded in the manifest.

A separate failure probe supplied an empty module cache with offline access. The copied-server build failed before any service started; the runner preserved its receipt, returned exit code 1, verified cleanup and left source hashes unchanged. This checks command-failure exit propagation without rerunning the database test.

This is a deterministic sequential synthetic check. Clean-restart survival does not establish crash or power-loss durability, and keyed `ON CONFLICT` behavior here does not establish general exactly-once execution, concurrent replay safety, failover, load capacity or production readiness. Runtime logs, binaries, caches and cluster data are retained outside the public source stage.


## Linux interface and recorded-evidence review: 2026-10-15

The original Go adapter, source guard and `tools/verify_recovery.py` were retained byte-for-byte. On Ubuntu 24.04.4 LTS x86_64, Python 3.12.3, existing Go 1.27.2 and PostgreSQL 18.6:

- An actual offline attempt with an incomplete cache failed at the copied-server build before service startup. Its retained receipt reports cleanup verified and no changed protected source. The collection helper initially expected later test logs and stopped on their absence; that did not make the failed native run a success.
- A new run used the original normal Go acquisition route with an initially empty run-local module cache. The server/test built, both `go mod verify` steps passed, the copied-module replacement was confirmed, and the actual selected Go test passed. The exact three rows survived a clean restart. The old runner's conservative `fresh_dependency_download_verified=false` field was retained; the new acquisition observation is recorded separately and is not a fresh operating-system or PostgreSQL installation claim.
- The new entrypoint then used PATH tool discovery, an output path containing spaces and Japanese text, a new synthetic cluster and that populated cache offline. Its original runner and read-only evidence review both passed. PostgreSQL stopped, the three selected listeners closed, the private socket directory was removed and all 95 protected component/adapter hashes stayed unchanged. Work/review directory modes were 0700; report files were 0600.
- Twenty-one Python tests cover the bounded reader and seven cover the entrypoint, including output refusal, path/cache separation, missing tools, retained failure logs and interrupt forwarding to a controlled child's cleanup. These protocol/wrapper tests do not replace the real Go/PostgreSQL test.
- Three static report variants were produced from the genuine success, genuine build failure and a separately changed inspection copy. Only the copy's selected log was edited; its original receipt stayed unchanged. The modified count and original stdout-hash mismatch were detected. This control is not another database execution.
- Isolated browser checks at widths 1440 and 390 compared all verdicts, scenario labels, 15 check rows and 15 selected phase rows to JSON. Keyboard disclosure/scroll, JSON links, print-visible limits and reduced motion passed; no external requests, active embeds or page errors occurred. Parent inspected the completed desktop and changed-evidence mobile images.

[verification/linux-review-20261015.json](verification/linux-review-20261015.json) identifies the final tested Python hashes and observation scope. Public examples contain three scrubbed review files each; raw receipts/logs, native binaries, caches and cluster data remain outside the repository.

Historical GitHub run [38060138489](https://github.com/skyon0522-ai/postgres-recovery-kit/actions/runs/38060138489) succeeded at `6bec69644d0744d30844820a9b4c4f3c775d6aae`. New-commit CI is unrun. Its prepared scope adds the Python tests to the existing source/build/compile checks; the database scenario remains a local result. Full upstream tests, another machine, fresh PostgreSQL setup, concurrent filesystem mutation, failover, load, crash/power-loss recovery and production use are unverified.
