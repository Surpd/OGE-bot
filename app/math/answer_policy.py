from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal as DecimalValue
from decimal import InvalidOperation
from enum import StrEnum
from fractions import Fraction


class AnswerFormat(StrEnum):
    SINGLE_NUMBER = "single_number"
    NUMERATOR = "numerator_of_reduced_fraction"
    PRESCRIBED_NUMERATOR = "numerator_with_prescribed_denominator"
    CHOICE_NUMBER = "choice_number"
    DIGIT_SEQUENCE = "digit_sequence"
    NON_NEGATIVE_INTEGER = "non_negative_integer"


def decimal_places(value: Fraction) -> int | None:
    denominator = value.denominator
    twos = 0
    fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return None
    return max(twos, fives)


def format_decimal(value: Fraction) -> str:
    places = decimal_places(value)
    if places is None:
        raise ValueError("A non-terminating decimal has no exact decimal format")
    if places == 0:
        return str(value.numerator)
    scale = 10**places
    scaled = value.numerator * scale // value.denominator
    sign = "-" if scaled < 0 else ""
    whole, remainder = divmod(abs(scaled), scale)
    fraction_part = f"{remainder:0{places}d}".rstrip("0")
    return f"{sign}{whole},{fraction_part}" if fraction_part else f"{sign}{whole}"


@dataclass(frozen=True, slots=True)
class AnswerPolicy:
    policy_id: str
    version: str
    answer_format: AnswerFormat
    max_decimal_places: int = 2
    max_absolute_value: int = 100
    required_decimal_places: int | None = None
    sign: str = "any"

    def format(self, exact_value: Fraction) -> str:
        if self.answer_format in {
            AnswerFormat.NUMERATOR,
            AnswerFormat.PRESCRIBED_NUMERATOR,
        }:
            return str(exact_value.numerator)
        if self.answer_format != AnswerFormat.SINGLE_NUMBER:
            raise ValueError(f"Answer format {self.answer_format} is not enabled for task 6")
        places = decimal_places(exact_value)
        if places is None or places > self.max_decimal_places:
            raise ValueError("Answer is outside the verified exact-decimal policy")
        if self.required_decimal_places is not None and places != self.required_decimal_places:
            raise ValueError("Answer precision differs from this family's verified format")
        if self.sign == "positive" and exact_value <= 0:
            raise ValueError("This family requires a positive answer")
        if self.sign == "negative" and exact_value >= 0:
            raise ValueError("This family requires a negative answer")
        if abs(exact_value) > self.max_absolute_value:
            raise ValueError("Answer magnitude exceeds the task-family policy")
        return format_decimal(exact_value)

    def parse(self, text: str) -> Fraction | None:
        normalized = text.strip().replace("−", "-").replace("٫", ",")
        if self.answer_format in {
            AnswerFormat.NUMERATOR,
            AnswerFormat.PRESCRIBED_NUMERATOR,
        }:
            if not re.fullmatch(r"[+-]?\d+", normalized):
                return None
            return Fraction(int(normalized))
        if self.answer_format != AnswerFormat.SINGLE_NUMBER:
            return None
        if not re.fullmatch(r"[+-]?(?:\d+(?:[,.]\d+)?|[,.]\d+)", normalized):
            return None
        try:
            return Fraction(DecimalValue(normalized.replace(",", ".")))
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return None

    def accepts(self, text: str, expected: str) -> bool:
        parsed = self.parse(text)
        expected_value = self.parse(expected)
        return parsed is not None and expected_value is not None and parsed == expected_value


NUMERIC_SHORT_ANSWER = AnswerPolicy("oge6.numeric-short", "1", AnswerFormat.SINGLE_NUMBER)
REDUCED_NUMERATOR = AnswerPolicy("oge6.reduced-fraction-numerator", "1", AnswerFormat.NUMERATOR)
PRESCRIBED_NUMERATOR = AnswerPolicy(
    "oge6.prescribed-denominator-numerator", "1", AnswerFormat.PRESCRIBED_NUMERATOR
)

TASK6_POLICIES = {
    NUMERIC_SHORT_ANSWER.policy_id: NUMERIC_SHORT_ANSWER,
    REDUCED_NUMERATOR.policy_id: REDUCED_NUMERATOR,
    PRESCRIBED_NUMERATOR.policy_id: PRESCRIBED_NUMERATOR,
}
