"""Helper for scripts/bench-assistant.ps1 (run that, not this).

Measures the model, the background tasks, Open WebUI chat requests (only with
ULTRON_API_KEY) and voice. Writes a JSON result file; progress goes to stderr.
Secrets are read from compose/.env and are never printed.
"""
import argparse
import http.client
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATEWAY = 'http://127.0.0.1:4000'
LLAMA = 'http://127.0.0.1:8080'
OWUI = 'http://localhost:3000'
CONTAINER = 'ultron-open-webui-1'
ANSI = re.compile(r'\x1b\[[0-9;]*m')

ONE_LINERS = [
    'Say hello in one short sentence.', 'Give me a one-line fun fact.', 'Tell me a short joke.',
    'What is a good name for a cat?', 'Say good morning in French.', 'Name a colour.',
    'Give me a motivational quote.', 'What is a prime number?', 'Tell me a one-word greeting.',
    'Name a fruit that is red.', 'What rhymes with blue?', 'Give me a two-word compliment.',
]


def log(*a):
    print(*a, flush=True)


def read_env():
    env = {}
    path = os.path.join(ROOT, 'compose', '.env')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8-sig'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    for k in ('ULTRON_API_KEY',):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = read_env()


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def post(url, key, payload, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    return urllib.request.urlopen(req, timeout=timeout)


def chat_stream(base, key, payload, path='/v1/chat/completions'):
    """Streams a chat request. Returns (ttft_s, total_s, usage, first_kind)."""
    payload = dict(payload, stream=True, stream_options={'include_usage': True})
    t0 = time.perf_counter()
    ttft, usage, kind = None, None, None
    with post(base + path, key, payload) as r:
        for raw in r:
            line = raw.decode('utf-8', 'replace').strip()
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get('usage'):
                usage = obj['usage']
            for ch in obj.get('choices') or []:
                d = ch.get('delta') or {}
                if ttft is None and (d.get('content') or d.get('tool_calls') or d.get('reasoning_content')):
                    ttft = time.perf_counter() - t0
                    kind = 'tool_call' if d.get('tool_calls') else 'text'
    return ttft, time.perf_counter() - t0, usage or {}, kind


def chat_once(base, key, payload):
    t0 = time.perf_counter()
    with post(base + '/v1/chat/completions', key, dict(payload, stream=False)) as r:
        obj = json.loads(r.read())
    return time.perf_counter() - t0, obj


# ---- llama-server view: metrics and the log file ---------------------------------------------

def llama_metrics():
    req = urllib.request.Request(LLAMA + '/metrics?model=ultron', headers={'Authorization': 'Bearer ' + ENV['LLAMA_API_KEY']})
    out = {}
    with urllib.request.urlopen(req, timeout=10) as r:
        for line in r.read().decode().splitlines():
            if line and not line.startswith('#'):
                k, v = line.split()
                out[k.replace('llamacpp:', '')] = float(v)
    return out


def llama_log_path():
    d = os.path.join(ROOT, 'logs')
    files = [os.path.join(d, f) for f in os.listdir(d) if f.startswith('llama-server-') and f.endswith('.log')]
    return max(files, key=os.path.getmtime)


class LogProbe:
    """Counts model-server requests and their GPU time from the server log between mark() and read()."""

    def __init__(self):
        self.path = llama_log_path()
        self.mark()

    def mark(self):
        self.offset = os.path.getsize(self.path)

    def read(self):
        with open(self.path, 'rb') as f:
            f.seek(self.offset)
            text = ANSI.sub('', f.read().decode('utf-8', 'replace'))
        reqs = {}
        for m in re.finditer(r'task (\d+) \|\s+(prompt eval time|eval time|total time)\s*=\s*([\d.]+) ms /\s*(\d+) (?:tokens|tokens)', text):
            t = reqs.setdefault(m.group(1), {})
            t[m.group(2)] = (float(m.group(3)), int(m.group(4)))
        done = []
        for tid, t in reqs.items():
            if 'total time' in t:
                done.append({'prompt_tokens_processed': t.get('prompt eval time', (0, 0))[1],
                             'prompt_ms': t.get('prompt eval time', (0, 0))[0],
                             'gen_tokens': t.get('eval time', (0, 0))[1], 'gen_ms': t.get('eval time', (0, 0))[0],
                             'total_ms': t['total time'][0]})
        return done

    def wait_idle(self, quiet=3.0, limit=120):
        t0, last, last_change = time.time(), None, time.time()
        while time.time() - t0 < limit:
            try:
                busy = llama_metrics().get('requests_processing', 0)
            except Exception:
                busy = 0
            size = os.path.getsize(self.path)
            if size != last or busy:
                last, last_change = size, time.time()
            elif time.time() - last_change >= quiet:
                return True
            time.sleep(0.5)
        return False


def gpu_seconds(m0, m1):
    return (m1['prompt_seconds_total'] - m0['prompt_seconds_total']) + \
           (m1['tokens_predicted_seconds_total'] - m0['tokens_predicted_seconds_total'])


# ---- context from Open WebUI ----------------------------------------------------------------

def docker_py(script, extra_env=None, timeout=240):
    cmd = ['docker', 'exec', '-i']
    for k, v in (extra_env or {}).items():
        cmd += ['-e', f'{k}={v}']
    cmd += [CONTAINER, 'python3', '-']
    p = subprocess.run(cmd, input=open(os.path.join(ROOT, 'scripts', script), 'rb').read(),
                       capture_output=True, timeout=timeout)
    for line in p.stdout.decode('utf-8', 'replace').splitlines():
        if line.startswith('BENCH_JSON:'):
            return json.loads(line[11:])
    raise RuntimeError(f'{script} produced no result: ' + p.stderr.decode('utf-8', 'replace')[-400:])


# ---- the measurements -----------------------------------------------------------------------

def build_payload(model, system_extra_prefix, user_line):
    system = model['system']
    if system_extra_prefix:
        system = system_extra_prefix + system
    return {'model': 'ultron', 'max_tokens': 24, 'tools': model['tools'],
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_line}]}


