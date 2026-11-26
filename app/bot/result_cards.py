"""Shared result layout for known aggregate outcomes and optional practice feedback."""

from app.bot.math_layout import Role, TrainingMessage
from app.bot.visual_models import (
    VisualBreakdown,
    VisualCard,
    VisualEntry,
    VisualMetric,
    VisualPractice,
    VisualSection,
)


def result_card(
    heading: str, issued: int, solved: int, independent: int, skipped: int, *, subtitle: str = "",
    practice: tuple[VisualPractice, ...] = (), recommendation: str = "", note: str = "",
    hint: str = "",
) -> VisualCard:
    breakdown = VisualBreakdown(
        independent, solved - independent, issued - solved - skipped, skipped,
    )
    if min(breakdown.independent, breakdown.assisted, breakdown.unsolved, breakdown.skipped) < 0:
        raise ValueError("Result counters must partition the issued tasks")
    return VisualCard(
        "training_result", heading, subtitle,
        metrics=(
            VisualMetric(f"{solved}/{issued}", "Решено верно", "good"),
            VisualMetric(f"{independent}/{issued}", "Самостоятельно"),
        ),
        sections=(VisualSection("Что повторить", (VisualEntry(recommendation),)),)
        if recommendation else (),
        note=note, hint=hint,
        breakdown=breakdown,
        practice=practice,
    )


def result_fallback(card: VisualCard) -> TrainingMessage:
    breakdown = card.breakdown
    assert breakdown is not None
    blocks: list[tuple[Role, str]] = [("title", card.title)]
    if card.subtitle:
        blocks.append(("position", card.subtitle))
    blocks.append(("stats", "\n".join((
        f"Решено верно: {breakdown.independent + breakdown.assisted} из {breakdown.total}",
        f"Самостоятельно: {breakdown.independent} из {breakdown.total}",
        f"Другие верные: {breakdown.assisted} · Не решено: {breakdown.unsolved} · "
        f"Пропущено: {breakdown.skipped}",
    ))))
    if card.note:
        blocks.append(("stats", card.note))
    if card.practice:
        blocks.append(("section", "Закрепление типа"))
        blocks.extend(("stats", f"{item.label}\n{item.status}.") for item in card.practice)
    for section in card.sections:
        blocks.append(("section", section.title))
        blocks.extend(("recommendation", entry.label) for entry in section.entries)
    if card.hint:
        blocks.append(("instruction", card.hint))
    return TrainingMessage(*blocks)
