# TYRES — покрытие и статус проверки

Исторический отчёт первоначальной реализации (tyres-v1); прежние числовые
пробы и версии изображений ниже не описывают текущую V2. Актуальная
структура и ограничения — в [матрице](OGE15_V2_FAMILY_REVIEW.md),
[приёмке](OGE15_V2_SOURCE_ACCEPTANCE.md) и [пробе 64 seed](OGE15_V2_DIVERSITY.md).


**Адаптер:** `app/math/scenarios/stories/TYRES.py`
**Исследование:** `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip`, `STORIES/TYRES/RESEARCH.md`, `FAMILIES.json`, `SOURCE_INDEX.csv` (2026-11-02).
**Специализированный V2:** недоступен; реализация ограничена проверенным полным комплектом 2026 и не заявляет полное покрытие банка.

## Семейства

| Family ID | Источник | Статус в адаптере | Тесты | Ограничения |
|---|---|---|---|---|
| `TYRES-TABLE-EXTREME` | FIPI-2026, positions 1–5, Q1 ([HTML mirror](https://egesto.ru/math-oge/varianty/0)); Решу ОГЭ №407953 and №400984 (min): [407953](https://math-oge.sdamgia.ru/problem?id=407953), [400984](https://math-oge.sdamgia.ru/problem?id=400984) | Enabled candidate: minimum width among non-empty cells at a selected rim diameter | 250+ independent checks; FIPI table vector; table/value mutations | Source 407953 asks the minimum at 15 inches (185 mm). Source 400984 asks the minimum at 16 inches, but its published answer is `1`, inconsistent with its table (185 mm); use the visible table as oracle, never that key. Generated values come from the chosen column only. |
| `TYRES-SIDEWALL` | FIPI-2026, position 2 ([HTML mirror](https://egesto.ru/math-oge/varianty/0)); Решу ОГЭ №462108 and №462128: [462108](https://math-oge.sdamgia.ru/problem?id=462108), [462128](https://math-oge.sdamgia.ru/problem?id=462128) | Enabled candidate | 250+ checks; №462128 independently recomputes 165×65/100 = 107.25 mm; marking/unit mutations | Height is derived from the visible width and profile percent, H=B×p/100; rim diameter is not part of this calculation. Decimal point and comma are accepted. |
| `TYRES-DIAMETER` | FIPI-2026, position 3 ([HTML mirror](https://egesto.ru/math-oge/varianty/0)); Решу ОГЭ №408172: [408172](https://math-oge.sdamgia.ru/problem?id=408172) | Enabled candidate | 250+ checks; №408172 vector for 165/70 R13 = 561.2 mm; base/unit mutations | Derive H=B×p/100, convert rim inches using 25.4 mm/in, then D=25.4R+2H. No extra rounding. |
| `TYRES-RADIUS-DELTA` | FIPI-2026, position 4 ([HTML mirror](https://egesto.ru/math-oge/varianty/0)); Решу ОГЭ №409262: [409262](https://math-oge.sdamgia.ru/problem?id=409262) | Enabled candidate | 250+ checks; FIPI vector = 2.75 mm; №409262 supplies the radius-difference structure; comparison-direction regression | Ask for the difference between wheel radii; generated wording compares larger and smaller radii, so the requested magnitude is absolute. Equal rim diameters in generated pairs cancel the rim term; independently compute sidewalls from marking. |
| `TYRES-PERCENT-ROTATION` | FIPI-2026, position 5 ([HTML mirror](https://egesto.ru/math-oge/varianty/0)); Решу ОГЭ №408173 and №480721: [408173](https://math-oge.sdamgia.ru/problem?id=408173), [480721](https://math-oge.sdamgia.ru/problem?id=480721) | Enabled candidate | 250+ checks; №408173 independently recomputes increase from 165/70 R13 to 175/60 R14 as 0.8%; №480721 uses 175/70 R12 → 175/65 R13 and gives 1.4%; rounding mutations | Compare circumferences via diameters: ((D₂−D₁)/D₁)×100%, round to tenths. Source examples use different markings/baselines; generated set restricts the requested change to positive increases. |
| `TYRES-DIAMETER-DELTA` | Решу ОГЭ №408171: [408171](https://math-oge.sdamgia.ru/problem?id=408171) | Disabled | Registration and absence from available five-question bundles | The card is labeled position 4, although the 2026 full-set Q4 is a radius-difference task. It asks diameter increase from 165/70 R13 to 195/50 R15 (14.8 mm); no source-confirmed compatible full bundle is available, so it stays disabled. |

FIPI источник полного набора: [демоверсия 2026 в HTML-зеркале](https://egesto.ru/math-oge/varianty/0). В наборе общая заводская маркировка `175/70 R12`; позиции: минимум ширины по таблице, высота боковины, диаметр заводского колеса, разность радиусов, процент увеличения пробега за оборот. Зеркало атрибутирует набор ФИПИ, но это не прямая публикация на домене ФИПИ. Ссылки Решу ОГЭ — карточки каталога; при разночтениях принадлежность к официальному полному комплекту не выводится только из номера карточки.

## Проверки

- `tests/test_tyres_story.py`: 9 тестов — deterministic seed, полный и одиночный планы, пяти-вопросный snapshot, asset restore после повторной сборки адаптера, числовая политика, исследовательский source vector, мутации единиц/маркировки/таблицы/базы/округления/изображения/seed, отсутствие подключения номера к Telegram menu.
- Основной oracle sweep: 250 первых seed; приёмочный sweep: 1 200 seed. Уникальные варианты при этом считаются по полям конкретного задания (без несвязанных частей общего контекста): Q1 — 1 200; Q2 — 210; Q3 — 209; Q4 — 1 003; Q5 — 1 142. Каждый вариант проходит `build_practice_plan`, то есть генератор, рендер и независимую проверку условий, ответов и полного набора.
- PNG: схема создана Pillow в фиксированном размере 960×620; подписи B/H/d/D проверены на изображении, видимый bounding box не обрезан. PNG одинаков при разных числовых параметрах и восстанавливается по SHA-256; таблица и маркировка остаются отдельным текстом.
- Single сохраняет все пять вопросов и общий контекст/asset, выбирая для решения одну позицию. Full использует те же контекст, таблицу и изображение на позициях 1–5.

## Ограничения

- V1 обозначен исследователем как частичный и не содержит отдельной генераторной спецификации, изображения-эталона, oracle vectors или полного набора фикстур для TYRES. Поэтому кроме полного набора 2026 альтернативные конструкции не комбинируются произвольно.
- Проверка демоверсии использовала опубликованное HTML-зеркало, а не оригинальный PDF на домене ФИПИ. Прямое независимое подтверждение официального оригинала остаётся ограничением provenance.
- `TYRES-DIAMETER-DELTA` не включён. Повторное включение требует сверить позицию №408171 с исходным годом/вариантом и подтвердить совместимость полного набора.
- 200+ вариантов — генераторная вариативность внутри исследованных конструкций, не оценка покрытия всего банка ОГЭ.
- Адаптер не зарегистрирован в Telegram тренировке и не добавлен в меню. Merge, deploy и production Supabase не выполнялись.
