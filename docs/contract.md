# Development 0.1.0 contract

This is a restricted PostgreSQL 17 subset, not general PostgreSQL schema cloning.

## SQL API

`fixture.plan(schema_name text, seeds_jsonb jsonb, row_cap integer DEFAULT 10000) RETURNS void` is SECURITY INVOKER with a fixed pg_catalog/pg_temp search path. Installation revokes PUBLIC execution. The installing role can use it; another role needs explicit schema USAGE, function EXECUTE, source SELECT, TEMP and privilege to take SHARE UPDATE EXCLUSIVE locks. Do not make it SECURITY DEFINER.

The caller owns one REPEATABLE READ transaction. Before its first snapshot, acquire SHARE UPDATE EXCLUSIVE on every ordinary source table using catalog-discovered, identifier-quoted names. Obtain that list before BEGIN. The Python transport implements this protocol and five-second statement/lock timeouts. Direct SQL callers must set their own timeouts before locking/calling; a timeout set inside the function would not bound its already-running statement. Calling without isolation or required locks fails with TRANSACTION or SCHEMA_CHANGED. Validation precedes application row reads.

Seeds are an array of 1..256 objects with exactly `table` and `pk`. The table is a table-name string; the key is a bigint-range integer. For direct JSONB calls, integer syntax is checked against PostgreSQL's JSONB textual representation, not the original JSON token spelling. Duplicate seeds are allowed. Numeric strings, fractions, booleans, extra fields and absent tables are rejected. Absent seed rows raise MISSING_SEED.

Least forward closure includes every seed and recursively referenced nonnull PK, once per table OID/key. Null adds nothing; incoming dependents are never included. An inconsistent missing referenced row is MISSING_REFERENCE.

Session-local outputs, all ON COMMIT DROP:

- `pg_temp.rf_tables(table_oid, name, pk, pk_name)`.
- `pg_temp.rf_columns(table_oid, ordinal, name, type, not_null)`.
- `pg_temp.rf_fks(table_oid, name, column_name, target_oid, target_table, target_column, match_type, on_update, on_delete, initially_deferred)`.
- `pg_temp.rf_selected(table_oid, pk, processed)`; keys are unique.
- `pg_temp.rf_counts(table_oid, row_count)`; includes zero counts.
- `pg_temp.rf_reasons(table_oid, pk, kind, from_oid, from_pk, constraint_name)`.

Seed reasons have kind `seed`, their own origin and an empty constraint name. FK reasons identify the referenced selected row, referencing origin and FK name. Reasons are unique by all fields. A failed statement publishes no partial new plan. Rollback to a savepoint preserves an earlier successful plan; success replaces it.

## Supported schema

One nonempty source schema, excluding fixture, information_schema and pg_* namespaces. 1..32 permanent ordinary tables; no inheritance, partitions, RLS, views, materialized/foreign tables, sequences, rewrite rules or secondary indexes. Exactly one single-column nondeferrable bigint PK per table, with NOT NULL. Columns may be bigint, integer, text or boolean, without typmods, arrays, defaults, identities, generated expressions or dropped-column slots. At most 64 columns/table and 512 total. User-defined source-namespace types are rejected except automatic table row/array types. Unsupported column types are rejected even when declared elsewhere. Unused functions are not exported.

Only PK/FK constraints are supported. No CHECK, UNIQUE, exclusion or other constraints. At most 128 FKs total. Every FK must be validated, deferrable, single-column bigint and reference a supported same-schema PK. Nullable and nonnullable FKs are supported. MATCH SIMPLE/FULL, all five update/delete actions, initial deferral and names are preserved. SET DEFAULT is accepted without a column default. Column-specific ON DELETE SET lists are rejected. User triggers are rejected; internal FK triggers are allowed. Checks include tables with zero selected rows.

Physical storage/index options, permissions, owners, comments, database locale and payload-column collation metadata are not cloned. The contract preserves the documented column types/nullability and PK/FK semantics, not arbitrary auxiliary PostgreSQL metadata.

## Limits and errors

Row cap: integer 1..10000, default 10000, aggregated across tables; overflow is ROW_CAP. Explanations: at most 20000, otherwise REASON_CAP. Aggregate CSV: 16 MiB, otherwise BYTE_CAP. Manifest: 1 MiB. Transport statement and lock timeouts: five seconds per statement, not a whole-job deadline. Source discovery fetches at most 33 table names before rejecting the table budget. Bundle enumeration rejects its first unexpected entry rather than materializing an arbitrary directory listing.

