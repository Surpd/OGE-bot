# Общий движок практических заданий №1–5

Статус: инфраструктурный этап; ни один сюжетный генератор не включён.
Исследовательская основа: `OGE_1_5_ALL_STORIES_RESEARCH_V1.zip` (пакет V1,
2026-11-02). В пакете 77 исследовательских семейств: 60 `enabled_candidate`,
10 `research_only`, 7 `blocked`. Ни один из этих статусов сам по себе не
разрешает выдачу ученикам. См. [карту покрытия](OGE1_5_COVERAGE.md).

## Файлы общего API

- `app/math/scenario_engine.py` — неизменяемые snapshots, интерфейсы, выбор
  режима/сюжета/позиции, независимые quality gates и пустой fail-closed registry.
- `app/math/scenarios/stories/<STORY_CODE>.py` — один будущий адаптер сюжета.
  Каждый модуль самостоятелен; добавление файла не требует правки общего реестра.
- `app/persistence/scenario_repository.py` — одна строка сценария, отдельные
  состояние/попытки для позиций, возобновление и атомарная обработка callback.
- `migrations/0012_oge15_scenarios.sql` — схема PostgreSQL для snapshots,
  прогресса и ссылок на переиспользуемые assets.

## Контракт сюжетного модуля

Модуль `stories/<CODE>.py` экспортирует `build_adapter() -> StoryAdapter`, где
`StoryAdapter` содержит:

| Поле | Интерфейс | Назначение |
|---|---|---|
| `generator` | `ScenarioGenerator.generate_scenario(seed) -> ScenarioDraft` | Создаёт общий мир один раз. Детерминированный собственный RNG; без Telegram, БД и LLM. |
| `question_builder` | `QuestionBuilder.build_question(scenario, position) -> QuestionDraft` | Строит позицию 1–5 из уже созданного мира. |
| `independent_oracle` | `validate_scenario(...)`, `validate_question(scenario, question, rendered)`, `validate_bundle(scenario, questions, rendered)` | Независимо проверяет модель, фактически отрендеренное условие и совместимость выбранного набора вопросов. Выбрасывает ошибку при расхождении. |
| `renderer` | `Renderer.render_scenario(scenario) -> RenderedScenario`; `restore_asset(snapshot, asset) -> bytes` | Один раз создаёт общий текст/таблицу/рисунок и возвращает ссылки на assets по SHA-256. Восстановление обязано детерминированно вернуть те же байты из immutable snapshot. |
| `answer_policies` | `Mapping[(policy_id, version), AnswerPolicy]` | Версионированная политика с `accepts(raw, canonical)`. |
| `family_registry` | `tuple[FamilyRegistration, ...]` | Семейство, позиция, статус источника, политика, source IDs и отдельный флаг `enabled=False` по умолчанию. |

`FamilyRegistry` отклоняет повторные story/family ID, неизвестные позиции,
отсутствующие политики для включённых типов и неполную пятёрку.
В production registry обнаруживает только добавленные story-файлы; текущая
директория пуста. Поэтому меню не предлагает №1–5 и случайный выбор не может
попасть в неработающий сюжет.

## Сборка и режимы

`build_practice_plan(PracticeRequest(...), registry)` выполняет общий fail-closed
pipeline: доступность выбранного режима → один `generate_scenario(seed)` → один
`render_scenario(scenario)` → вопросы 1–5 → проверки oracle/policy/family → один
`ScenarioSnapshot`. В `single` указывается `position=1..5` или `None` для
случайной позиции; `story_code` — сюжет или `None` для случайного. В обоих режимах
snapshot содержит все пять связанных вопросов одного seed. Для `single`
`selected_positions` содержит ровно выбранную позицию, а запись прогресса создаётся
только для неё; для `full` выбирается `(1, 2, 3, 4, 5)`.

У каждой позиции есть обязательное поле `scenario_seed`, которое сверяется с
seed сценария. Snapshot immutable, schema version 1. При восстановлении он
читается из БД, а не генерируется заново. Тексты задач, ответ, политика, подсказки,
разбор, модель, provenance и общая презентация сериализуются один раз.

## PostgreSQL и Telegram state

