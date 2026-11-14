import json
import re
import shutil
import subprocess

import pytest

from app.bot.progress_widget import (
    WIDGET_HTML,
    handle_widget_query,
    overview_data,
    widget_response,
    widget_size,
)
from app.bot.widget_api import AnswerWidgetQuery, SendWidget
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import summarize


def test_widget_html_stays_within_official_size_limits_and_is_self_contained():
    html_size, compressed_size = widget_size()
    assert html_size <= 32768
    assert compressed_size <= 4096
    assert "https://" not in WIDGET_HTML
    assert "--tg-theme-bg-color" in WIDGET_HTML
    assert "max-width:560px" in WIDGET_HTML
    assert 'name="viewport" content="width=device-width,initial-scale=1"' in WIDGET_HTML
    assert "font:100% system-ui" in WIDGET_HTML
    assert "overflow-wrap:anywhere" in WIDGET_HTML
    assert not re.search(r"overflow(?:-[xy])?\s*:\s*(?:auto|scroll)\b", WIDGET_HTML)
    assert "max-height:" not in WIDGET_HTML


def test_number_pagination_is_local_and_displays_four_rows(tmp_path):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to execute the widget's local pagination")
    html_path = tmp_path / "widget.html"
    html_path.write_text(WIDGET_HTML, encoding="utf-8")
    harness = r"""
const fs=require('fs'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8');
const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const root={innerHTML:'',listener:null,addEventListener(_name,fn){this.listener=fn}};
global.document={getElementById(){return root}};
let requests=0;
const empty=process.argv[2]==='empty';
const rows=Array.from({length:14},(_,i)=>[
  i+1,empty?0:8,empty?0:5,3,1,2,1,4,1
]);
global.TelegramWidget={
  chatData:JSON.stringify({tab:'n',r:rows}),
  request(){requests++;return Promise.resolve({result:'{}'})}
};
global.window={TelegramWidget};
eval(script);
const count=()=>[...root.innerHTML.matchAll(/<article class="row">/g)].length;
const getNumbers=()=>[...root.innerHTML.matchAll(
  /<div class="num">№(\d+)<\/div>/g
)].map(m=>Number(m[1]));
if(empty){
  assert(root.innerHTML.includes('Завершённых заданий пока нет'));
  assert(!root.innerHTML.includes('data-npage'));
  process.exit(0)
}
assert.equal(count(),4);assert.deepEqual(getNumbers(),[1,2,3,4]);
const click=(dataset)=>root.listener({target:{closest(){return {dataset}}}});
click({npage:'1'});assert.deepEqual(getNumbers(),[5,6,7,8]);
assert.equal(requests,0,'pagination must not create widget_query requests');
click({npage:'1'});assert.deepEqual(getNumbers(),[9,10,11,12]);
click({npage:'1'});assert.deepEqual(getNumbers(),[13,14]);
click({npage:'-1'});assert.deepEqual(getNumbers(),[9,10,11,12]);
click({detail:'9'});assert(root.innerHTML.includes('Верно с первой попытки'));
assert.equal(count(),4);assert.equal(requests,0);
"""
    for mode in ("full", "empty"):
        result = subprocess.run(
            ["node", "-e", harness, str(html_path), mode],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_widget_overview_uses_only_defined_completed_result_metrics():
    data = summarize([
        {"number": 9, "family_id": "OGE09-F001", "outcome": "solved",
         "attempt_records": [{"attempt_no": 1, "is_correct": True, "used_hint": False}]},
        {"number": 9, "family_id": "OGE09-F001", "outcome": "failed",
         "attempt_records": [{"attempt_no": 1, "is_correct": False}]},
        {"number": 12, "family_id": "OGE12-F001", "outcome": "issued"},
    ])
    overview = json.loads(overview_data(data))
    assert overview["p"]["c"] == 2
    assert overview["p"]["u"] == 1
    assert overview["p"]["e"] == 1
    assert overview["p"]["x"] == 0
    assert "2 из 5" in overview["p"]["r"]


def test_widget_overview_discloses_legacy_hint_unknowns():
    data = summarize([{
        "number": 9, "family_id": "OGE09-F001", "outcome": "solved",
        "attempt_records": [],
    }])
    overview = json.loads(overview_data(data))
    assert overview["p"]["x"] == 1
    assert "неизвестным использованием подсказки" in WIDGET_HTML


@pytest.mark.asyncio
async def test_widget_uses_private_telegram_identity_and_bounded_queries():
    repository = MemoryRepository()
    repository.issued9[42] = {"p1": {"family_id": "OGE09-F001", "condition": "2 + 2"}}
    repository.outcomes9[42] = {"p1": "solved"}
    repository.attempts9[42] = [
        {"problem_id": "p1", "attempt_no": 1, "is_correct": True, "used_hint": False}
    ]
    calls = []

    async def bot(method, **kwargs):
        calls.append(method)
        return True

    base = {
        "id": "q-1",
        "from": {"id": 42},
        "chat": {"id": 42, "type": "private"},
        "type": {"type": "data"},
        "data": "refresh",
    }
    await handle_widget_query(bot, repository, base)
    assert len(calls) == 1 and isinstance(calls[0], AnswerWidgetQuery)
    assert json.loads(calls[0].data)["p"]["c"] == 1

    calls.clear()
    await handle_widget_query(bot, repository, {**base, "id": "q-2",
                                                  "chat": {"id": 43, "type": "private"}})
    assert len(calls) == 1 and calls[0].data == '{"tab":"err"}'

    calls.clear()
    await handle_widget_query(bot, repository, {**base, "id": "q-3", "data": "x" * 65})
    assert len(calls) == 1 and calls[0].data == '{"tab":"err"}'

    history = await widget_response(repository, 42, "tab:h")
    assert len(history.encode("utf-8")) <= 1024
    assert "c" not in json.loads(history)["r"][0]
    empty = await widget_response(repository, 43, "tab:h")
    assert json.loads(empty)["r"] == []


def test_bot_api_10_4_adapters_use_official_method_names():
    send = SendWidget(chat_id=42, html=WIDGET_HTML, is_shared=False)
    answer = AnswerWidgetQuery(widget_query_id="query", data="{}")
    assert send.__api_method__ == "sendWidget"
    assert answer.__api_method__ == "answerWidgetQuery"
    assert send.chat_id == 42 and send.is_shared is False


def test_local_previews_embed_the_production_widget_layout_and_logic():
    from pathlib import Path

    previews = Path(__file__).parents[1] / "reports" / "previews"
    production_style = re.search(r"<style>(.*?)</style>", WIDGET_HTML, re.S).group(1)
    production_script = list(re.finditer(r"<script>(.*?)</script>", WIDGET_HTML, re.S))[-1].group(1)
    for name in ("progress-widget-preview.html", "progress-widget-preview-dark.html"):
        preview = (previews / name).read_text(encoding="utf-8")
        assert production_style in preview
        scripts = list(re.finditer(r"<script>(.*?)</script>", preview, re.S))
        assert production_script in [match.group(1) for match in scripts]
