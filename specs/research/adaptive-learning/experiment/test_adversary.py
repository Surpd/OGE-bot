"""Adversarial regression tests. Run: python -m unittest -v test_adversary."""

import random
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from adapter import Adapter
from model import Engine, Event

POLICIES = ("rules", "weighted", "bkt")


def put(engine, index, result, day=0, skill=0, family=None, snapshot=None):
    return engine.apply(
        Event(
            str(index),
            day,
            skill,
            snapshot if snapshot is not None else str(index),
            index % 2 if family is None else family,
            result,
        )
    )


def advance(engine):
    for index in range(6):
        put(engine, index, "clean")
    assert engine.skills[0].stage == "provisional"
    due = engine.skills[0].due
    put(engine, 6, "clean", due)
    assert engine.skills[0].stage == "confirmed"
    return due


class EvidenceTests(unittest.TestCase):
    def test_cold_start_skip_unknown_and_isolated_outcomes(self):
        for policy in POLICIES:
            for outcome in ("skip", "unknown", "error", "clean"):
                engine = Engine(policy, (0,))
                self.assertEqual(engine.queue(0), [0])
                put(engine, 0, outcome)
                self.assertIn(engine.skills[0].stage, {"unknown", "check"})
                self.assertFalse(engine.awards)
            self.assertEqual(Engine(policy, ()).queue(0), [])

    def test_assistance_retries_and_replay_farming(self):
        for policy in POLICIES:
            for first in ("hint", "solution", "error", "skip", "unknown", "retry"):
                engine = Engine(policy, (0,))
                for n in range(10):
                    put(engine, 2 * n, first, n, snapshot=str(n))
                    put(engine, 2 * n + 1, "clean", n, snapshot=str(n))
                self.assertNotIn(engine.skills[0].stage, {"provisional", "confirmed"})
                self.assertFalse(engine.awards)

    def test_same_item_or_one_family_is_insufficient(self):
        for policy in POLICIES:
            for fixed_item in (True, False):
                engine = Engine(policy, (0,))
                for n in range(35):
                    put(engine, n, "clean", n, family=0, snapshot="one" if fixed_item else str(n))
                self.assertFalse(engine.awards)
                self.assertNotIn(engine.skills[0].stage, {"confirmed", "provisional"})

    def test_delay_and_no_erase_on_calendar_or_lapse(self):
        for policy in POLICIES:
            engine = Engine(policy, (0,))
            due = advance(engine)
            first_awards = set(engine.awards)
            engine.queue(due + 150)
            self.assertEqual(engine.skills[0].stage, "confirmed")
            put(engine, 7, "error", due + 150)
            self.assertEqual(engine.skills[0].stage, "confirmed")
            for n in range(8, 18):
                put(engine, n, "error", due + 150)
            self.assertEqual(engine.skills[0].stage, "practice")
            self.assertEqual(first_awards, engine.awards)
            for n in range(18, 30):
                put(engine, n, "clean", due + 151 + n)
            self.assertEqual(first_awards, engine.awards)

    def test_repeated_event_preserves_history_and_achievement(self):
        for policy in POLICIES:
            engine = Engine(policy, (0,))
            advance(engine)
            initial = dict(engine.events)
            for event in tuple(initial.values()):
                self.assertFalse(engine.apply(event))
            self.assertEqual(initial, engine.events)
            self.assertEqual(engine.awards, {0})

    def test_old_prehistory_expires(self):
        engine = Engine("rules", (0,))
        put(engine, 0, "clean", 0)
        put(engine, 1, "clean", 0)
        put(engine, 2, "clean", 370)
        self.assertEqual(engine.skills[0].stage, "unknown")

    def test_volume_in_one_day_cannot_confirm(self):
        for policy in POLICIES:
            engine = Engine(policy, (0,))
            for n in range(100):
                put(engine, n, "clean")
            self.assertFalse(engine.awards)
            self.assertEqual(engine.skills[0].stage, "provisional")

    def test_overdue_cap_and_disabled_skills(self):
        engine = Engine(skills=tuple(range(80)))
        for key in engine.skills:
            engine.skills[key].due = 2
            engine.skills[key].stage = "confirmed"
        picks = engine.queue(500)
        self.assertLessEqual(len(picks), 2)
        self.assertEqual(len(set(picks)), len(picks))
        self.assertEqual(engine.queue(500, limit=0), [])
        self.assertNotIn(80, picks)

    def test_seeded_duplicate_and_extra_assistance_metamorphism(self):
        for seed in range(100):
            rng = random.Random(seed)
            policy = POLICIES[seed % 3]
            base, noisy = Engine(policy, (0, 1)), Engine(policy, (0, 1))
            for n in range(80):
                skill = rng.randrange(2)
                event = Event(
                    str(n),
                    n // 3,
                    skill,
                    str(n),
                    rng.randrange(3),
                    rng.choice(("clean", "error", "hint", "skip", "solution")),
                )
                base.apply(event)
                noisy.apply(event)
                noisy.apply(event)
                noisy.apply(Event("again" + str(n), n // 3, skill, str(n), event.family, "clean"))
                self.assertEqual(base.awards, noisy.awards)
                self.assertEqual(base.skills[skill].stage, noisy.skills[skill].stage)
                self.assertEqual(base.skills[skill].due, noisy.skills[skill].due)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "example.db")
        self.flags = {(0, 0), (0, 1)}
        self.a = Adapter(self.path, self.flags)
        self.slot = self.a.issue("alice", 0, 0, "original", check_eligible=True)

    def tearDown(self):
        self.a.db.close()
        self.tmp.cleanup()

    def count(self):
        return self.a.db.execute("SELECT COUNT(*) FROM event").fetchone()[0]

    def test_wrong_user_old_button_duplicate_update(self):
        self.assertFalse(self.a.record("bob", self.slot, 0, "bob", 0, "correct"))
        self.assertTrue(self.a.record("alice", self.slot, 0, "err", 0, "error"))
        self.assertFalse(self.a.record("alice", self.slot, 0, "stale", 0, "correct"))
        self.assertTrue(self.a.record("alice", self.slot, 1, "fix", 0, "correct"))
        self.assertFalse(self.a.record("alice", self.slot, 1, "fix", 0, "correct"))
        self.assertFalse(self.a.record("alice", self.slot, 2, "after", 0, "correct"))
        engine = self.a.replay("alice", (0,))
        self.assertEqual([e.outcome for e in engine.events.values()], ["error", "retry"])
        self.assertEqual(self.count(), 2)

    def test_resume_and_reissued_original_vs_new_analog(self):
        self.assertEqual(self.a.issue("alice", 0, 1, "other"), self.slot)
        self.a.record("alice", self.slot, 0, "first", 0, "skip")
        replay = self.a.issue("alice", 0, 0, "original", check_eligible=True)
        self.a.record("alice", replay, 0, "repeat", 86500, "correct")
        new = self.a.issue("alice", 0, 1, "unseen", check_eligible=True)
        self.a.record("alice", new, 0, "new", 86500, "correct")
        events = tuple(self.a.replay("alice", (0,)).events.values())
        self.assertEqual([e.outcome for e in events], ["skip", "retry", "clean"])
        self.assertEqual([e.day for e in events], [0, 1, 1])

    def test_solution_and_hint_then_answer(self):
        for n, kind in enumerate(("solution", "hint")):
            slot = self.slot if n == 0 else self.a.issue("alice", 0, 1, "next")
            self.a.record("alice", slot, 0, f"help{n}", 0, kind)
            self.a.record("alice", slot, 1, f"answer{n}", 0, "correct")
        events = tuple(self.a.replay("alice", (0,)).events.values())
        self.assertEqual([e.outcome for e in events], ["solution", "solution", "hint", "hint"])

    def test_exam_available_families_and_flag_switch(self):
        with self.assertRaises(ValueError):
            self.a.issue("alice", 0, 1, "new-exam", "exam")
        with self.assertRaises(ValueError):
            self.a.issue("alice", 0, 2, "disabled")
        exam = self.a.issue("bob", 0, 1, "exam", "exam")
        for n, action in enumerate(("hint", "solution")):
            self.assertFalse(self.a.record("bob", exam, 0, f"h{n}", 0, action))
        self.a.eligible = frozenset({(0, 0)})
        self.assertFalse(self.a.record("bob", exam, 0, "after-disable", 0, "correct"))
        fresh = self.a.issue("bob", 0, 0, "eligible", "exam")
        self.assertNotEqual(fresh, exam)
        self.assertTrue(self.a.record("bob", fresh, 0, "independent", 0, "correct"))

    def test_concurrent_answers_commit_once(self):
        barrier = threading.Barrier(2)

        def send(n):
            another = Adapter(self.path, self.flags)
            try:
                barrier.wait(timeout=5)
                return another.record("alice", self.slot, 0, str(n), 0, "correct")
            finally:
                another.db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(send, (0, 1))), [False, True])
        self.assertEqual(self.count(), 1)

    def test_failure_before_correct_has_no_reward_advantage(self):
        for learner, induced_error in (("honest", False), ("strategist", True)):
            for day in range(30):
                slot = self.a.issue(learner, 0, day % 2, str(day), check_eligible=True)
                if induced_error:
                    self.a.record(learner, slot, 0, learner + "e" + str(day), day * 86400, "error")
                self.a.record(
                    learner, slot, int(induced_error), learner + str(day), day * 86400, "correct"
                )
        self.assertEqual(self.a.replay("honest", (0,)).awards, {0})
        self.assertFalse(self.a.replay("strategist", (0,)).awards)

    def test_only_approved_checks_can_certify_even_if_all_guesses_correct(self):
        for day in range(90):
            slot = self.a.issue("guess", 0, day % 2, str(day))
            self.a.record("guess", slot, 0, "guess" + str(day), day * 86400, "correct")
        projected = self.a.replay("guess", (0,))
        self.assertFalse(projected.awards)
        self.assertEqual(projected.skills[0].stage, "unknown")
        raw = self.a.db.execute("SELECT count(*) FROM event WHERE raw_action='correct'").fetchone()
        self.assertEqual(raw[0], 90)

    def test_mid_transaction_failure_and_retry(self):
        self.a.db.executescript(
            "CREATE TRIGGER fail_update BEFORE UPDATE ON slot "
            "BEGIN SELECT RAISE(ABORT,'test failure'); END;"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.a.record("alice", self.slot, 0, "id", 0, "correct")
        self.assertEqual(self.count(), 0)
        self.a.db.execute("DROP TRIGGER fail_update")
        self.assertTrue(self.a.record("alice", self.slot, 0, "id", 0, "correct"))
        for statement in ("DELETE FROM event", "UPDATE event SET day=999"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.a.db.execute(statement)
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
