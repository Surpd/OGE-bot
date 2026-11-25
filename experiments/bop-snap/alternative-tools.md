# Альтернативы для растрового персонажа — практическая проверка

Дата: 2026-11-24 · Windows x64 · Node 24.15.0. Checkout’ы, зависимости и результаты — в `.tmp/bop-alternatives`. Использовались только демо-изображения из самих проектов; пользовательские картинки не передавались, платных действий не было.

## Итог

| Инструмент | Проверенный результат | Оценка для одного плоского PNG |
| --- | --- | --- |
| [TextRig](https://github.com/blackoutbuild/textrig) | Собрал rig/atlas по встроенным PNG + готовым skeleton/polygons; filmstrip содержит 8/8 разных кадров, mesh deformation активна. Сборка выдала предупреждения по разметке. | Наиболее узкий и прямой pipeline. Требует подготовить геометрию (обычно это делает подключённый агент) и проверить render; не доказано «автоматически бросил PNG — получил готовую анимацию». |
| [Rev2D](https://github.com/RevStudio/Rev2D) | Встроенный Hana model: `validate` 0 errors/0 warnings, PNG 512×640 отрисован и просмотрен. | Поддерживает одну иллюстрацию, но нужно разметить 20 landmarks. Предназначен в первую очередь для фронтального bust, мелкие глаза в маленьком изображении могут остаться неподвижны. |
| [Rive Agents / CLI](https://rive.app/agents) | CLI 1.11.0 проверил и отрендерил `hello_rive`; verify без ошибок, screenshot 800×600 просмотрен. Sample — оранжевый квадрат, не персонаж. | Мощная общая среда для raster/vector сцен; tested CLI не выполняет автоматический image-to-rig. Растровому персонажу нужны подготовленный rig/mesh и авторинг агентом/в редакторе. |
| [OpenBone](https://github.com/UXCentury/open-bone) | Готовая модель `fox.obone`: validate OK, PNG отрендерен и просмотрен. | Общий editor/runtime/MCP для authored rigs; прогон не обнаружил готовой конверсии одного PNG в скелет. |

## Проверки и версии

### TextRig

- Commit `24de122` (`2026-09-23`), в manifest версия не указана. Renderer по lockfile: pixi-dragonbones-runtime 8.0.3, pixi.js 8.19.0, Playwright 1.61.1.
- До запуска изучен `install.sh`: он устанавливает Python/npm deps, скачивает u2net (~170 MB) в user home и Playwright Chromium. Сам скрипт не запускался. Только нужные pipeline deps и renderer packages установлены в `.tmp`, с `--ignore-scripts`; u2net не загружался.
- На `examples/robot/{source.png,skeleton.json,pieces.json,animations.json}` вызван `pipeline/build_pieces_rig.py`: 7 pieces, 1 variant, atlas 1969×977, DragonBones JSON. Выданы предупреждения: неразмеченные части source, заливка скрытых областей до 165 px, несколько весов fallback на IDW.
- Локальный Playwright renderer (Chromium 149.0.7827.55) сделал idle filmstrip: 8/8 кадров разные, 8/8 состояний mesh вершин разные. PNG 797,265 B: `.tmp/bop-alternatives/textrig/renderer/out/bop-robot.filmstrip.png`; GIF 3,651,854 B.
- Это проверка сборки/рендера по уже подготовленной геометрии демо, не автоматического распознавания суставов. Filmstrip просмотрен: idle движение небольшое, смена свечения глаза видна; build warnings требуют ручного review.

### Rev2D

- Commit `f144581` (`2026-10-06`), package version 0.1.0. Зависимости поставлены `npm ci --ignore-scripts`; Node 24.15.0 удовлетворяет `>=22`.
- `validate examples/hana/hana.r2d.json --json`: 0 errors/0 warnings. `render ... --overlay bones,warps,labels`: PNG 512×640, 101,887 B, просмотрен; это существующий пример, не новый avatar build.
- `docs avatar` описывает однокартинный путь: draft spec с 20 landmarks → vision/grid → ручная/агентская разметка → validate/overlay → build → review поз и исправления. Лучше всего подходит фронтальный bust с прозрачным фоном; поворот не показывает скрытую часть рисунка. Маленькие глаза могут остаться статичны. Сами картинки/модели остаются локально.
- В документации отмечено: avatar workflow доступен из CLI, avatar tools в MCP server пока отсутствуют.

### Rive

- Windows CLI `1.11.0`; официальный manifest и SHA256 архива сверены. Installer изучен, но не запускался, поскольку он изменяет пользовательский `PATH`; официальный архив извлечён в `.tmp` вручную. `hello_rive --verify` сообщил 0 errors/0 warnings, `--screenshot` создал 800×600 PNG (`.tmp/bop-alternatives/rive-hello.png`). Нет Rive аккаунта, login/publish не выполнялись. Analytics отключена во временном профиле внутри `.tmp`.
- [Официальная страница](https://rive.app/agents) говорит, что локальный CLI build/preview/test бесплатен и доступен без входа; встроенный AI Agent использует кредиты и на бесплатном тарифе ограничен. Движок поддерживает raster, но доступный demo прогон не проверял skeletal rig персонажа.

### OpenBone

- Commit `c7d76c6` (`2026-11-23`), monorepo version 0.4.11. Manifest указывает pnpm 10.34.5, фактически использован pnpm 11.25.0; lockfile принят. Проверены `package.json`: lifecycle install/postinstall/prepare hooks не обнаружены. Пакеты установлены `--ignore-scripts` в локальный store и `node_modules`.
- `pnpm cli validate examples/fox.obone` → `OK`; `pnpm cli render ... --animation idle --time 1 --bones` → PNG 239,900 B, просмотрен. Это pre-rigged sample, не конверсия PNG.

## Блокеры и ограничения

- Обычный sandbox блокировал сетевые обращения git/pip/npm; после разрешённого escalation скачаны публичные исходники и lockfile deps в `.tmp`. Для TextRig pipeline пришлось добавить в изолированный venv OpenCV, который импортируется даже при сборке pieces; никаких глобальных настроек не менял.
- TextRig setup и Rive installer не запускались: первый пишет модель в профиль пользователя, второй добавляет путь в пользовательский `PATH`. Для Rive скачан официальный archive с проверкой SHA256; для TextRig отдельно установлен только локальный минимум для демо без u2net/rembg.
- Проверки используют только демо-контент. Для небольшого pixel-art персонажа mesh деформация способна смазывать пиксельные края; нужна проверка исходных/согнутых поз и сравнение с покадровой анимацией. У TextRig есть явные build warnings на готовом примере, поэтому production-качество этим прогоном не подтверждено.
- Выбор: TextRig — первый кандидат для flat PNG, но с ручной валидацией; Rev2D — для фронтального аватара/bust с landmark-разметкой; Rive/OpenBone — если важнее общий editor/runtime и интеграция, чем автоматическая нарезка изображения.

## Ссылки

- [TextRig README](https://github.com/blackoutbuild/textrig) · [install.sh](https://github.com/blackoutbuild/textrig/blob/master/install.sh)
- [Rev2D README](https://github.com/RevStudio/Rev2D) · локальный `node bin/rev2d.js docs avatar`
- [Rive Agents](https://rive.app/agents) · [Pricing/CLI FAQ](https://www.rive.app/pricing)
- [OpenBone README](https://github.com/UXCentury/open-bone) · [CLI docs](https://github.com/UXCentury/open-bone/blob/main/packages/cli/README.md)
