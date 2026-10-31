# Хостинг, бесплатность, безопасность

## Решение
- GitHub repo `Surpd/OGE-bot` + Render **Web Service** (FastAPI/aiogram webhook) + существующий Supabase project `hguwrwjqleifjaxikzol`.
- Не трогать Render My Island/MMT, VPS IslandQuiz или школьные базы.
- Render service: https://oge-trainer.onrender.com
- Платные ресурсы Render/Supabase не включать без явного согласования.

## Бесплатность
Использовать текущий Render Web Service и Supabase project на уже выбранных бесплатных уровнях. Не включать платный instance, диск, managed database или add-on без согласия. Бесплатный Render может засыпать при простое; webhook/восстановление проверять отдельно.

## Telegram webhook
- HTTPS endpoint `/telegram/webhook`, Telegram `setWebhook` с `secret_token`; проверять `X-Telegram-Bot-Api-Secret-Token` constant-time.
- Обрабатывать `update_id` идемпотентно в БД, включая параллельные повторы. Не логировать содержимое сообщений без необходимости.
- После смены среды/токена перепривязать webhook только после smoke-теста URL. Health endpoint `/health` не раскрывает личные данные.
- Нельзя работать polling worker и webhook одновременно.

## Доступы / секреты
- В legacy zip есть токен. Перед повторным запуском перевыпустить через BotFather, сохранить только в Render environment. Если оригинальный бот остался у людей в Telegram, это всё равно тот же скомпрометированный токен.
- Secret роли БД только backend; RLS обязательно в публичных таблицах, сервисная роль не попадает в клиентские ссылки. Админские роли — на сервере.
- Telegram ID не должен позволять читать чужой прогресс. Для несовершеннолетних не просить фамилии/номера телефонов; хранить минимум данных, доступы учителей отдельные.
- Бэкапы: отдельный экспорт схемы + anonymized bank/attempts, без несанкционированных публикаций, проверять восстановление.

## Deploy protocol
1. `make test` / `pytest` → lint/typecheck + миграции;
2. Staging smoke test (health, `/start`, ответ, дважды одинаковый update_id);
3. Проверить остаток бесплатных лимитов и логи;
4. Перевести флаг выпуска; при ошибке — быстрый rollback предыдущего digest;
5. Записать версию генераторов и бота в release manifest.
