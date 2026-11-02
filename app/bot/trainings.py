"""Authoritative training registration; legacy snapshots retain their wire identifiers."""

from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class Training:
    number: int
    title: str
    availability_module: str | None = None

    @property
    def mode(self) -> str:
        return f"task{self.number}"

    @property
    def available(self) -> bool:
        if self.availability_module is None:
            return True
        return bool(import_module(self.availability_module).ENABLED_FAMILIES)


TRAININGS = (
    Training(6, "Вычисления"),
    Training(7, "Числа и координатная прямая", "app.math.oge07_scheduler"),
    Training(8, "Степени и корни"),
    Training(9, "Уравнения"),
    Training(10, "Вероятность"),
    Training(11, "Графики функций", "app.math.oge11"),
    Training(12, "Формулы"),
    Training(13, "Неравенства", "app.math.inequalities"),
    Training(14, "Прогрессии"),
)
BY_NUMBER = {item.number: item for item in TRAININGS}
