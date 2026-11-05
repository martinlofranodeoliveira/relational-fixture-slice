# Relational Fixture Slice

Development version **0.1.0**, by [Lofrano Tecnologia](https://lofranotecnologia.com.br). Original SQL and a small psycopg transport/laboratory, licensed MIT. Repository: [martinlofranodeoliveira/relational-fixture-slice](https://github.com/martinlofranodeoliveira/relational-fixture-slice).

Extract a bounded PostgreSQL 17 fixture from explicit primary keys, follow **outgoing** foreign keys, and restore CSV plus regenerated supported DDL into a separate empty schema. Task 100 includes its project and organization, not sibling task 101. This deliberately narrow development tool is not a general backup or anonymizer.

## Install and run

The qualified hash lock targets non-root Linux amd64 and CPython 3.11. Use Python 3.11+, and PostgreSQL **17** tools at `/usr/lib/postgresql/17/bin`. The laboratory requires `/proc`, pidfds, child-subreaper support and `renameat2`. Run it in a dedicated process with default SIGCHLD disposition, no other reaper and no unrelated children. Do not parallelize tests.

From the repository root, in an unprivileged writable directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
. .venv/bin/activate
python3 tests/run.py
python3 bin/fixture_slice.py demo --assert
python3 bin/fixture_slice.py demo --assert --json
```

To install the Python package and its trusted SQL scripts in that virtual environment:

```sh
.venv/bin/python -m pip install .
```

The scripts are installed under the environment's `share/relational-fixture-slice/sql` directory. `fixture_slice.resources.read_sql('install.sql')` reads the trusted installation script. The demo does not load files from the test suite.

Dependency installation uses the configured Python package index. Tests and demo are subsequently offline: no model/API, telemetry, external listeners, installed database, Docker socket or credentials. Normal successful runs stop both private clusters, verify child statuses, and remove their temporary namespace. **Uncertain shutdown is a failure that preserves the namespace**, reports its path and requires disposal of the enclosing isolated environment before removal. There is no arbitrary descendant-killing facility.

CI uses the pinned PostgreSQL 17 bookworm image digest recorded in [testing](docs/testing.md), prepares Python, and runs tests as the unprivileged `postgres` account. The runner reports actual Python, psycopg, PostgreSQL tool and server versions. Native runs explicitly report when no image digest was supplied.

## Example output

The deterministic human-readable prefix is:

```text
Relational Fixture Slice — development 0.1.0
task-100: 3 rows; verified
shared-parent: 4 rows; verified
project-only: 2 rows; verified
null-reference: 1 rows; verified
cycle: 2 rows; verified
snapshot: 3 rows; verified
row-cap: ROW_CAP; rollback verified
composite: UNSUPPORTED_SCHEMA; rollback verified
corrupt-reference: FOREIGN_KEY; rollback verified
```

A JSON report follows; `--json` prints only that report. It includes per-table counts, six successful cases and three expected rejections. Version qualification appears in the test runner, not deterministic demo output. These are output examples, not a claim of an executed test run.

## Small SQL example

Install `sql/install.sql` on the synthetic source as the planning role. The function is SECURITY INVOKER and PUBLIC execution is revoked. Run `sql/demo_data.sql` only in an isolated synthetic database.

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '5s';
LOCK TABLE ONLY sample.organization, ONLY sample.project,
           ONLY sample.task, ONLY sample.node IN SHARE UPDATE EXCLUSIVE MODE;
SELECT fixture.plan('sample', '[{"table":"task","pk":100}]'::jsonb, 10000);
SELECT t.name, s.pk FROM pg_temp.rf_selected s
JOIN pg_temp.rf_tables t USING (table_oid) ORDER BY t.name, s.pk;
SELECT * FROM pg_temp.rf_counts;
SELECT * FROM pg_temp.rf_reasons;
COMMIT;
```

Obtain the table list before BEGIN. Locks must precede the transaction's first snapshot: do not issue a catalog SELECT inside this transaction before locking. The Python transport implements discovery, locking and revalidation.

## Small Python example

```python
from fixture_slice.bundle import export_bundle, import_bundle

# Idle autocommit psycopg connections to separate synthetic PG17 databases.
# 'bundles' already exists, is trusted, and has no symlink ancestors.
report = export_bundle(source, 'sample', [{'table': 'task', 'pk': 100}], 'bundles/task-100')
restored = import_bundle(target, 'restored', 'bundles/task-100')
print(report['rows'], restored['rows'])  # 3 3
```

Without package installation, run from the checkout with `src` on Python's import path. The CLI intentionally exposes neither arbitrary connection strings nor SQL selectors. Integrations own their connections and data authorization.

## Contract and rationale

Supported: ordinary permanent tables, one nondeferrable bigint PK, nullable or nonnullable single-bigint deferrable FKs targeting supported PKs, and bigint/integer/text/boolean columns. Nullability, FK match/actions and initial deferral are preserved. Internal FK triggers are accepted; user triggers are rejected. Defaults, identities, generated columns, CHECKs, extra indexes/constraints, RLS, partitions, inheritance, arrays and user-defined types are rejected before export.

Defaults: 10,000 aggregate selected rows, 16 MiB aggregate CSV and five seconds per transport SQL statement. Further budgets bound seeds, tables, columns, FKs, explanations and manifest bytes. PostgreSQL COPY and maintained psycopg handle NULL, empty strings, quotes, newlines and Unicode. The COPY null marker is independent of the caller's string-literal setting.

One source REPEATABLE READ transaction and structural locks protect the database snapshot while allowing concurrent row updates. A visited `(OID, PK)` set terminates cycles and deduplicates shared parents. Import executes no bundle SQL: it regenerates finite supported DDL and validates data and deferred FKs in one transaction. Atomic no-overwrite publication occurs only after successful export.

See [contract](docs/contract.md), [design](docs/design.md), [manifest](docs/manifest.md), [examples](docs/examples.md) and [security model](docs/security-model.md).

## Limitations

Not general PostgreSQL cloning, broad standards compliance, a cross-database/filesystem snapshot, hard disk/RSS quota, crash-durable backup or production-readiness claim. Zero-row tables remain represented for FK DDL. Permissions, owners, comments, sequences, functions, physical storage settings and database locale are not cloned. Use a trusted bundle parent and exclusively controlled target schema; hostile concurrent filesystem writers and privileged database administrators are outside the boundary. Payload is not anonymized. All bundled records are synthetic.

[Português](README.pt-BR.md) · [Contributing](CONTRIBUTING.md) · [Security reports](SECURITY.md)

The committed `requirements.lock` records the real resolver-selected CPython 3.11 Linux amd64 wheels, verified against official PyPI SHA-256 metadata. Other interpreters/platforms need a separate intentional resolution; they are not qualified by this lock.
