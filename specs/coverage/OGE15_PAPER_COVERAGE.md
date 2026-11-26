# OGE №1–5, сюжет PAPER «Форматы бумаги»

**Редакция:** V1, исследование от 2026-11-02. **Реализация:** `paper-v5`.
**Область:** общий движок практических задач №1–5; один связный сценарий на пять позиций.

Семейства ниже основаны на пакете `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`,
раздел `STORIES/PAPER/`. Каталог «Решу ОГЭ» проверен по указанным карточкам;
это не заявление об официальной индивидуальной проверке ФИПИ или о полном покрытии банка.
Сгенерированные условия являются самостоятельными аналогами подтверждённых конструкций.

## Матрица семейств

| ID | № | Статус V1 | Источники и происхождение | Решение реализации |
|---|---:|---|---|---|
| `PAPER-F01` | 1 | `enabled_candidate` | [408268](https://math-oge.sdamgia.ru/problem?id=408268), `catalog_verified`; research index attributes a separate SPB-2025-2502 example, not independently checked | Candidate is limited to a bijection from four requested formats to four unlabeled dimension rows, with the answer as four row numbers in the requested order. Do not infer whole-bank coverage from this prototype. |
| `PAPER-F02` | 2 | `enabled_candidate` | [408281](https://math-oge.sdamgia.ru/problem?id=408281), explicitly attributed to Saint Petersburg mock 06.02.2025, variant 2501; [408284](https://math-oge.sdamgia.ru/problem?id=408284), `catalog_verified` | Verified source cases are A2→A3 and A0→A5. The generator generalizes to Aᵢ→Aⱼ for 0≤i<j≤6; intermediate pairs are mathematical analogues, not individually source-checked. With one to five starting sheets, the answer is the initial count times 2^(j−i). |
| `PAPER-F03` | 3 | `enabled_candidate` | [408300](https://math-oge.sdamgia.ru/problem?id=408300), `catalog_verified`; [408313](https://math-oge.sdamgia.ru/problem?id=408313) is the A7 length rounding variant | The requested ISO side is read from the common table and rounded to a multiple of 5 or 10. Inputs already divisible by the step are excluded. Exact ties specify rounding to the larger multiple. |
| `PAPER-F04` | 4 | `enabled_candidate` | [408314](https://math-oge.sdamgia.ru/problem?id=408314), `catalog_verified` | Source asks for A3 smaller-side / larger-side. The candidate keeps this direction across A0–A7, takes both dimensions from the table, and rounds to tenths or hundredths. |
| `PAPER-F05` | 4 | `research_only` | Ширяева, *Задачник ОГЭ 2025*, стр. 2; no stable catalog task ID or public source URL independently verified | Reverse ratio (larger/smaller) remains disabled; evidence is a secondary collection only. |
| `PAPER-F06` | 4 | `enabled_candidate` | [408320](https://math-oge.sdamgia.ru/problem?id=408320), `catalog_verified` | Source asks for A2 diagonal / smaller side, deriving A2 sides from the shared A3 row (420×297): A2 is 594×420. The condition names the next format used for reconstruction. Four exactly reversible ISO cuts support tenths or hundredths and a diagonal divided by either side. |
| `PAPER-F07` | 5 | `enabled_candidate` | [408333](https://math-oge.sdamgia.ru/problem?id=408333), [408343](https://math-oge.sdamgia.ru/problem?id=408343), [460960](https://math-oge.sdamgia.ru/problem?id=460960), `catalog_verified` | The candidate scales in both directions between A3 and A4 for 8–24 pt. The stated long-side rule determines the scale from the shared rows. |
| `PAPER-F08` | 3 | `blocked` | [408294](https://math-oge.sdamgia.ru/problem?id=408294), `conflicted` | Выключено: площадь A1 равна 5000 см² по идеальному определению A0=1 м² и 4995,54 см² по округлённым размерам 841×594 мм. |
| `PAPER-F09` | 5 | `blocked` | [408323](https://math-oge.sdamgia.ru/problem?id=408323), exam attributed, not independently verified; [408331](https://math-oge.sdamgia.ru/problem?id=408331), `catalog_verified` | Выключено: масса по идеальной площади и по округлённым размерам расходится (1250/1243,2 г; 4500/4475,52 г). |

В полном источниковом индексе также описан связанный пробный вариант Санкт-Петербурга
05.02.2025, вариант 2 (`SPB-2025-2502`), с проверочными производными ответами
`4132`, `8`, `840`, `0,7`, `11`. Они использованы как regression-вектор, а не как
копия официального ключа. Источник помечен `exam_attributed_not_independently_verified`.

## Реализованная модель

- Один seed задаёт четыре строки таблицы с исходными размерами для всех
  зависимых вопросов. Таблица показывает номер строки и две стороны.
  Форматы определяются по площадям относительно A0. Пять вопросов используют
  один сценарий и одну таблицу.
- Справочник A0…A7 хранит округлённые пары `(длинная, короткая)` в миллиметрах;
  площадь A0=1 м² применяется только для последовательных переходов формата.
  Площадь по определению никогда не подменяется площадью из округлённых размеров.
- Ответы проверяются версиями политик: перестановка четырёх строк, положительное
  целое число листов, округлённое целое число миллиметров, десятичное отношение,
  целое число пунктов шрифта. Для десятичных ответов принимаются точка и запятая.
- Oracle заново разбирает видимое условие и общую текстовую таблицу, сверяет
  размеры, направление отношения, единицы, округление, подсказки, решение,
  provenance и совместимость всех пяти позиций.
- Renderer создаёт собственную PNG-схему A0–A5 и отдельную PNG-таблицу 4×3
  в памяти. Snapshot фиксирует два SHA-256 asset reference; восстановление таблицы
  использует сохранённые строки, версию генератора и проверяет digest.
  Старые снимки восстанавливают исходный PNG. Для ответов на отношения
  сохранена политика v1, новые снимки используют v2.

## Качество и естественная ёмкость

[Отчёт качества paper-v5](../../reports/oge15-paper-quality.json) фиксирует
проверку генератора и математическое разнообразие. Полная ёмкость обновлённых
семейств по релевантным параметрам составляет F02 — 30, F03 — 13, F04 — 16,
F06 — 16, F07 — 34. Форматы серии A близки по пропорциям, поэтому разные
размеры могут давать одинаковый ответ после округления. Для F06 используются
только A2, A3, A5 и A6, у которых точные размеры восстанавливаются удвоением
короткой стороны следующего формата. Приёмка проверяет полные сценарии и
видимые условия независимым расчётом.

F05/F08/F09 не генерируются и не доступны через реестр. Публикация и подключение
Telegram-потока остаются отдельным этапом общего движка.
