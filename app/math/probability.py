"""Exact, Telegram-independent generators for verified OGE task 10 structures."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy, decimal_places

GENERATOR_VERSION = "0.1.0"
ANSWER_POLICY = AnswerPolicy(
    "oge10.probability-decimal",
    "1",
    AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=3,
    max_absolute_value=1,
)

DRAW_CATEGORY = "OGE10-F001-DRAW-CATEGORY"
COMPLEMENT = "OGE10-F002-COMPLEMENT"
EMPIRICAL = "OGE10-F006-EMPIRICAL-FREQUENCY"
DISJOINT_UNION = "OGE10-F007-DISJOINT-UNION-RESIDUAL"
REMAINDER_CATEGORY = "OGE10-F008-REMAINDER-CATEGORY"
OVERLAPPING_GROUP = "OGE10-F009-OVERLAPPING-GROUPS"

ENABLED_FAMILIES = (
    DRAW_CATEGORY,
    COMPLEMENT,
    REMAINDER_CATEGORY,
    DISJOINT_UNION,
    OVERLAPPING_GROUP,
    EMPIRICAL,
)

SOURCE_IDS: dict[str, tuple[str, ...]] = {
    DRAW_CATEGORY: ("132732", "311525"),
    COMPLEMENT: ("149", "132730"),
    REMAINDER_CATEGORY: ("132738",),
    DISJOINT_UNION: ("325580",),
    OVERLAPPING_GROUP: ("311512",),
    EMPIRICAL: ("132746", "132748"),
}

CountForms = tuple[str, str, str]

_CHIPS: CountForms = ("фишка", "фишки", "фишек")
_TICKETS: CountForms = ("билет", "билета", "билетов")
_FLASHLIGHTS: CountForms = ("фонарик", "фонарика", "фонариков")
_CABINS: CountForms = ("кабинка", "кабинки", "кабинок")
_MARKERS: CountForms = ("маркер", "маркера", "маркеров")
_PEOPLE: CountForms = ("человек", "человека", "человек")


def counted_phrase(
    count: int,
    noun_forms: CountForms,
    adjective_forms: CountForms | None = None,
) -> str:
    """Render a numeric noun phrase with Russian 1 / 2–4 / 5+ agreement."""
    if count < 0:
        raise ValueError("Count cannot be negative")
    last_two = count % 100
    last = count % 10
    if last == 1 and last_two != 11:
        form_index = 0
    elif 2 <= last <= 4 and not 12 <= last_two <= 14:
        form_index = 1
    else:
        form_index = 2
    pieces = [str(count)]
    if adjective_forms is not None:
        pieces.append(adjective_forms[form_index])
    pieces.append(noun_forms[form_index])
    return " ".join(pieces)


@dataclass(frozen=True, slots=True)
class ProbabilityProblem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_ids: tuple[str, ...]
    condition: str
    answer: Fraction
    correct_answer: str
    answer_policy_id: str
    answer_policy_version: str
    sample_space: tuple[frozenset[str], ...]
    event: dict[str, object]
    hints: tuple[str, str]
    solution: tuple[str, ...]
    fingerprint: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_ids": list(self.reference_ids),
            "condition": self.condition,
            "correct_answer": self.correct_answer,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "sample_space": [sorted(outcome) for outcome in self.sample_space],
            "event": self.event,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
        }


def _exact_answer(value: Fraction) -> str:
    places = decimal_places(value)
    if not 0 <= value <= 1 or places is None or places > ANSWER_POLICY.max_decimal_places:
        raise ValueError("Probability is outside the confirmed exact decimal answer policy")
    return ANSWER_POLICY.format(value)


def enumerate_probability(
    sample_space: tuple[frozenset[str], ...], event: dict[str, object]
) -> Fraction:
    """Independent oracle: enumerate equally likely records and evaluate a small event AST."""

    if not sample_space:
        raise ValueError("The outcome space must not be empty")

    def matches(outcome: frozenset[str], predicate: dict[str, object]) -> bool:
        kind = predicate.get("kind")
        if kind == "has":
            label = predicate.get("label")
            return isinstance(label, str) and label in outcome
        if kind == "not":
            inner = predicate.get("event")
            return isinstance(inner, dict) and not matches(outcome, cast(dict[str, object], inner))
        if kind == "or":
            terms = predicate.get("events")
            return isinstance(terms, list) and any(
                isinstance(term, dict) and matches(outcome, cast(dict[str, object], term))
                for term in terms
            )
        raise ValueError("Unsupported probability event AST")

    favorable = sum(matches(outcome, event) for outcome in sample_space)
    return Fraction(favorable, len(sample_space))


def _fingerprint(family_id: str, semantic_values: tuple[int, ...]) -> str:
    canonical = json.dumps([family_id, semantic_values], separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _problem(
    family_id: str,
    seed: int,
    condition: str,
    sample_space: tuple[frozenset[str], ...],
    event: Mapping[str, object],
    semantic_values: tuple[int, ...],
    hints: tuple[str, str],
    solution: tuple[str, ...],
) -> ProbabilityProblem:
    event_value = dict(event)
    answer = enumerate_probability(sample_space, event_value)
    rendered_answer = _exact_answer(answer)
    fingerprint = _fingerprint(family_id, semantic_values)
    return ProbabilityProblem(
        problem_id=str(uuid5(NAMESPACE_URL, f"oge10:{GENERATOR_VERSION}:{family_id}:{seed}")),
        seed=seed,
        generator_version=GENERATOR_VERSION,
        family_id=family_id,
        reference_ids=SOURCE_IDS[family_id],
        condition=condition,
        answer=answer,
        correct_answer=rendered_answer,
        answer_policy_id=ANSWER_POLICY.policy_id,
        answer_policy_version=ANSWER_POLICY.version,
        sample_space=sample_space,
        event=event_value,
        hints=hints,
        solution=solution,
        fingerprint=fingerprint,
    )


def _draw_category(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.randint(12, 100)
    first = rng.randint(1, total - 2)
    second = rng.randint(1, total - first - 1)
    third = total - first - second
    counts = {"red": first, "blue": second, "green": third}
    target = rng.choice(tuple(counts))
    space = tuple(frozenset({label}) for label, count in counts.items() for _ in range(count))
    event = {"kind": "has", "label": target}
    color_forms = {
        "red": ("красная", "красные", "красных"),
        "blue": ("синяя", "синие", "синих"),
        "green": ("зелёная", "зелёные", "зелёных"),
    }
    color_accusative = {"red": "красную", "blue": "синюю", "green": "зелёную"}[target]
    condition = (
        f"В наборе {counted_phrase(total, _CHIPS)}: "
        f"{counted_phrase(first, _CHIPS, color_forms['red'])}, "
        f"{counted_phrase(second, _CHIPS, color_forms['blue'])} и "
        f"{counted_phrase(third, _CHIPS, color_forms['green'])}. "
        "Наугад выбирают одну фишку. Найдите вероятность выбрать "
        f"{color_accusative} фишку."
    )
    value = Fraction(counts[target], total)
    return _problem(
        DRAW_CATEGORY,
        seed,
        condition,
        space,
        event,
        (total, first, second, third, counts[target]),
        (
            "Определите число всех фишек и число фишек нужного цвета.",
            "Событию благоприятствуют только фишки выбранного цвета.",
        ),
        (
            f"Всего равновозможных исходов: {total}.",
            f"Подходящих исходов: {counted_phrase(counts[target], _CHIPS, color_forms[target])}.",
            f"Вероятность равна {counts[target]}/{total} = {_exact_answer(value)}.",
        ),
    )


def _complement(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.randint(15, 100)
    unknown = rng.randint(1, total - 1)
    prepared = total - unknown
    space = tuple(frozenset({"prepared"}) for _ in range(prepared)) + tuple(
        frozenset({"unprepared"}) for _ in range(unknown)
    )
    event = {"kind": "not", "event": {"kind": "has", "label": "unprepared"}}
    condition = (
        f"На экзамене {counted_phrase(total, _TICKETS)}; ученик не выучил {unknown} из них. "
        "Билет выбирают наугад. Найдите вероятность того, что билет выучен."
    )
    value = Fraction(prepared, total)
    return _problem(
        COMPLEMENT,
        seed,
        condition,
        space,
        event,
        (total, unknown),
        (
            "Событие «билет выучен» противоположно событию «билет не выучен».",
            "Сначала найдите число выученных билетов как дополнение до общего количества.",
        ),
        (
            f"Всего {counted_phrase(total, _TICKETS)}; не выучено {unknown}.",
            f"Выучено {total} − {unknown} = {counted_phrase(prepared, _TICKETS)}.",
            f"Вероятность равна {prepared}/{total} = {_exact_answer(value)}.",
        ),
    )


def _empirical_frequency(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.choice((20, 25, 40, 50, 80, 100, 200))
    defective = rng.randint(1, total - 1)
    working = total - defective
    known_label = rng.choice(("working", "defective"))
    target = "defective" if known_label == "working" else "working"
    known_count = working if known_label == "working" else defective
    known_adjective = "исправных" if known_label == "working" else "неисправных"
    target_adjective = "неисправный" if target == "defective" else "исправный"
    space = tuple(frozenset({"working"}) for _ in range(working)) + tuple(
        frozenset({"defective"}) for _ in range(defective)
    )
    event = {"kind": "has", "label": target}
    condition = (
        f"В партии {counted_phrase(total, _FLASHLIGHTS)}. "
        f"Количество {known_adjective} фонариков — {known_count}. "
        "Оцените по относительной частоте вероятность выбрать "
        f"{target_adjective} фонарик."
    )
    favorable = defective if target == "defective" else working
    value = Fraction(favorable, total)
    return _problem(
        EMPIRICAL,
        seed,
        condition,
        space,
        event,
        (total, known_count, 1 if known_label == "working" else 0),
        (
            "Используйте данные наблюдений как относительную частоту.",
            "Найдите число нужных предметов как дополнение до размера всей партии.",
        ),
        (
            f"Нужных фонариков {total} − {known_count} = "
            f"{counted_phrase(favorable, _FLASHLIGHTS)}.",
            f"Относительная частота равна {favorable}/{total}.",
            f"Вероятность равна {_exact_answer(value)}.",
        ),
    )


def _remainder_category(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.choice((20, 24, 30, 40, 50, 60, 80, 100))
    first = rng.randint(1, total // 3)
    second = rng.randint(1, total - first - 1)
    remainder = total - first - second
    space = (
        tuple(frozenset({"blue"}) for _ in range(first))
        + tuple(frozenset({"green"}) for _ in range(second))
        + tuple(frozenset({"red"}) for _ in range(remainder))
    )
    event = {"kind": "has", "label": "red"}
    condition = (
        f"На колесе обозрения {counted_phrase(total, _CABINS)}: "
        f"{counted_phrase(first, _CABINS, ('синяя', 'синие', 'синих'))}, "
        f"{counted_phrase(second, _CABINS, ('зелёная', 'зелёные', 'зелёных'))}, "
        "остальные красные. Кабинку выбирают наугад. Найдите вероятность попасть "
        "в красную кабинку."
    )
    value = Fraction(remainder, total)
    return _problem(
        REMAINDER_CATEGORY,
        seed,
        condition,
        space,
        event,
        (total, first, second),
        (
            "Количество красных кабинок не дано напрямую.",
            "Вычтите из общего количества кабинки двух известных цветов.",
        ),
        (
            f"Красных кабинок {total} − {first} − {second} = "
            f"{counted_phrase(remainder, _CABINS, ('красная', 'красные', 'красных'))}.",
            f"Всего равновозможных кабинок {total}.",
            f"Вероятность равна {remainder}/{total} = {_exact_answer(value)}.",
        ),
    )


def _disjoint_union(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.choice((40, 50, 80, 100, 120, 200))
    first = rng.randint(1, total // 3)
    second = rng.randint(1, total // 8)
    max_third = min(total // 8, total - first - second - 3)
    wanted_parity = (total - first - second) % 2
    choices = [n for n in range(1, max_third + 1) if n % 2 == wanted_parity]
    if not choices:
        raise ValueError("Unable to choose visible counts with a positive even remainder")
    third = rng.choice(choices)
    hidden_each = (total - first - second - third) // 2
    if total - first - second - third <= 2 or (total - first - second - third) % 2:
        raise ValueError("The visible counts must leave an even positive remainder")
    space = (
        tuple(frozenset({"red"}) for _ in range(first))
        + tuple(frozenset({"green"}) for _ in range(second))
        + tuple(frozenset({"violet"}) for _ in range(third))
        + tuple(frozenset({"blue"}) for _ in range(hidden_each))
        + tuple(frozenset({"black"}) for _ in range(hidden_each))
    )
    event = {
        "kind": "or",
        "events": [{"kind": "has", "label": "red"}, {"kind": "has", "label": "black"}],
    }
    condition = (
        f"В ящике {counted_phrase(total, _MARKERS)}: "
        f"{counted_phrase(first, _MARKERS, ('красный', 'красных', 'красных'))}, "
        f"{counted_phrase(second, _MARKERS, ('зелёный', 'зелёных', 'зелёных'))}, "
        f"{counted_phrase(third, _MARKERS, ('фиолетовый', 'фиолетовых', 'фиолетовых'))}. "
        "Синих и чёрных поровну; других маркеров нет. Один маркер выбирают наугад. "
        "Найдите вероятность выбрать красный или чёрный маркер."
    )
    favorable = first + hidden_each
    value = Fraction(favorable, total)
    return _problem(
        DISJOINT_UNION,
        seed,
        condition,
        space,
        event,
        (total, first, second, third, hidden_each),
        (
            "Сначала вычислите остаток после подсчёта известных цветов.",
            "Остаток делится поровну между синими и чёрными; нужные цвета не пересекаются.",
        ),
        (
            f"Остаток: {total} − {first} − {second} − {third} = {2 * hidden_each}.",
            "Чёрных маркеров "
            f"{counted_phrase(hidden_each, _MARKERS, ('чёрный', 'чёрных', 'чёрных'))}; "
            f"благоприятных {first} + {hidden_each} = {counted_phrase(favorable, _MARKERS)}.",
            f"Вероятность равна {favorable}/{total} = {_exact_answer(value)}.",
        ),
    )


def _overlapping_groups(seed: int) -> ProbabilityProblem:
    rng = random.Random(seed)
    total = rng.randint(20, 60)
    only_english = rng.randint(1, total // 5)
    only_french = rng.randint(1, total // 5)
    both = rng.randint(1, total // 6)
    neither = total - only_english - only_french - both
    if neither <= 0:
        raise ValueError("The groups must leave at least one person outside both groups")
    space = (
        tuple(frozenset({"english"}) for _ in range(only_english))
        + tuple(frozenset({"french"}) for _ in range(only_french))
        + tuple(frozenset({"english", "french"}) for _ in range(both))
        + tuple(frozenset() for _ in range(neither))
    )
    event = {"kind": "has", "label": "french"}
    condition = (
        f"В группе {counted_phrase(total, _PEOPLE)}: {only_english} знают только английский, "
        f"{only_french} — только французский, а {both} знают оба языка. "
        "Найдите вероятность того, что случайно выбранный человек знает французский."
    )
    favorable = only_french + both
    value = Fraction(favorable, total)
    return _problem(
        OVERLAPPING_GROUP,
        seed,
        condition,
        space,
        event,
        (total, only_english, only_french, both),
        (
            "Человек, знающий оба языка, тоже входит в группу знающих французский.",
            "Сложите только число знающих французский и число знающих оба языка.",
        ),
        (
            f"Знают французский {counted_phrase(only_french, _PEOPLE)} + "
            f"{counted_phrase(both, _PEOPLE)} = {counted_phrase(favorable, _PEOPLE)}.",
            f"Всего равновозможных выборов {total}.",
            f"Вероятность равна {favorable}/{total} = {_exact_answer(value)}.",
        ),
    )


_GENERATORS = {
    DRAW_CATEGORY: _draw_category,
    COMPLEMENT: _complement,
    REMAINDER_CATEGORY: _remainder_category,
    DISJOINT_UNION: _disjoint_union,
    OVERLAPPING_GROUP: _overlapping_groups,
    EMPIRICAL: _empirical_frequency,
}


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> ProbabilityProblem:
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported OGE-10 generator version: {generator_version}")
    generator = _GENERATORS.get(family_id)
    if generator is None:
        raise ValueError(f"OGE-10 family is not enabled: {family_id}")
    if seed < 0:
        raise ValueError("seed must be non-negative")
    # Some valid sample-space counts yield repeating or overlong decimals. Retry
    # boundedly with a deterministic seed stream, retaining the caller's seed in
    # the public problem identity and snapshot.
    for offset in range(128):
        try:
            generated = generator(seed + offset)
        except ValueError:
            continue
        if generated.seed != seed:
            generated = replace(
                generated,
                seed=seed,
                problem_id=str(
                    uuid5(NAMESPACE_URL, f"oge10:{GENERATOR_VERSION}:{family_id}:{seed}")
                ),
            )
        if validate_rendered_problem(generated):
            return generated
    raise RuntimeError(f"Bounded generation failed for {family_id} at seed {seed}")


def solve_rendered_condition(problem: ProbabilityProblem) -> Fraction | None:
    """Reconstruct the probability from the student-facing Russian text alone."""
    visible = tuple(int(value) for value in re.findall(r"\d+", problem.condition))
    if problem.family_id == DRAW_CATEGORY:
        if len(visible) != 4 or sum(visible[1:]) != visible[0]:
            return None
        target = next(
            (
                label
                for word, label in (("красную", "red"), ("синюю", "blue"), ("зелёную", "green"))
                if word in problem.condition
            ),
            None,
        )
        if target is None:
            return None
        counts = dict(zip(("red", "blue", "green"), visible[1:], strict=True))
        return Fraction(counts[target], visible[0])
    if problem.family_id == COMPLEMENT:
        if (
            len(visible) != 2
            or "не выучил" not in problem.condition
            or "выучен" not in problem.condition
        ):
            return None
        return Fraction(visible[0] - visible[1], visible[0])
    if problem.family_id == EMPIRICAL:
        if len(visible) != 2 or "относительной частоте" not in problem.condition:
            return None
        return Fraction(visible[0] - visible[1], visible[0])
    if problem.family_id == REMAINDER_CATEGORY:
        if len(visible) != 3 or "остальные красные" not in problem.condition:
            return None
        return Fraction(visible[0] - visible[1] - visible[2], visible[0])
    if problem.family_id == DISJOINT_UNION:
        if (
            len(visible) != 4
            or "или" not in problem.condition
            or "поровну" not in problem.condition
        ):
            return None
        total, red, green, violet = visible
        remainder = total - red - green - violet
        if remainder <= 0 or remainder % 2:
            return None
        return Fraction(red + remainder // 2, total)
    if problem.family_id == OVERLAPPING_GROUP:
        if (
            len(visible) != 4
            or "оба языка" not in problem.condition
            or "французский" not in problem.condition
        ):
            return None
        total, _only_english, only_french, both = visible
        if total <= 0 or only_french + both > total:
            return None
        return Fraction(only_french + both, total)
    return None


def validate_rendered_problem(problem: ProbabilityProblem) -> bool:
    """Require the visible condition, explicit sample space and event oracle to agree."""
    rendered = solve_rendered_condition(problem)
    if rendered is None or rendered != problem.answer:
        return False
    visible = tuple(int(value) for value in re.findall(r"\d+", problem.condition))
    if problem.family_id == DRAW_CATEGORY:
        color_forms = {
            "red": ("красная", "красные", "красных"),
            "blue": ("синяя", "синие", "синих"),
            "green": ("зелёная", "зелёные", "зелёных"),
        }
        if len(visible) != 4 or not all(
            phrase in problem.condition
            for phrase in (
                counted_phrase(visible[0], _CHIPS),
                counted_phrase(visible[1], _CHIPS, color_forms["red"]),
                counted_phrase(visible[2], _CHIPS, color_forms["blue"]),
                counted_phrase(visible[3], _CHIPS, color_forms["green"]),
            )
        ):
            return False
        target = next(
            (
                label
                for word, label in (
                    ("красную", "red"),
                    ("синюю", "blue"),
                    ("зелёную", "green"),
                )
                if word in problem.condition
            ),
            None,
        )
        counts = tuple(
            sum(label in outcome for outcome in problem.sample_space)
            for label in ("red", "blue", "green")
        )
        if target is None or len(visible) != 4 or visible[1:] != counts:
            return False
        if problem.event != {"kind": "has", "label": target}:
            return False
    elif problem.family_id == COMPLEMENT:
        if len(visible) != 2 or counted_phrase(visible[0], _TICKETS) not in problem.condition:
            return False
        excluded = problem.event.get("event")
        if problem.event.get("kind") != "not" or excluded != {
            "kind": "has",
            "label": "unprepared",
        }:
            return False
        if (
            len(visible) != 2
            or visible[0] != len(problem.sample_space)
            or sum("unprepared" in outcome for outcome in problem.sample_space) != visible[1]
        ):
            return False
    elif problem.family_id == EMPIRICAL:
        if len(visible) != 2 or counted_phrase(visible[0], _FLASHLIGHTS) not in problem.condition:
            return False
        known_label_word = (
            "исправных" if "Количество исправных" in problem.condition else "неисправных"
        )
        if f"Количество {known_label_word} фонариков — {visible[1]}." not in problem.condition:
            return False
        target = "defective" if "неисправный фонарик" in problem.condition else "working"
        if problem.event != {"kind": "has", "label": target}:
            return False
        known_label = "working" if target == "defective" else "defective"
        if len(visible) != 2 or visible[0] != len(problem.sample_space):
            return False
        if sum(known_label in outcome for outcome in problem.sample_space) != visible[1]:
            return False
    elif problem.family_id == REMAINDER_CATEGORY:
        if len(visible) != 3 or not all(
            phrase in problem.condition
            for phrase in (
                counted_phrase(visible[0], _CABINS),
                counted_phrase(visible[1], _CABINS, ("синяя", "синие", "синих")),
                counted_phrase(visible[2], _CABINS, ("зелёная", "зелёные", "зелёных")),
            )
        ):
            return False
        if problem.event != {"kind": "has", "label": "red"}:
            return False
        counts = (
            sum("blue" in outcome for outcome in problem.sample_space),
            sum("green" in outcome for outcome in problem.sample_space),
        )
        if len(visible) != 3 or visible[0] != len(problem.sample_space) or visible[1:] != counts:
            return False
    elif problem.family_id == DISJOINT_UNION:
        if len(visible) != 4 or not all(
            phrase in problem.condition
            for phrase in (
                counted_phrase(visible[0], _MARKERS),
                counted_phrase(visible[1], _MARKERS, ("красный", "красных", "красных")),
                counted_phrase(visible[2], _MARKERS, ("зелёный", "зелёных", "зелёных")),
                counted_phrase(visible[3], _MARKERS, ("фиолетовый", "фиолетовых", "фиолетовых")),
            )
        ):
            return False
        if problem.event != {
            "kind": "or",
            "events": [
                {"kind": "has", "label": "red"},
                {"kind": "has", "label": "black"},
            ],
        }:
            return False
        counts = (
            sum("red" in outcome for outcome in problem.sample_space),
            sum("green" in outcome for outcome in problem.sample_space),
            sum("violet" in outcome for outcome in problem.sample_space),
        )
        if len(visible) != 4 or visible[0] != len(problem.sample_space) or visible[1:] != counts:
            return False
    elif problem.family_id == OVERLAPPING_GROUP:
        if not visible or counted_phrase(visible[0], _PEOPLE) not in problem.condition:
            return False
        if problem.event != {"kind": "has", "label": "french"}:
            return False
        counts = (
            sum(outcome == frozenset({"english"}) for outcome in problem.sample_space),
            sum(outcome == frozenset({"french"}) for outcome in problem.sample_space),
            sum(outcome == frozenset({"english", "french"}) for outcome in problem.sample_space),
        )
        if len(visible) != 4 or visible[0] != len(problem.sample_space) or visible[1:] != counts:
            return False
    return enumerate_probability(problem.sample_space, problem.event) == rendered


def structural_signature(problem: ProbabilityProblem) -> str:
    return problem.family_id
