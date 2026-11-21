"""School notation for existing, immutable first-part text templates."""

import re

from app.math.probability import counted_phrase


def learner_text(text: str, family: str) -> str:
    if not family.startswith("OGE") or not family[3:5].isdigit() or int(family[3:5]) > 19:
        return text
    # The wire policy accepts both decimal separators. Numbered steps use a dot
    # followed by a space, so they are not decimal literals.
    text = re.sub(r"(?<=\d)\.(?=\d)", ",", text)
    if family.startswith(("OGE09-", "OGE11-", "OGE13-")):
        # Only polynomial terms, never the leading zero of a decimal, exponent,
        # or the value of a boundary comparison such as x ≤ 0.
        text = re.sub(
            r"(?<=[x²)\d])\s*[+−-]\s*0x?(?=\s*(?:[)=<>≤≥+−-]|$))", "", text, flags=re.MULTILINE
        )
        text = re.sub(r"(?<=[=(])\s*0\s*([−-])\s*(?=\d*x)", r"\1", text)
    if family.startswith("OGE13-"):
        text = text.replace("<=", "≤").replace(">=", "≥")
    if family.startswith("OGE10-"):
        text = re.sub(
            r"\b(\d+) знают",
            lambda m: (
                m[1] + (" знает" if int(m[1]) % 10 == 1 and int(m[1]) % 100 != 11 else " знают")
            ),
            text,
        )
    if family == "OGE12-R012":
        text = text.replace("для тела в воде", "для полностью погружённого в воду тела")
    if family.startswith("OGE14-"):
        text = re.sub(
            r"каждую следующую секунду тормозной путь уменьшался на (\d+) м",
            r"за каждую следующую секунду автомобиль проезжал на \1 м меньше",
            text,
        )
        text = text.replace(
            "половина вещества А превращается в вещество Б.",
            "половина вещества А превращается в вещество Б без потери массы. "
            "В начале вещества Б нет.",
        )
        text = re.sub(r"Каждые (\d+) минут\b", r"С интервалом \1 мин", text)
        text = re.sub(r"каждые (\d+) минут\b", r"с интервалом \1 мин", text)
        text = re.sub(r"интервал (\d+) минут\b", r"интервал длительностью \1 мин", text)
        text = re.sub(
            r"(через) (\d+) минут\b",
            lambda m: m[1] + " " + counted_phrase(int(m[2]), ("минуту", "минуты", "минут")),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(\d+) интервалов\b",
            lambda m: counted_phrase(int(m[1]), ("интервал", "интервала", "интервалов")),
            text,
        )
        text = re.sub(
            r"ровно (\d+) раз\b",
            lambda m: "ровно " + counted_phrase(int(m[1]), ("раз", "раза", "раз")),
            text,
        )
        text = re.sub(r"прошло (\d+) минут\b", r"прошло \1 мин", text)
    if family == "OGE15-F13":
        text = text.replace(
            "Коэффициент подобия:",
            "Так как MN ∥ AC, у треугольников MBN и ABC попарно равные углы. Коэффициент подобия:",
        )
        text = text.replace("S_MBN", "Площадь треугольника MBN")
    if family == "OGE15-F06":
        text = text.replace(
            "Высота равностороннего треугольника равна",
            "Медиана делит равносторонний треугольник на два равных "
            "прямоугольных треугольника, поэтому она же высота. Высота равна",
        )
    if family == "OGE16-C06":
        text = text.replace(
            "sin = 7/25",
            "по тангенсу катеты относятся как 7 к 24. "
            "По теореме Пифагора гипотенуза в тех же долях равна 25, "
            "так как 7² + 24² = 25². Поэтому sin ∠BCA = 7/25",
        )
    if family.startswith("OGE18-"):
        text = re.sub(
            r"\b(\d+) клеток\b",
            lambda m: counted_phrase(int(m[1]), ("клетка", "клетки", "клеток")),
            text,
        )
    return text
