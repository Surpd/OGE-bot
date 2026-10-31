from __future__ import annotations

import random
from fractions import Fraction
from math import gcd, lcm
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import decimal_places, format_decimal
from app.math.ast import (
    Binary,
    Decimal,
    Expr,
    FractionBar,
    FractionLiteral,
    Group,
    Integer,
    MixedNumber,
    evaluate,
    fraction_text,
    render,
)
from app.math.oracle import validate_rendered_problem
from app.math.problem import Problem, create_problem
from app.math.registry import GENERATOR_SPECS, SPEC_BY_ID, GeneratorSpec

GENERATOR_VERSION = "0.2.0"
SUPPORTED_FAMILIES = tuple(spec.family_id for spec in GENERATOR_SPECS)
_FRACTION_DENOMINATORS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 15, 20, 25, 30, 42, 50)
_FINITE_DENOMINATORS = (2, 4, 5, 10, 20, 25, 50, 100)
_FRACTION_ADD_ATOMS = tuple(
    sorted(
        {
            Fraction(numerator, denominator)
            for denominator in (2, 4, 5, 8, 10, 20, 25, 40, 50, 100)
            for numerator in range(1, min(4 * denominator, 50) + 1)
            if Fraction(numerator, denominator).denominator > 1
            and Fraction(numerator, denominator) < 4
        }
    )
)
_FRACTION_ADD_PAIRS = tuple(
    (left, right)
    for index, left in enumerate(_FRACTION_ADD_ATOMS)
    for right in _FRACTION_ADD_ATOMS[index:]
    if Fraction(101, 100) <= left + right <= Fraction(399, 100)
    and (decimal_places(left + right) or 0) <= 2
)
_FRACTION_DIVISORS = tuple(
    sorted(
        Fraction(numerator, denominator)
        for denominator in (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 50)
        for numerator in range(2, 51)
        if Fraction(numerator, denominator) <= 8
    )
)
_FRACTION_DIVISION_PAIRS = tuple(
    (target, divisor, target * divisor)
    for target in (
        Fraction(numerator, 100) for numerator in range(10, 200) if numerator % 10
    )
    for divisor in _FRACTION_DIVISORS
    if (target * divisor).denominator > 1
    and (target * divisor).numerator <= 100
    and (target * divisor).denominator <= 50
    and target * divisor <= 5
    and divisor.denominator > 1
)
_MIXED_SUBTRACTION_CASES = tuple(
    (whole, Fraction(numerator, 10))
    for whole in range(4, 16)
    for numerator in range(1, 81)
    if numerator % 10
    and Fraction(numerator, 10) < Fraction(2 * whole + 1, 2)
    and (Fraction(2 * whole + 1, 2) - Fraction(numerator, 10)).denominator == 10
)


def _rng(family_id: str, seed: int) -> random.Random:
    return random.Random(f"{GENERATOR_VERSION}:{family_id}:{seed}")


def _fraction_atom(value: Fraction) -> Expr:
    if value.denominator == 1:
        return Integer(value.numerator)
    return FractionLiteral(value.numerator, value.denominator)


def _decimal_atom(value: Fraction, places: int) -> Decimal:
    scale = 10**places
    scaled = value * scale
    if scaled.denominator != 1:
        raise ValueError("Decimal rendering would lose exact digits")
    return Decimal(scaled.numerator, places)


def _positive_tenths(rng: random.Random, minimum_units: int, maximum_units: int) -> Fraction:
    units = rng.randint(minimum_units, maximum_units)
    return Fraction(units, 10)


def _positive_hundredths(rng: random.Random, minimum_units: int, maximum_units: int) -> Fraction:
    candidates = [n for n in range(minimum_units, maximum_units + 1) if n % 10]
    if not candidates:
        raise ValueError("No two-decimal target fits the requested range")
    return Fraction(rng.choice(candidates), 100)


