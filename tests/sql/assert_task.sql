DO $$
BEGIN
    IF (SELECT count(*) FROM restored.task) <> 1
       OR (SELECT count(*) FROM restored.project) <> 1
       OR (SELECT count(*) FROM restored.organization) <> 1
       OR (SELECT count(*) FROM restored.node) <> 0 THEN
        RAISE EXCEPTION 'independent assertion: exact three-row fixture';
    END IF;
    IF NOT EXISTS (
        SELECT FROM restored.task t JOIN restored.project p ON p.id=t.project_id
        JOIN restored.organization o ON o.id=p.organization_id
        WHERE t.id=100 AND p.id=10 AND o.id=1 AND p.label=''
          AND t.title=E'texto,"quoted"\nlinha — ação' AND NOT t.done AND t.effort=-4
          AND o.label=E'Organização "A"\nline'
    ) OR EXISTS(SELECT FROM restored.task WHERE id=101)
      OR EXISTS(SELECT FROM restored.organization WHERE id=2) THEN
        RAISE EXCEPTION 'independent assertion: values or forward closure';
    END IF;
END;
$$;
