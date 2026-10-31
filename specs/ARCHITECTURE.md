# Архитектура OGE Trainer v1

## Поток запросов
`Telegram -> webhook HTTPS (FastAPI + aiogram) -> application/session service -> verified generator -> oracle -> renderer -> Telegram Bot API`; `application service <-> Supabase PostgreSQL/Storage`.

1. **Render Web Service**: один контейнер Python с FastAPI и Telegram webhook. **Не polling параллельно webhook**, иначе будут потери/дубли.
2. **Существующий Supabase project**: пользователи, состояния сессий, попытки, снимки выданных заданий, версии семейств, метаданные готовых рисунков. База Render не создаётся.
3. **GitHub**: код, atlas source, миграции, CI, тесты. Не хранить секреты и массово чужие задания.
4. **Math core**: самостоятельная библиотека Python без Telegram, DB, HTTP, Groq. Детеминизм, безопасные числа, стабильные API.
5. **Content**: для №1–5 и визуально сложных задач готовые подтверждённые изображения/параметры; для арифметики/алгебры генерация **на лету**.
6. **Renderer**: структурированные blocks → HTML-safe Telegram text; TeX для изображений формул при необходимости; для графики SVG → PNG и `sendPhoto`/`sendDocument`, кэш по content hash.

## Контракт Problem (проектируемая схема; реализовать как Pydantic-модели)
- identity: `problem_id`, `exam_year`, `number`, `family_id`, `generator_version`, `seed`, `fingerprint`.
- model: `parameters`, `math_ast`, `semantic_world_id` для комплекта 1–5.
- presentation: `statement_blocks`, `image_ref`, `options`, `unit`, `format_instructions`.
- grading: `answer_kind`, `canonical_answer`, `acceptable_equivalents`, `grading_policy`, `answer_oracle_version`.
- guidance: `hints`, `solution_steps`, `skill_tags`, `difficulty`.
- provenance: `reference_ids` (только ID/URLs источников), `qc_passed`, `qc_run_id`.
- `Problem` после отправки ученику сериализуется **immutable**; хранить не только seed, иначе рефактор генератора изменит исторические задания.

## Детерминизм и уникальность
`generate(family_id, seed, version)` всегда возвращает одно значение. Seed должен использовать собственный RNG, не глобальный random; значения времени или внешний LLM не участвуют. Fingerprint: `hash(versioned AST + mathematical params + target + visible relevant text/figure)`; отдельно shape-hash для контроля математически эквивалентных задач. Для персональной истории хранить и fingerprint, и family_id.

## Когда онлайн, а когда банк
- Обычный выбор задания → серверный **алгоритм** для включённых и проверенных семейств; не запрос к Groq.
- Сюжет 1–5 → один согласованный общий мир + подготовленное/программно созданное изображение и пять вопросов.
- Геометрия/графики → программа строит по параметрам при наличии надёжного рендера или использует небольшую готовую библиотеку; ни один генератор не считается качественным только из-за правильных чисел без геометрической проверки.
- Банки только для редких/визуальных случаев и сертифицированных утверждений №19.

## Fail-closed
Любой несовпавший oracle, ошибка рендера, некорректная единица/диапазон, неоднозначный выбор или лимит времени → отказ от данной выдачи, structured diagnostic, попытка другого **включённого** семейства. Если нельзя — сообщение «Сейчас нет доступной задачи этого типа»; не отправлять сомнительный вариант.

## Проектное дерево для Codex
```
app/
  api/            # webhook/health/optional internal routes
  bot/            # menus, callbacks, formatters
  core/           # sessions, progression, grading, recommendations
  math/           # AST, families, RNG, independent oracles
  render/         # statements + SVG/PNG
  persistence/    # Postgres, transactions and repositories
migrations/       # database migrations
atlas/            # versioned, verified coverage registry
tests/            # fixtures, math property, integration and bot
scripts/          # research, bulk validation, smoke verification
.github/workflows/ci.yml
Dockerfile
pyproject.toml
AGENTS.md
```

## Миграция на Mini App
Позже создать отдельный клиент (возможно GPT Sites), оставить всю математическую логику и хранение без изменений. Подготовить REST/application interfaces сейчас, **но не создавать фронтенд v1**.
