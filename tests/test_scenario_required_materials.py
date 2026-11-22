"""Reviewed input matrix, independent of the production media selector; no Telegram/API calls."""
import csv
import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendPhoto
from aiogram.types import Message

from app.bot import error_replay, mixed_training, progress, scenario_materials, scenario_training
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    build_practice_plan,
)
from app.math.scenarios.mobile_photos import scenario_photos
from app.persistence.error_replay import ReplaySource
from app.persistence.repository import MemoryRepository
from app.persistence.scenario_repository import ScenarioPostgresRepository, ScenarioSession

CASES = list(csv.DictReader(Path('reports/scenario-material-coverage.csv').open()))


@lru_cache
def saved(story, seed):
    return build_practice_plan(
        PracticeRequest(PracticeMode.FULL, int(seed), story), scenario_training.public_registry(),
    ).snapshot


def test_matrix_covers_exact_public_registry():
    assert {row['family'] for row in CASES} == set().union(
        *scenario_training.PUBLIC_FAMILIES.values()
    )
    assert len(CASES) == 40
    assert 'ROUTE' not in {row['story'] for row in CASES}


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['family'])
async def test_required_payload_before_question_on_every_path(case, monkeypatch):
    original = saved(case['story'], case['seed'])
    # Restart JSON roundtrip, never a new world.
    snapshot = ScenarioSnapshot.from_snapshot(json.loads(json.dumps(original.to_snapshot())))
    position = int(case['position'])
    question = snapshot.questions[position - 1]
    assert question.family_id == case['family']
    all_photos = scenario_photos(snapshot)
    expected = [all_photos[int(i)] for i in case['indexes'].split()]
    before = snapshot.to_snapshot()
    events = []

    async def text(*args, **kwargs):
        body = args[2] if len(args) > 2 else args[0]
        events.append(('text', body, kwargs.get('reply_markup')))
        return SimpleNamespace(message_id=100 + len(events))

    async def photo(*args, **kwargs):
        upload = args[2] if len(args) > 2 else args[0]
        events.append(('photo', upload.data, None))
        return SimpleNamespace(message_id=100 + len(events))

    for module in (scenario_materials, mixed_training, error_replay):
        monkeypatch.setattr(module, 'send_text', text)
        monkeypatch.setattr(module, 'send_photo', photo)
    from app.bot import presentation

    monkeypatch.setattr(presentation, 'send_text', text)
    message = AsyncMock(spec=Message)
    message.message_id = 10
    message.delete = AsyncMock()
    message.answer.side_effect = text
    message.answer_photo.side_effect = photo
    repository = MemoryRepository()
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), position)
    problem['problem_id'] = str(uuid4())
    problem['number'] = position
    session = ScenarioSession(
        uuid4(), uuid4(), PracticeMode.FULL, 'active', position, 0, 'active', 0, 0,
        None, None, snapshot,
    )
    store = AsyncMock(spec=ScenarioPostgresRepository)
    store.close_legacy_with_exposed_answer.return_value = False
    for path in ('single', 'full', 'resume', 'mix', 'mix-adjacent', 'replay', 'history'):
        events.clear()
        if path in ('single', 'full', 'resume'):
            await scenario_training.render_session(
                message, store, replace(session, mode=(
                    PracticeMode.SINGLE if path == 'single' else PracticeMode.FULL
                )), show_assets=path != 'resume', show_current_asset=path == 'resume',
                user_id_override=7,
            )
        elif path.startswith('mix'):
            previous = {**problem, 'number': position - 1} if path == 'mix-adjacent' else None
            await mixed_training._send_problem(
                message, repository, AsyncMock(), problem, user_id=7, previous_problem=previous,
            )
        elif path == 'replay':
            source = ReplaySource('scenario', uuid4(), position, position, problem,
                                  snapshot.to_snapshot())
            await error_replay._render(
                message, repository, AsyncMock(), {'id': str(uuid4()), 'status': 'active'},
                source, user_id=7, materials=error_replay._materials(source),
            )
        else:
            from app.persistence import error_replay as replay_persistence

            source = ReplaySource('scenario', uuid4(), position, position, problem,
                                  snapshot.to_snapshot())
            monkeypatch.setattr(replay_persistence, 'load_original_source',
                                AsyncMock(return_value=source))
            monkeypatch.setattr(progress, 'training_record_detail', AsyncMock(return_value={
                **problem, 'outcome': 'solved', 'attempt_records': [],
            }))
            reference = progress.encode_record_ref(f's:{source.source_id}:{position}')
            page = f'item:{reference}:{progress.encode_return_page("history:0")}'
            await progress.progress_navigation(message, repository, 7, page)
        assert [value for kind, value, _ in events if kind == 'photo'] == expected, path
        prompt_indexes = [i for i, (kind, body, _) in enumerate(events)
                          if kind == 'text' and question.condition in body]
        assert prompt_indexes == [len(events) - 1], path
        assert events[0][1] == scenario_materials.scenario_context_for_question(snapshot, position)
        labels = [b.text for row in events[-1][2].inline_keyboard for b in row]
        assert '📷 Схема / данные' in labels, path
        assert snapshot.to_snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['render', 'delivery'])
