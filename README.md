# PostgreSQL network recovery and keyed retry rehearsal

Rehearse what a database client can observe when a network outage refuses a write, and when a committed write loses its acknowledgement. This local example runs an actual copied Toxiproxy server, a go-pg connection pool and a new synthetic PostgreSQL cluster. It checks recovery through the same pool, a keyed conditional retry and exact rows after a clean database restart.

The distinction matters when deciding whether to retry a timed-out operation: a client error alone does not establish that the database rejected it. Here an independent connection observes the committed row before the same key is retried with `ON CONFLICT DO NOTHING`.

## Repository guide

The [runner](tools/verify_recovery.py) starts the local services and selects
[`TestDurableRecovery`](recovery-improvement/example/recovery_test.go). The
[adapted example](recovery-improvement/example/), [copied components](components/)
and [provenance](PROVENANCE.md) show what executes and what was changed.
Use the [verification record](VERIFICATION.md) for observed results and
[research note](RESEARCH.md) for the retry rationale.

## Run the rehearsal

Use Linux as a non-root user, Python 3, `ss` from iproute2, Go 1.27.2 and PostgreSQL 18.6 binaries. The runner checks the two runtime versions. Use an existing native Linux output directory; PostgreSQL requires effective private data-directory permissions. Nothing is installed by these commands.

From the repository directory, with the specified Go and PostgreSQL tools on PATH:

```sh
python3 -B tools/verify_source.py
mkdir -p "$HOME/.cache/postgres-recovery-kit"
python3 -B tools/verify_recovery.py \
  --go "$(command -v go)" \
  --pg-bin "$(pg_config --bindir)" \
  --output-parent "$HOME/.cache/postgres-recovery-kit"
```

If the tools are elsewhere, replace `--go` with the executable path and `--pg-bin` with the PostgreSQL 18.6 binary directory. Normal Go dependency downloads use the standard checksum-verified module route. To reuse an already populated verified module cache without downloading, add `--module-cache /path/to/modules --offline`. The local evidence reused such a cache; a fresh download has not been tested for this stage.

The source check reports `status=source_verified`, `component_files=87`, `adapted_files=8` and an empty `changed` array. The rehearsal builds the copied server and selected test, allocates three fresh loopback ports, runs only `TestDurableRecovery`, performs a clean PostgreSQL restart and reads back:

```text
after-outage|value:after-outage
before-outage|value:before-outage
lost-ack|value:lost-ack
```

Its final JSON identifies the generated `receipt.json`, `status=recovery_and_keyed_retry_passed_restart_readback_verified` and `cleanup_verified=true`. The receipt records `durable_rows_after_restart`, `changed_protected_paths=[]`, `listeners_final=[]` and `postgres_stopped=true`. All owned services stop; the unique cluster data, builds and logs remain under the chosen output parent. Each execution creates a new directory. A failed assertion, command or cleanup returns exit code 1 and preserves the available evidence.

## Demonstrated behavior

1. A pre-outage keyed write inserts one row.
2. Disabling the proxy makes Ping and the outage write fail; the independent observer finds no outage row.
3. Restoring the proxy lets the same pool recover within a five-second acceptance bound and insert a post-outage row.
4. A downstream timeout drops one acknowledgement. The client returns an I/O timeout while the independent observer finds the exact committed row.
5. Removing the toxic lets the same pool recover. Repeating the same key affects zero rows and preserves its payload.
6. A clean PostgreSQL restart retains all three exact key/payload pairs with `fsync`, `synchronous_commit` and `full_page_writes` set to `on`.

[PROVENANCE.md](PROVENANCE.md) identifies the executed copies and adaptation. [VERIFICATION.md](VERIFICATION.md) separates historical baseline evidence, the corrected recovery check and the portable stage run.

[RESEARCH.md](RESEARCH.md) explains the acknowledged-write uncertainty that motivates this specific rehearsal.

## Limits

This is one deterministic, sequential synthetic scenario with loopback-only listeners and trust authentication. It establishes this pool's recovery and this keyed SQL operation's observed behavior. It does not establish general exactly-once execution, concurrent replay safety, failover, crash or power-loss recovery, load capacity or production readiness. The five-second limit applies to each recovery acceptance check; the entire test and cleanup can take longer.

The original example's schema, seed and processing functions are retained and compiled; the selected recovery test does not execute them. Do not run `main.go` as this rehearsal: it retains the upstream example's original database and port choices. The retained latency/reset tests are not selected by the runner. The workflow currently configures source checks and compilation only; remote CI has not run.
