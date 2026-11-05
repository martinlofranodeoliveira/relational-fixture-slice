CREATE SCHEMA sample;
CREATE TABLE sample.organization (
    id bigint CONSTRAINT organization_pk PRIMARY KEY,
    label text NOT NULL
);
CREATE TABLE sample.project (
    id bigint CONSTRAINT project_pk PRIMARY KEY,
    organization_id bigint NOT NULL,
    label text,
    CONSTRAINT project_organization_fk FOREIGN KEY (organization_id)
        REFERENCES sample.organization(id) MATCH SIMPLE ON UPDATE CASCADE ON DELETE RESTRICT
        DEFERRABLE INITIALLY IMMEDIATE
);
CREATE TABLE sample.task (
    id bigint CONSTRAINT task_pk PRIMARY KEY,
    project_id bigint,
    title text,
    done boolean NOT NULL,
    effort integer,
    CONSTRAINT task_project_fk FOREIGN KEY (project_id)
        REFERENCES sample.project(id) MATCH SIMPLE ON UPDATE NO ACTION ON DELETE SET NULL
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE sample.node (
    id bigint CONSTRAINT node_pk PRIMARY KEY,
    next_id bigint,
    label text,
    CONSTRAINT node_next_fk FOREIGN KEY (next_id) REFERENCES sample.node(id)
        MATCH FULL ON UPDATE NO ACTION ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);
INSERT INTO sample.organization VALUES (1, E'Organização "A"\nline'), (2, 'Unused synthetic organization');
INSERT INTO sample.project VALUES (10, 1, ''), (20, 2, NULL);
INSERT INTO sample.task VALUES
    (100, 10, E'texto,"quoted"\nlinha — ação', false, -4),
    (101, 10, 'Another synthetic child', true, 0),
    (103, NULL, E'\\N', false, NULL),
    (104, NULL, NULL, true, 7);
BEGIN;
INSERT INTO sample.node VALUES (7, 8, 'seven'), (8, 7, 'eight');
COMMIT;
