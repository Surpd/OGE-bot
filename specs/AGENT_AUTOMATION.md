# GitHub-first Agent Handoff v1 — без платных API

Аудит: 07.11.2026. **Статус: инфраструктурный feature-PR. Это не полноценный автономный агентский цикл.** Никаких изменений Telegram UX, генераторов, Supabase и production.

## 1. Проверенный baseline

- `AGENTS.md`: требования к Codex, независимые математические oracle, бесплатность, запрет релиза без подтверждения.
- `specs/QUALITY.md`: source IDs, render/AST fidelity, математические oracle, QA-выборки, fail-closed. AI-review не заменяет эти проверки.
- `specs/TRAINING_UX_CONTRACT.md`: нормативный UX №1–19; изменение не требуется.
- `.github/workflows/ci.yml`: `pull_request` и `push main`; job `quality` (Ruff, mypy, pytest + PostgreSQL 17), `oge15-linux-render` (Docker + PNG). Workflow CI **не изменён**.
- `specs/ARCHITECTURE.md`: FastAPI/aiogram + Render + Supabase; GitHub orchestration не получает никакого доступа к этим production-интеграциям.
- GitHub: `main` по состоянию на аудит `protected: false`, репозиторных rulesets нет. Это **отдельная реальная проблема**: зелёный CI сам по себе не делает проверки обязательными при merge.

## 2. Машина состояний и реальные переходы

```text
[GitHub Issue / задача]  --вручную--> [Codex Cloud / исполнитель]
                                               |
                                         вручную: PR/push
                                               |
                                     GitHub CI, автоматически
                                               |
                          workflow_run: completed (после merge этого PR)
                                               |
                        GitHub Agent Handoff, автоматически
                          /         |          |          \
                   awaiting_ci blocked_ci blocked_review awaiting_independent_review
                          |         |          |          /
                     GitHub CI + независимое APPROVED ревью текущего SHA
                                               |
                              ready_for_human_acceptance
                                               |
                                       человек: решение
                                            merge
```

Отдельные статусы: `blocked_manual` (label `agent:blocked`), `blocked_draft`, `blocked_max_repairs`, `closed`.

**Реально реализовано в v1:** после завершённого CI PR (событие `workflow_run`), безопасно из *default branch* читаются актуальные PR, последний CI-run для текущего SHA, jobs и независимые reviews. Координатор вычисляет статус, публикует или обновляет единственный machine-readable sticky comment PR. Повторное событие с теми же данными не создаёт новую запись. Владелец может запросить refresh комментарием `/agent status` либо запустить workflow вручную через `workflow_dispatch` (dry-run по умолчанию).

**Не реализовано:** автоматическое создание задачи, триггер Codex Cloud на основании GitHub события, AI-review, автоматическое извлечение замечаний и отправка исполнителю, генерация исправляющего commit/push, увеличение счётчика выполненных исправлений, слияние и deploy. Изменение review после CI без нового commit само по себе **не** инициирует workflow; нужна команда refresh до второй фазы. Документация и `AGENTS.md` не являются заменой этим подключениям.

## 3. Безопасность и защита от дубликатов

1. Привилегированный `workflow_run` запускает `actions/checkout` исключительно для `github.event.repository.default_branch` (`persist-credentials: false`). Нельзя checkout/execute PR-код, читать untrusted workflow artifacts или secrets.
2. Workflow permissions: `contents: read`, `actions: read`, `pull-requests: read`, `issues: write` только для sticky PR comment. Не нужны PAT, OpenAI API key, Render/Supabase/Telegram secrets.
3. `concurrency` по номеру PR, `cancel-in-progress: false`; повторный run без изменений не создаёт новые комментарии. Stale `workflow_run` игнорируется, если не соответствует *последнему* CI-run текущего PR/SHA.
4. Принимается только run с `name: CI`, `event: pull_request`, текущим `head_sha`, PR association и `conclusion: success`. Обе обязательные jobs должны иметь `completed/success`. Неизвестные или отсутствующие jobs блокируют. При переименовании CI jobs согласованно обновить список.
5. Комментарий ищется по строгому маркеру и автору `github-actions[bot]`. Два комментария, повреждённая запись или счётчик, ошибка GitHub API/пагинации дают fail-closed, а не ложное `ready`. Публикация комментария — **единственная** мутация.
6. Независимость ревью: учитываются reviews от аккаунтов, отличных от автора PR; approval должен относиться к **текущему commit SHA**. `COMMENTED` не равен `APPROVED`; `CHANGES_REQUESTED` явно блокирует. Не подменять независимый review самопроверкой Codex.
7. `repair_cycles` хранится в комментарии, допустимый диапазон `0..3`, `next_repair_cycle(3)` запрещён; после 3 исправлений и остающихся дефектов `blocked_max_repairs`. **В v1 счётчик остаётся 0**, потому что исполнитель ещё не вызывает функцию и не совершает реальных автоматических исправлений.
8. Готовность — статус **для человека**, не разрешение на merge/release. Нельзя объявлять математические генераторы доказанно корректными только по PR approval.