async def test_required_diagram_failure_blocks_question_and_retry_preserves_snapshot(
    failure, monkeypatch,
):
    snapshot = saved('FLAT', '0')
    session = ScenarioSession(uuid4(), uuid4(), PracticeMode.FULL, 'active', 1, 0,
                              'active', 0, 0, None, None, snapshot)
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock(return_value=SimpleNamespace(message_id=100))
    message.answer_photo = AsyncMock()
    store = AsyncMock(spec=ScenarioPostgresRepository)
    store.close_legacy_with_exposed_answer.return_value = False
    renderer = scenario_materials.scenario_photos_for_question
    if failure == 'render':
        monkeypatch.setattr(scenario_materials, 'scenario_photos_for_question',
                            lambda *a: (_ for _ in ()).throw(OSError('synthetic render failure')))
    else:
        message.answer_photo.side_effect = TelegramNetworkError(
            method=SendPhoto(chat_id=7, photo='synthetic'), message='synthetic timeout',
        )
    await scenario_training.render_session(message, store, session, show_assets=True,
                                           user_id_override=7)
    assert message.answer.await_args.args[0] == scenario_materials.MATERIALS_UNAVAILABLE
    assert all(snapshot.questions[0].condition not in c.args[0]
               for c in message.answer.await_args_list)
    store.set_condition_message.assert_not_awaited()
    monkeypatch.setattr(scenario_materials, 'scenario_photos_for_question', renderer)
    message.answer_photo.side_effect = None
    message.answer.reset_mock()
    await scenario_training.render_session(message, store, session, show_assets=True,
                                           user_id_override=7)
    assert snapshot.questions[0].condition in message.answer.await_args.args[0]
    store.set_condition_message.assert_awaited_once_with(7, session.session_id, 1, 100)


def test_stove_catalogue_text_fallback_retains_every_operand_without_solution(monkeypatch):
    case = next(c for c in CASES if c['family'] == 'STOVE-F01-CAPACITY-LIMITS')
    snapshot = saved(case['story'], case['seed'])
    monkeypatch.setattr(scenario_materials, 'scenario_photos_for_question',
                        lambda *a: (_ for _ in ()).throw(OSError('synthetic font failure')))
    context, photos = scenario_materials.prepare_scenario_materials(snapshot, 1)
    assert photos == ()
    for row in snapshot.context['stoves']:
        assert f"Печь №{row['id']}" in context
        assert f"{row['min_m3']}–{row['max_m3']} м³" in context
        assert f"цена {row['price_rub']} руб." in context
    assert snapshot.questions[0].solution_steps[0] not in context


