# Хостинг, бесплатность, безопасность

## Решение
- GitHub private repo + Northflank **Sandbox** combined service c Dockerfile/Python FastAPI/aiogram webhook + отдельный Supabase Postgres/Storage.
- Не трогать Render My Island/MMT, VPS IslandQuiz или школьные базы.
- Northflank skill для Codex: https://github.com/northflank/skills
- Northflank build/deploy: https://northflank.com/docs/v1/application/getting-started/build-and-deploy-your-code

## Бесплатность: проверять до создания ресурсов
На 31.10.2026 https://northflank.com/pricing показывает Sandbox free, до 2 сервисов, 2 jobs, 1 базы и до $20 ресурсов, always on. **Но** https://northflank.com/docs/v1/application/billing/pricing-on-northflank утверждает, что платёжный метод нужен всем, и Sandbox не рекомендуется для production. Это противоречие — не игнорировать. Codex не должен обещать 0 ₽ без подтверждения условий конкретного аккаунта или оплачивать/подключать карту автоматически.

На практике допускается пробный закрытый школьный проект на Sandbox в рамках условий использования. Для широкого/постоянного публичного применения понадобится отдельное решение о соответствии условиям и SLA; предполагать бесплатную непрерывную эксплуатацию нельзя.

## Telegram webhook
- HTTPS endpoint `/telegram/webhook`, Telegram `setWebhook` с `secret_token`; проверять `X-Telegram-Bot-Api-Secret-Token` constant-time.
- Обрабатывать `update_id` идемпотентно в БД, включая параллельные повторы. Не логировать содержимое сообщений без необходимости.
- После смены среды/токена перепривязать webhook только после smoke-теста URL. Health endpoint `/health` не раскрывает личные данные.
- Нельзя работать polling worker и webhook одновременно.

## Доступы / секреты
- В legacy zip есть токен. Перед повторным запуском перевыпустить через BotFather, сохранить только в Northflank secret settings. Если оригинальный бот остался у людей в Telegram, это всё равно тот же скомпрометированный токен.
- Secret роли БД только backend; RLS обязательно в публичных таблицах, сервисная роль не попадает в клиентские ссылки. Админские роли — на сервере.
- Telegram ID не должен позволять читать чужой прогресс. Для несовершеннолетних не просить фамилии/номера телефонов; хранить минимум данных, доступы учителей отдельные.
- Бэкапы: отдельный экспорт схемы + anonymized bank/attempts, без несанкционированных публикаций, проверять восстановление.

## Deploy protocol
1. `make test` / `pytest` → lint/typecheck + миграции;
2. Staging smoke test (health, `/start`, ответ, дважды одинаковый update_id);
3. Проверить остаток бесплатных лимитов и логи;
4. Перевести флаг выпуска; при ошибке — быстрый rollback предыдущего digest;
5. Записать версию генераторов и бота в release manifest.
