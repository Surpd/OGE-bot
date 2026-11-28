# bop Admin mobile preview and acceptance

## Scope

Gallery of admin screens rendered from the production text and `InlineKeyboardMarkup` API with synthetic service fixtures. This report covers visual review at 360, 390, and 430 CSS pixels only. No learner flow, database, Telegram account, or production service is used.

## Artifacts

- Gallery: `reports/bop-admin-preview/index.html`
- Rendered screen payloads: `reports/bop-admin-preview/payloads/`
- Screenshots: `reports/bop-admin-preview/screenshots/`
- Rebuild command: `python scripts/bop_admin_preview.py`

## Verified checks

The gallery was generated from `app.admin.screens.render_screen`, which returns the production message text and aiogram `InlineKeyboardMarkup`. It contains 12 admin screens, a selected №13 subtype view, and three empty or unavailable states. The 16 payload files preserve each message and keyboard exactly as serialized by aiogram. Fixtures use synthetic UUIDs, PostgreSQL-shaped timestamps, a Moscow report window, mature-cohort dates, and UTC budget month boundaries. The №7 task detail includes the production QA action for `OGE07-DIRECT`; the №13 written view and replay list exercise page navigation. All values are hard-coded; the generator imports no service, database, bot, or settings modules.

| Check | Status | Evidence |
|---|---|---|
| Synthetic fixtures only; no credentials or production service calls | PASS | `scripts/bop_admin_preview.py`; 16 payloads tagged synthetic, empty, or unavailable |
| All admin screens and selected views render production text and Telegram markup | PASS | 12 screen flows + №13 subtype view + 3 state variants; 131 keyboard buttons; callback data and `success` style retained |
| Usage modes and Tools entry | PASS | Usage shows eight persisted or unknown mode labels. Tools shows the exact-check callback. |
| Task-family QA action and list pagination | PASS | №7 detail has `adm:preview:qa_family`; task list, written, and replay views expose their next-page action |
| 360 px viewport | PASS | Browser: document width 360 px; no message overflow. Screenshot: [mobile-360.png](bop-admin-preview/screenshots/mobile-360.png) |
| 390 px viewport | PASS | Browser: document width 390 px; no message overflow. Screenshot: [mobile-390.png](bop-admin-preview/screenshots/mobile-390.png) |
| 430 px viewport | PASS | Browser: document width 430 px; no message overflow. Screenshot: [mobile-430.png](bop-admin-preview/screenshots/mobile-430.png) |
| Keyboard target sizing | PASS | Buttons are at least 44 px high; narrowest rendered button width at 360 px is about 87 px |
| Browser console | PASS | Fresh gallery load: zero console errors or warnings |
| Python lint and formatting | PASS | `python -m ruff check scripts/bop_admin_preview.py`; `python -m ruff format --check scripts/bop_admin_preview.py` |
| Localized metric and status labels | PASS | Written-work and system payloads show the finalized Russian labels |

## Limitations

This is a browser rendering of Telegram Bot API message text and keyboard markup, not a Telegram client screenshot. It does not verify Telegram delivery, callback handling, authorization, or live service values. The Tools screen uses its no-identity `/qa` instruction; the companion deep-link URL branch is not previewed because no real companion identity is supplied.


## Интеграционная приёмка

Адресный прогон дал 257 успешных тестов на локальной PostgreSQL 17.11. Из прогона
исключён один тест точного снимка геометрии №16 с зависимостью от шрифта и рендера
в Windows. Отдельно прошли Ruff, mypy, сверка 60 статических PNG и сборка wheel/sdist.

Контрольный набор PostgreSQL 17.11 проверил учебные действия на обеих границах
московского окна, зрелость когорты, отдельный учёт попыток и задач, неизвестную
помощь, разбор после ответа, принятые письменные отправки, ревизии, диагностику
и удержания прошлых периодов. Отчёт выполняет запросы к ограниченным представлениям
в `READ ONLY` на существующем пуле приложения. Проверки доступа используют
настоящий PostgreSQL. Регрессии companion проверили раздельные диспетчеры,
недоступную аналитику, запрет переходов через чужой webhook и сброс тестовой
истории без изменения основной схемы.

`EXPLAIN (ANALYZE, BUFFERS)` на 8 000 синтетических учениках, 80 000 попытках
и 4 000 письменных проверках в локальной PostgreSQL 17.11 с окном семь дней.

| Запрос | Время PostgreSQL, мс |
|---|---:|
| Главная | 59,9 |
| Дни активности | 17,0 |
| Режимы | 43,6 |
| Возврат на второй неделе | 33,2 |
| Список типов | 380,4 |
| Детали семейства | 378,2 |
| Письменные проверки | 10,0 |
| Бюджет и расходы | 10,6 |

Быстрые периодные выборки используют индексы времени попыток и проверок.
Типы и детали дополнительно соединяют задачи и проекцию вариантов. Замер
сделан без Telegram и сетевой задержки. План воспроизводится тестом
`test_admin_query_plans_on_synthetic_history`.


## Повторная приёмка PR №122

Адресный набор прошёл на PostgreSQL 17.11 (45 тестов). Отдельный финальный
прогон модуля companion подтвердил оба маршрута (14 тестов).

- PostgreSQL-тест использует действующий триггер активации сюжетных позиций и
  проверяет отдельно одиночный вопрос и сюжетную пятёрку. В том же отчёте
  проверены четыре коротких режима, новая сессия полного цикла и неизвестный
  режим старых записей. Возобновление старой сессии сохраняет её классификацию.
- Действующее подключение приложения и локальный запуск с недоступной
  статистикой проходят путь от `/start` через «Инструменты» до режима
  «Как ученик» и обратно. Тест нажимает кнопки, полученные от настоящего
  aiogram-диспетчера через записывающий Telegram-транспорт. Экран состояния показал оба варианта
  фактического SHA, `RENDER_GIT_COMMIT` и `APP_BUILD_SHA`.
- Галерея переснята на ширинах 360, 390 и 430 px. В ней видны обновлённые
  режимы и рабочий переход в точные проверки.

## Проверка выпуска

При переходе на общий пул прошли 22 адресных теста аналитики и companion.
Отдельный набор миграций, основного webhook и письменной проверки дал 54
успешных теста на PostgreSQL 17.11.

- Проверить автоматический деплой по SHA `main`, HTTP 200 от `/health` и
  появление миграции `0038_admin_analytics.sql` в журнале основной схемы.
- Сверить записи запуска основного webhook, companion и его 28-дневного
  отчёта. При наличии трафика проверить успешную обработку обновлений
  основного бота после переключения на новый экземпляр.
- Открытие `/start` в companion проверяется из владельческого чата, когда
  доступна авторизованная сессия Telegram.
