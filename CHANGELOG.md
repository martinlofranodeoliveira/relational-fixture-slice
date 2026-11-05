# Changelog

## 0.1.0 — Unreleased

Development version; no release, deployment or executed-test claims.

- Add catalog-validated SQL planning for the single-bigint-PK PostgreSQL subset.
- Compute bounded least forward FK closure, counts and dependency reasons in session-local tables.
- Add snapshot-preserving COPY CSV export, typed format-1 manifests and atomic no-overwrite publication.
- Regenerate finite supported DDL and restore all data with deferred FK validation in one transaction.
- Restrict laboratory signal authority to retained unreaped direct-child pidfds; remove recursive descendant PID discovery.
- Bound child-list reads, diagnostic files, waits and adopted-child reaping; preserve namespaces when shutdown cannot be verified.
- Require actual zero child statuses for successful lifecycle completion.
- Pin psycopg 3.3.8 and the PostgreSQL 17 bookworm CI image digest; record actual runtime versions.
- Validate Python seeds before serialization and bound source discovery/bundle enumeration.
- Stabilize COPY null semantics across session string settings and detect nonrelation target-schema objects.
- Include trusted SQL installation data in package builds; remove demo dependence on test files.
- Strengthen adversarial lifecycle, quoted-identifier, savepoint, missing-reference, filesystem and rollback regressions.
- Document English/Portuguese usage, precise limits, failure preservation and security boundaries.
