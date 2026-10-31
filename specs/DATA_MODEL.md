# Минимальная модель данных (Postgres, проектный контракт)

Не создавать таблицы до реализации первой версии миграций. Схема ниже — спецификация для Codex, а не уже действующая БД.

| Таблица | Ключевые поля | Назначение |
|---|---|---|
| `users` | `id uuid`, `telegram_user_id bigint UNIQUE`, `created_at`, `preferences jsonb` | Минимальный профиль |
| `family_registry` | `family_id text`, `version text`, `status`, `exam_year`, `evidence jsonb`, `last_tested_at` | Рубильник для каждого подтипа |
| `sessions` | `id`, `user_id`, `mode`, `state`, `started_at`, `finished_at`, `active_problem_id` | Прогресс тренировки |
| `issued_problems` | `id`, `user_id`, `session_id`, `family_id`, `generator_version`, `seed`, `fingerprint`, `shape_fingerprint`, `snapshot jsonb`, `issued_at` | Неизменяемое задание после выдачи |
| `attempts` | `id`, `problem_id`, `user_id`, `attempt_no`, `raw_answer`, `normalized_answer`, `is_correct`, `used_hint`, `created_at` | Проверка и история |
| `telegram_updates` | `update_id bigint UNIQUE`, `processed_at`, `status` | Идемпотентность webhook |
| `error_reports` | `problem_id`, `kind`, `diagnostics`, `status`, `created_at` | Блокировки, регрессии |
| `assets` | `sha256`, `storage_path`, `content_type`, `width`, `height`, `generator_version` | Подготовленная/генерируемая графика |

## Индексы / инварианты
- Unique `(telegram_user_id)`, `(update_id)`, `(problem_id, attempt_no)`.
- Index `(user_id, issued_at desc)`, `(user_id, family_id, issued_at desc)`, `(fingerprint)`, `(family_id,status)`.
- Все выдачи сохраняют snapshot **до** взаимодействия с учеником; уже выданные задания не меняются при изменении генератора.
- `attempts` сохраняет честную историю; решения с подсказками и повторными попытками не засчитываются в метрику «с первой попытки».
- Не сохранять заготовки миллионов алгоритмических примеров; только реально выданные снимки, визуальные ассеты и небольшие готовые проверенные банки.
- По умолчанию все семьи `research_only`, включение только после quality gate.
