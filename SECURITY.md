# Security and operating limits

## Local synthetic data only

The rehearsal creates a new PostgreSQL cluster containing three fixed synthetic key/payload pairs. It starts PostgreSQL and the copied Toxiproxy on fresh loopback ports with local trust authentication, then stops its owned services. Other processes on the same machine can reach those ports during a run. Use an isolated local development environment, never expose the ports, and do not supply real database credentials or business data. The entrypoint has no existing-database URL option.

Go dependencies are acquired through the original checksum-verified module route unless an explicit populated cache is selected with `--offline`. Go, PostgreSQL, Python and `ss` must already be installed. No system service, account, shell profile or host configuration is installed by the commands in this repository.

## Evidence and output

The result viewer is read-only: it opens a bounded receipt and constant selected stdout filenames beside it. It does not connect to PostgreSQL, rerun recovery, retry a write or authenticate the saved records. Editable receipts and hashes can be forged together. Static path/type checks are not a defense against hostile concurrent filesystem mutation; use a stable owner-controlled tree.

The viewer rejects symbolic links and special files, malformed or oversized inputs, duplicate JSON keys and existing output paths. It exports only selected checks, phase names and hashes; raw command arguments, local paths, ports, database values and full logs remain in the private run directory. The generated work directory is private on Linux; existing parent permissions are not changed. A new report directory uses mode 0700 and files use mode 0600. Inspect before sharing even a scrubbed report.

An interrupt is forwarded to the owned runner so its existing cleanup can finish. A retained failure receipt and its `cleanup_verified` value must be checked after a failed or interrupted run; do not infer stopped services merely from an absent report. Data and logs are retained, including on failure. The viewer's report describes recorded evidence, not the database's current state.

## Reporting a problem

For ordinary reproducible bugs, use this repository's GitHub Issues with synthetic data and a minimal scrubbed example. Do not post credentials, real rows, raw local logs, or confidential vulnerability details. This repository does not advertise a private security contact; if confidential reporting is needed, first request a private channel without posting the sensitive details.

## Boundaries

One sequential synthetic recovery test and a clean PostgreSQL restart do not establish crash or power-loss recovery, general exactly-once execution, concurrent replay safety, failover, load capacity or production readiness. Retained upstream examples have their own ports and assumptions: run the documented entrypoint, not `main.go`.