## 4. Подписка и расходы

| Компонент | Что доступно без дополнительных API-расходов | Ограничения |
| --- | --- | --- |
| GitHub Actions + GITHUB_TOKEN + Python stdlib | Действующий CI, метаданные, запись статуса PR, event coordinator | GitHub Actions quotas; workflow активен только после merge в default branch |
| Codex Cloud/CLI через ChatGPT login | Запуск задач и работа с PR в рамках доступного плана/лимитов | Нет доказанного бесплатного GitHub-event endpoint для запуска новых задач по токену Actions |
| Codex Code Review, GitHub integration | Может делать независимый review по настройке/команде `@codex review` | Требуется активация и проверка прав; comments не создают GitHub APPROVED автоматически |
| GitHub Action с `codex exec` / API | Потенциальная phase 2 с агентным исполнителем и повторными правками | Требует отдельной авторизации, расходов/кредитов API и разрешения владельца — **выключено** |

При работе через ChatGPT-подписку расходуются её собственные лимиты Codex. Использование отдельного OpenAI API key тарифицируется отдельно; возможные API credits на некоторых планах не являются разрешением автоматически подключать API.

## 5. Следующая фаза — точные действия

1. После человеческого review и зелёного CI владелец решает, сливать ли данный инфраструктурный PR. **До merge `workflow_run` нового файла не активен**, а `workflow_dispatch` из feature-ветки не является живым тестом.
2. В GitHub Settings → Rules / Branch protection защитить `main`, требовать pull request и оба существующих checks (`quality`, `oge15-linux-render`), ограничить обход правил. Не делать новый coordinator required check до сквозной проверки.
3. Разрешить workflow `issues:write` для `GITHUB_TOKEN` через настройки Actions. На изолированном **новом** тестовом PR проверить: dry-run, CI completion → sticky comment, повтор → без записи, изменение SHA → пересчёт, label `agent:blocked` → стоп. PR #33 не изменять.
4. Подключить в Codex Cloud GitHub repo и, отдельно, Codex Code Review. Посмотреть реальные review events и их семантику. Codex COMMENTED не может формально засчитываться как APPROVED.
5. Для настоящей автопетли согласовать внешний dispatcher с API/одобренным GitHub App: `contents:write` **только feature-ветки**, `pull_requests:write`, `issues:write`, `actions:read`, `checks:read`; ни production, ни merge. Хранить `dispatch_id`, input/output checksums, head SHA; увеличивать `repair_cycles` после подтверждённого запуска исправляющего агента; максимум 3, затем `blocked_max_repairs`.
6. Пройти staging end-to-end: failed CI → auto dispatch → исправляющий commit → повторное CI → **отдельный** review → fix по замечанию → human acceptance. Пока такого испытания нет, слово «полностью автономно» неприменимо.

## 6. Приёмочная модель на PR #33

Достоверные метаданные GitHub на момент аудита: PR #33 открыт, `feat/oge15-session-switch`, head `e2595d4721b0960e5c5357bf8919a7de039afe21`; CI run `42018737288` = success, jobs `quality` и `oge15-linux-render` = success; independent reviews `[]`, PR comments `[]`.

Сохранён точный обезличенный технический fixture `tests/fixtures/pr33_agent_handoff.json`. Команда:

```bash
python scripts/agent_handoff.py --fixture tests/fixtures/pr33_agent_handoff.json --dry-run
```

Выдаёт `awaiting_independent_review`, `repair_cycles=0`. Автотесты проверяют, что независимый approval *текущего SHA* перевёл бы состояние в `ready_for_human_acceptance`, плохой CI или review возвращают блокировку, старый SHA не принимается, а 4-е исправление не разрешено.

**Это offline моделирование на реальных полученных данных, не live CI workflow end-to-end.** Существующий PR #33, его код, reviews, labels и comments не изменяются.
