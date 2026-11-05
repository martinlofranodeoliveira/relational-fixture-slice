CREATE SCHEMA IF NOT EXISTS fixture;

CREATE OR REPLACE FUNCTION fixture.plan(schema_name text, seeds_jsonb jsonb, row_cap integer DEFAULT 10000)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    ns oid;
    t record;
    c record;
    f record;
    s jsonb;
    tab oid;
    ident bigint;
    ref bigint;
    exists_row boolean;
    added integer;
    total integer := 0;
    reason_total integer := 0;
    todo record;
BEGIN
    IF current_setting('transaction_isolation') <> 'repeatable read' THEN
        RAISE EXCEPTION 'TRANSACTION: REPEATABLE READ is required';
    END IF;
    IF row_cap IS NULL OR row_cap < 1 OR row_cap > 10000 THEN
        RAISE EXCEPTION 'INPUT: row_cap must be 1..10000';
    END IF;
    IF seeds_jsonb IS NULL OR jsonb_typeof(seeds_jsonb) <> 'array' THEN
        RAISE EXCEPTION 'INPUT: seeds must be an array';
    END IF;
    IF jsonb_array_length(seeds_jsonb) NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'INPUT: supply 1..256 seeds';
    END IF;
    SELECT oid INTO ns FROM pg_namespace WHERE nspname = schema_name;
    IF ns IS NULL OR schema_name = 'fixture' OR schema_name = 'information_schema'
       OR left(schema_name, 3) = 'pg_' THEN
        RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: source namespace';
    END IF;
    IF (SELECT count(*) FROM pg_class WHERE relnamespace = ns AND relkind = 'r') NOT BETWEEN 1 AND 32 THEN
        RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: require 1..32 ordinary tables';
    END IF;
    IF EXISTS (SELECT FROM pg_class WHERE relnamespace = ns AND
        (relkind NOT IN ('r', 'i') OR relispartition OR relrowsecurity OR relforcerowsecurity
         OR relpersistence <> 'p')) THEN
        RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: relation kind, persistence, partition or RLS';
    END IF;
    IF EXISTS (
        SELECT FROM pg_type x WHERE x.typnamespace = ns
        AND x.typrelid NOT IN (SELECT oid FROM pg_class WHERE relnamespace = ns AND relkind = 'r')
        AND x.typelem NOT IN (SELECT reltype FROM pg_class WHERE relnamespace = ns AND relkind = 'r')
    ) THEN
        RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: user-defined type';
    END IF;

    -- The caller must acquire these locks before its first snapshot. Requiring them
    -- also prevents a newly discovered, unlocked table from silently entering a plan.
    FOR t IN SELECT oid, relname FROM pg_class WHERE relnamespace = ns AND relkind = 'r' ORDER BY oid LOOP
        IF NOT EXISTS (SELECT FROM pg_locks WHERE pid = pg_backend_pid()
            AND locktype = 'relation' AND relation = t.oid AND granted
            AND mode = 'ShareUpdateExclusiveLock') THEN
            RAISE EXCEPTION 'SCHEMA_CHANGED: pre-snapshot table lock required for %', t.relname;
        END IF;
        EXECUTE format('LOCK TABLE ONLY %I.%I IN SHARE UPDATE EXCLUSIVE MODE', schema_name, t.relname);
    END LOOP;

    DROP TABLE IF EXISTS pg_temp.rf_reasons, pg_temp.rf_selected, pg_temp.rf_fks,
        pg_temp.rf_columns, pg_temp.rf_counts, pg_temp.rf_tables;
    CREATE TEMP TABLE rf_tables (
        table_oid oid PRIMARY KEY, name text UNIQUE NOT NULL,
        pk text NOT NULL, pk_name text NOT NULL
    ) ON COMMIT DROP;
    CREATE TEMP TABLE rf_columns (
        table_oid oid NOT NULL, ordinal integer NOT NULL, name text NOT NULL,
        type text NOT NULL, not_null boolean NOT NULL, PRIMARY KEY(table_oid, ordinal)
    ) ON COMMIT DROP;
    CREATE TEMP TABLE rf_fks (
        table_oid oid NOT NULL, name text NOT NULL, column_name text NOT NULL,
        target_oid oid NOT NULL, target_table text NOT NULL, target_column text NOT NULL,
        match_type text NOT NULL, on_update text NOT NULL, on_delete text NOT NULL,
        initially_deferred boolean NOT NULL, PRIMARY KEY(table_oid, name)
    ) ON COMMIT DROP;
    CREATE TEMP TABLE rf_selected (
        table_oid oid NOT NULL, pk bigint NOT NULL, processed boolean NOT NULL DEFAULT false,
        PRIMARY KEY(table_oid, pk)
    ) ON COMMIT DROP;
    CREATE TEMP TABLE rf_reasons (
        table_oid oid NOT NULL, pk bigint NOT NULL, kind text NOT NULL,
        from_oid oid NOT NULL, from_pk bigint NOT NULL, constraint_name text NOT NULL,
        PRIMARY KEY(table_oid, pk, kind, from_oid, from_pk, constraint_name)
    ) ON COMMIT DROP;
    CREATE TEMP TABLE rf_counts (table_oid oid PRIMARY KEY, row_count bigint NOT NULL) ON COMMIT DROP;

    -- Re-discover and validate after all locks; no application row is read above.
    FOR t IN SELECT oid, relname FROM pg_class WHERE relnamespace = ns AND relkind = 'r' ORDER BY oid LOOP
        IF EXISTS (SELECT FROM pg_inherits WHERE inhrelid = t.oid OR inhparent = t.oid)
           OR EXISTS (SELECT FROM pg_trigger WHERE tgrelid = t.oid AND NOT tgisinternal)
           OR EXISTS (SELECT FROM pg_rewrite WHERE ev_class = t.oid)
           OR EXISTS (SELECT FROM pg_index WHERE indrelid = t.oid AND NOT indisprimary)
           OR EXISTS (SELECT FROM pg_constraint WHERE conrelid = t.oid AND contype NOT IN ('p', 'f'))
           OR EXISTS (SELECT FROM pg_attrdef WHERE adrelid = t.oid) THEN
            RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: constraints, indexes, inheritance, rules, triggers or defaults on %', t.relname;
        END IF;
        IF (SELECT count(*) FROM pg_attribute WHERE attrelid = t.oid AND attnum > 0) NOT BETWEEN 1 AND 64
           OR EXISTS (SELECT FROM pg_attribute WHERE attrelid = t.oid AND attnum > 0 AND
               (attisdropped OR atttypid NOT IN ('int8'::regtype, 'int4'::regtype, 'text'::regtype, 'bool'::regtype)
                OR atttypmod <> -1 OR attndims <> 0 OR attidentity <> '' OR attgenerated <> '' OR atthasdef)) THEN
            RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: columns on %', t.relname;
        END IF;
        IF (SELECT count(*) FROM pg_constraint WHERE conrelid = t.oid AND contype = 'p') <> 1 THEN
            RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: one primary key required on %', t.relname;
        END IF;
        SELECT p.conname, p.conkey, p.condeferrable, a.attname, a.atttypid, a.attnotnull
        INTO c FROM pg_constraint p
        JOIN pg_attribute a ON a.attrelid = p.conrelid AND a.attnum = p.conkey[1]
        WHERE p.conrelid = t.oid AND p.contype = 'p';
        IF cardinality(c.conkey) <> 1 OR c.condeferrable OR c.atttypid <> 'int8'::regtype OR NOT c.attnotnull THEN
            RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: nondeferrable single bigint primary key required';
        END IF;
        INSERT INTO rf_tables VALUES (t.oid, t.relname, c.attname, c.conname);
        INSERT INTO rf_columns
        SELECT t.oid, attnum, attname,
            CASE atttypid WHEN 'int8'::regtype THEN 'bigint' WHEN 'int4'::regtype THEN 'integer'
                WHEN 'text'::regtype THEN 'text' ELSE 'boolean' END, attnotnull
        FROM pg_attribute WHERE attrelid = t.oid AND attnum > 0 ORDER BY attnum;
    END LOOP;
    IF (SELECT count(*) FROM rf_columns) > 512 OR
       (SELECT count(*) FROM pg_constraint WHERE conrelid IN (SELECT table_oid FROM rf_tables) AND contype = 'f') > 128 THEN
        RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: metadata budget';
    END IF;
    FOR f IN SELECT * FROM pg_constraint WHERE conrelid IN (SELECT table_oid FROM rf_tables) AND contype = 'f' LOOP
        IF cardinality(f.conkey) <> 1 OR cardinality(f.confkey) <> 1 OR NOT f.condeferrable
           OR NOT f.convalidated OR f.confmatchtype NOT IN ('s', 'f')
           OR f.confupdtype NOT IN ('a', 'r', 'c', 'n', 'd') OR f.confdeltype NOT IN ('a', 'r', 'c', 'n', 'd')
           OR f.confdelsetcols IS NOT NULL
           OR NOT EXISTS (SELECT FROM rf_tables WHERE table_oid = f.confrelid)
           OR NOT EXISTS (SELECT FROM pg_constraint p WHERE p.conrelid = f.confrelid AND p.contype = 'p' AND p.conkey = f.confkey)
           OR NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid = f.conrelid AND attnum = f.conkey[1] AND atttypid = 'int8'::regtype) THEN
            RAISE EXCEPTION 'UNSUPPORTED_SCHEMA: foreign key %', f.conname;
        END IF;
        INSERT INTO rf_fks
        SELECT f.conrelid, f.conname, a.attname, f.confrelid, rt.name, rt.pk,
            f.confmatchtype, f.confupdtype, f.confdeltype, f.condeferred
        FROM pg_attribute a CROSS JOIN rf_tables rt
        WHERE a.attrelid = f.conrelid AND a.attnum = f.conkey[1] AND rt.table_oid = f.confrelid;
    END LOOP;

    FOR s IN SELECT value FROM jsonb_array_elements(seeds_jsonb) LOOP
        IF jsonb_typeof(s) <> 'object' THEN RAISE EXCEPTION 'INPUT: seed object required'; END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(s)) <> 2 OR NOT (s ? 'table' AND s ? 'pk')
           OR jsonb_typeof(s->'table') <> 'string' OR jsonb_typeof(s->'pk') <> 'number'
           OR (s->>'pk') !~ '^-?(0|[1-9][0-9]*)$' THEN
            RAISE EXCEPTION 'INPUT: seed requires table string and integer pk';
        END IF;
        IF (s->>'pk')::numeric NOT BETWEEN -9223372036854775808::numeric AND 9223372036854775807::numeric THEN
            RAISE EXCEPTION 'INPUT: bigint seed out of range';
        END IF;
        SELECT table_oid INTO tab FROM rf_tables WHERE name = s->>'table';
        IF tab IS NULL THEN RAISE EXCEPTION 'INPUT: unknown seed table'; END IF;
        ident := (s->>'pk')::bigint;
        SELECT * INTO t FROM rf_tables WHERE table_oid = tab;
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.%I WHERE %I = $1)', schema_name, t.name, t.pk)
            INTO exists_row USING ident;
        IF NOT exists_row THEN RAISE EXCEPTION 'MISSING_SEED: %.%', t.name, ident; END IF;
        INSERT INTO rf_selected(table_oid, pk) VALUES (tab, ident) ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS added = ROW_COUNT;
        total := total + added;
        IF total > row_cap THEN RAISE EXCEPTION 'ROW_CAP: selected rows exceed %', row_cap; END IF;
        INSERT INTO rf_reasons VALUES (tab, ident, 'seed', tab, ident, '') ON CONFLICT DO NOTHING;
    END LOOP;
    SELECT count(*) INTO reason_total FROM rf_reasons;
    LOOP
        SELECT * INTO todo FROM rf_selected WHERE NOT processed ORDER BY table_oid, pk LIMIT 1;
        EXIT WHEN NOT FOUND;
        UPDATE rf_selected SET processed = true WHERE table_oid = todo.table_oid AND pk = todo.pk;
        SELECT * INTO t FROM rf_tables WHERE table_oid = todo.table_oid;
        FOR f IN SELECT * FROM rf_fks WHERE table_oid = todo.table_oid ORDER BY name LOOP
            EXECUTE format('SELECT %I FROM %I.%I WHERE %I = $1', f.column_name, schema_name, t.name, t.pk)
                INTO ref USING todo.pk;
            IF ref IS NULL THEN CONTINUE; END IF;
            EXECUTE format('SELECT EXISTS (SELECT FROM %I.%I WHERE %I = $1)', schema_name, f.target_table, f.target_column)
                INTO exists_row USING ref;
            IF NOT exists_row THEN RAISE EXCEPTION 'MISSING_REFERENCE: %', f.name; END IF;
            INSERT INTO rf_selected(table_oid, pk) VALUES (f.target_oid, ref) ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS added = ROW_COUNT;
            total := total + added;
            IF total > row_cap THEN RAISE EXCEPTION 'ROW_CAP: selected rows exceed %', row_cap; END IF;
            INSERT INTO rf_reasons VALUES (f.target_oid, ref, 'fk', todo.table_oid, todo.pk, f.name) ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS added = ROW_COUNT;
            reason_total := reason_total + added;
            IF reason_total > 20000 THEN RAISE EXCEPTION 'REASON_CAP: dependency explanation budget'; END IF;
        END LOOP;
    END LOOP;
    INSERT INTO rf_counts SELECT rt.table_oid, count(rs.pk) FROM rf_tables rt
        LEFT JOIN rf_selected rs USING (table_oid) GROUP BY rt.table_oid;
END;
$$;
REVOKE ALL ON FUNCTION fixture.plan(text, jsonb, integer) FROM PUBLIC;
