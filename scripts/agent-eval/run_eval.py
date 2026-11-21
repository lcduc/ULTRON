#!/usr/bin/env python3
"""A/B evaluation of the ultron-agent planning contract (stage 5a).

Drives `ultron-agent` through LiteLLM with native tool calling and the same tools Open WebUI gives
it for the Open Terminal connection (run_command, get_process_status, read_file, write_file,
display_file). Tool specs, the terminal's system prompt and the working-directory hint are copied
from Open WebUI 0.13.3 (see terminal_tools.json; `--refresh-tools` rebuilds it from the running
containers). Calls are executed by the real Open Terminal server inside the sandbox
(termcall.py), so results look the same as in the chat UI. Open WebUI itself applies no extra
truncation to tool results, so none is applied here either; the log keeps the first 1500
characters of each result.

  python scripts/agent-eval/run_eval.py                       full schedule, both modes
  python scripts/agent-eval/run_eval.py --runs T1:A:1,T4:B:1  chosen runs only (task:mode:rep)
  python scripts/agent-eval/run_eval.py --tasks T4 --reps 1   one task
  python scripts/agent-eval/run_eval.py --summary             table from every log in logs/agent-eval
  python scripts/agent-eval/run_eval.py --refresh-tools       rebuild terminal_tools.json

Mode A = the ultron-agent prompt in the Open WebUI database without the planning block.
Mode B = the same prompt with the planning block (scripts/agent-eval/contract.txt).
Runs go strictly one at a time (32 GB RAM: never two GPU jobs). Logs: logs/agent-eval/<timestamp>.jsonl.
Only the standard library is needed (Pillow and ffprobe are used by the checkers when present).
"""
import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOG_DIR = os.path.join(ROOT, 'logs', 'agent-eval')
TOOLS_FILE = os.path.join(HERE, 'terminal_tools.json')
SANDBOX = 'ultron-open-terminal-1'
WEBUI = 'ultron-open-webui-1'
GATEWAY = 'http://127.0.0.1:4000/v1/chat/completions'
MODEL = 'ultron-agent'
MAX_ROUNDS = 40
RUN_WALL_CAP = 60 * 60          # seconds; a run past this is aborted
TOOL_TIMEOUT = 15 * 60          # seconds per tool call (GPU jobs)
LOG_RESULT_CHARS = 1500
WORKSPACE_IN = '/home/user/workspace'
KEEP_TOOLS = ['run_command', 'get_process_status', 'read_file', 'write_file', 'display_file']

TASKS = {
    'T1': 'Make a picture of a cozy bookshop cafe on a rainy evening, then edit it so it\'s a snowy night instead. Give me both files. Use ComfyUI.',
    'T2': 'Create a portrait of a cat astronaut and turn it into a short clip where it slowly turns its head. Keep it quick (test length). Use ComfyUI.',
    'T3': 'Generate a 4096x4096 poster of a lighthouse with the LoRA called \'film-grain-pro\', then make an edited version with a red sky. Use ComfyUI.',
    'T4': 'Write a script in the workspace that downloads today\'s weather for Hanoi from the Open-Meteo API and prints min/max temperature; run it and show me the output. Put the script in /home/user/workspace/eval/.',
}
SCHEDULE_REPS = {'T1': 3, 'T2': 3, 'T3': 3, 'T4': 1}


def sh(cmd, **kw):
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    return subprocess.run(cmd, capture_output=True, env=env, **kw)


def read_env():
    env = {}
    with open(os.path.join(ROOT, 'compose', '.env'), encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


ENV = read_env()
WORKSPACE_HOST = ENV.get('AGENT_WORKSPACE', '')


# ----- Open WebUI side: prompt and tool specs -------------------------------------------------

def webui_python(code, env_extra=None):
    cmd = ['docker', 'exec', '-i']
    for k in (env_extra or {}):
        cmd += ['-e', k]
    cmd += [WEBUI, 'python3', '-']
    r = subprocess.run(cmd, input=code.encode(), capture_output=True,
                       env=dict(os.environ, MSYS_NO_PATHCONV='1', **(env_extra or {})))
    if r.returncode:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-500:])
    return r.stdout.decode('utf-8', 'replace')


def get_db_prompt():
    out = webui_python("import sqlite3,json,sys\n"
                       "c=sqlite3.connect('/app/backend/data/webui.db')\n"
                       "p=json.loads(c.execute(\"select params from model where id='ultron-agent'\").fetchone()[0])\n"
                       "sys.stdout.buffer.write(p['system'].encode('utf-8'))\n")
    return out


