# Выбор сюжетов и ротация внутри номера

Записаны исходящие методы и параметры Bot API, сформированные Telegram Dispatcher
для синтетического ученика с отдельным состоянием в PostgreSQL. Для записей с
вложениями сохранены отправленные PNG и их SHA-256.

- Выбор сюжета для [№1](number-1.json), [№2](number-2.json), [№3](number-3.json),
  [№4](number-4.json), [№5](number-5.json) и прежний выбор типов для [№6](number-6-unchanged.json).
- [Сразу начать единственный тип «Бумаги»](paper-direct.json).
- [Выбрать тип «Печей»](stove-types.json) и [начать конкретный тип](stove-explicit-family.json).
- [Переключить занятие](story-switch.json) и [начать все типы выбранного сюжета](story-all-issued.json).
- [Возобновить сохранённое задание](story-resume.json), получить [итог пяти заданий](story-checkpoint.json)
  и [продолжить с тем же сюжетом](story-next-block.json).
- [Начать весь №3](whole-number-issued.json) и [пройти два круга по шести сюжетам](whole-number-rotation.json).

Запись воспроизводится через `scripts/story_navigation_acceptance.py` с локальным PostgreSQL.