def _make_problem(
    spec: GeneratorSpec,
    seed: int,
    expression: Expr,
    *,
    hints: tuple[str, ...],
    solution: tuple[str, ...],
    subtype: str,
    answer_value: Fraction | None = None,
    answer_suffix: str = "",
    condition_prefix: str = "Найдите значение выражения: ",
) -> Problem:
    problem = create_problem(
        problem_id=str(
            uuid5(
                NAMESPACE_URL,
                f"oge-trainer:{spec.family_id}:{seed}:{GENERATOR_VERSION}",
            )
        ),
        seed=seed,
        generator_version=GENERATOR_VERSION,
        family_id=spec.family_id,
        reference_structure_id=spec.reference_structure_id,
        reference_ids=spec.source_ids,
        subtype=subtype,
        expression=expression,
        answer_policy=spec.policy,
        hints=hints,
        solution=solution,
        answer_value=answer_value,
        answer_suffix=answer_suffix,
        condition_prefix=condition_prefix,
    )
    validate_rendered_problem(problem)
    return problem


def _fraction_add(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    first, second = rng.choice(_FRACTION_ADD_PAIRS)
    target = first + second
    expression = Binary("+", _fraction_atom(first), _fraction_atom(second))
    common = lcm(first.denominator, second.denominator)
    numerator = first.numerator * (common // first.denominator) + second.numerator * (
        common // second.denominator
    )
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Приведи дроби к общему знаменателю.",
            "Сложи числители, сократи результат и запиши точное конечное десятичное число.",
        ),
        solution=(
            f"Общий знаменатель: {common}.",
            f"{first} + {second} = {numerator}/{common} = {spec.policy.format(target)}.",
        ),
        subtype="ordinary_fraction_addition",
        condition_prefix="Вычислите: ",
    )


def _fraction_subtract(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    for _ in range(256):
        magnitude = Fraction(rng.randint(1, 5), 10)
        denominator = rng.choice(_FINITE_DENOMINATORS)
        left = Fraction(rng.randint(1, min(denominator * 2, 50)), denominator)
        right = left + magnitude
        if left.denominator > 1 and right.denominator > 1:
            break
    else:
        raise RuntimeError("Could not construct two non-integer fractional subtrahends")
    expression = Binary("-", _fraction_atom(left), _fraction_atom(right))
    common = lcm(left.denominator, right.denominator)
    left_numerator = left.numerator * (common // left.denominator)
    right_numerator = right.numerator * (common // right.denominator)
    result = left - right
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Приведи дроби к общему знаменателю.",
            "Вычитай из меньшего значения большее; проверь знак результата.",
        ),
        solution=(
            f"Общий знаменатель: {common}.",
            f"{left_numerator}/{common} − {right_numerator}/{common} = "
            f"{fraction_text(result)} = {spec.policy.format(result)}.",
        ),
        subtype="ordinary_fraction_subtraction_negative_result",
        condition_prefix="Вычислите: ",
    )


def _fraction_multiply(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    target = Fraction(rng.choice([n for n in range(1, 51) if n % 10]), 10)
    right_candidates = [
        Fraction(1, 2),
        Fraction(2, 3),
        Fraction(3, 4),
        Fraction(4, 5),
        Fraction(3, 2),
        Fraction(5, 4),
    ]
    right_candidates = [
        value
        for value in right_candidates
        if (target / value).denominator > 1
        and (target / value).numerator <= 100
        and (target / value).denominator <= 50
    ]
    if not right_candidates:
        raise RuntimeError("No source-shaped fraction factors for selected target")
    right = rng.choice(right_candidates)
    left = target / right
    if left.denominator == 1 or right.denominator == 1:
        raise RuntimeError("Multiplication prototype requires two displayed fractions")
    expression = Binary("*", _fraction_atom(left), _fraction_atom(right))
    product = left * right
    cancel_left_numerator = gcd(abs(left.numerator), right.denominator)
    cancel_right_numerator = gcd(abs(right.numerator), left.denominator)
    reduced_left = Fraction(
        left.numerator // cancel_left_numerator,
        left.denominator // cancel_right_numerator,
    )
    reduced_right = Fraction(
        right.numerator // cancel_right_numerator,
        right.denominator // cancel_left_numerator,
    )
    if cancel_left_numerator > 1 or cancel_right_numerator > 1:
        reduction_step = (
            f"Перекрёстно сокращаем: {fraction_text(left)} · {fraction_text(right)} = "
            f"{fraction_text(reduced_left)} · {fraction_text(reduced_right)}."
        )
    else:
        reduction_step = (
            f"Перемножаем числители и знаменатели: "
            f"{left.numerator * right.numerator}/{left.denominator * right.denominator}."
        )
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Перемножь числители и знаменатели; до умножения можно выполнить сокращение.",
            "Сократи полученную дробь и переведи её в конечную десятичную запись.",
        ),
        solution=(
            reduction_step,
            f"Получаем {fraction_text(product)} = {spec.policy.format(target)}.",
        ),
        subtype="ordinary_fraction_multiplication",
    )


