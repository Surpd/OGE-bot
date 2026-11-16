"""Independent visible-statement solver and coordinate verifier for circles v3.

No generator imports: statements, topology, targets and metric witnesses are checked
before a saved answer or image can enter the Telegram flow.
"""

from __future__ import annotations

import ast
import math
import re
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal
from app.math.oge16_oracle import angle, cross, distance, dot, near, require, square_root, vector

N = r"([0-9]+(?:,[0-9]+)?)"


EXPECTED_THEOREMS = {
    "A01": "Треугольники AOB и COD равнобедренные, а углы AOB и COD вертикальные. "
    "Их углы при основаниях равны.",
    "A02": "Вписанный угол равен половине центрального угла, опирающегося на ту же дугу.",
    "A03": "Углы AOB и AOD в сумме равны 180°. Угол ACB равен половине угла AOB.",
    "A04": "Угол ANB опирается на диаметр и равен 90°. Углы NAB и NMB опираются на одну дугу NB.",
    "A05": "Угол, опирающийся на диаметр, прямой. Острые углы прямоугольного "
    "треугольника в сумме равны 90°.",
    "A06": "AB — диаметр; угол ACB прямой. По теореме Пифагора AC² = (2R)² − BC².",
    "B01": "Радиус в точке касания перпендикулярен касательной. Её длина "
    "находится по теореме Пифагора.",
    "B02": "Сумма углов между касательными и радиусами равна 180°. В "
    "равнобедренном треугольнике AOB угол ABO равен половине угла между "
    "касательными.",
    "B03": "Перпендикуляр из центра делит хорду пополам; половина хорды равна √(R² − d²).",
    "B04": "Квадрат касательной равен произведению внешней части секущей на всю "
    "секущую: AK² = AB · AC.",
    "B05": "Угол между касательной и хордой равен половине градусной меры "
    "заключённой между ними дуги.",
    "C01": "Сторона квадрата равна диаметру вписанной окружности; диагональ равна "
    "стороне, умноженной на √2.",
    "C02": "Расстояние между параллельными основаниями равно диаметру вписанной окружности.",
    "C03": "Площадь треугольника равна произведению полупериметра на радиус вписанной окружности.",
    "C04": "Для равностороннего треугольника R = 2r, h = 3r, a = 2r√3 = R√3.",
    "C05": "В описанном четырёхугольнике суммы противоположных сторон равны: AB + CD = BC + AD.",
    "C06": "Диагонали ромба перпендикулярны, а AC делит угол C пополам. Радиус "
    "равен (AC/2) · sin(∠BCA); sin = 7/25.",
    "D01": "Сумма противоположных углов вписанного четырёхугольника равна 180°.",
    "D02": "Для равностороннего треугольника R = 2r, h = 3r, a = 2r√3 = R√3.",
    "D03": "Диагональ квадрата равна диаметру окружности, а сторона равна R√2.",
    "D04": "По теореме синусов AB = 2R · sin C, значит R = AB/(2 sin C).",
    "D05": "Если сторона квадрата a, то OA² = a² + (a/2)² = 5a²/4. Поэтому S = 4R²/5.",
    "D06": "Диагональ — диаметр окружности. Стороны равны d · sin α и d · cos α; cos α = 0,8.",
}


