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
| `renderer` | `Renderer.render_scenario(scenario) -> RenderedScenario` | Один раз создаёт общий текст/таблицу/рисунок. Возвращает ссылки на assets по SHA-256, не копии PNG в вопросах. |
| `answer_policies` | `Mapping[(policy_id, version), AnswerPolicy]` | Версионированная политика с `accepts(raw, canonical)`. |
| `family_registry` | `tuple[FamilyRegistration, ...]` | Семейство, позиция, статус источника, политика, source IDs и отдельный флаг `enabled=False` по умолчанию. |

`FamilyRegistry` отклоняет повторные story/family ID, неизвестные позиции,
отсутствующие политики для включённых типов и неполную пятёрку для режима `full`.
В production registry обнаруживает только добавленные story-файлы; текущая
директория пуста. Поэтому меню не предлагает №1–5 и случайный выбор не может
попасть в неработающий сюжет.

## Сборка и режимы

`build_practice_plan(PracticeRequest(...), registry)` выполняет общий fail-closed
pipeline: доступность выбранного режима → один `generate_scenario(seed)` → один
`render_scenario(scenario)` → вопросы 1–5 → проверки oracle/policy/family → один
`ScenarioSnapshot`. В `single` указывается `position=1..5` или `None` для
случайной позиции; `story_code` — сюжет или `None` для случайного. Одиночный
snapshot сохраняет выбранный вопрос и общий контекст, поэтому отдельная проверенная
позиция доступна до завершения полной пятёрки. В `full` `position` запрещена,
`selected_positions` всегда `(1, 2, 3, 4, 5)`, а вопросы хранятся единым snapshot.

У каждой позиции есть обязательное поле `scenario_seed`, которое сверяется с
seed сценария. Snapshot immutable, schema version 1. При восстановлении он
читается из БД, а не генерируется заново. Тексты задач, ответ, политика, подсказки,
разбор, модель, provenance и общая презентация сериализуются один раз.

## PostgreSQL и Telegram state

`ScenarioPostgresRepository.start_session()` атомарно сохраняет snapshot и одну
сессию. Таблица `oge15_question_progress` содержит только исход/попытки/подсказки
по позиции; она не дублирует вопросы, текст сценария или картинку. `resume_session()`
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

Assets хранятся отдельно по digest. `oge15_scenario_assets` добавляет одну ссылку
на картинку на сценарий; `oge15_protected_assets` перечисляет изображения,
используемые незавершёнными сессиями, для будущей компактизации PNG. Компактор
должен исключать все эти digest; PNG bytes нельзя помещать в вопросные строки.

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
