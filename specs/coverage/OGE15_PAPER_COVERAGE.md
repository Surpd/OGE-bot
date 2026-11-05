# OGE №1–5, сюжет PAPER «Форматы бумаги»

**Редакция:** V1, исследование от 2026-11-02. **Реализация:** `paper-v3`.
**Область:** общий движок практических задач №1–5; один связный сценарий на пять позиций.

Семейства ниже основаны на пакете `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`,
раздел `STORIES/PAPER/`. Каталог «Решу ОГЭ» проверен по указанным карточкам;
это не заявление об официальной индивидуальной проверке ФИПИ или о полном покрытии банка.
Сгенерированные условия являются самостоятельными аналогами подтверждённых конструкций.

## Матрица семейств

| ID | № | Статус V1 | Источники и происхождение | Решение реализации |
|---|---:|---|---|---|
| `PAPER-F01` | 1 | `enabled_candidate` | [408268](https://math-oge.sdamgia.ru/problem?id=408268), `catalog_verified`; research index attributes a separate SPB-2025-2502 example, not independently checked | Candidate is limited to a bijection from four visible format labels to four visible dimension rows, with the answer as four row numbers in the requested order. Do not infer whole-bank coverage from this prototype. |
| `PAPER-F02` | 2 | `enabled_candidate` | [408281](https://math-oge.sdamgia.ru/problem?id=408281), explicitly attributed to Saint Petersburg mock 06.02.2025, variant 2501; [408284](https://math-oge.sdamgia.ru/problem?id=408284), `catalog_verified` | Verified source cases are A2→A3 and A0→A5. The generator generalizes to Aᵢ→Aⱼ for 0≤i<j≤6; intermediate pairs are mathematical analogues, not individually source-checked. Answer is repeated doubling, 2^(j−i). |
| `PAPER-F03` | 3 | `enabled_candidate` | [408300](https://math-oge.sdamgia.ru/problem?id=408300), `catalog_verified`; [408313](https://math-oge.sdamgia.ru/problem?id=408313) is the A7 length rounding variant | Current structure is only A0 width read from the common dimensions table, rounded to nearest ten. A7 rounding is excluded from this generator. |
| `PAPER-F04` | 4 | `enabled_candidate` | [408314](https://math-oge.sdamgia.ru/problem?id=408314), `catalog_verified` | Source asks for A3 smaller-side / larger-side. The candidate asks for that ratio without stating the dimensions; both sides are read from the shared A3 row (420×297), then rounded to tenths. |
| `PAPER-F05` | 4 | `research_only` | Ширяева, *Задачник ОГЭ 2025*, стр. 2; no stable catalog task ID or public source URL independently verified | Reverse ratio (larger/smaller) remains disabled; evidence is a secondary collection only. |
| `PAPER-F06` | 4 | `enabled_candidate` | [408320](https://math-oge.sdamgia.ru/problem?id=408320), `catalog_verified` | Source asks for A2 diagonal / smaller side, deriving A2 sides from the shared A3 row (420×297): A2 is 594×420. Current condition withholds these dimensions; oracle derives them from the visible common table. |
| `PAPER-F07` | 5 | `enabled_candidate` | [408333](https://math-oge.sdamgia.ru/problem?id=408333), [408343](https://math-oge.sdamgia.ru/problem?id=408343), [460960](https://math-oge.sdamgia.ru/problem?id=460960), `catalog_verified` | Current candidate is restricted to A4→A3 and source-seen 10 or 15 pt. It asks for the new point size without stating the scale; the long-side ratio (420/297) is derived from the shared A3/A4 table rows. |
| `PAPER-F08` | 3 | `blocked` | [408294](https://math-oge.sdamgia.ru/problem?id=408294), `conflicted` | Выключено: площадь A1 равна 5000 см² по идеальному определению A0=1 м² и 4995,54 см² по округлённым размерам 841×594 мм. |
| `PAPER-F09` | 5 | `blocked` | [408323](https://math-oge.sdamgia.ru/problem?id=408323), exam attributed, not independently verified; [408331](https://math-oge.sdamgia.ru/problem?id=408331), `catalog_verified` | Выключено: масса по идеальной площади и по округлённым размерам расходится (1250/1243,2 г; 4500/4475,52 г). |

В полном источниковом индексе также описан связанный пробный вариант Санкт-Петербурга
05.02.2025, вариант 2 (`SPB-2025-2502`), с проверочными производными ответами
`4132`, `8`, `840`, `0,7`, `11`. Они использованы как regression-вектор, а не как
копия официального ключа. Источник помечен `exam_attributed_not_independently_verified`.

## Реализованная модель

- Один seed задаёт четыре табличных формата (обязательно A0, A3 и A4),
  задачу о разрезании, округление ширины A0, один из двух типов позиции 4 и
  масштабирование шрифта A4→A3. Пять snapshots используют тот же seed.
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
  использует сохранённые строки и проверяет digest. Постоянное blob-хранилище не нужно.

## Качество и естественная ёмкость

Исторические быстрые/основные прогоны и 1200-seed fingerprint-анализ сохранены в
[`reports/oge15-paper-quality.json`](../../reports/oge15-paper-quality.json); отчёт
предшествует `paper-v3` и его количества уникальных структур не являются QA
`paper-v3`. В текущей модели F03, F04 и F06 имеют по одной source-bounded форме;
F07 имеет два проверенных значения шрифта (10 и 15 пт) при неизменном переходе
A4→A3. У F02 не более 21 пары индексов и шесть ответов. Это естественная
ёмкость источниковых конструкций, без искусственных числовых клонов и обещания
200 уникальных вариантов для каждого семейства.

F05/F08/F09 не генерируются и не доступны через реестр. Публикация и подключение
Telegram-потока остаются отдельным этапом общего движка.
