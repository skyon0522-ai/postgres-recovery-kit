# Research background

Pat Helland's [Life beyond Distributed Transactions: an Apostate's Opinion](https://www.cidrdb.org/cidr2007/papers/cidr07p15.pdf), a position paper in the [CIDR 2007 program](https://www.cidrdb.org/cidr2007/program.html), discusses the failure window between a durable update and its acknowledgement and the resulting repeated messages.

This rehearsal checks that uncertainty in one PostgreSQL operation: a downstream fault loses the acknowledgement, a direct observer finds the committed row, and a same-key conditional INSERT affects zero rows. The implementation uses the copied Toxiproxy/go-pg example plus the new verifier. It does not reproduce the paper's platform or validate its scalability discussion, distributed-transaction claims or a general exactly-once guarantee.

The primary PDF was inspected again on 2026-10-15: its page 3 discussion of at-least-once messaging explains the durable-update/acknowledgement window. This is design background, not empirical validation of this tool. The new offline viewer checks recorded evidence and does not extend the paper’s claims.
