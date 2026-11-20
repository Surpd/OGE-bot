BEGIN;
CREATE TABLE IF NOT EXISTS part2_families (
    family_id text PRIMARY KEY, number smallint NOT NULL CHECK (number BETWEEN 20 AND 25),
    title text NOT NULL
);
CREATE TABLE IF NOT EXISTS part2_subtypes (
    subtype_id text PRIMARY KEY, family_id text NOT NULL REFERENCES part2_families,
    title text NOT NULL
);
CREATE TABLE IF NOT EXISTS part2_cards (
    task_id text PRIMARY KEY, subtype_id text NOT NULL REFERENCES part2_subtypes
);
CREATE TABLE IF NOT EXISTS part2_versions (
    task_id text REFERENCES part2_cards, version integer CHECK (version > 0),
    payload jsonb NOT NULL, digest text NOT NULL, available boolean NOT NULL DEFAULT false,
    PRIMARY KEY(task_id, version)
);
ALTER TABLE part2_families ENABLE ROW LEVEL SECURITY;
ALTER TABLE part2_subtypes ENABLE ROW LEVEL SECURITY;
ALTER TABLE part2_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE part2_versions ENABLE ROW LEVEL SECURITY;
COMMIT;