def check_calculation(key: str, source: str, calculation: str, expected: Fraction) -> None:
    """Check displayed numeric steps with a separate restricted arithmetic parser."""
    pieces = calculation.rstrip(".").split(" = ")
    if key == "A01":
        require(
            pieces == ["Углы при основаниях равны: искомый угол", format_decimal(expected)],
            "Incorrect base-angle explanation",
        )
        return
    prefixes = {
        "A02": "∠ACB",
        "A03": "∠AOD" if source == "349314" else "∠ACB",
        "A04": "∠NMB",
        "A05": "Искомый угол",
        "A06": "AC",
        "B01": "Длина касательной",
        "B02": "∠ABO",
        "B03": "Длина хорды",
        "B04": "AK",
        "B05": "∠ABC",
        "C01": "S" if source in {"324364", "341707"} else "d" if source == "356369" else "r",
        "C02": "h",
        "C03": "S",
        "C04": "r" if source == "356488" else "h" if source == "356498" else "a",
        "C05": "AD",
        "C06": "r",
        "D01": "∠C",
        "D02": "a",
        "D03": "a",
        "D04": "R",
        "D05": "S",
        "D06": "S",
    }
    require(len(pieces) == 3 and pieces[0] == prefixes[key], "Incorrect solution target")
    expression = pieces[1].replace(",", ".").replace("−", "-").replace("·", "*")
    expression = expression.replace("²", "**2").replace("sin 45°", "(sqrt(2)/2)")
    expression = re.sub(r"√([0-9]+(?:\.[0-9]+)?)", r"sqrt(\1)", expression)
    expression = expression.replace("√(", "sqrt(")
    expression = re.sub(r"(?<=[0-9)])(?=sqrt\()", "*", expression)

    def evaluate(node: ast.AST) -> float:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            require(abs(node.value) < 10**9, "Oversized displayed calculation")
            return float(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            require(
                node.func.id == "sqrt" and len(node.args) == 1 and not node.keywords,
                "Unexpected displayed function",
            )
            return math.sqrt(evaluate(node.args[0]))
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow) and right == 2:
                return left**2
        raise ValueError("Unexpected displayed calculation syntax")

    near(evaluate(ast.parse(expression, mode="eval").body), float(expected))


def match(pattern: str, text: str) -> list[Fraction]:
    m = re.fullmatch(pattern, text)
    require(m is not None, "Visible condition/target changed")
    assert m is not None
    return [Fraction(s.replace(",", ".")) for s in m.groups()]


def area(vertices: list[Any]) -> float:
    return (
        abs(sum(cross(a, b) for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True)))
        / 2
    )


def tangencies(p: dict[str, Any], names: str, center: Any, radius: float) -> None:
    vertices = [p[n] for n in names]
    signs = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        side = vector(a, b)
        length = math.hypot(*side)
        require(length > 1e-8, "Degenerate side")
        projection = dot(vector(a, center), side) / length**2
        require(0 < projection < 1, "Tangency is outside side")
        signs.append(cross(side, vector(a, center)))
        near(abs(signs[-1]) / length, radius)
    require(all(s > 0 for s in signs) or all(s < 0 for s in signs), "Incircle is outside polygon")


def equal_sides(p: dict[str, Any], names: str) -> list[float]:
    vertices = [p[n] for n in names]
    lengths = [distance(a, b) for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True)]
    for length in lengths[1:]:
        near(length, lengths[0])
    return lengths


