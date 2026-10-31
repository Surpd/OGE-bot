from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from app.math.answer_policy import AnswerPolicy
from app.math.ast import Expr, evaluate, render


@dataclass(frozen=True, slots=True)
class Problem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_structure_id: str
    reference_ids: tuple[str, ...]
    subtype: str
    expression: Expr
    condition: str
    answer_policy: AnswerPolicy
    exact_value: Fraction
    correct_answer: str
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_structure_id": self.reference_structure_id,
            "reference_ids": list(self.reference_ids),
            "subtype": self.subtype,
            "expression": render(self.expression),
            "condition": self.condition,
            "answer_policy_id": self.answer_policy.policy_id,
            "answer_policy_version": self.answer_policy.version,
            "exact_numerator": self.exact_value.numerator,
            "exact_denominator": self.exact_value.denominator,
            "correct_answer": self.correct_answer,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
        }


def create_problem(
    *,
    problem_id: str,
    seed: int,
    generator_version: str,
    family_id: str,
    reference_structure_id: str,
    reference_ids: tuple[str, ...],
    subtype: str,
    expression: Expr,
    answer_policy: AnswerPolicy,
    hints: tuple[str, ...],
    solution: tuple[str, ...],
    answer_suffix: str = "",
    condition_prefix: str = "Вычислите: ",
    answer_value: Fraction | None = None,
) -> Problem:
    exact_value = evaluate(expression)
    answer = answer_policy.format(answer_value if answer_value is not None else exact_value)
    condition = f"{condition_prefix}{render(expression)}{answer_suffix}"
    from hashlib import sha256

    fingerprint = sha256(
        f"{family_id}|{answer_policy.policy_id}|{condition}|{answer}".encode()
    ).hexdigest()
    return Problem(
        problem_id=problem_id,
        seed=seed,
        generator_version=generator_version,
        family_id=family_id,
        reference_structure_id=reference_structure_id,
        reference_ids=reference_ids,
        subtype=subtype,
        expression=expression,
        condition=condition,
        answer_policy=answer_policy,
        exact_value=exact_value,
        correct_answer=answer,
        hints=hints,
        solution=solution,
        fingerprint=fingerprint,
    )