def _fraction_divide(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    target, divisor, dividend = rng.choice(_FRACTION_DIVISION_PAIRS)
    expression = Binary("/", Group(_fraction_atom(dividend)), Group(_fraction_atom(divisor)))
    reciprocal = Fraction(divisor.denominator, divisor.numerator)
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Замени деление умножением на дробь, обратную делителю.",
            "Сократи множители и запиши результат конечной десятичной дробью.",
        ),
        solution=(
            f"{fraction_text(dividend)} : {fraction_text(divisor)} = "
            f"{fraction_text(dividend)} · {fraction_text(reciprocal)}.",
            f"Сокращаем и получаем {spec.policy.format(target)}.",
        ),
        subtype="ordinary_fraction_division",
    )


def _reciprocal_sum(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    half_units = rng.choice(tuple(range(5, 40, 2)))
    target = Fraction(half_units, 2)
    candidates: list[tuple[int, int]] = []
    for a in range(target.numerator // target.denominator + 1, 81):
        remainder = Fraction(1, 1) / target - Fraction(1, a)
        if remainder <= 0:
            continue
        candidate_b = Fraction(1, 1) / remainder
        if candidate_b.denominator == 1 and 2 <= candidate_b.numerator <= 80:
            candidates.append((a, candidate_b.numerator))
    if not candidates:
        raise RuntimeError("No integer denominators satisfy the nested-fraction policy")
    a, denominator_b = rng.choice(candidates)
    inner = Binary("+", FractionLiteral(1, a), FractionLiteral(1, denominator_b))
    expression = Binary("/", Integer(1), Group(inner))
    product = a * denominator_b
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Сначала вычисли сумму дробей в знаменателе.",
            "Разделить 1 на полученную дробь — значит умножить на обратную дробь.",
        ),
        solution=(
            f"В знаменателе: 1/{a} + 1/{denominator_b} = {a + denominator_b}/{product}.",
            f"Обращаем дробь: {product}/{a + denominator_b} = {spec.policy.format(target)}.",
        ),
        subtype="reciprocal_of_sum_of_two_unit_fractions",
    )


def _decimal_add(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    target_units = rng.choice([n for n in range(67, 172) if n % 10])
    valid_splits = [
        first
        for first in range(29, 94)
        if first < target_units and 29 <= target_units - first <= 93
    ]
    if not valid_splits:
        raise RuntimeError("No decimal addends satisfy the source-shaped answer policy")
    first_units = rng.choice(valid_splits)
    second_units = target_units - first_units
    first = Fraction(first_units, 10)
    second = Fraction(second_units, 10)
    target = Fraction(target_units, 10)
    expression = Binary("+", _decimal_atom(first, 1), _decimal_atom(second, 1))
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Сложи десятичные дроби, совместив запятые.",
            "Сохрани один знак после запятой; округление не требуется.",
        ),
        solution=(
            f"{render(expression)} = {spec.policy.format(target)}.",
            "Складываем десятые и единицы отдельно.",
        ),
        subtype="decimal_addition_single_operation",
    )


def _decimal_subtract(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    negative = rng.randrange(5) < 4
    magnitude_units = rng.choice(
        [n for n in range(5, 46) if n % 10] if negative else [n for n in range(1, 46) if n % 10]
    )
    magnitude = Fraction(magnitude_units, 10)
    base_units = rng.randint(17, 94 - magnitude_units)
    base = Fraction(base_units, 10)
    first, second = (base, base + magnitude) if negative else (base + magnitude, base)
    target = first - second
    expression = Binary("-", _decimal_atom(first, 1), _decimal_atom(second, 1))
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Вычитай по разрядам, совместив запятые.",
            "Если вычитаемое больше уменьшаемого, ответ будет отрицательным.",
        ),
        solution=(
            f"{render(expression)} = {spec.policy.format(target)}.",
            "Выполняем вычитание точно, без округления.",
        ),
        subtype="decimal_subtraction_one_decimal_place",
    )