def model_level(ctx, n):
    model = ctx['models']['ultron']
    key = ENV['OPENAI_API_KEY']
    res = {'tools': len(model['tools']), 'tool_names': model['tool_names'],
           'tool_schema_chars': len(json.dumps(model['tools'])), 'system_chars': len(model['system'])}
    log('model level: priming')
    chat_stream(GATEWAY, key, build_payload(model, '', ONE_LINERS[0]))
    warm, cold, pt, kinds = [], [], None, []
    for i in range(n):
        ttft, _, usage, kind = chat_stream(GATEWAY, key, build_payload(model, '', ONE_LINERS[(i + 1) % len(ONE_LINERS)]))
        warm.append(ttft); pt = usage.get('prompt_tokens', pt); kinds.append(kind)
    for i in range(n):
        ttft, _, usage, kind = chat_stream(GATEWAY, key, build_payload(model, f'[{uuid.uuid4().hex[:8]}] ', ONE_LINERS[i % len(ONE_LINERS)]))
        cold.append(ttft); pt = usage.get('prompt_tokens', pt)
    res.update({'prompt_tokens': pt, 'ttft_warm_prefix_s': med(warm), 'ttft_warm_runs': [round(x, 2) for x in warm if x],
                'ttft_cold_s': med(cold), 'ttft_cold_runs': [round(x, 2) for x in cold if x], 'first_output': kinds[0]})
    # tokens by part, from the server's tokenizer: system alone and system + tools
    key_ = ENV['LLAMA_API_KEY']
    try:
        def toks(payload):
            _, _, u, _ = chat_stream(GATEWAY, key, dict(payload, max_tokens=1))
            return u.get('prompt_tokens')
        bare = {'model': 'ultron', 'messages': [{'role': 'system', 'content': model['system']}, {'role': 'user', 'content': 'Hi'}]}
        res['prompt_tokens_no_tools'] = toks(bare)
    except Exception as e:  # noqa: BLE001
        log('token split failed', e)
    return res


def task_level(ctx, reps=3):
    key = ENV['OPENAI_API_KEY']
    probe = LogProbe()
    tasks = {'title': [ctx['tasks']['title']], 'tags': [ctx['tasks']['tags']], 'follow_up': ctx['tasks']['follow_ups'],
             'follow_up_think': ctx['tasks']['follow_ups'][2:]}
    res = {}
    for name, prompts in tasks.items():
        rows = []
        for i in range(reps):
            for p in prompts:
                probe.wait_idle(quiet=1.5); m0 = llama_metrics(); probe.mark()
                wall, obj = chat_once(GATEWAY, key, {'model': 'ultron-think' if name == 'follow_up_think' else 'ultron', 'messages': [{'role': 'user', 'content': p}],
                                                     **({'max_tokens': 1000} if name == 'title' else {})})
                probe.wait_idle(quiet=1.0); m1 = llama_metrics()
                u = obj.get('usage', {})
                rows.append({'wall_s': wall, 'gpu_s': gpu_seconds(m0, m1), 'prompt_tokens': u.get('prompt_tokens'),
                             'completion_tokens': u.get('completion_tokens'),
                             'out': (obj['choices'][0]['message'].get('content') or '')[:120]})
        res[name] = {'gpu_s': med([r['gpu_s'] for r in rows]), 'wall_s': med([r['wall_s'] for r in rows]),
                     'prompt_tokens': med([r['prompt_tokens'] for r in rows]),
                     'completion_tokens': med([r['completion_tokens'] for r in rows]),
                     'sample_output': rows[0]['out'], 'runs': len(rows)}
        log(f'task {name}: gpu {res[name]["gpu_s"]} s')
    return res


