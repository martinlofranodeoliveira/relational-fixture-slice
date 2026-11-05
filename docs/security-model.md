# Security model

Development 0.1.0 assumes synthetic data, trusted repository installation and database roles, trusted parent directories and no hostile concurrent filesystem writers. Use an exclusively controlled target schema. The CLI connects only to two clusters it creates. The Python API accepts application-owned connections and cannot determine whether their data are sensitive.

## Defenses

- SECURITY INVOKER, fixed function search_path and no PUBLIC execute grant.
- Catalog identifiers quoted with PostgreSQL `%I` and psycopg Identifier.
- Supported metadata validation before row reads; finite selected/explanation sets.
- Python seed type/count/range validation before JSON serialization.
- No arbitrary predicates, bundle SQL, COPY PROGRAM, server filenames or extension loading.
- Finite typed manifest and fixed keyword maps; index-generated filenames.
- Duplicate-key/type checks and manifest/CSV byte limits.
- No-follow relative opens, regular/single-link checks, no symlink ancestors and bounded expected-name enumeration.
- Same-stream hashing and explicit transactional FK checking. Hashes are not authorization.
- Atomic no-overwrite publication and cleanup of only the identified owned stage.
- Target-namespace dependency checks, including nonrelation objects.
- Direct-child-only pidfds, WNOWAIT observation, signal-before-reap shutdown and permanent revocation of signal authority before reaping.

## Process authority and preservation

The lab requires a dedicated non-root Linux process, default SIGCHLD disposition and no competing reaper. It retains direct Popen objects and opens pidfds only while they are unreaped direct children. It never opens a pidfd based on a descendant PID read from /proc: a postmaster can reap its backend and that PID can be reused before a later open. A retained postmaster does not retain all its descendants.

Only this process's bounded direct/adopted child list is read, solely to veto file cleanup. No recursive process tree or machine-wide enumeration exists. Adopted descendants are never signaled. After bounded direct shutdown, all pidfds are closed and authority is revoked before status-consuming waits. Normal success requires zero observed exit statuses and an empty final child list.

Uncertain shutdown raises CLEANUP and preserves the private namespace. There is no automatic finalizer deletion or broad recovery sweep. The enclosing isolated environment is the ultimate teardown boundary. Native failed runs require caller-managed namespace disposal before data removal. This intentionally fails closed instead of claiming arbitrary descendant cleanup.

## Boundaries

Payload is copied verbatim. This package does not find secrets, anonymize or authorize data. Do not use private/production databases. PostgreSQL superusers and attackers able to modify trusted directories can violate assumptions; O_NOFOLLOW is not a hostile-writer sandbox.

Logical row, metadata and serialized-byte limits are not hard RSS or filesystem quotas. An individual PostgreSQL row can consume memory before the byte cap is observed. Statement timeouts are per statement, not a whole-job deadline or response-time SLA. Fixed-child deadlines, bounded logs and child-list budgets do not turn the lab into a general service supervisor.

Column types/nullability and supported PK/FK semantics are preserved, not arbitrary metadata, database locale or physical storage settings. Atomic publication is not crash-durable backup. Killed processes can leave their own stages or namespaces; no prefix-based deletion facility is provided.

Report vulnerabilities privately through [SECURITY.md](../SECURITY.md). Do not include real records or credentials.
