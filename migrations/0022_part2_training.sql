BEGIN;
CREATE TABLE IF NOT EXISTS part2_issues (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 owner bigint NOT NULL REFERENCES users(telegram_user_id),
 number smallint NOT NULL CHECK (number BETWEEN 20 AND 25),
 task_id text NOT NULL, version integer NOT NULL, subtype_id text NOT NULL REFERENCES part2_subtypes,
 issued_at timestamptz NOT NULL DEFAULT now(), touched_at timestamptz NOT NULL DEFAULT now(),
 closed boolean NOT NULL DEFAULT false, hints integer NOT NULL DEFAULT 0 CHECK (hints BETWEEN 0 AND 2),
 revision integer NOT NULL DEFAULT 1,
 FOREIGN KEY (task_id,version) REFERENCES part2_versions
);
CREATE UNIQUE INDEX IF NOT EXISTS part2_open_number ON part2_issues(owner,number) WHERE NOT closed;
CREATE INDEX IF NOT EXISTS part2_recent ON part2_issues(owner,number,issued_at);
CREATE TABLE IF NOT EXISTS part2_work (
 issue_id bigint NOT NULL REFERENCES part2_issues, revision integer NOT NULL,
 message_id bigint NOT NULL, media_group text, body text, photo text, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(issue_id,message_id)
);
CREATE INDEX IF NOT EXISTS part2_work_album ON part2_work(media_group) WHERE media_group IS NOT NULL;
ALTER TABLE part2_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE part2_work ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON part2_issues, part2_work FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON part2_issues, part2_work FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON part2_issues, part2_work FROM authenticated;
    END IF;
END $$;

COMMIT;