def _decimal_multiply(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    for _ in range(128):
        left_units = rng.randint(16, 96)
        right_units = rng.randint(16, 96)
        product_units = left_units * right_units
        if 816 <= product_units <= 2016 and product_units % 10 != 0:
            break
    else:
        raise RuntimeError("Could not construct a two-place decimal product")
    left = Fraction(left_units, 10)
    right = Fraction(right_units, 10)
    target = Fraction(product_units, 100)
    expression = Binary("*", _decimal_atom(left, 1), _decimal_atom(right, 1))
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Умножь числа без запятых.",
            "В произведении отдели две цифры после запятой — по одной от каждого множителя.",
        ),
        solution=(
            f"{left_units} · {right_units} = {product_units}.",
            f"В двух множителях всего два десятичных знака: ответ {spec.policy.format(target)}.",
        ),
        subtype="decimal_multiplication_two_one_decimal_operands",
    )


def _mixed_number_subtract(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    whole, target = rng.choice(_MIXED_SUBTRACTION_CASES)
    numerator, denominator = 1, 2
    mixed_value = Fraction(whole * denominator + numerator, denominator)
    decimal_value = mixed_value - target
    expression = Binary(
        "-", MixedNumber(whole, numerator, denominator), _decimal_atom(decimal_value, 1)
    )
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            f"Преобразуй смешанное число {whole} 1/2 в неправильную дробь.",
            "Запиши десятичную дробь как обыкновенную и выполни вычитание точно.",
        ),
        solution=(
            f"{whole} 1/2 = {mixed_value}.",
            f"{fraction_text(mixed_value)} − {format_decimal(decimal_value)} = "
            f"{spec.policy.format(target)}.",
        ),
        subtype="mixed_number_minus_decimal",
    )


def _reduced_numerator(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    for _ in range(256):
        d1 = rng.choice(tuple(d for d in _FRACTION_DENOMINATORS if d <= 14))
        d2 = rng.choice(tuple(d for d in _FRACTION_DENOMINATORS if d <= 14))
        n1 = rng.randint(1, d1 - 1)
        n2 = rng.randint(1, d2 - 1)
        value = Fraction(n1, d1) - Fraction(n2, d2)
        if 0 < value < 1 and value.numerator <= 20 and value.denominator > 1:
            break
    else:
        raise RuntimeError("Could not construct a positive reduced fraction")
    expression = Binary("-", FractionLiteral(n1, d1), FractionLiteral(n2, d2))
    suffix = (
        ". Представьте результат в виде несократимой обыкновенной дроби. "
        "В ответ запишите числитель этой дроби"
    )
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Сначала выполни вычитание как обыкновенных дробей.",
            "Сократи результат до несократимой дроби; в ответе требуется только числитель.",
        ),
        solution=(
            f"Значение выражения: {fraction_text(value)}.",
            f"Дробь несократима; её числитель — {value.numerator}.",
        ),
        subtype="reduced_fraction_numerator",
        answer_value=Fraction(value.numerator),
        answer_suffix=suffix,
    )