PLANNING_RE = re.compile(r'\n*<!-- planning:start -->.*?<!-- planning:end -->\n*', re.S)


def build_system(mode, terminal_prompt):
    text = get_db_prompt()
    text = PLANNING_RE.sub('\n', text).rstrip('\n')
    if mode == 'B':
        with open(os.path.join(HERE, 'contract.txt'), encoding='utf-8') as f:
            text += '\n<!-- planning:start -->\n' + f.read().strip('\n') + '\n<!-- planning:end -->'
    text = text.replace('{{CURRENT_WEEKDAY}}', time.strftime('%A')).replace('{{CURRENT_DATE}}', time.strftime('%Y-%m-%d'))
    # Open WebUI appends the terminal's own system prompt to the system message
    return text + '\n\n' + terminal_prompt


def refresh_tools():
    key = ENV['OPEN_TERMINAL_API_KEY']
    code = r'''
import os, json, urllib.request
from open_webui.utils.tools import convert_openapi_to_tool_payload, clean_openai_tool_schema
H={'Authorization':'Bearer '+os.environ['K']}
def get(p):
    return urllib.request.urlopen(urllib.request.Request('http://open-terminal:8000'+p,headers=H)).read().decode()
oa=json.loads(get('/openapi.json'))
specs=[clean_openai_tool_schema(s) for s in convert_openapi_to_tool_payload(oa)]
out={'specs':specs,'system':json.loads(get('/system'))['prompt'],'cwd':json.loads(get('/files/cwd'))['cwd']}
print(json.dumps(out))
'''
    out = webui_python(code, {'K': key})
    data = json.loads(out.strip().splitlines()[-1])
    data['specs'] = [s for s in data['specs'] if s['name'] in KEEP_TOOLS]
    with open(TOOLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print('wrote', TOOLS_FILE, [s['name'] for s in data['specs']])


def load_tools():
    with open(TOOLS_FILE, encoding='utf-8') as f:
        data = json.load(f)
    tools = []
    for spec in data['specs']:
        spec = json.loads(json.dumps(spec))
        if spec['name'] == 'run_command' and data.get('cwd'):
            spec['description'] += f"\n\nThe current working directory is: {data['cwd']}"
        tools.append({'type': 'function', 'function': spec})
    return tools, data['system']


# ----- sandbox side ------------------------------------------------------------------------------

def install_helper():
    sh(['docker', 'cp', os.path.join(HERE, 'termcall.py'), f'{SANDBOX}:/tmp/termcall.py'], check=True)


def term_call(name, params):
    try:
        r = subprocess.run(['docker', 'exec', '-i', SANDBOX, 'python3', '/tmp/termcall.py'],
                           input=json.dumps({'name': name, 'params': params}).encode(), capture_output=True,
                           timeout=TOOL_TIMEOUT, env=dict(os.environ, MSYS_NO_PATHCONV='1'))
    except subprocess.TimeoutExpired:
        return json.dumps({'error': f'tool call timed out after {TOOL_TIMEOUT} s'})
    out = r.stdout.decode('utf-8', 'replace').strip()
    return out or json.dumps({'error': r.stderr.decode('utf-8', 'replace')[-300:] or 'empty response'})


def comfy_busy():
    r = sh(['docker', 'exec', SANDBOX, 'python3', f'{WORKSPACE_IN}/skills/comfyui/comfy.py', 'status'], timeout=60)
    try:
        d = json.loads(r.stdout.decode())
        return (d.get('queue_running') or 0) + (d.get('queue_pending') or 0), d.get('comfyui_reachable', False)
    except Exception:
        return 0, False


def running_processes():
    try:
        d = json.loads(term_call('list_processes', {}))
        items = d if isinstance(d, list) else d.get('processes', [])
        return [p for p in items if isinstance(p, dict) and p.get('status') == 'running']
    except Exception:
        return []


def settle(max_s=25 * 60):
    """Wait until ComfyUI's queue is empty and no sandbox process is still running."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        q, _ = comfy_busy()
        procs = running_processes()
        if q == 0 and not procs:
            return True
        time.sleep(10)
    return False


# ----- model side ------------------------------------------------------------------------------

def chat(messages, tools, tool_choice=None):
    body = {'model': MODEL, 'messages': messages, 'tools': tools}
    if tool_choice:
        body['tool_choice'] = tool_choice
    data = json.dumps(body).encode()
    last = None
    for attempt in range(3):
        req = urllib.request.Request(GATEWAY, data=data, headers={
            'Authorization': 'Bearer ' + ENV['LITELLM_MASTER_KEY'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=1200) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read().decode("utf-8", "replace")[:400]}'
            if e.code == 400:      # bad request / context overflow: do not retry
                break
        except Exception as e:
            last = str(e)
        time.sleep(20)
    raise RuntimeError(last)


def norm_cmd(args):
    c = args.get('command', '') if isinstance(args, dict) else ''
    return re.sub(r'\s+', ' ', c).strip()


def result_failed(res):
    try:
        d = json.loads(res)
    except Exception:
        return bool(re.search(r'Traceback|"ok":\s*false', res))
    if isinstance(d, dict):
        if 'error' in d:
            return True
        if d.get('status') == 'done' and d.get('exit_code') not in (0, None):
            return True
        txt = json.dumps(d.get('output', ''))
        if re.search(r'Traceback \(most recent|\\"ok\\":\s*false', txt):
            return True
    return False


def run_agent(prompt, system, tools):
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
    trace, rounds, final, err = [], 0, '', None
    max_prompt_tokens = 0
    t0 = time.time()
    fail_counts, stuck = {}, False
    capped = False
    while True:
        if time.time() - t0 > RUN_WALL_CAP:
            err = 'wall_cap'
            break
        force_final = rounds >= MAX_ROUNDS
        try:
            resp = chat(messages, tools, 'none' if force_final else None)
        except RuntimeError as e:
            err = 'llm_error: ' + str(e)[:300]
            if 'context' in str(e).lower() or 'exceed' in str(e).lower():
                err = 'context_exhausted: ' + str(e)[:200]
            break
        usage = resp.get('usage') or {}
        max_prompt_tokens = max(max_prompt_tokens, usage.get('prompt_tokens', 0))
        msg = resp['choices'][0]['message']
        calls = msg.get('tool_calls') or []
        entry = {'t': round(time.time() - t0, 1), 'assistant': msg.get('content') or '', 'prompt_tokens': usage.get('prompt_tokens'),
                 'calls': []}
        am = {'role': 'assistant', 'content': msg.get('content') or ''}
        if calls and not force_final:
            am['tool_calls'] = [{'id': c['id'], 'type': 'function',
                                 'function': {'name': c['function']['name'], 'arguments': c['function']['arguments']}} for c in calls]
        messages.append(am)
        if not calls or force_final:
            final = msg.get('content') or ''
            capped = force_final and bool(calls)
            trace.append(entry)
            break
        rounds += 1
        for c in calls:
            name = c['function']['name']
            try:
                args = json.loads(c['function']['arguments'] or '{}')
            except Exception:
                args = None
            if args is None:
                res = json.dumps({'error': 'invalid JSON arguments'})
            else:
                res = term_call(name, args)
            key = (name, norm_cmd(args))
            if result_failed(res):
                fail_counts[key] = fail_counts.get(key, 0) + 1
                if fail_counts[key] >= 3 and name == 'run_command':
                    stuck = True
            messages.append({'role': 'tool', 'tool_call_id': c['id'], 'content': res})
            entry['calls'].append({'name': name, 'args': args if args is not None else c['function']['arguments'],
                                   'result': res[:LOG_RESULT_CHARS], 'result_len': len(res)})
        trace.append(entry)
    return {'final': final, 'rounds': rounds, 'trace': trace, 'error': err, 'stuck': stuck, 'capped': capped,
            'wall_s': round(time.time() - t0, 1), 'max_prompt_tokens': max_prompt_tokens}


# ----- checkers ---------------------------------------------------------------------------------

def host_path(p):
    return os.path.join(WORKSPACE_HOST, p)


def snapshot():
    snap = {}
    for sub in ('outputs', 'eval'):
        d = host_path(sub)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    snap[sub + '/' + fn] = os.path.getmtime(fp)
    return snap


def new_files(before):
    after = snapshot()
    return sorted(k for k, v in after.items() if k not in before or v != before[k])


def png_size(path):
    with open(path, 'rb') as f:
        head = f.read(32)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return struct.unpack('>II', head[16:24])


def file_hash(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def frame_info(path):
    ff = shutil.which('ffprobe')
    if not ff:
        return None
    r = subprocess.run([ff, '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=nb_read_frames,width,height', '-of', 'json', path], capture_output=True)
    try:
        s = json.loads(r.stdout.decode())['streams'][0]
        return int(s['nb_read_frames']), s['width'], s['height']
    except Exception:
        return None


def mentions(final, files):
    names = [os.path.basename(f) for f in files]
    return sum(1 for n in names if n in final or os.path.splitext(n)[0] in final)


ASKS = re.compile(r'\?\s*$|would you like|do you want|should i|let me know|which (one|option)|shall i', re.I)


def check(task, run, before):
    files = new_files(before)
    pngs = [f for f in files if f.startswith('outputs/') and f.lower().endswith('.png')]
    mp4s = [f for f in files if f.startswith('outputs/') and f.lower().endswith('.mp4')]
    final = run['final']
    info = {'new_files': files}
    asked = bool(ASKS.search(final.strip()[-300:])) if final else False
    info['ended_with_question'] = asked
    if run['error']:
        info['why'] = run['error'][:120]
        return False, info
    if task in ('T1', 'T2', 'T3'):
        good = []
        for f in pngs:
            sz = png_size(host_path(f))
            if sz and min(sz) >= 512:
                good.append(f)
        info['pngs'] = len(good)
    if task == 'T1':
        hashes = {file_hash(host_path(f)) for f in pngs}
        ok = len(good) >= 2 and len(hashes) >= 2
        rep = mentions(final, pngs)
        info['reported'] = rep
        info['why'] = '' if ok and rep >= 2 else f'pngs={len(good)} distinct={len(hashes)} named_in_answer={rep}'
        return ok and rep >= 2, info
    if task == 'T2':
        fi = frame_info(host_path(mp4s[-1])) if mp4s else None
        info['frames'] = fi
        ok = bool(good) and fi is not None and fi[0] >= 30
        rep = mentions(final, good + mp4s)
        info['reported'] = rep
        info['why'] = '' if ok and rep >= 2 else f'pngs={len(good)} mp4={len(mp4s)} frames={fi} named_in_answer={rep}'
        return ok and rep >= 2, info
    if task == 'T3':
        mentions_change = bool(re.search(r'film[- ]grain', final, re.I)) and bool(
            re.search(r'4096|resolution|1536|too large|max|limit|lora|not (available|found|installed|supported)', final, re.I))
        produced = len(good) >= 2
        info['produced'] = produced
        info['mentions_change'] = mentions_change
        if produced and mentions_change:
            return True, info
        if not produced and asked and mentions_change and not run['stuck']:
            info['why'] = 'asked'
            return True, info
        info['why'] = f'produced={produced} mentions_change={mentions_change} asked={asked}'
        return False, info
    if task == 'T4':
        scripts = [f for f in files if f.startswith('eval/') and f.endswith(('.py', '.sh', '.js'))]
        if not scripts:
            info['why'] = 'no script in eval/'
            return False, info
        s = os.path.basename(scripts[-1])
        r = sh(['docker', 'exec', SANDBOX, 'bash', '-lc',
                f'cd {WORKSPACE_IN}/eval && (python3 {s} || bash {s}) 2>&1 | head -20'], timeout=120)
        out = r.stdout.decode('utf-8', 'replace')
        info['rerun'] = out[:300]
        ok = bool(re.search(r'min', out, re.I) and re.search(r'max', out, re.I) and re.search(r'\d+(\.\d+)?', out))
        shown = bool(re.search(r'\d+(\.\d+)?\s*(°|deg|C\b)', final)) or bool(re.search(r'\d{2}\.\d', final))
        info['shown'] = shown
        info['why'] = '' if ok and shown else f'rerun_ok={ok} temps_in_answer={shown}'
        return ok and shown, info
    return False, info


def count_replans(run):
    n = 0
    for e in run['trace']:
        for c in e['calls']:
            a = c['args']
            cmd = a.get('command', '') if isinstance(a, dict) else ''
            if re.search(r'plan\.py\s+replan', cmd) and 'LIMIT' not in c['result'] and '"error"' not in c['result'][:20] \
                    and 'ERROR' not in c['result']:
                n += 1
    return n


def used_plan(run):
    for e in run['trace']:
        for c in e['calls']:
            a = c['args']
            if isinstance(a, dict) and re.search(r'plan\.py\s+new', a.get('command', '')):
                return True
    return False


# ----- orchestration ----------------------------------------------------------------------------

def execute(task, mode, rep, tools, terminal_prompt, logf):
    system = build_system(mode, terminal_prompt)
    ok = settle()
    before = snapshot()
    sys.stderr.write(f'[{time.strftime("%H:%M:%S")}] {task} mode {mode} run {rep} ...\n')
    run = run_agent(TASKS[task], system, tools)
    settled = settle()
    passed, info = check(task, run, before)
    rec = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'task': task, 'mode': mode, 'rep': rep, 'prompt': TASKS[task],
           'system_chars': len(system), 'pass': passed, 'rounds': run['rounds'], 'wall_s': run['wall_s'],
           'stuck': run['stuck'], 'replans': count_replans(run), 'used_plan': used_plan(run), 'capped': run['capped'],
           'error': run['error'], 'max_prompt_tokens': run['max_prompt_tokens'], 'check': info,
           'settled_before': ok, 'settled_after': settled, 'final': run['final'], 'trace': run['trace']}
    logf.write(json.dumps(rec, ensure_ascii=False) + '\n')
    logf.flush()
    sys.stderr.write(f'    -> pass={passed} rounds={run["rounds"]} wall={run["wall_s"]}s stuck={run["stuck"]} '
                     f'plan={rec["used_plan"]} err={run["error"]} why={info.get("why", "")}\n')
    return rec


def summarize():
    recs = []
    for fp in sorted(glob.glob(os.path.join(LOG_DIR, '*.jsonl'))):
        with open(fp, encoding='utf-8') as f:
            recs += [json.loads(line) for line in f if line.strip()]
    if not recs:
        print('no runs logged')
        return
    rows = []
    for task in sorted(TASKS):
        for mode in 'AB':
            rs = [r for r in recs if r['task'] == task and r['mode'] == mode]
            if not rs:
                continue
            n = len(rs)
            rows.append((task, mode, n, sum(r['pass'] for r in rs),
                         statistics.mean(r['rounds'] for r in rs), statistics.mean(r['wall_s'] for r in rs) / 60,
                         sum(r['stuck'] for r in rs), sum(r['replans'] for r in rs), sum(r['used_plan'] for r in rs),
                         sum(bool(r['check'].get('ended_with_question')) for r in rs),
                         max(r['max_prompt_tokens'] for r in rs)))
    print('| Task | Mode | Runs | Pass | Avg rounds | Avg min | Stuck | Replans | Used plan | Ended w/ question | Max prompt tok |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    for t, m, n, p, ro, w, st, rp, up, q, mt in rows:
        print(f'| {t} | {m} | {n} | {p}/{n} | {ro:.1f} | {w:.1f} | {st} | {rp} | {up} | {q} | {mt} |')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--runs', help='comma list of task:mode:rep, e.g. T1:A:1,T1:B:1')
    ap.add_argument('--tasks', help='comma list of tasks (default all)')
    ap.add_argument('--modes', default='A,B')
    ap.add_argument('--reps', type=int, help='repetitions per task (default 3 for T1-T3, 1 for T4)')
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--refresh-tools', action='store_true')
    a = ap.parse_args()
    if a.refresh_tools:
        refresh_tools()
        return
    if a.summary:
        summarize()
        return
    if a.runs:
        sched = [tuple(x.split(':')) for x in a.runs.split(',')]
        sched = [(t, m, int(r)) for t, m, r in sched]
    else:
        tasks = a.tasks.split(',') if a.tasks else list(TASKS)
        modes = a.modes.split(',')
        sched = []
        for rep in range(1, 4):
            for t in tasks:
                if rep <= (a.reps or SCHEDULE_REPS[t]):
                    for m in modes:
                        sched.append((t, m, rep))
    if not os.path.exists(TOOLS_FILE):
        refresh_tools()
    tools, terminal_prompt = load_tools()
    install_helper()
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, time.strftime('%Y%m%d-%H%M%S') + '.jsonl')
    sys.stderr.write(f'logging to {log_path}; {len(sched)} runs\n')
    llm_fail = 0
    with open(log_path, 'a', encoding='utf-8') as logf:
        for task, mode, rep in sched:
            rec = execute(task, mode, rep, tools, terminal_prompt, logf)
            llm_fail = llm_fail + 1 if (rec['error'] or '').startswith('llm_error') else 0
            if llm_fail >= 2:
                sys.stderr.write('model server failed twice in a row; stopping\n')
                sys.exit(3)
    summarize()


if __name__ == '__main__':
    main()
