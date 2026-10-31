from __future__ import annotations

from dataclasses import dataclass

from app.math.answer_policy import (
    PRESCRIBED_NUMERATOR,
    REDUCED_NUMERATOR,
    AnswerFormat,
    AnswerPolicy,
)


@dataclass(frozen=True, slots=True)
class GeneratorSpec:
    family_id: str
    reference_structure_id: str
    source_ids: tuple[str, ...]
    selection_weight: int
    expression_shape: str
    policy: AnswerPolicy
    manual_limits: ManualComplexityLimits


@dataclass(frozen=True, slots=True)
class ManualComplexityLimits:
    max_intermediate_numerator: int
    max_intermediate_denominator: int
    max_common_denominator: int
    max_integer_factor: int
    max_estimated_steps: int


def _manual(
    max_numerator: int,
    max_denominator: int,
    max_common_denominator: int,
    max_integer_factor: int,
    max_steps: int,
) -> ManualComplexityLimits:
    return ManualComplexityLimits(
        max_numerator,
        max_denominator,
        max_common_denominator,
        max_integer_factor,
        max_steps,
    )


def _numeric(
    family_id: str,
    places: int,
    *,
    required_places: int | None = None,
    sign: str = "positive",
    max_value: int = 100,
) -> AnswerPolicy:
    return AnswerPolicy(
        policy_id=f"oge6.{family_id.lower()}.numeric",
        version="1",
        answer_format=AnswerFormat.SINGLE_NUMBER,
        max_decimal_places=places,
        max_absolute_value=max_value,
        required_decimal_places=required_places,
        sign=sign,
    )


GENERATOR_SPECS = (
    GeneratorSpec(
        "OGE06-F001-ADD",
        "oge6.fraction.add.two_terms",
        ("314264",),
        1,
        "add(fraction,fraction)",
        _numeric("OGE06-F001-ADD", 2, max_value=20),
        _manual(400, 100, 100, 125, 5),
    ),
    GeneratorSpec(
        "OGE06-F001-SUB",
        "oge6.fraction.subtract.two_terms",
        ("314265",),
        1,
        "subtract(fraction,fraction)",
        _numeric("OGE06-F001-SUB", 1, required_places=1, sign="negative", max_value=10),
        _manual(400, 100, 100, 125, 5),
    ),
    GeneratorSpec(
        "OGE06-F002-MUL",
        "oge6.fraction.multiply.two_terms",
        ("383596",),
        1,
        "multiply(fraction,fraction)",
        _numeric("OGE06-F002-MUL", 1, required_places=1, max_value=20),
        _manual(250, 100, 1, 100, 5),
    ),
    GeneratorSpec(
        "OGE06-F002-DIV",
        "oge6.fraction.divide.two_terms",
        ("350101",),
        1,
        "divide(group(fraction),group(fraction))",
        _numeric("OGE06-F002-DIV", 2, required_places=2, max_value=10),
        _manual(3000, 1000, 1, 100, 6),
    ),
    GeneratorSpec(
        "OGE06-F004-DEC-ADD",
        "oge6.decimal.add.two_terms",
        ("316784", "355404"),
        2,
        "add(decimal,decimal)",
        _numeric("OGE06-F004-DEC-ADD", 1, required_places=1, max_value=20),
        _manual(171, 10, 10, 100, 3),
    ),
    GeneratorSpec(
        "OGE06-F004-DEC-SUB",
        "oge6.decimal.subtract.two_terms",
        ("369727", "369795", "369824", "369853", "384399"),
        5,
        "subtract(decimal,decimal)",
        _numeric("OGE06-F004-DEC-SUB", 1, required_places=1, sign="any", max_value=10),
        _manual(450, 10, 10, 100, 3),
    ),
    GeneratorSpec(
        "OGE06-F004-DEC-MUL",
        "oge6.decimal.multiply.two_terms",
        ("349924", "350570", "461940"),
        3,
        "multiply(decimal,decimal)",
        _numeric("OGE06-F004-DEC-MUL", 2, required_places=2, max_value=30),
        _manual(2016, 100, 1, 100, 4),
    ),
    GeneratorSpec(
        "OGE06-F006-MIXED-MINUS-DECIMAL",
        "oge6.mixed_number.subtract.decimal",
        ("448832",),
        1,
        "subtract(mixed_number,decimal)",
        _numeric("OGE06-F006-MIXED-MINUS-DECIMAL", 1, required_places=1, max_value=10),
        _manual(155, 10, 10, 160, 5),
    ),
    GeneratorSpec(
        "OGE06-F008-REDUCED-NUMERATOR",
        "oge6.fraction.subtract.then_reduced_numerator",
        ("439897",),
        1,
        "subtract(fraction,fraction)",
        REDUCED_NUMERATOR,
        _manual(196, 196, 196, 14, 6),
    ),
    GeneratorSpec(
        "OGE06-F009-PRESCRIBED-NUMERATOR",
        "oge6.fraction.convert_to_prescribed_denominator_numerator",
        ("450504",),
        1,
        "subtract(fraction,fraction)",
        PRESCRIBED_NUMERATOR,
        _manual(140, 140, 140, 140, 6),
    ),
)

SPEC_BY_ID = {spec.family_id: spec for spec in GENERATOR_SPECS}
SELECTION_WEIGHT_TOTAL = sum(spec.selection_weight for spec in GENERATOR_SPECS)

if SELECTION_WEIGHT_TOTAL != 17:
    raise RuntimeError(
        "OGE-6 enabled weights must match 17 prototypes; confirmed scarce families are disabled"
    )