def _prescribed_denominator_numerator(
    seed: int, rng: random.Random, spec: GeneratorSpec
) -> Problem:
    for _ in range(256):
        d1 = rng.choice((4, 5, 6, 7, 8, 9, 10, 12, 14))
        d2 = rng.choice((4, 5, 6, 7, 8, 9, 10, 12, 14))
        common = lcm(d1, d2)
        denominator = common * rng.choice((2, 3))
        if denominator > 140:
            continue
        n1 = rng.randint(1, d1 - 1)
        n2 = rng.randint(1, d2 - 1)
        answer_numerator = n1 * (denominator // d1) - n2 * (denominator // d2)
        if 1 <= answer_numerator <= 40 and denominator <= 100:
            break
    else:
        raise RuntimeError("Could not construct the prescribed-denominator task")
    expression = Binary("-", FractionLiteral(n1, d1), FractionLiteral(n2, d2))
    suffix = (
        f". Запишите выражение в виде дроби со знаменателем {denominator}. "
        "В ответ запишите числитель полученной дроби"
    )
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Приведи обе дроби к указанному знаменателю.",
            "Вычти полученные числители; эту дробь сокращать не нужно.",
        ),
        solution=(
            f"Числители после приведения: {n1 * (denominator // d1)} и {n2 * (denominator // d2)}.",
            f"Разность равна {answer_numerator}/{denominator}; ответ — {answer_numerator}.",
        ),
        subtype="fraction_numerator_with_prescribed_denominator",
        answer_value=Fraction(answer_numerator),
        answer_suffix=suffix,
    )


def _decimal_quotient_bar(seed: int, rng: random.Random, spec: GeneratorSpec) -> Problem:
    for _ in range(128):
        denominator_units = rng.randint(11, 49)
        quotient = rng.randint(2, 9)
        numerator_units = denominator_units * quotient
        if numerator_units <= 990 and numerator_units % 10 != 0:
            break
    else:
        raise RuntimeError("Could not construct a decimal fraction-bar quotient")
    numerator = Fraction(numerator_units, 10)
    denominator = Fraction(denominator_units, 10)
    expression = FractionBar(_decimal_atom(numerator, 1), _decimal_atom(denominator, 1))
    exact = Fraction(quotient)
    return _make_problem(
        spec,
        seed,
        expression,
        hints=(
            "Умножь числитель и знаменатель на 10, чтобы убрать запятые.",
            "Раздели полученные целые числа.",
        ),
        solution=(
            f"{format_decimal(numerator)} / {format_decimal(denominator)} = "
            f"{numerator_units} / {denominator_units}.",
            f"Выполняем деление: {spec.policy.format(exact)}.",
        ),
        subtype="decimal_division_written_as_fraction_bar",
    )


_BUILDERS = {
    "OGE06-F001-ADD": _fraction_add,
    "OGE06-F001-SUB": _fraction_subtract,
    "OGE06-F002-MUL": _fraction_multiply,
    "OGE06-F002-DIV": _fraction_divide,
    "OGE06-F004-DEC-ADD": _decimal_add,
    "OGE06-F004-DEC-SUB": _decimal_subtract,
    "OGE06-F004-DEC-MUL": _decimal_multiply,
    "OGE06-F006-MIXED-MINUS-DECIMAL": _mixed_number_subtract,
    "OGE06-F008-REDUCED-NUMERATOR": _reduced_numerator,
    "OGE06-F009-PRESCRIBED-NUMERATOR": _prescribed_denominator_numerator,
}


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Problem:
    if family_id not in SPEC_BY_ID:
        raise ValueError(f"Unknown or disabled OGE task-6 family: {family_id}")
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported generator version: {generator_version}")
    if type(seed) is not int or seed < 0 or seed >= 2**63:
        raise ValueError("seed must be an integer in [0, 2**63)")
    spec = SPEC_BY_ID[family_id]
    problem = _BUILDERS[family_id](seed, _rng(family_id, seed), spec)
    if problem.exact_value != evaluate(problem.expression):
        raise AssertionError("Stored exact value differs from the AST")
    return problem


def choose_family(seed: int) -> str:
    if type(seed) is not int or seed < 0 or seed >= 2**63:
        raise ValueError("seed must be an integer in [0, 2**63)")
    rng = random.Random(f"{GENERATOR_VERSION}:catalog-weighted-selection:{seed}")
    choice = rng.randrange(sum(spec.selection_weight for spec in GENERATOR_SPECS))
    for spec in GENERATOR_SPECS:
        if choice < spec.selection_weight:
            return spec.family_id
        choice -= spec.selection_weight
    raise AssertionError("Weighted family selection fell through")


def generate_random(seed: int, generator_version: str = GENERATOR_VERSION) -> Problem:
    family_id = choose_family(seed)
    return generate(family_id, seed, generator_version)