`ScenarioPostgresRepository.start_session()` атомарно сохраняет snapshot и одну
сессию. Snapshot содержит все пять вопросов и общий контекст один раз. Таблица
`oge15_question_progress` содержит только исход/попытки/подсказки по выбранным
позициям; она не дублирует вопросы, текст сценария или картинку. `resume_session()`
восстанавливает прежний immutable snapshot. `record_attempt()` блокирует строку
позиции, ограничивает две попытки и отвергает старое сообщение/повторный Telegram
message ID. `apply_callback()` проверяет одноразовый callback query ID, текущую
позицию, revision и ID управляющего сообщения в одной транзакции.

Действия соответствуют `TRAINING_UX_CONTRACT.md`: hint только на активной позиции,
solution закрывает самостоятельный зачёт, skip завершает активную позицию,
next разрешён только после терминального исхода, pause/resume сохраняют активное
состояние. При full переход идёт только к следующему номеру того же snapshot.
`oge15_position_stats` предоставляет строки по позициям 1–5 и общую строку
`position=0`, с теми же метриками issued/attempts/correct/skipped/hints/solutions.

### Общий контракт графики: детерминированное восстановление без blob-хранилища

Все семь адаптеров используют один путь; отдельный bucket/диск/S3 и платные
сервисы не подключаются. Источник изображения — сохранённый `ScenarioSnapshot`
(`context`, версии генератора и compatibility matrix) плюс версия кода адаптера.
`render_scenario()` строит PNG или SVG в памяти; bytes сразу передаются Telegram
как `sendPhoto` для PNG или `sendDocument` для SVG. После перезапуска Render
`restore_asset(snapshot, asset)` повторно строит bytes из snapshot, не обращаясь к
seed/рандому и не генерируя заново ответ. Для идентичного окружения/версии должны
получиться байты с тем же SHA-256; иначе выдача прекращается с ошибкой целостности.

`ScenarioAssetRef.sha256` — SHA-256 точных отправляемых байтов, MIME ограничен
`image/png`/`image/svg+xml`, `storage_key` — только стабильный `sha256/<digest>.<ext>`
идентификатор, а не путь к диску или облаку. Перед отправкой общий helper
`restore_asset_bytes(renderer, snapshot, asset)` сверяет принадлежность asset
snapshot и digest. Ключ по digest дедуплицирует `oge15_assets`; сценарии ссылаются
на один ключ через `oge15_scenario_assets`. Сами PNG/SVG байты не сохраняются ни в
PostgreSQL, ни в локальной файловой системе; Telegram `file_id` можно кэшировать
позже как оптимизацию, но восстановление от него не зависит.

Это согласуется с PR #19: `oge15_protected_assets` включает digest, связанные с
активными/поставленными на паузу сессиями, а будущая компактизация не должна
удалять эти ссылки. После завершения сценария неиспользуемые refs/metadata можно
удалять по digest; файлы-сироты не накапливаются, потому что движок их не создаёт.
Никакой отдельной migration для blob storage не нужна. Адаптер обязан сохранить
совместимость генерации байтов в пределах snapshot schema и версии renderer; если
старую версию рендеринга нельзя восстановить, модуль оставляет семейство выключенным
до реализации совместимого пути.

## Независимая работа семи сюжетных модулей

Каждая будущая ветка может добавить один файл `app/math/scenarios/stories/<CODE>.py`
и свои изолированные тесты/спецификации. Не менять `scenario_engine.py`, общий
registry, repository или миграцию, пока адаптер соответствует этому контракту.
Сюжетный модуль не создаёт миграций и не включает семейства без source/oracle/
render/quality review и отдельного решения о публикации. Текущие имена истории:
`TYRES`, `PAPER`, `STOVE`, `TARIFF`, `ROUTE`, `GARDEN`, `FLAT`.

Обязательные применимые уроки: LL-03 (PostgreSQL restart), LL-05 (пауза/restore),
LL-06/19 (устаревшие действия и одноразовая навигация), LL-09 (версия AnswerPolicy),
LL-12 (разделять next и skip), LL-13 (условие отдельно от keyboard), LL-16
(общий UX harness), LL-20 (runtime assets). Для каждого генератора также применять
LL-01/02/14/17: независимо проверять отображённую математику и provenance.

## Схема и проверки

Миграция `0012_oge15_scenarios.sql` добавлена после текущих миграций `0001–0011`
из актуального `main`. PostgreSQL 17 — обязательный CI сервис проекта. Адресные
проверки: `tests/test_scenario_engine.py`, `tests/test_scenario_postgres.py` и
`tests/test_migrations_startup.py`; полный CI запускается один раз после адресных
проверок. Ни миграция, ни таблицы не применялись к production Supabase.
