# Copied source and adaptation

The runtime component is [Shopify Toxiproxy v2.12.0](https://github.com/Shopify/toxiproxy/tree/3ccd6a79cbc6c6a72b884d295ad314b75cdf3962), commit `3ccd6a79cbc6c6a72b884d295ad314b75cdf3962`, Git tree `4dd08e162152ffbaa95fbe87c6f0cc51af0b409e`. All 87 files in `components/toxiproxy` are raw Git-blob copies of that pinned tree. This includes its source, tests, module manifests, documentation, scripts and MIT notice. No component source was changed.

[source-copy-manifest.json](source-copy-manifest.json) records relative paths, byte counts, SHA-256, Git blob IDs and original Git modes. [tools/verify_source.py](tools/verify_source.py) checks all 87 component blobs and eight adapter files. `--check-modes` additionally checks POSIX permissions after importing to Git or a native filesystem; Windows permission reporting does not establish the source's executable bits. Preserve the three executable `components/toxiproxy/scripts/test-*` modes when importing. `.gitattributes` disables text conversion so checkout does not rewrite raw bytes.

## Original implementation inspected and reused

- `_examples/tests/db_test.go`: initial proxy creation, client API calls and PostgreSQL connection path. Its original latency and reset test assertions remain in the adapter, but are not executed by this selected rehearsal.
- `_examples/tests/db.go`, `main.go` and `models.go`: original schema, seed and processing workload. These are byte-identical copies that compile with the adapter; they do not execute in `TestDurableRecovery`.
- `cmd/server/server.go`, `client/proxy.go` and the timeout toxic: copied server startup, proxy enable/disable and downstream fault injection. The public runner builds the server directly from this component. The adapter's local module replacement resolves its Toxiproxy API to the same copied tree.
- The candidate's already executed `run-isolated.py`: fresh owned cluster/build directories, alternate loopback ports, clean restart/readback, retained data, service cleanup and failed-run exit propagation.

The four upstream workload/test files and MIT notice were initially copied before adaptation. The candidate's `go.mod` and `go.sum` were authored to make that example a runnable module; they are not upstream example files. The adapter keeps `db.go`, `main.go`, `models.go`, `go.sum` and `LICENSE` unchanged from that baseline. `db_test.go` adapts endpoint selection, single-connection timeout options and externally owned server startup. `go.mod` gives the adapter a separate module name and preserves the local component replacement.

[adaptation.diff](adaptation.diff) records original-example → final-adapter changes. [adaptation.json](adaptation.json) identifies those files and their hashes. The authored 124-line `recovery_test.go` adds the persistent keyed SQL operation, independent observer and bounded recovery assertions. Its SHA-256 is `0e3a5d7bbcf572c80f15dd27f83e57c452e2fa85e1c9209c1ffd09cefc38414a`.

The reuse boundary is explicit: the copied Toxiproxy server/client and adapted proxy/connection helper actually execute; unchanged `setupDB`, `seed` and `process` only compile; the recovery SQL and its assertions are the new extension. The project does not claim that the new SQL workload was an existing upstream implementation.

## Portable runner and publication layout

[runner-adaptation.diff](runner-adaptation.diff) and [runner-adaptation.json](runner-adaptation.json) record the existing isolated runner → portable public runner change. The prior operator's home paths are redacted from the public diff; exact original and final hashes are retained. Changes are limited to explicit tool/output paths, building the copied server, optional module-cache reuse, source preservation checks and recorded runtime/tool evidence. The cleanup and narrow recovery sequence are retained.

The existing `transactional-outbox-service` publication stage was inspected for its README run instructions, separate provenance and verification documents, relative source manifest, component verifier and CI organization. This stage follows that structure. It does not copy that service's implementation.

The root and adapter LICENSE preserve the upstream MIT notice; `components/toxiproxy/LICENSE` remains identical. Dependency modules retain their licenses and are checked by `go mod verify`. Generated binaries, dependency caches, synthetic cluster data, machine-specific receipts and runtime logs are excluded from the source stage.