SQL errors use stable message prefixes, not custom SQLSTATEs. Python FixtureError has a `code`: domain prefixes above, INPUT, UNSUPPORTED_SCHEMA, MANIFEST, PATH, DIGEST, ROW_COUNT, TARGET_NOT_EMPTY, PUBLISH, VERSION, PLATFORM, TRANSACTION, DATABASE, FOREIGN_KEY, INSTALLATION and laboratory categories below. PostgreSQL diagnostic text after the category is not stable. Filesystem failures can raise OSError. CLI operation failure exits 1; interruption normally exits 130. A cleanup failure can supersede another error to report preserved resources. Connections roll back operation transactions on failure.

## Python transport and installation

`export_bundle(conn, schema, seeds, destination, row_cap=10000, *, after_plan=None)` returns rows/counts/reasons. `import_bundle(conn, schema, bundle)` returns rows/counts. Connections must be idle autocommit psycopg connections to UTF8 PG17 databases. Python seeds must be a list of plain dicts with string identifiers and plain int keys; bool/float are not integers here. Validation occurs before JSON serialization and staging.

Use separate synthetic source/target databases. The demo owns two clusters. The source remains in one REPEATABLE READ transaction through planning and COPY. The optional trusted in-process after_plan observation hook can demonstrate snapshot behavior; exceptions abort export. COPY uses STDIN/STDOUT, never server filenames or PROGRAM. Its null marker is `\N`, with local standard_conforming_strings enabled for the operation and the caller's setting restored at transaction end.

Destination must not exist. Its trusted parent already exists. Parent traversal and symlink ancestors are rejected. Publication is Linux atomic no-overwrite. Normal export failure cleans only its identified stage. Killed processes may leave stages; no recovery sweep exists.

Import accepts an absent or object-empty schema, exclusively used by the application. Relations, types, routines and other catalog objects depending on that namespace cause TARGET_NOT_EMPTY. All fixture DDL, COPY, counts/digests and deferred FK validation share one transaction. Failure leaves an initially empty schema with zero fixture tables; creation of an absent schema also rolls back. Hashes are integrity checks, not authenticity. No bundle SQL is executed.

The package includes trusted install/demo SQL under `share/relational-fixture-slice/sql` in a normal virtual-environment installation. `resources.read_sql` accepts only their two fixed filenames. A checkout also works. Relocatable `pip --target` layouts are not supported by this resource locator.

## Private laboratory ownership

The laboratory requires a dedicated non-root Linux process, default SIGCHLD disposition and no other child reaper. It initializes exactly two owned PG17 clusters with private Unix sockets and no TCP listeners. Fixed commands have 30-second execution deadlines; startup allows 15 seconds/server. At most two direct children are supervised at once; at most twelve live application connections are retained. Closed connections are discarded from that list.

Pidfds are obtained only for retained, unreaped direct Popen children. No descendant PID obtained from /proc grants signaling authority. Only this process's bounded direct/adopted child list is inspected, as a conservative cleanup veto. There is no recursive PID-tree walk or machine-wide process enumeration.

Shutdown sends SIGINT to direct children, observes them with WNOWAIT for up to five seconds, and sends SIGKILL only to remaining owned direct pidfds. A further two-second observation window follows. All signal authority is revoked and pidfds closed before any direct-child reap. Adopted children are never signaled: nonblocking waits allow up to one second for natural termination, with finite iteration/status budgets. Normal success requires actual zero direct/adopted exit statuses and an empty final child list. Nonzero statuses are CHILD_FAILED even when file cleanup is safe.

The local child-list read is at most 4096 bytes/64 entries; diagnostic files retain at most 64 KiB per child and pipes bound pending output. These are logical bounds, not hard disk/RSS quotas.

If termination cannot be verified, CLEANUP reports the preserved mode-0700 namespace. It is not removed automatically or by an object finalizer. Dispose of the enclosing isolated container/namespace before removing those data. A native caller must provide that disposal boundary after failed shutdown. No arbitrary descendant-cleanup claim is made. Other laboratory categories include OWNERSHIP, STARTUP, CHILD_LAUNCH, CHILD_TIMEOUT and LAB_LIMIT.
