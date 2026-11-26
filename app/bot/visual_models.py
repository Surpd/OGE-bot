"""Immutable display data for optional PNG cards."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualEntry:
    label: str
    key: str = ""
    detail: str = ""
    value: str = ""
    tone: str = "neutral"
    icon: str = ""


@dataclass(frozen=True)
class VisualSection:
    title: str
    entries: tuple[VisualEntry, ...]
    layout: str = "list"


@dataclass(frozen=True)
class VisualMetric:
    value: str
    label: str
    tone: str = "neutral"


@dataclass(frozen=True)
class VisualBreakdown:
    independent: int
    assisted: int  # All remaining verified answers, including repeats or unknown assistance.
    unsolved: int
    skipped: int

    @property
    def total(self) -> int:
        return self.independent + self.assisted + self.unsolved + self.skipped


@dataclass(frozen=True)
class VisualPractice:
    label: str
    count: int
    target: int
    confirmed: bool = False

    @property
    def status(self) -> str:
        if self.confirmed:
            return "Тип закреплён"
        remaining = self.target - self.count
        if remaining % 10 == 1 and remaining % 100 != 11:
            label = "самостоятельное решение"
        elif 2 <= remaining % 10 <= 4 and not 12 <= remaining % 100 <= 14:
            label = "самостоятельных решения"
        else:
            label = "самостоятельных решений"
        return f"Ещё {remaining} {label} для закрепления"


@dataclass(frozen=True)
class VisualCard:
    screen: str
    title: str
    subtitle: str = ""
    sections: tuple[VisualSection, ...] = ()
    metrics: tuple[VisualMetric, ...] = ()
    note: str = ""
    hint: str = ""
    breakdown: VisualBreakdown | None = None
    practice: tuple[VisualPractice, ...] = ()
