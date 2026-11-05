DO $$
BEGIN
    IF (SELECT count(*) FROM restored.node) <> 2 OR NOT EXISTS (
        SELECT FROM restored.node a JOIN restored.node b ON b.id=a.next_id
        WHERE a.id=7 AND b.id=8 AND b.next_id=7 AND a.label='seven' AND b.label='eight'
    ) THEN
        RAISE EXCEPTION 'independent assertion: two-node cycle';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_constraint WHERE conrelid='restored.node'::regclass
          AND conname='node_next_fk' AND contype='f' AND condeferrable AND condeferred AND convalidated
          AND confmatchtype='f'
    ) THEN
        RAISE EXCEPTION 'independent assertion: deferred validated MATCH FULL constraint';
    END IF;
END;
$$;
