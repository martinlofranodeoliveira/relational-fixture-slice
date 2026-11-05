CREATE SCHEMA bad;
CREATE TABLE bad.task (
    id bigint NOT NULL,
    part bigint NOT NULL,
    title text,
    PRIMARY KEY(id, part)
);
INSERT INTO bad.task VALUES (100, 1, 'Synthetic unsupported composite key');
