# OGE Trainer

Фундамент Telegram-тренажёра первой части ОГЭ по математике (задания 1–19). Этот этап
не включает генераторы задач: номера и режимы остаются закрытыми до отдельной проверки качества.

## Состояние

- Backend: FastAPI + aiogram, HTTPS webhook `/telegram/webhook`, health endpoint `/health`.
- Хранилище: PostgreSQL/Supabase; схема находится в `migrations/`.
- Пользователь регистрируется по Telegram ID. `update_id` защищён уникальным ключом; повторы
  завершённого события игнорируются.
- Секреты задаются переменными окружения. Никогда не копируйте токен старого бота.
- Атлас в `atlas/` описывает кандидатов семейств; сам по себе он не подтверждает готовность задач.

## Локальный запуск

Требуются Python 3.12+ и PostgreSQL 17+.

```powershell
uv sync --frozen --all-extras
Copy-Item .env.example .env
uv run uvicorn app.main:app --reload
```

Заполните `DATABASE_URL`, `TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET` только в локальном
`.env` или защищённых secrets хостинга. Приложение применяет идемпотентную миграцию при старте.
Telegram webhook устанавливается только после настройки публичного HTTPS URL и секретов.

## Качество

```powershell
uv run ruff check .
uv run mypy app
uv run pytest -q
```

CI запускает эти проверки и интеграционные тесты с PostgreSQL 17.

## Границы релиза

Кнопки меню доступны, но режимы практики отвечают, что раздел готовится. Генераторы задач,
Mini App, Groq и публичный доступ не включены. См. `specs/ROADMAP.md`.