@pytest.mark.asyncio
async def test_screenshot_capacity_limits_23_12_20_gets_catalogue_before_question(monkeypatch):
    # Synthetic seed reproduces the exact requested boundary order in IMG_8028.
    # The original screenshot's seed is unknown; do not claim identical room dimensions.
    snapshot = saved('STOVE', '155')
    question = snapshot.questions[0]
    assert question.family_id == 'STOVE-F01-CAPACITY-LIMITS'
    assert question.condition.endswith('23, 12, 20.')
    events = []

    async def text(*args, **kwargs):
        events.append(('text', args[2]))
        return SimpleNamespace(message_id=len(events) + 100)

    async def photo(*args, **kwargs):
        events.append(('photo', args[2].data))

    monkeypatch.setattr(scenario_materials, 'send_text', text)
    monkeypatch.setattr(scenario_materials, 'send_photo', photo)
    monkeypatch.setattr(mixed_training, 'send_text', text)
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), 1)
    problem.update(problem_id=str(uuid4()), number=1)
    await mixed_training._send_problem(AsyncMock(), MemoryRepository(), AsyncMock(), problem,
                                       user_id=7, previous_problem={'number': 19})
    assert [kind for kind, _ in events] == ['text', 'photo', 'text']
    assert events[1][1] == scenario_photos(snapshot)[0]
    assert question.condition in events[-1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize('stale', [False, True])
@pytest.mark.parametrize('shown', [False, True])
async def test_mixed_data_button_is_bound_to_saved_problem_without_regeneration(
    stale, shown, monkeypatch,
):
    from datetime import UTC, datetime

    from aiogram.types import CallbackQuery, Chat, User

    snapshot = saved('PAPER', '1')
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), 4)
    problem.update(problem_id=str(uuid4()), number=4, outcome='issued',
                   prompt_message_id=300 if shown else None)
    repository = MemoryRepository()
    await repository.save_user_state(7, 'mixed')
    store = AsyncMock()
    store.state.return_value = {'problem': problem}
    monkeypatch.setattr(mixed_training, 'MixedTrainingRepository', lambda repo: store)
    monkeypatch.setattr(mixed_training, 'answer_callback', AsyncMock())
    delivery = AsyncMock(return_value=True)
    monkeypatch.setattr(mixed_training, 'send_scenario_materials', delivery)
    monkeypatch.setattr(mixed_training, 'send_text', AsyncMock(
        return_value=SimpleNamespace(message_id=400)))
    callback = CallbackQuery(
        id='synthetic-data', from_user=User(id=7, is_bot=False, first_name='Synthetic'),
        chat_instance='synthetic', data=f"mixed:data:{uuid4() if stale else problem['problem_id']}",
        message=Message(message_id=200, date=datetime.now(UTC),
                        chat=Chat(id=7, type='private'), text='Схема / данные'),
    )
    before = dict(problem)
    await mixed_training.mixed_callback(callback, repository)
    assert delivery.await_count == (0 if stale else 1)
    if not stale:
        assert delivery.await_args.args[2].to_snapshot() == snapshot.to_snapshot()
        assert delivery.await_args.args[3] == 4
    assert problem == before
    store.issue_current.assert_not_awaited()
    if shown or stale:
        store.set_prompt.assert_not_awaited()
        mixed_training.send_text.assert_not_awaited()
    else:
        store.set_prompt.assert_awaited_once_with(7, problem['problem_id'], 400)


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'screen'), [
    ('active', 'error_replay'), ('solved', 'error_replay'), ('failed', 'error_replay'),
    ('solution_viewed', 'error_replay'), ('active', 'main_menu'), ('active', 'progress'),
])
async def test_replay_data_button_preserves_original_attempt_and_snapshot(
    status, screen, monkeypatch,
):
    from datetime import UTC, datetime

    from aiogram.types import CallbackQuery, Chat, User

    snapshot = saved('STOVE', '155')
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), 1)
    source = ReplaySource('scenario', uuid4(), 1, 1, problem, snapshot.to_snapshot())
    replay = {'id': str(uuid4()), 'status': status, 'attempt_count': 1}
    monkeypatch.setattr(error_replay, '_active_replay', AsyncMock(return_value=(replay, source)))
    monkeypatch.setattr(error_replay, 'answer_callback', AsyncMock())
    delivery = AsyncMock(return_value=True)
    monkeypatch.setattr(error_replay, 'send_scenario_materials', delivery)
    monkeypatch.setattr(error_replay, '_feedback', AsyncMock())
    callback = CallbackQuery(
        id='synthetic-replay-data', from_user=User(id=7, is_bot=False, first_name='Synthetic'),
        chat_instance='synthetic',
        data=f"replay:{error_replay.replay_token(UUID(replay['id']))}:d",
        message=Message(message_id=200, date=datetime.now(UTC),
                        chat=Chat(id=7, type='private'), text='Схема / данные'),
    )
    repository = MemoryRepository()
    await repository.save_user_state(7, screen)
    await error_replay.callback(callback, repository)
    if status == 'active' and screen == 'error_replay':
        assert delivery.await_args.args[2].to_snapshot() == snapshot.to_snapshot()
    else:
        delivery.assert_not_awaited()
        error_replay._feedback.assert_not_awaited()
    assert await repository.user_state(7) == screen
    assert replay['attempt_count'] == 1 and replay['status'] == status


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['mix', 'replay', 'history'])
async def test_media_timeout_and_explicit_retry_keep_the_same_issue(path, monkeypatch):
    snapshot = saved('FLAT', '0')
    problem = mixed_training._scenario_question(snapshot.to_snapshot(), 1)
    problem.update(problem_id=str(uuid4()), number=1)
    source = ReplaySource('scenario', uuid4(), 1, 1, problem, snapshot.to_snapshot())
    replay = {'id': str(uuid4()), 'status': 'active', 'attempt_count': 1}
    texts = []

    async def text(*args, **kwargs):
        texts.append(args[2])
        return SimpleNamespace(message_id=501)

    photo = AsyncMock(side_effect=TelegramNetworkError(
        method=SendPhoto(chat_id=7, photo='synthetic'), message='synthetic timeout',
    ))
    for module in (scenario_materials, mixed_training, error_replay):
        monkeypatch.setattr(module, 'send_text', text)
    from app.bot import presentation

    monkeypatch.setattr(presentation, 'send_text', text)
    monkeypatch.setattr(scenario_materials, 'send_photo', photo)
    store = AsyncMock()
    repository = MemoryRepository()

    async def deliver():
        if path == 'mix':
            await mixed_training._send_problem(AsyncMock(), repository, store, problem, user_id=7)
        elif path == 'replay':
            await error_replay._render(AsyncMock(), repository, store, replay, source,
                                       user_id=7, materials=error_replay._materials(source))
        else:
            from app.persistence import error_replay as replay_persistence

            monkeypatch.setattr(replay_persistence, 'load_original_source',
                                AsyncMock(return_value=source))
            monkeypatch.setattr(progress, 'training_record_detail', AsyncMock(return_value={
                **problem, 'outcome': 'solved', 'attempt_records': [],
            }))
            reference = progress.encode_record_ref(f's:{source.source_id}:1')
            page = f'item:{reference}:{progress.encode_return_page("history:0")}'
            await progress.progress_navigation(AsyncMock(), repository, 7, page)

    await deliver()
    assert texts[-1] == scenario_materials.MATERIALS_UNAVAILABLE
    assert all(snapshot.questions[0].condition not in body for body in texts)
    store.set_prompt.assert_not_awaited()
    assert photo.await_count == 1  # No automatic duplicate after ambiguous delivery.
    photo.side_effect = None
    await deliver()
    assert snapshot.questions[0].condition in texts[-1]
    expected_id = problem['problem_id'] if path == 'mix' else UUID(replay['id'])
    if path == 'history':
        store.set_prompt.assert_not_awaited()
    else:
        store.set_prompt.assert_awaited_once_with(7, expected_id, 501)
    assert replay['attempt_count'] == 1
    assert problem['scenario_snapshot'] == snapshot.to_snapshot()


