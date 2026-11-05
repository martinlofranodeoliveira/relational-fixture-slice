# Synthetic examples

These examples refer to `sql/demo_data.sql` in an isolated source. Install `sql/install.sql` first. No defaults or generated values are needed: every fixture key and payload is explicit.

## Explain why a parent was included

Inside the documented locked REPEATABLE READ transaction:

```sql
SELECT fixture.plan('sample', '[{"table":"task","pk":100},{"table":"task","pk":101}]'::jsonb, 10000);
SELECT target.name AS selected_table, r.pk, r.kind,
       origin.name AS from_table, r.from_pk, r.constraint_name
FROM pg_temp.rf_reasons r
JOIN pg_temp.rf_tables target ON target.table_oid=r.table_oid
JOIN pg_temp.rf_tables origin ON origin.table_oid=r.from_oid
ORDER BY selected_table, r.pk, from_table, r.from_pk;
```

Two task seed reasons, two task-to-project reasons and one project-to-organization reason explain four selected rows. The common project is selected once. Reasons describe graph edges, not just a single spanning tree.

## Forward closure, not child expansion

```sql
SELECT fixture.plan('sample', '[{"table":"project","pk":10}]'::jsonb, 10000);
SELECT t.name, c.row_count FROM pg_temp.rf_tables t
JOIN pg_temp.rf_counts c USING(table_oid) ORDER BY t.name;
```

Counts: node 0, organization 1, project 1, task 0. All four table definitions remain representable in a bundle, but no task rows are pulled in.

## Cycle and null

Seed node 7: select node 7 and node 8, then stop. Import creates the FK as deferrable, loads both rows and explicitly checks constraints. Seed task 103: select only task 103; its project_id remains SQL NULL and its title is the literal text `\N`, not SQL NULL.

## A bounded rejection

```sql
SAVEPOINT bounded_attempt;
SELECT fixture.plan('sample', '[{"table":"task","pk":100}]'::jsonb, 2);
ROLLBACK TO SAVEPOINT bounded_attempt;
```

The SELECT raises a message beginning ROW_CAP. The rollback line is executed by a client handling that error; it is not a promise that every SQL client continues automatically after errors. No new partial plan is visible. Python export performs rollback and removes only its own stage. It never publishes a two-row prefix of the required three-row closure.

## Snapshot demonstration

`python3 bin/fixture_slice.py demo --assert` exports after planning task 100, while a second private source connection updates project 10 to organization 2. The source snapshot still contains organization 1. Independent target SQL checks the restored three-row join and verifies no organization-2 row. This demonstrates database MVCC, not storage-wide snapshotting.
