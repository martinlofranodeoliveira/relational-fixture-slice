# Design

Development version 0.1.0 separates relational reasoning from transport. PostgreSQL owns catalog validation, key traversal and explanation tables. Python owns COPY streams, finite manifest validation, generated supported DDL, filesystem publication and the two-cluster laboratory. There is no runtime model/API dependency.

## Snapshot and structure

The transport discovers at most 33 source table names in autocommit, then begins REPEATABLE READ. It sets local timeouts and issues catalog-quoted `LOCK TABLE ONLY ... IN SHARE UPDATE EXCLUSIVE MODE` before any snapshot-taking query. LOCK is a no-snapshot utility statement. `fixture.plan` is the first snapshot-taking query, discovers metadata again, requires corresponding already-held locks and re-locks/revalidates before application row reads.

A table missing under its discovered name fails rather than being guessed around. A newly visible ordinary table without a prelock produces SCHEMA_CHANGED. Unsupported relation kinds are rejected. The schema represented is the one visible at this transaction's first snapshot; later unrelated objects are not added. Structural changes to locked tables are blocked, while ordinary RowExclusive row updates remain compatible. This is one database snapshot, not a cross-database or filesystem snapshot.

Direct SQL callers must follow the same pre-snapshot lock protocol and set their timeouts before calling. Merely acquiring locks after taking an earlier snapshot is not a substitute. Locks remain until transaction end.

## Closure

The selected set has primary key `(table_oid, pk)`. Seeds are verified before insertion. Each unprocessed selected row has each outgoing FK inspected; nonnull references are verified and inserted with conflict suppression. Every edge records a reason even if its target was already visited. A processed flag terminates cycles. Shared parents contribute one row, not one row per child. Incoming FKs are never traversed.

The function statement is atomic. A failed plan exposes no partial new temporary tables. Rollback to a savepoint restores an earlier successful plan, including its reasons. Successful planning replaces it. All plan tables are ON COMMIT DROP. Internal PostgreSQL FK constraint triggers are intentionally allowed; rejecting all pg_trigger rows would incorrectly reject supported schemas.

## Transport and publication

Tables sort by UTF-8 identifier order, rows by bigint PK and columns by catalog ordinal. Empty tables remain for closed FK DDL. PostgreSQL COPY handles CSV parsing/quoting. The transport sets local standard_conforming_strings so `\N` always denotes the intended null marker, regardless of incoming session configuration.

Python validates finite seed shapes before JSON serialization. During export it checks aggregate bytes before writing each chunk and hashes the same bytes written. All CSVs and the typed manifest are completed and file-fsynced in a private adjacent stage. After source commit, the stage directory is fsynced, then Linux renameat2 RENAME_NOREPLACE publishes it. No check-then-overwrite emulation is used.

Atomic visibility is not power-loss durability: the parent directory is not fsynced. A crash can leave private stages. Normal failure checks the created stage's device, inode and owner and cleans only that exact stage, never a prefix-based sweep.

## Restore

The manifest contains only four built-in types, one PK and finite FK metadata. Names go through psycopg Identifier; type/action/match keywords come from fixed maps. No SQL is read from bundles. Files are opened relative to a directory FD with O_NOFOLLOW; regular singly-linked files are required. Hashing consumes the same stream sent into COPY.

Directory enumeration stops on an unexpected name and retains at most the expected 33 names. The exclusively used target must be object-empty, including schema objects other than relations/types/functions. The catalog dependency check covers additional objects such as collations.

CREATE TABLE, ADD FOREIGN KEY, COPY, byte/hash/count verification and SET CONSTRAINTS ALL IMMEDIATE share one transaction. Creating deferrable FKs before loading supports cycles without disabling validation. Import failure rolls back fixture tables and an initially absent schema. Auxiliary storage/index options and database locale are not regenerated.

## Direct-child ownership

The lab is deliberately not a general process-tree supervisor. It accepts only fixed internal PostgreSQL commands; lifecycle tests use a separate fixed helper. No shell, pg_ctl daemonization or remote service management is involved.

The dedicated process requires default SIGCHLD disposition and a single reaper. Popen objects are retained; pidfds are opened only for these unreaped direct children. This avoids the unsafe pattern of reading a descendant PID and opening a pidfd after its parent may have reaped it and the kernel reused the number. A numeric /proc child list is only a bounded veto against cleanup, never signal authority.

SIGINT requests fast shutdown of the two direct postmasters. WNOWAIT observes their status without reaping. Only still-live direct children receive final SIGKILL. Pidfds are closed and signaling authority permanently revoked before status-consuming waits. Direct waits are nonblocking once exit was observed. Adopted descendants receive no signals; bounded nonblocking reaping waits for natural termination. Every observed exit status must be zero for normal success, and the final direct/adopted list must be empty.

Output pipes bound queued diagnostics. Polling drains bounded chunks into files capped at 64 KiB, discarding excess. Child commands, startup, shutdown observations, child-list reads and adopted-child loops all have finite bounds.

An uncertain shutdown preserves the private namespace and raises CLEANUP with its path. No TemporaryDirectory finalizer can subsequently delete that datadir. The enclosing isolated environment is the ultimate teardown boundary; native failed runs require caller-managed namespace disposal. Zero remaining observable children under the dedicated/single-reaper assumptions is the cleanup criterion, not a claim to supervise arbitrary daemon trees.

## Packaging

Trusted install/demo SQL is included as installation data under the virtual environment's share directory. A finite resource locator also supports a source checkout. The demo's independent SQL checks live in the demo module, not in uninstalled test files. Bundle inputs never select resource names.

References: PostgreSQL 17 [recursive queries](https://www.postgresql.org/docs/17/queries-with.html), [constraint timing](https://www.postgresql.org/docs/17/sql-set-constraints.html), [COPY](https://www.postgresql.org/docs/17/sql-copy.html), and [isolation](https://www.postgresql.org/docs/17/transaction-iso.html).