def test_missing_modern_heating_table_is_not_silently_ignored(monkeypatch):
    from app.math.scenarios import mobile_photos

    snapshot = saved('GARDEN', '0')
    monkeypatch.setattr(mobile_photos, 'scenario_photos', lambda s: (b'plan',))
    with pytest.raises(ValueError, match='Required scenario material is missing'):
        mobile_photos.scenario_photos_for_question(snapshot, 5)


@pytest.mark.asyncio
async def test_replay_navigation_allows_two_consecutive_data_requests(monkeypatch):
    from datetime import UTC, datetime

    from aiogram import Bot
    from aiogram.types import CallbackQuery, Chat, User
    from test_inline_dispatcher_postgres import TelegramSession

    from app.bot.navigation import navigation_callback

    repository = MemoryRepository()
    await repository.save_user_state(7, 'error_replay')
    transport = TelegramSession()
    bot = Bot('123456:synthetic_token_for_offline_tests', session=transport)
    snapshot = saved('STOVE', '155')
    source = ReplaySource('scenario', uuid4(), 1, 1,
                          mixed_training._scenario_question(snapshot.to_snapshot(), 1),
                          snapshot.to_snapshot())
    replay = {'id': str(uuid4()), 'status': 'active', 'attempt_count': 1}
    monkeypatch.setattr(error_replay, '_active_replay', AsyncMock(return_value=(replay, source)))
    incoming = Message(message_id=10, date=datetime.now(UTC),
                       chat=Chat(id=7, type='private')).as_(bot)
    try:
        await error_replay._feedback(incoming, repository, 7, replay, 'Продолжить', scenario=True)
        for index in range(2):
            _, menu_id, _ = repository.navigation_messages[7]
            message = transport.messages[menu_id]
            button = next(b for row in message.reply_markup.inline_keyboard for b in row
                          if b.text == '📷 Схема / данные')
            callback = CallbackQuery(
                id=f'data-{index}', from_user=User(id=7, is_bot=False, first_name='Synthetic'),
                chat_instance='synthetic', data=button.callback_data, message=message,
            ).as_(bot)
            await navigation_callback(callback, repository)
            assert repository.navigation_messages[7][1] != menu_id
        # The callback from the preceding keyboard revision is now stale.
        await navigation_callback(callback, repository)
        assert replay['attempt_count'] == 1 and replay['status'] == 'active'
        assert sum(c.__api_method__ == 'sendPhoto' for c in transport.calls) == 2
    finally:
        await bot.session.close()


def test_completed_replay_keeps_progress_navigation_and_data_is_in_history():
    from app.bot.navigation import navigation_screen

    markup = error_replay._keyboard('synthetic', completed=True, scenario=True)
    assert navigation_screen(markup) == 'progress'
    assert all(not b.callback_data.startswith('replay:')
               for row in markup.inline_keyboard for b in row)
