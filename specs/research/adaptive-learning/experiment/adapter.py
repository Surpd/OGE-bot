"""SQLite research adapter. The bot/server authenticates the learner and grades answers.
A callback supplies a slot id and revision, never an answer classification, clock or scope.
"""

import sqlite3
from contextlib import contextmanager

from model import Engine, Event

DDL = """
CREATE TABLE IF NOT EXISTS slot (
    id INTEGER PRIMARY KEY,
    learner TEXT NOT NULL,
    skill INTEGER NOT NULL,
    family INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('training','exam')),
    revision INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    seen_before INTEGER NOT NULL DEFAULT 0,
    check_eligible INTEGER NOT NULL,
    help TEXT NOT NULL DEFAULT '',
    errors INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS active_learner ON slot(learner) WHERE active=1;
CREATE INDEX IF NOT EXISTS exposure ON slot(learner,snapshot);
CREATE TABLE IF NOT EXISTS inbox(update_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS event(
    seq INTEGER PRIMARY KEY,
    update_id TEXT NOT NULL UNIQUE,
    slot_id INTEGER NOT NULL REFERENCES slot(id),
    day INTEGER NOT NULL,
    raw_action TEXT NOT NULL,
    outcome TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON event
BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON event
BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


class Adapter:
    def __init__(self, path, eligible):
        self.eligible = frozenset(eligible)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(DDL)

    @contextmanager
    def _write(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def issue(self, learner, skill, family, snapshot, mode="training", *, check_eligible=False):
        """Research allowlist mirrors a server-side eligibility decision for (skill, family)."""
        if (skill, family) not in self.eligible:
            raise ValueError("unavailable family")
        with self._write():
            active = self.db.execute(
                "SELECT id,skill,family,mode FROM slot WHERE learner=? AND active=1", (learner,)
            ).fetchone()
            if active:
                if (active["skill"], active["family"]) in self.eligible:
                    if active["mode"] != mode:
                        raise ValueError("resume or close the active mode first")
                    return active["id"]
                self.db.execute("UPDATE slot SET active=0 WHERE id=?", (active["id"],))
            seen = self.db.execute(
                "SELECT 1 FROM slot WHERE learner=? AND snapshot=? LIMIT 1",
                (learner, snapshot),
            ).fetchone()
            return self.db.execute(
                "INSERT INTO slot(learner,skill,family,snapshot,mode,seen_before,check_eligible) "
                "VALUES(?,?,?,?,?,?,?)",
                (learner, skill, family, snapshot, mode, int(bool(seen)), int(check_eligible)),
            ).lastrowid

    def record(self, learner, slot_id, rev, update_id, utc_seconds, action):
        """Inputs action and time are trusted server values; times are Unix UTC."""
        if action not in {"hint", "solution", "error", "correct", "skip"}:
            raise ValueError(action)
        with self._write():
            delivered = self.db.execute(
                "INSERT OR IGNORE INTO inbox(update_id) VALUES(?)", (update_id,)
            )
            if not delivered.rowcount:
                return False
            slot = self.db.execute(
                "SELECT * FROM slot WHERE id=? AND learner=? AND revision=? AND active=1",
                (slot_id, learner, rev),
            ).fetchone()
            if not slot or (slot["skill"], slot["family"]) not in self.eligible:
                return False
            if slot["mode"] == "exam" and action in {"hint", "solution"}:
                return False
            help_used = slot["help"]
            errors = slot["errors"]
            outcome = action
            if action == "correct":
                if help_used:
                    outcome = help_used
                elif errors or slot["seen_before"]:
                    outcome = "retry"
                else:
                    outcome = "clean"
            elif action in {"hint", "solution"}:
                help_used = "solution" if "solution" in (help_used, action) else "hint"
            elif action == "error":
                errors += 1
            if action == "error" and slot["seen_before"]:
                outcome = "retry"
            if outcome in {"clean", "error"} and not slot["check_eligible"]:
                outcome = "unknown"
            self.db.execute(
                "INSERT INTO event(update_id,slot_id,day,raw_action,outcome) VALUES(?,?,?,?,?)",
                (update_id, slot_id, int(utc_seconds) // 86400, action, outcome),
            )
            self.db.execute(
                "UPDATE slot SET active=?, revision=revision+1, help=?, errors=? WHERE id=?",
                (int(action not in {"correct", "skip"}), help_used, errors, slot_id),
            )
            return True

    def replay(self, learner, skills, policy="rules"):
        engine = Engine(policy=policy, skills=skills)
        rows = self.db.execute(
            "SELECT e.update_id,e.day,s.skill,s.snapshot,s.family,e.outcome "
            "FROM event e JOIN slot s ON s.id=e.slot_id WHERE s.learner=? ORDER BY e.seq",
            (learner,),
        )
        for row in rows:
            engine.apply(Event(*tuple(row)))
        return engine
