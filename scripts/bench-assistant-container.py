"""Runs INSIDE the open-webui container (docker exec -i ... python3 - < this file).

Rebuilds, with Open WebUI's own code, what it sends to the model for the Ultron
assistant: the system prompt and tool schemas of a model, and the prompts of the
background tasks (title, tags, follow-ups) for a typical 3-turn chat.
Read-only: it only reads webui.db and calls the calendar MCP server's tools/list.
It prints one line: BENCH_JSON:<json>. Nothing secret is printed.
"""
import asyncio
import json
import os
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, '/app/backend')
os.chdir('/app/backend')

MODELS = [m for m in os.environ.get('BENCH_MODELS', 'ultron,ultron-think').split(',') if m]

CHAT = [
    ('user', 'How do I get better at learning guitar chords quickly? I only have about twenty minutes a day.'),
    ('assistant', "Twenty focused minutes a day is enough if you structure them. Spend five minutes on finger "
     "stretches and clean fretting of one open chord at a time, ten minutes switching between two chords you "
     "already know with a metronome at a slow tempo, and five minutes playing a simple song that uses them. "
     "Start with the open chords Em, Am, D, G and C. Add a new chord only when you can switch between the "
     "current ones in under a second. Press just behind the fret with the tips of your fingers, and play each "
     "string one by one to find buzzing notes. Short daily sessions beat one long weekly session, because the "
     "muscle memory is built during sleep."),
    ('user', 'Which two chords should I switch between first, and what tempo should the metronome be at?'),
    ('assistant', "Begin with G and C, or with Em and Am if G feels like too big a stretch. Em and Am share "
     "the same finger shape, so only the position changes, which makes the switch easy to feel. Set the "
     "metronome to about 50 beats per minute and change chord on every fourth beat. When you can do ten clean "
     "switches in a row without looking at your hand, raise it by 5 beats per minute. Expect to reach 80 within "
     "a couple of weeks. If a switch fails, slow down instead of pushing through, since practicing mistakes "
     "locks them in."),
    ('user', 'Thanks. Can you suggest an easy song that only needs Em and Am so I can use them right away?'),
    ('assistant', "Try 'Horse With No Name' by America. The verses are just Em and D6/9, and you can play the "
     "D6/9 as a simple shape by lifting fingers off the Em chord. If you want a version with Am, 'Knockin' on "
     "Heaven's Door' uses G, D, Am and C, which you can build up to after the first two chords. Play the "
     "strumming pattern down, down-up, up-down-up at a slow speed, and sing or hum along so your timing "
     "stays steady."),
]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


async def main():
    from open_webui.models.config import Config  # noqa: F401
    from open_webui.utils.task import (
        follow_up_generation_template,
        tags_generation_template,
        title_generation_template,
        prompt_template,
    )
    from open_webui.config import (
        DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
        DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE,
        DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE,
    )
    from open_webui.utils.tools import get_builtin_tools

    db = sqlite3.connect('file:/app/backend/data/webui.db?mode=ro', uri=True)
    user_row = db.execute("select id,name,role from user where role='admin' limit 1").fetchone()
    user = {'id': user_row[0], 'name': user_row[1], 'role': user_row[2]}
    cfg = {k: json.loads(v) for k, v in db.execute(
        "select key,value from config where key in ('task.title.prompt_template','task.tags.prompt_template',"
        "'task.follow_up.prompt_template','tool_server.connections','task.follow_up.enable','task.tags.enable',"
        "'task.title.enable','memories.enable','memories.system_context.enable','memories.background_review.enable')")}

    request = SimpleNamespace(state=SimpleNamespace(internal=False, direct=False), app=SimpleNamespace(state=SimpleNamespace()))
    out = {'models': {}, 'tasks': {}, 'notes': [],
           'settings': {k: v for k, v in cfg.items() if k.startswith(('task.', 'memories.')) and 'template' not in k}}

    # MCP tool specs, exactly as Open WebUI asks for them.
    mcp_specs = []
    try:
        from open_webui.utils.mcp.client import MCPClient
        conn = next((c for c in cfg.get('tool_server.connections', []) if c.get('type') == 'mcp'), None)
        key = os.environ.get('CALENDAR_MCP_API_KEY') or (conn or {}).get('key') or ''
        client = MCPClient(event_caller=None, server_name='google_mcp')
        await client.connect(url=(conn or {}).get('url', 'http://calendar-mcp:8000/mcp'),
                             headers={'Authorization': f'Bearer {key}'})
        mcp_specs = await client.list_tool_specs()
        await client.disconnect()
    except BaseException as e:  # noqa: BLE001
        out['notes'].append(f'MCP tools/list failed: {type(e).__name__}: {e}')

    for name in MODELS:
        row = db.execute('select params, meta from model where id=?', (name,)).fetchone()
        params, meta = json.loads(row[0] or '{}'), json.loads(row[1] or '{}')
        model = {'id': name, 'info': {'meta': meta, 'params': params}}
        caps = meta.get('capabilities') or {}
        # features as the browser sends them: default-on web search (defaultFeatureIds),
        # memory from the user's Memory switch (on unless switched off), no image/code toggles.
        features = {
            'web_search': 'web_search' in (meta.get('defaultFeatureIds') or []),
            'memory': True,
            'image_generation': False,
            'code_interpreter': False,
        }
        extra = {'__user__': user, '__metadata__': {'chat_id': 'bench', 'session_id': 'bench'}, '__files__': []}
        tools = await get_builtin_tools(request, extra, features, model)
        specs = [t['spec'] for t in tools.values()]
        names = [s.get('name') for s in specs]
        if meta.get('toolIds'):
            specs += mcp_specs
            names += [s.get('name') for s in mcp_specs]
        system = await prompt_template(params.get('system', ''), user)
        out['models'][name] = {
            'system': system,
            'tools': [{'type': 'function', 'function': s} for s in specs],
            'tool_names': names,
            'memory_capability': bool(caps.get('memory')),
            'model_params': {k: v for k, v in params.items() if k not in ('system', 'custom_params')},
        }

    # Task prompts for the typical chat. Defaults are used when the DB template is empty.
    def tpl(key, default):
        return cfg.get(key) or default

    msgs = [{'role': r, 'content': c, 'id': f'm{i}'} for i, (r, c) in enumerate(CHAT)]
    # Title runs at the start of the first message, when the assistant reply is still empty.
    title = await title_generation_template(
        tpl('task.title.prompt_template', DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE),
        [msgs[0], {'role': 'assistant', 'content': ''}], user)
    # Tags run after the first reply only (frontend asks for title/tags when the chat has 2 messages).
    tags = await tags_generation_template(
        tpl('task.tags.prompt_template', DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE), msgs[:2], user)
    # Follow-ups run after every reply.
    follow = []
    for n in (2, 4, 6):
        follow.append(await follow_up_generation_template(
            tpl('task.follow_up.prompt_template', DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE),
            msgs[:n], user, use_default=not cfg.get('task.follow_up.prompt_template')))
    out['tasks'] = {'title': title, 'tags': tags, 'follow_ups': follow}
    out['chat'] = CHAT
    print('BENCH_JSON:' + json.dumps(out), flush=True)


asyncio.run(main())