def solve(snapshot: dict[str, Any]) -> Fraction:
    key = snapshot["family_id"].removeprefix("OGE16-")
    text, g = snapshot["condition"], snapshot["geometry"]
    p, radius, center = g["points"], g["radius"], g["center"]
    require(center == [0.0, 0.0] and 0 < radius <= 10000, "Invalid circle")
    require(
        all(len(q) == 2 and all(math.isfinite(z) for z in q) for q in p.values()), "Invalid point"
    )
    require(g["arc"] is None, "Unexpected arc annotation")
    source = snapshot["provenance"]["task_id"]
    expected_source: str
    variant = 0
    scale = Fraction(1)
    on_circle = ""
    expected_names = ""
    edges: str
    answer: Fraction
    if key == "A01":
        reverse = "Угол OCD" in text
        given, target = ("OCD", "OAB") if reverse else ("OAB", "OCD")
        (a,) = match(
            rf"В окружности с центром O проведены диаметры AD и BC\. Угол {given} "
            rf"равен {N}°\. Найдите угол {target}\. Ответ дайте в градусах\.",
            text,
        )
        require(0 < a < 90, "Angle domain")
        answer = a
        near(distance(p["A"], p["D"]), 2 * radius)
        near(distance(p["B"], p["C"]), 2 * radius)
        for triple in (given, target):
            near(angle(p[triple[0]], p[triple[1]], p[triple[2]]), float(a))
        expected_source = "142" if reverse else source
        require(source in ({"142"} if reverse else {"116", "314850"}), "Wrong source variant")
        variant = {"116": 0, "142": 1, "314850": 2}[source]
        scale = a - (30 if reverse else 70) + 1
        expected_names, on_circle, edges = "OABCD", "ABCD", "AD BC AB CD"
    elif key == "A02":
        (a,) = match(
            rf"Треугольник ABC вписан в окружность с центром O\. Угол AOB равен "
            rf"{N}°\. Найдите угол ACB\. Ответ дайте в градусах\.",
            text,
        )
        answer = a / 2
        near(angle(p["A"], p["O"], p["B"]), float(a))
        near(angle(p["A"], p["C"], p["B"]), float(answer))
        expected_source = source
        require(source in {"311956", "314811"}, "Wrong source")
        variant = int(source == "314811")
        scale = (a - (48 if variant == 0 else 84)) / 2 + 1
        expected_names, on_circle, edges = "OABC", "ABC", "OA OB AC BC AB"
    elif key == "A03":
        reverse = "Угол ACB" in text.split(". ")[1]
        given, target = ("ACB", "AOD") if reverse else ("AOD", "ACB")
        (a,) = match(
            rf"В окружности с центром O отрезки AC и BD — диаметры\. Угол {given} "
            rf"равен {N}°\. Найдите угол {target}\. Ответ дайте в градусах\.",
            text,
        )
        answer = 180 - 2 * a if reverse else (180 - a) / 2
        require(0 < answer < 180, "Angle domain")
        near(distance(p["A"], p["C"]), 2 * radius)
        near(distance(p["B"], p["D"]), 2 * radius)
        near(angle(p[given[0]], p[given[1]], p[given[2]]), float(a))
        near(angle(p[target[0]], p[target[1]], p[target[2]]), float(answer))
        expected_source = "349314" if reverse else "311517"
        variant = int(reverse)
        central = answer if reverse else a
        scale = ((108 if reverse else 110) - central) / 4 + 1
        expected_names, on_circle, edges = "OABCD", "ABCD", "AC BD CB AB"
    elif key == "A04":
        (a,) = match(
            rf"На окружности по разные стороны от диаметра AB взяты точки M и N\. "
            rf"Угол NBA равен {N}°\. Найдите угол NMB\. Ответ дайте в градусах\.",
            text,
        )
        answer = 90 - a
        near(distance(p["A"], p["B"]), 2 * radius)
        require(
            cross(vector(p["A"], p["B"]), vector(p["A"], p["M"]))
            * cross(vector(p["A"], p["B"]), vector(p["A"], p["N"]))
            < 0,
            "Same semicircle",
        )
        near(angle(p["N"], p["B"], p["A"]), float(a))
        near(angle(p["N"], p["M"], p["B"]), float(answer))
        expected_source, scale = "339419", a - 38 + 1
        expected_names, on_circle, edges = "ABMN", "ABMN", "AB BN NM MB"
    elif key == "A05":
        diameter_is_ab = "стороне AB" in text
        diameter, target = ("AB", "ABC") if diameter_is_ab else ("AC", "C")
        (a,) = match(
            rf"Центр окружности, описанной около треугольника ABC, лежит на стороне "
            rf"{diameter}\. Угол BAC равен {N}°\. Найдите угол {target}\. Ответ "
            rf"дайте в градусах\.",
            text,
        )
        answer = 90 - a
        near(distance(p[diameter[0]], p[diameter[1]]), 2 * radius)
        near(angle(p["B"], p["A"], p["C"]), float(a))
        near(
            angle(p["A"], p["B"], p["C"]) if diameter_is_ab else angle(p["A"], p["C"], p["B"]),
            float(answer),
        )
        require(
            source in ({"348379"} if diameter_is_ab else {"341673", "339503", "341329"}),
            "Wrong diameter source",
        )
        expected_source = source
        variant = {"341673": 0, "348379": 1, "339503": 2, "341329": 3}[source]
        scale = a - (75, 30, 75, 44)[variant] + 1
        expected_names, on_circle, edges = "ABC", "ABC", "AB BC CA"
    elif key == "A06":
        r, leg = match(
            rf"Центр окружности, описанной около треугольника ABC, лежит на стороне "
            rf"AB\. Радиус окружности равен {N}\. Найдите AC, если BC = {N}\.",
            text,
        )
        answer = square_root(4 * r * r - leg * leg)
        near(radius, float(r))
        near(distance(p["A"], p["B"]), 2 * radius)
        near(distance(p["B"], p["C"]), float(leg))
        near(distance(p["A"], p["C"]), float(answer))
        near(angle(p["A"], p["C"], p["B"]), 90)
        expected_source, scale = "348961", leg / 12
        expected_names, on_circle, edges = "ABC", "ABC", "AB BC CA"
    elif key == "B01":
        r, out = match(
            rf"На отрезке AB выбрана точка C так, что AC = {N}, BC = {N}\. "
            rf"Окружность с центром A проходит через C\. Найдите длину касательной"
            rf", проведённой из точки B к этой окружности\.",
            text,
        )
        answer = square_root((r + out) ** 2 - r * r)
        near(distance(p["A"], center), 0)
        near(radius, float(r))
        near(distance(p["B"], p["C"]), float(out))
        near(distance(p["A"], p["B"]), float(r + out))
        near(dot(vector(p["T"], p["A"]), vector(p["T"], p["B"])), 0)
        near(distance(p["B"], p["T"]), float(answer))
        expected_source, scale = "340174", r / 75
        expected_names, on_circle, edges = "ABCTL", "CTL", "LB BT"
    elif key == "B02":
        (a,) = match(
            rf"Касательные в точках A и B к окружности с центром O пересекаются под "
            rf"углом {N}°\. Найдите угол ABO\. Ответ дайте в градусах\.",
            text,
        )
        answer = a / 2
        near(angle(p["A"], p["P"], p["B"]), float(a))
        for name in "AB":
            near(dot(vector(p[name], center), vector(p[name], p["P"])), 0)
        near(angle(p["A"], p["B"], p["O"]), float(answer))
        expected_source, scale = "340337", (a - 72) / 2 + 1
        expected_names, on_circle, edges = "ABOP", "AB", "PA PB AO BO AB"
    elif key == "B03":
        r, d = match(
            rf"Найдите длину хорды окружности радиусом {N}, если расстояние от "
            rf"центра окружности до хорды равно {N}\.",
            text,
        )
        answer = 2 * square_root(r * r - d * d)
        near(radius, float(r))
        near(distance(p["A"], p["B"]), float(answer))
        chord_vector = vector(p["A"], p["B"])
        near(abs(cross(chord_vector, vector(p["A"], center))) / math.hypot(*chord_vector), float(d))
        near(distance(p["O"], p["M"]), float(d))
        near(dot(vector(p["O"], p["M"]), vector(p["A"], p["B"])), 0)
        for axis in (0, 1):
            near(p["M"][axis], (p["A"][axis] + p["B"][axis]) / 2)
        expected_source, scale = "340587", r / 13
        expected_names, on_circle, edges = "ABOM", "AB", "AB OM"
    elif key == "B04":
        external, whole = match(
            rf"Через точку A вне окружности проведены касательная AK и секущая "
            rf"ABC\. AB = {N}, AC = {N}\. Найдите AK\.",
            text,
        )
        require(0 < external < whole, "Secant ordering")
        answer = square_root(external * whole)
        near(distance(p["A"], p["B"]), float(external))
        near(distance(p["A"], p["C"]), float(whole))
        near(distance(p["B"], p["C"]), float(whole - external))
        near(dot(vector(p["K"], center), vector(p["K"], p["A"])), 0)
        near(distance(p["A"], p["K"]), float(answer))
        expected_source, scale = "356543", external / 2
        expected_names, on_circle, edges = "ABCK", "BCK", "AC AK"
    elif key == "B05":
        (a,) = match(
            rf"На окружности отмечены точки A и B так, что меньшая дуга AB равна "
            rf"{N}°\. Прямая BC касается окружности в точке B так, что угол ABC "
            rf"острый\. Найдите угол ABC\. Ответ дайте в градусах\.",
            text,
        )
        answer = a / 2
        require(0 < a < 180, "Minor arc domain")
        near(angle(p["A"], center, p["B"]), float(a))
        near(dot(vector(p["B"], center), vector(p["B"], p["C"])), 0)
        near(angle(p["A"], p["B"], p["C"]), float(answer))
        expected_source, scale = "369504", (a - 72) / 2 + 1
        expected_names, on_circle, edges = "ABC", "AB", "AB BC"
    elif key == "C01":
        require(source in {"324364", "341707", "356369", "356399"}, "Wrong square source")
        variant = {"324364": 0, "341707": 1, "356369": 2, "356399": 3}[source]
        if variant < 2:
            (r,) = match(
                rf"Найдите площадь квадрата, описанного вокруг окружности радиуса {N}\.", text
            )
            answer = 4 * r * r
            near(radius, float(r))
            scale = r / (83 if variant == 0 else 7)
        elif variant == 2:
            (coeff,) = match(
                rf"Радиус вписанной в квадрат окружности равен {N}√2\. Найдите "
                rf"диагональ этого квадрата\.",
                text,
            )
            answer = 4 * coeff
            near(radius, float(coeff) * math.sqrt(2))
            scale = coeff / 2
            near(distance(p["A"], p["C"]), float(answer))
        else:
            (side,) = match(
                rf"Сторона квадрата равна {N}\. Найдите радиус окружности, "
                rf"вписанной в этот квадрат\.",
                text,
            )
            answer = side / 2
            near(radius, float(answer))
            scale = side / 6
        equal_sides(p, "ABCD")
        near(angle(p["A"], p["B"], p["C"]), 90)
        tangencies(p, "ABCD", center, radius)
        expected_source = source
        expected_names, on_circle, edges = "ABCD", "", "AB BC CD DA"
    elif key == "C02":
        iso = "равнобедренную" in text
        adjective = "равнобедренную " if iso else ""
        (r,) = match(
            rf"Радиус окружности, вписанной в {adjective}трапецию, равен {N}\. "
            rf"Найдите высоту этой трапеции\.",
            text,
        )
        answer = 2 * r
        near(radius, float(r))
        tangencies(p, "ABCD", center, radius)
        near(cross(vector(p["A"], p["D"]), vector(p["B"], p["C"])), 0)
        near(abs(p["A"][1] - p["B"][1]), float(answer))
        if iso:
            near(distance(p["A"], p["B"]), distance(p["C"], p["D"]))
        expected_source = "448769" if iso else "355413"
        variant = int(iso)
        scale = r / (12 if iso else 16)
        expected_names, on_circle, edges = "ABCD", "", "AB BC CD DA"
    elif key == "C03":
        perim, side, r = match(
            rf"Периметр треугольника равен {N}, одна из сторон равна {N}, а радиус "
            rf"вписанной в него окружности равен {N}\. Найдите площадь этого "
            rf"треугольника\.",
            text,
        )
        answer = perim * r / 2
        near(
            sum(distance(p[a], p[b]) for a, b in (("A", "B"), ("B", "C"), ("C", "A"))), float(perim)
        )
        near(distance(p["A"], p["B"]), float(side))
        near(area([p[n] for n in "ABC"]), float(answer))
        near(radius, float(r))
        tangencies(p, "ABC", center, radius)
        expected_source, scale = "356329", perim / 50
        expected_names, on_circle, edges = "ABC", "", "AB BC CA"
    elif key in {"C04", "D02"}:
        expected_names, on_circle, edges = "ABC", "", "AB BC CA"
        equal_sides(p, "ABC")
        triangle_side = distance(p["A"], p["B"])
        height = 2 * area([p[n] for n in "ABC"]) / triangle_side
        if key == "D02":
            (coeff,) = match(
                rf"Радиус окружности, описанной около равностороннего треугольника, "
                rf"равен {N}√3\. Найдите длину стороны этого треугольника\.",
                text,
            )
            answer = 3 * coeff
            near(radius, float(coeff) * math.sqrt(3))
            near(triangle_side, float(answer))
            expected_source, scale = "356533", coeff / 2
            on_circle = "ABC"
        elif source == "356488":
            (coeff,) = match(
                rf"Сторона равностороннего треугольника равна {N}√3\. Найдите "
                rf"радиус окружности, вписанной в этот треугольник\.",
                text,
            )
            answer = coeff / 2
            near(triangle_side, float(coeff) * math.sqrt(3))
            near(radius, float(answer))
            scale = coeff / 2
            expected_source = "356488"
        elif source == "356498":
            (r,) = match(
                rf"Радиус окружности, вписанной в равносторонний треугольник, равен "
                rf"{N}\. Найдите высоту этого треугольника\.",
                text,
            )
            answer = 3 * r
            near(radius, float(r))
            near(height, float(answer))
            scale = r / 5
            expected_source = "356498"
            variant = 1
        elif source == "356518":
            (coeff,) = match(
                rf"Радиус окружности, вписанной в равносторонний треугольник, равен "
                rf"{N}√3\. Найдите длину стороны этого треугольника\.",
                text,
            )
            answer = 6 * coeff
            near(radius, float(coeff) * math.sqrt(3))
            near(triangle_side, float(answer))
            scale = coeff / 2
            expected_source = "356518"
            variant = 2
        else:
            (coeff,) = match(
                rf"В окружность с центром O вписан равносторонний треугольник\. "
                rf"Расстояние от точки O до сторон треугольника равно {N}√3/2\. "
                rf"Найдите длину стороны треугольника\.",
                text,
            )
            answer = 3 * coeff
            near(triangle_side, float(answer))
            scale = coeff
            expected_source = "472375"
            variant = 3
            near(radius, float(coeff) * math.sqrt(3))
            on_circle = "ABC"
            expected_names = "ABCO"
        if key == "C04":
            tangencies(p, "ABC", center, radius / 2 if variant == 3 else radius)
    elif key == "C05":
        trap = text.startswith("Трапеция")
        prefix = (
            "Трапеция ABCD с основаниями AD и BC описана" if trap else "Четырёхугольник ABCD описан"
        )
        ab, bc, cd = match(
            rf"{prefix} около окружности\. AB = {N}, BC = {N}, CD = {N}\. Найдите AD\.", text
        )
        answer = ab + cd - bc
        require(answer > 0, "Positive missing side")
        tangencies(p, "ABCD", center, radius)
        for pair, length in (("AB", ab), ("BC", bc), ("CD", cd), ("AD", answer)):
            near(distance(p[pair[0]], p[pair[1]]), float(length))
        if trap:
            near(cross(vector(p["A"], p["D"]), vector(p["B"], p["C"])), 0)
            require(source in {"356603", "438296"}, "Wrong trapezoid source")
            variant = 1 if source == "356603" else 2
            scale = ab / 11
        else:
            require(source == "356579", "Wrong quadrilateral source")
            scale = ab / 7
        expected_source = source
        expected_names, on_circle, edges = "ABCD", "", "AB BC CD DA"
    elif key == "C06":
        (diag,) = match(
            rf"Диагональ AC ромба ABCD равна {N}, а тангенс угла BCA равен 7/24\. "
            rf"Найдите радиус окружности, вписанной в ромб\.",
            text,
        )
        answer = diag * Fraction(7, 50)
        equal_sides(p, "ABCD")
        tangencies(p, "ABCD", center, radius)
        near(distance(p["A"], p["C"]), float(diag))
        near(math.tan(math.radians(angle(p["B"], p["C"], p["A"]))), 7 / 24)
        near(radius, float(answer))
        expected_source, scale = "472385", diag / 48
        expected_names, on_circle, edges = "ABCD", "", "AB BC CD DA AC"
    elif key == "D01":
        trap = text.startswith("Трапеция")
        noun = (
            "Трапеция ABCD с основаниями AD и BC вписана" if trap else "Четырёхугольник ABCD вписан"
        )
        (a,) = match(
            rf"{noun} в окружность\. Угол A равен {N}°\. Найдите угол C\. Ответ дайте в градусах\.",
            text,
        )
        answer = 180 - a
        near(angle(p["B"], p["A"], p["D"]), float(a))
        near(angle(p["B"], p["C"], p["D"]), float(answer))
        turns = [
            cross(vector(p[x], p[y]), vector(p[y], p[z]))
            for x, y, z in (("A", "B", "C"), ("B", "C", "D"), ("C", "D", "A"), ("D", "A", "B"))
        ]
        require(all(t > 0 for t in turns) or all(t < 0 for t in turns), "Nonconvex cyclic polygon")
        if trap:
            near(cross(vector(p["A"], p["D"]), vector(p["B"], p["C"])), 0)
        expected_source = "356448" if trap else "356438"
        variant = int(trap)
        scale = a - (81 if trap else 82) + 1
        expected_names, on_circle, edges = "ABCD", "ABCD", "AB BC CD DA"
    elif key == "D03":
        (coeff,) = match(
            rf"Радиус окружности, описанной около квадрата, равен {N}√2\. Найдите "
            rf"длину стороны этого квадрата\.",
            text,
        )
        answer = 2 * coeff
        equal_sides(p, "ABCD")
        near(angle(p["A"], p["B"], p["C"]), 90)
        near(radius, float(coeff) * math.sqrt(2))
        near(distance(p["A"], p["B"]), float(answer))
        expected_source, scale = "369738", coeff / 16
        expected_names, on_circle, edges = "ABCD", "ABCD", "AB BC CD DA"
    elif key == "D04":
        (coeff,) = match(
            rf"В треугольнике ABC угол C равен 45°, AB = {N}√2\. Найдите радиус "
            rf"окружности, описанной около этого треугольника\.",
            text,
        )
        answer = coeff
        near(angle(p["A"], p["C"], p["B"]), 45)
        near(distance(p["A"], p["B"]), float(coeff) * math.sqrt(2))
        near(radius, float(answer))
        expected_source, scale = "450514", coeff / 6
        expected_names, on_circle, edges = "ABC", "ABC", "AB BC CA"
    elif key == "D05":
        (r,) = match(
            rf"Точка O является серединой стороны CD квадрата ABCD\. Радиус "
            rf"окружности с центром O, проходящей через вершину A, равен {N}\. "
            rf"Найдите площадь квадрата ABCD\.",
            text,
        )
        answer = Fraction(4, 5) * r * r
        sides = equal_sides(p, "ABCD")
        near(angle(p["A"], p["B"], p["C"]), 90)
        near(radius, float(r))
        near(distance(center, p["O"]), 0)
        for axis in (0, 1):
            near(p["O"][axis], (p["C"][axis] + p["D"][axis]) / 2)
        near(sides[0] ** 2, float(answer))
        near(area([p[n] for n in "ABCD"]), float(answer))
        expected_source, scale = "462105", r / 5
        expected_names, on_circle, edges = "ABCDOLR", "ABLR", "AB BC CD DA LR"
    elif key == "D06":
        (d,) = match(
            rf"Синус угла между стороной и диагональю прямоугольника равен 0,6\. "
            rf"Диаметр описанной около него окружности равен {N}\. Найдите площадь "
            rf"прямоугольника\.",
            text,
        )
        answer = d * d * Fraction(12, 25)
        for triple in ("ABC", "BCD", "CDA", "DAB"):
            near(angle(p[triple[0]], p[triple[1]], p[triple[2]]), 90)
        near(2 * radius, float(d))
        near(distance(p["A"], p["C"]), float(d))
        near(math.sin(math.radians(angle(p["D"], p["A"], p["C"]))), 0.6)
        near(area([p[n] for n in "ABCD"]), float(answer))
        expected_source, scale = "472378", d / 10
        expected_names, on_circle, edges = "ABCD", "ABCD", "AB BC CD DA AC"
    else:
        raise ValueError("Unknown complete family")
    require(source == expected_source, "Source mismatch")
    hidden = {
        "B01": ["T", "L"],
        "B02": ["P"],
        "B03": list("ABOM"),
        "C01": list("ABCD"),
        "C02": list("ABCD"),
        "C03": list("ABC"),
        "C04": list("ABC"),
        "D02": list("ABC"),
        "D03": list("ABCD"),
        "D05": ["L", "R"],
        "D06": list("ABCD"),
    }.get(key, [])
    require(g.get("hidden_labels", []) == hidden, "Extra or missing visible labels")
    require(set(p) == set(expected_names), "Unexpected point labels")
    require(
        len(g["segments"]) == len(edges.split())
        and {"".join(sorted(e)) for e in g["segments"]}
        == {"".join(sorted(e)) for e in edges.split()},
        "Unexpected construction",
    )
    for name in on_circle:
        near(distance(p[name], center), radius)
    if "O" in p:
        near(distance(p["O"], center), 0)
    require(
        snapshot["parameters"] == [str(Fraction(variant)), str(scale)],
        "Parameters differ from visible inputs",
    )
    require(scale.denominator == 1 and 1 <= scale <= 10, "Source scaling bound")
    require(answer > 0 and answer <= 40000, "Short-answer bound")
    require(snapshot["correct_answer"] == format_decimal(answer), "Wrong exact answer")
    require(
        snapshot["solution"][-1].endswith(f" = {format_decimal(answer)}."), "Wrong visible solution"
    )
    require(
        isinstance(snapshot["hints"], list)
        and len(snapshot["hints"]) == 1
        and snapshot["solution"] == [*snapshot["hints"], snapshot["solution"][-1]],
        "Invalid hint/proof structure",
    )
    require(snapshot["hints"] == [EXPECTED_THEOREMS[key]], "Theorem or hint changed")
    check_calculation(key, source, snapshot["solution"][-1], answer)
    return answer
