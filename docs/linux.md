# Linux setup and operation

## Existing tools

Use a non-root Linux account with Python 3.12, `ss` from iproute2, Go **1.27.2** and PostgreSQL **18.6** binaries. The original runner checks the two runtime versions. Nothing in this repository installs PostgreSQL or changes an existing database.

Use the [official Go installation guide](https://go.dev/doc/install) and [PostgreSQL 18 installation documentation](https://www.postgresql.org/docs/18/installation.html) if these tools are missing. Select the versions above; the guides may show another version. This project has not established a minimal clean-OS package list or a fresh PostgreSQL installation recipe.

If tools are already on PATH, inspect them with:

```sh
python3 --version
go version
pg_config --version
pg_config --bindir
command -v ss
```

The PostgreSQL binary directory must contain `postgres`, `initdb`, `pg_ctl`, `createdb` and `psql`. Choose a native Linux work location outside the checkout; do not put a PostgreSQL cluster on a Windows-mounted directory. Existing output is never replaced.

## Run

From the repository directory:

```sh
python3 -B tools/run_rehearsal.py \
  --output-dir "$HOME/.cache/postgres-recovery-kit/run-$(date +%s)"
```

The command locates `go` and `pg_config` on PATH, invokes the original source-checked runner, then produces an offline review. Native binaries, a new synthetic cluster, logs and evidence remain under the new work directory. The command prints the log directory at startup and a final JSON record containing `receipt` and `report`. Open that `report.html` in a browser. No web server or account is needed.

For tools outside PATH, pass their actual paths:

```sh
python3 -B tools/run_rehearsal.py \
  --go /absolute/path/to/go \
  --pg-bin /absolute/path/to/postgresql-18.6/bin \
  --output-dir "$HOME/.cache/postgres-recovery-kit/explicit-run-$(date +%s)"
```

Dependency acquisition uses Go's normal module proxy and checksum database, scoped to a new run-local cache. To use a previously populated verified cache, add `--module-cache /absolute/path/to/modules --offline`. An incomplete offline cache fails the build, retains its logs and produces a failed review; it is not silently filled from the network.

## Read a recorded result again

The final `result.json` identifies the original `receipt` path. Keep the receipt together with its sibling stdout files. A separate read-only review never connects to a database:

```sh
python3 -B tools/review_run.py \
  --receipt /absolute/path/to/verification/receipt.json \
  --output /absolute/path/to/new-review-directory
```

Replace both paths. The output parent must already exist, and the new output must be outside the original run. The viewer emits `report.html`, `review.json` and `selected-proof.json`. Exit 0 means corroborated recorded success, 1 means a recorded failure or evidence mismatch, and 2 means invalid/unreadable evidence or output. A partial new output can remain after an output error.

The full entrypoint returns 0 only if the original rehearsal exits 0 and the evidence review passes. Other failures return 1; an interrupt returns 130. Inspect `runner.stdout`, `runner.stderr`, `result.json` and the original receipt after failure. Do not treat the saved success string as a live health check or proof that cleanup occurred today.

## What each outcome means

| Stage | Client observation | Independent recorded observation |
| --- | --- | --- |
| Proxy disabled | Connection/write error | No row for `during-outage` |
| Reply dropped after commit | I/O timeout | One `lost-ack` row with its expected payload |
| Fault removed, same key retried | Conditional INSERT affects zero rows | Original row retained; exact three-row set survives a clean restart |

These are the fixed rehearsal's acceptance conditions. A green review requires the recorded source/version checks, ordered test events, selected stdout hashes, exact final rows and recorded cleanup to agree. It does not provide a general retry policy for an arbitrary business operation.

## Inspect or develop

```sh
python3 -B tools/verify_source.py
python3 -B -m unittest discover -s tools -p 'test_*.py' -v
```

The source verifier covers the copied component and protected Go adapter. Python tests cover the new entrypoint and recorded-evidence reader; they do not replace the native database test. See [VERIFICATION.md](../VERIFICATION.md) for the exact observed environments and [SECURITY.md](../SECURITY.md) for data, interruption and reporting boundaries.
