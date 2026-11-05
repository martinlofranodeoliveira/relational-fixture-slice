# Bundle format 1

Product development version: 0.1.0. The on-disk format version is integer `1`; these are separate version namespaces.

A bundle is one directory containing `manifest.json` and `t000.csv`, `t001.csv` and subsequent canonical files, one per schema table, including empty tables. There are no SQL files. Extra entries are rejected. Files must be regular, not symlinks or multiply linked files. Bundle ancestor directories must not be symlinks.

The manifest is UTF-8 JSON, at most 1 MiB. Duplicate keys, unknown fields, invalid UTF-8, nonfinite numbers, incorrect boolean/integer types and inconsistent totals are rejected. Table names are unique and sorted by Unicode code point, equivalent to UTF-8 byte order. Identifiers are nonempty UTF-8, NUL-free and at most 63 bytes; punctuation is permitted and quoted as an identifier, never interpreted as SQL.

Exact root fields:

- `format`: `relational-fixture-slice`.
- `version`: integer 1.
- `encoding`: `UTF8`.
- `tables`: 1..32 table objects.
- `total_rows`: sum of per-table rows, 0..10000.
- `total_bytes`: sum of per-file bytes, 0..16777216.

Exact table fields:

- `name`, `pk`, `pk_name`: table name, PK column name and PK constraint name.
- `columns`: ordered objects with exactly `name`, `type`, `not_null`. Types are `bigint`, `integer`, `text`, `boolean`. Nullability is a JSON boolean. The designated PK must be bigint and nonnullable.
- `foreign_keys`: objects with exactly `name`, `column`, `target_table`, `target_column`, `match`, `on_update`, `on_delete`, `initially_deferred`.
- `file`: exactly `tNNN.csv` for that table's zero-based index.
- `rows`, `bytes`: nonnegative integer claims within aggregate budgets.
- `sha256`: 64 lowercase hexadecimal characters over the exact CSV bytes.

FK match codes are `s` SIMPLE and `f` FULL. Action codes are `a` NO ACTION, `r` RESTRICT, `c` CASCADE, `n` SET NULL, `d` SET DEFAULT. Every FK is deferrable; initial deferral is a separate boolean. Referenced columns must be the designated target PK. Constraint names must be unique per table, including the PK.

CSV uses PostgreSQL COPY with FORMAT CSV, default comma delimiter/double-quote escaping, NULL `\N`, UTF8 encoding and no header. Literal `\N` text is quoted by PostgreSQL, distinguishing it from null. Empty strings, embedded newlines and double quotes retain their values. Export rows are ordered by PK. Import does not require that order: PK uniqueness, exact counts and all FKs are validated in the target transaction.

The SHA-256 and size are checked while streaming the same bytes into COPY. They are integrity claims, not signatures. An attacker can rehash a malformed reference; deferred FK validation must still reject it. This is an explicit regression test. CSV parsing remains PostgreSQL's responsibility through psycopg COPY, not a second homemade CSV grammar.
