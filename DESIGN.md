# Design

The network-fault mechanism remains the existing copied Toxiproxy server and protected Go/go-pg adapter. The Python entrypoint calls the original recovery runner rather than duplicating its lifecycle. The runner creates a new local synthetic cluster, runs the selected test, restarts PostgreSQL, compares rows and stops its owned services.

The new entrypoint adds standard Linux tool discovery, exclusive work-directory creation and an offline review. Its interrupt handling lets the original coordinator finish its cleanup. Failures retain their data and logs; missing output is not a cleanup guarantee.

The reader reuses the Backup Restore Drill presentation pattern: verdict and useful scenario first, technical evidence in keyboard-accessible details, then visible scope. It reads only a bounded receipt and fixed sibling stdout basenames. It never follows stored command paths or queries a database. Matching step hashes, ordered test assertions, source/version checks, restart, exact rows and recorded cleanup must all agree before scenario cards say corroborated.

The inspection results are editable historical evidence, not authenticated statements or current database state. Selected reports omit raw logs, paths, ports, credentials and values. The existing [source manifest](source-copy-manifest.json), [provenance](PROVENANCE.md) and [research note](RESEARCH.md) retain implementation lineage and its scope.
