"""Private HTML Widget UI and bounded Bot API payloads for learner progress."""
# ruff: noqa: E501 -- embedded HTML/CSS/JS is intentionally compact for Telegram's 4 KiB limit.
from __future__ import annotations

import json
import zlib
from typing import Any, cast

from app.persistence.training_insights import (
    _STORY_NAMES,
    family_name,
    training_insights,
    training_record_detail,
)

WIDGET_HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{color-scheme:light dark;font:100% system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--tg-theme-text-color,#17212b);background:var(--tg-theme-bg-color,#fff)}*{box-sizing:border-box}body{margin:0;padding:8px;background:var(--tg-theme-bg-color,#fff)}.app{max-width:560px;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:8px}.title{font-size:1.15rem;font-weight:750;line-height:1.1}.muted{color:var(--tg-theme-hint-color,#71808f);font-size:.75rem}.refresh,.tabs button,.more,.page button{font:inherit;color:var(--tg-theme-button-text-color,#fff);background:var(--tg-theme-button-color,#3390ec);border:0;border-radius:12px;min-height:40px;padding:7px 9px}.refresh{font-size:.8rem;white-space:nowrap}.tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-bottom:8px}.tabs button{color:var(--tg-theme-text-color,#17212b);background:var(--tg-theme-secondary-bg-color,#f2f4f5);padding:6px 4px;font-size:.82rem;line-height:1.1;overflow-wrap:anywhere}.tabs button.active{color:var(--tg-theme-button-text-color,#fff);background:var(--tg-theme-button-color,#3390ec)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.card,.row,.item,.detail{background:var(--tg-theme-secondary-bg-color,#f2f4f5);border-radius:12px;padding:8px;min-width:0}.card b{display:block;font-size:1.3rem;margin:2px 0;overflow-wrap:anywhere}.card span{font-size:.75rem;color:var(--tg-theme-hint-color,#71808f)}.recommend{margin-top:7px;padding:8px;border-radius:11px;background:var(--tg-theme-section-bg-color,var(--tg-theme-secondary-bg-color,#f2f4f5));line-height:1.25}.rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.row{display:grid;grid-template-columns:minmax(0,1fr);align-content:start;gap:5px}.row .more{width:100%;min-width:0}.num{font-size:1rem;font-weight:750}.rowtext{min-width:0;overflow-wrap:anywhere}.rowtext strong{display:block;font-size:.9rem;line-height:1.15}.rowtext small{display:block;color:var(--tg-theme-hint-color,#71808f);font-size:.72rem;margin-top:2px}.bar{height:5px;margin-top:4px;border-radius:8px;background:var(--tg-theme-bg-color,#fff);overflow:hidden}.bar i{display:block;height:100%;background:var(--tg-theme-button-color,#3390ec)}.more{font-size:.78rem;min-width:66px;padding:6px 8px;line-height:1.1}.detail{grid-column:1/-1;font-size:.82rem;line-height:1.25;overflow-wrap:anywhere}.items{display:grid;gap:5px}.item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px;align-items:center}.item strong{font-size:.88rem;line-height:1.15;overflow-wrap:anywhere}.item small{display:block;color:var(--tg-theme-hint-color,#71808f);font-size:.72rem;margin-top:2px;overflow-wrap:anywhere}.item button,.page button{min-height:38px}.toggle,.page{display:flex;align-items:center;gap:6px;margin:0 0 7px}.toggle button{flex:1}.empty,.error,.loading{text-align:center;padding:12px 8px;color:var(--tg-theme-hint-color,#71808f)}.error{color:var(--tg-theme-destructive-text-color,#d14b4b)}.page{justify-content:space-between;margin-top:6px}.page button:disabled{opacity:.45}.page button{flex:1}.tag{display:inline-block;border-radius:8px;padding:2px 6px;background:var(--tg-theme-bg-color,#fff);font-size:.7rem;line-height:1.15;overflow-wrap:anywhere}.condition{grid-column:1/-1;line-height:1.3;overflow-wrap:anywhere}.attempts{grid-column:1/-1;display:flex;gap:5px;flex-wrap:wrap}
</style></head><body><main id="app" class="app"><div class="loading">Загружаем прогресс…</div></main><script>
const root=document.getElementById('app'),NUMBER_PAGE=4,HISTORY_PAGE=3;let tab='o',payload=null,busy=false,errorText='',detail=null,numberPage=0,historyMode='history',historyPage=0,lastHistory=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusName=s=>({solved:'Решено',failed:'Две ошибки',skipped:'Пропущено',solution_viewed:'Открыт разбор',issued:'В процессе',active:'В процессе',unknown:'Нет данных'})[s]||'Нет данных';
function shell(body){root.innerHTML='<header class="top"><div><div class="title">Мой прогресс</div><div class="muted">Только ваши результаты</div></div><button class="refresh" data-q="refresh">Обновить</button></header><nav class="tabs" aria-label="Разделы прогресса"><button class="'+(tab==='o'?'active':'')+'" data-q="tab:o">Обзор</button><button class="'+(tab==='n'?'active':'')+'" data-q="tab:n">По номерам</button><button class="'+(tab==='h'?'active':'')+'" data-q="tab:h">История и ошибки</button></nav>'+body+(errorText?'<div class="error">'+esc(errorText)+'</div>':'')+(busy?'<div class="loading">Обновляем…</div>':'')}
function overview(p){let body='<section class="grid"><div class="card"><span>Завершено заданий</span><b>'+(p.c||0)+'</b></div><div class="card"><span>Решено без подсказок</span><b>'+(p.u||0)+'</b></div><div class="card"><span>Решено с подсказкой</span><b>'+(p.h||0)+'</b></div><div class="card"><span>Были ошибки · пропущено</span><b>'+(p.e||0)+' · '+(p.s||0)+'</b></div></section><div class="muted">Старых правильных решений с неизвестным использованием подсказки: '+(p.x||0)+'.</div><div class="recommend"><b>Что попробовать дальше</b><br>'+esc(p.r||'Пока мало данных для рекомендации.')+'</div>';shell(body)}
function numbers(rows){let hasResults=rows.some(x=>x[1]>0),pages=hasResults?Math.ceil(rows.length/NUMBER_PAGE):0;if(numberPage>=pages)numberPage=Math.max(0,pages-1);let visible=rows.slice(numberPage*NUMBER_PAGE,(numberPage+1)*NUMBER_PAGE),body='';if(!hasResults){body='<div class="empty">Завершённых заданий пока нет. Начните с любого номера.</div>'}else{body='<section class="rows">'+visible.map(x=>{let n=x[0],done=x[1],correct=x[2],expanded=detail===n,bar=done>=5;return '<article class="row"><div class="num">№'+n+'</div><div class="rowtext"><strong>'+correct+' верно из '+done+' завершённых</strong>'+(bar?'<div class="bar"><i style="width:'+Math.round(correct/done*100)+'%"></i></div>':'<small>Пока мало данных ('+done+'/5)</small>')+'</div><button class="more" data-detail="'+n+'">'+(expanded?'Скрыть':'Подробнее')+'</button>'+(expanded?'<div class="detail">Без подсказки: '+x[3]+' · С подсказкой: '+x[4]+'<br>Задания с ошибкой: '+x[5]+' · Пропуски: '+x[6]+'<br>Верно с первой попытки: '+x[7]+' · Со второй: '+x[8]+'</div>':'')+'</article>'}).join('')+'</section>'}if(pages>1)body+='<div class="page"><button data-npage="-1" '+(numberPage===0?'disabled':'')+'>← Назад</button><span class="muted">'+(numberPage+1)+' / '+pages+'</span><button data-npage="1" '+(numberPage>=pages-1?'disabled':'')+'>Дальше →</button></div>';shell(body)}
function history(rows,more){let body='<div class="toggle"><button class="more" data-q="history:0">Все занятия</button><button class="more" data-q="errors:0">С ошибками</button></div>';if(!rows.length)body+='<div class="empty">Записей пока нет.</div>';else{body+='<section class="items">'+rows.map(x=>'<article class="item"><div><strong>№'+esc(x.n)+' · '+esc(x.f)+'</strong><small>'+esc(x.d)+' · '+esc(statusName(x.o))+(x.e?' · была ошибка':'')+'</small></div><button class="more" data-item="'+esc(x.i)+'">Подробно</button></article>').join('')+'</section><div class="page">'+(historyPage>0?'<button data-q="'+historyMode+':'+Math.max(0,historyPage-HISTORY_PAGE)+'">Назад</button>':'')+(more?'<button data-q="'+historyMode+':'+(historyPage+HISTORY_PAGE)+'">Ещё</button>':'')+'</div>'}shell(body)}
function itemDetail(d){let attempts=(d.a||[]).map(a=>'<span class="tag">'+a.n+'-я попытка: '+(a.ok?'верно':'ошибка')+(a.h?' · была подсказка':'')+'</span>').join('');shell('<article class="item"><div><strong>'+esc(d.n)+' · '+esc(d.f)+'</strong><small>'+esc(d.date||'')+' · '+esc(statusName(d.o))+'</small></div><button class="more" data-back="1">Назад</button><div class="condition">'+esc(d.c)+'</div><div class="attempts">'+(attempts||'<span class="muted">Попыток нет в сохранённой истории.</span>')+'</div></article>')}
function draw(data){errorText='';payload=data;if(data.tab==='o'){tab='o';overview(data.p||{})}else if(data.tab==='n'){tab='n';detail=null;numberPage=0;numbers(data.r||[])}else if(data.tab==='h'){tab='h';detail=null;historyMode=data.m||'history';historyPage=data.p||0;lastHistory=data;history(data.r||[],!!data.more)}else if(data.tab==='d'){tab='h';itemDetail(data.d)}else if(data.tab==='err'){tab=data.keep||'o';errorText='Не удалось загрузить данные. Нажмите «Обновить» и попробуйте ещё раз.';shell('<div class="empty">Данные не изменены.</div>')}}
function request(q){if(busy)return;if(!window.TelegramWidget||typeof TelegramWidget.request!=='function'){errorText='Откройте текстовую версию прогресса из меню бота.';shell('<div class="empty">В этом клиенте виджеты недоступны.</div>');return}busy=true;errorText='';shell('<div class="loading">Загружаем…</div>');TelegramWidget.request(q).then(a=>{busy=false;try{draw(JSON.parse(a.result||'{}'))}catch(_){errorText='Не удалось прочитать ответ.';shell('<div class="empty">Данные пока недоступны.</div>')}},()=>{busy=false;errorText='Не удалось обновить данные. Повторите попытку.';shell('<div class="empty">Ваши сохранённые тренировки не изменены.</div>')})}
root.addEventListener('click',e=>{let b=e.target.closest('button');if(!b)return;if(b.dataset.npage){numberPage=Math.max(0,Math.min(Math.ceil((payload.r||[]).length/NUMBER_PAGE)-1,numberPage+Number(b.dataset.npage)));detail=null;numbers(payload.r||[]);return}if(b.dataset.q){request(b.dataset.q);return}if(b.dataset.detail){let n=Number(b.dataset.detail);detail=detail===n?null:n;numbers(payload.r||[]);return}if(b.dataset.item){request('item:'+b.dataset.item);return}if(b.dataset.back&&lastHistory){draw(lastHistory)}});
try{let init=TelegramWidget&&TelegramWidget.chatData?JSON.parse(TelegramWidget.chatData):null;if(init)draw(init);else request('refresh')}catch(_){request('refresh')}
</script></body></html>'''


def widget_size(html: str = WIDGET_HTML) -> tuple[int, int]:
    raw = html.encode("utf-8")
    return len(raw), len(zlib.compress(raw, level=9))


def _json(data: dict[str, Any]) -> str:
    value = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(value.encode("utf-8")) > 1024:
        raise ValueError("Telegram Widget data exceeds 1024 UTF-8 bytes")
    return value


def overview_data(insights: dict[str, Any]) -> str:
    total = insights["total"]
    completed = total["completed"]
    if completed < 5:
        recommendation = f"Для точной рекомендации нужно больше данных: завершено {completed} из 5."
    else:
        candidates = [
            (values["error_tasks"] + values["skipped"], number)
            for number, values in insights["numbers"].items()
            if values["completed"]
        ]
        count, number = max(candidates, default=(0, 0))
        recommendation = (
            f"Можно повторить №{number}: там {count} заданий с ошибкой или пропуском."
            if count and number else "В завершённых заданиях ошибок и пропусков не было."
        )
    return _json({"tab": "o", "p": {
        "c": completed, "u": total["unassisted_correct"],
        "h": total["assisted_correct"], "e": total["error_tasks"],
        "s": total["skipped"], "x": total["unknown_assistance"], "r": recommendation,
    }})


async def widget_response(repository: Any, telegram_user_id: int, request: str) -> str:
    """Resolve one bounded, read-only widget request for the authenticated Telegram user."""
    if request == "refresh":
        return overview_data(await training_insights(repository, telegram_user_id))
    if request == "tab:o":
        return overview_data(await training_insights(repository, telegram_user_id))
    if request == "tab:n":
        insights = await training_insights(repository, telegram_user_id, "numbers")
        number_rows = [[number, *[values[key] for key in (
            "completed", "correct", "unassisted_correct", "assisted_correct", "error_tasks",
            "skipped", "first_correct", "second_correct",
        )]] for number, values in insights["numbers"].items()]
        return _json({"tab": "n", "r": number_rows})
    if request == "tab:h":
        request = "history:0"
    if request.startswith(("history:", "errors:")):
        section, raw_offset = request.split(":", 1)
        if not raw_offset.isascii() or not raw_offset.isdigit():
            return _json({"tab": "err"})
        offset = min(int(raw_offset), 1_000_000)
        insights = await training_insights(repository, telegram_user_id, f"{section}:{offset}", 3)
        records = insights[section]
        rows: list[dict[str, Any]] = []
        for record in records:
            family = str(record["family_id"])
            if family.startswith("OGE15:"):
                name = _STORY_NAMES.get(family.partition(":")[2], "Сюжет")
                pos = str(record["record_id"]).rsplit(":", 1)[-1]
                family_name_text = f"{name}, вопрос {pos}"
                number_label: int | str = "1–5"
            else:
                family_name_text = record["family_name"]
                number_label = record["number"]
            stamp = record.get("issued_at")
            date = stamp.strftime("%d.%m.%y") if stamp else "дата неизвестна"
            rows.append({
                "i": record["record_id"], "n": number_label,
                "f": family_name_text[:20], "d": date, "o": record["outcome"],
                "e": record["has_error"],
            })
        return _json({"tab": "h", "m": section, "p": offset, "r": rows,
                      "more": offset + len(rows) < insights["page_total"]})
    if request.startswith("item:"):
        record_id = request[5:]
        record = await training_record_detail(repository, telegram_user_id, record_id)
        if record is None:
            return _json({"tab": "err"})
        family = str(record["family_id"])
        name = (
            f"{_STORY_NAMES.get(family.partition(':')[2], 'Практическое задание')} · вопрос "
            f"{record_id.rsplit(':', 1)[-1]}"
            if family.startswith("OGE15:") else family_name(family)
        )
        date = record.get("issued_at")
        attempts = [
            {"n": row["attempt_no"], "ok": row["is_correct"], "h": row.get("used_hint") is True}
            for row in record.get("attempt_records", [])
        ]
        return _json({"tab": "d", "d": {
            "n": record["number"], "f": name, "date": date.strftime("%d.%m.%y") if date else "",
            "o": record["outcome"], "c": " ".join(str(record.get("condition") or "").split())[:200],
            "a": attempts,
        }})
    return _json({"tab": "err"})


def initial_widget_data(insights: dict[str, Any]) -> str:
    return overview_data(insights)


async def send_progress_widget(message: Any, repository: Any, telegram_user_id: int) -> bool:
    """Send a private, non-shared Widget; return False when the API/client rejects it."""
    from app.bot.navigation import bind_navigation, navigation_revision, prepare_navigation_markup
    from app.bot.progress import progress_widget_keyboard
    from app.bot.widget_api import SendWidget

    if getattr(getattr(message, "chat", None), "type", None) != "private":
        return False
    bot = getattr(message, "bot", None)
    if bot is None:
        return False
    html_bytes, compressed_bytes = widget_size()
    if html_bytes > 32768 or compressed_bytes > 4096:
        raise ValueError("Progress Widget exceeds Telegram HTML size limits")
    try:
        data = await training_insights(repository, telegram_user_id)
        chat_data = initial_widget_data(data)
        markup = prepare_navigation_markup(progress_widget_keyboard())
        sent = await bot(SendWidget(
            chat_id=message.chat.id,
            html=WIDGET_HTML,
            chat_data=chat_data,
            allow_queries=True,
            is_shared=False,
            height=600,
            caption="Ваш прогресс по заданиям ОГЭ",
            reply_markup=markup,
        ))
        await repository.save_user_state(telegram_user_id, "progress")
        await bind_navigation(
            sent, repository, telegram_user_id, "progress", navigation_revision(markup)
        )
        return True
    except Exception as error:
        # API 10.4 may be unavailable on the configured Bot API endpoint/client.
        import logging

        logging.getLogger("oge_trainer").warning(
            "progress_widget_send_failed error_type=%s", type(error).__name__
        )
        return False


async def handle_widget_query(bot: Any, repository: Any, query: dict[str, Any]) -> None:
    """Answer every supported Widget query, enforcing private-chat owner identity."""
    from app.bot.widget_api import AnswerWidgetQuery

    query_id = query.get("id")
    if not isinstance(query_id, str) or not query_id:
        return
    sender = query.get("from")
    chat = query.get("chat")
    query_type = query.get("type")
    data = query.get("data")
    result = _json({"tab": "err"})
    try:
        valid = (
            isinstance(sender, dict) and type(sender.get("id")) is int and sender["id"] > 0
            and isinstance(chat, dict) and chat.get("type") == "private"
            and type(chat.get("id")) is int and chat["id"] == sender["id"]
            and not query.get("widget_id")
            and isinstance(query_type, dict) and query_type.get("type") == "data"
            and isinstance(data, str) and 1 <= len(data.encode("utf-8")) <= 64
        )
        if valid:
            import asyncio

            sender_data = cast(dict[str, Any], sender)
            result = await asyncio.wait_for(
                widget_response(repository, sender_data["id"], cast(str, data)), timeout=10
            )
    except Exception as error:
        import logging

        logging.getLogger("oge_trainer").warning(
            "progress_widget_query_failed error_type=%s", type(error).__name__
        )
    await bot(AnswerWidgetQuery(widget_query_id=query_id, data=result), request_timeout=4)


__all__ = [
    "WIDGET_HTML", "handle_widget_query", "initial_widget_data", "send_progress_widget",
    "widget_response", "widget_size",
]