def cache_effect(ctx, reps=4):
    """TTFT of the next chat message right after a chat message, versus right after a background task."""
    model = ctx['models']['ultron']
    key = ENV['OPENAI_API_KEY']
    probe = LogProbe()
    out = {}
    for name, prompt in (('follow_up', ctx['tasks']['follow_ups'][2]), ('tags', ctx['tasks']['tags'])):
        direct, after = [], []
        for i in range(reps):
            chat_stream(GATEWAY, key, build_payload(model, '', ONE_LINERS[i]))      # reply 1 leaves the prefix in the slot
            probe.wait_idle(quiet=1.0)
            t, _, u, _ = chat_stream(GATEWAY, key, build_payload(model, '', ONE_LINERS[i + 4]))  # message 2 straight away
            direct.append(t); probe.wait_idle(quiet=1.0)
            chat_once(GATEWAY, key, {'model': 'ultron', 'messages': [{'role': 'user', 'content': prompt}]})  # background task
            probe.wait_idle(quiet=1.0)
            probe.mark()
            t, _, u, _ = chat_stream(GATEWAY, key, build_payload(model, '', ONE_LINERS[i + 8]))  # message 2 after the task
            after.append(t); probe.wait_idle(quiet=1.0)
            r = probe.read()
            out.setdefault(name + '_processed_tokens', []).append(r[0]['prompt_tokens_processed'] if r else None)
        out[name] = {'ttft_next_message_direct_s': med(direct), 'ttft_next_message_after_task_s': med(after)}
        log(f'cache effect {name}: {out[name]}')
    return out


def chat_level(ctx, n=5):
    key = ENV['ULTRON_API_KEY']
    probe = LogProbe()
    res = {'runs': []}
    for i in range(n):
        probe.wait_idle(quiet=2.0); probe.mark(); m0 = llama_metrics()
        payload = {'model': 'ultron', 'max_tokens': 40, 'session_id': 'bench-' + uuid.uuid4().hex[:6],
                   'features': {'memory': True, 'web_search': True},
                   'background_tasks': {'follow_up_generation': True},
                   'messages': [{'role': 'user', 'content': ONE_LINERS[i % len(ONE_LINERS)]}]}
        try:
            ttft, total, usage, kind = chat_stream(OWUI, key, payload, '/api/chat/completions')
        except urllib.error.HTTPError as e:
            return {'error': f'HTTP {e.code} from Open WebUI: {e.read()[:200].decode("utf-8", "replace")}'}
        probe.wait_idle(quiet=4.0, limit=90); m1 = llama_metrics()
        reqs = probe.read()
        res['runs'].append({'ttft_s': ttft, 'total_s': total, 'prompt_tokens': usage.get('prompt_tokens'),
                            'llama_requests': len(reqs), 'gpu_s': gpu_seconds(m0, m1)})
    res['ttft_s'] = med([r['ttft_s'] for r in res['runs']])
    res['llama_requests_per_turn'] = med([r['llama_requests'] for r in res['runs']])
    res['gpu_s_per_turn'] = med([r['gpu_s'] for r in res['runs']])
    res['prompt_tokens'] = med([r['prompt_tokens'] for r in res['runs']])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--ctx-file', default='')
    a = ap.parse_args()
    result = {}
    if a.ctx_file and os.path.exists(a.ctx_file):
        ctx = json.load(open(a.ctx_file, encoding='utf-8'))
    else:
        log('reading prompts and tool schemas from Open WebUI (about 30 s)')
        ctx = docker_py('bench-assistant-container.py', {'CALENDAR_MCP_API_KEY': ENV.get('CALENDAR_MCP_API_KEY', '')})
        if a.ctx_file:
            json.dump(ctx, open(a.ctx_file, 'w', encoding='utf-8'))
    result['context_notes'] = ctx.get('notes')
    result['memory_tool_present'] = 'add_memory' in ctx['models']['ultron']['tool_names']
    result['model'] = model_level(ctx, a.runs)
    result['tasks'] = task_level(ctx)
    st = ctx.get('settings', {})
    t = result['tasks']
    on = lambda k: 1 if st.get(k) else 0  # noqa: E731
    result['task_settings'] = {'follow_ups': bool(st.get('task.follow_up.enable')), 'tags': bool(st.get('task.tags.enable')),
                               'title': bool(st.get('task.title.enable')),
                               'memories_background_review': bool(st.get('memories.background_review.enable'))}
    # background GPU seconds in a 3-turn chat as the settings stand: follow-ups after every reply, tags and title once
    for label, fu in (('ultron', 'follow_up'), ('ultron_think', 'follow_up_think')):
        result['task_settings']['gpu_s_per_3_turn_chat_' + label] = round(
            3 * on('task.follow_up.enable') * t[fu]['gpu_s'] + on('task.tags.enable') * t['tags']['gpu_s']
            + on('task.title.enable') * t['title']['gpu_s'], 2)
    result['cache_effect'] = cache_effect(ctx)
    if ENV.get('ULTRON_API_KEY'):
        result['chat'] = chat_level(ctx)
    else:
        result['chat'] = {'skipped': 'ULTRON_API_KEY missing'}
    try:
        result['voice'] = docker_py('bench-voice-container.py')
    except Exception as e:  # noqa: BLE001
        result['voice'] = {'error': str(e)[:300]}
    json.dump(result, open(a.out, 'w', encoding='utf-8'), indent=1)


main()
