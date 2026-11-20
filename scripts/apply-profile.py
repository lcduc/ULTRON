"""Puts compose/profile.md into the system prompts of ultron, ultron-think and ultron-agent.

    python scripts/apply-profile.py                 apply (or refresh) the profile
    python scripts/apply-profile.py --remove        take the profile block out again
    python scripts/apply-profile.py --profile FILE  use another file (for testing)

The profile goes between <!-- profile:start --> and <!-- profile:end -->, right after the
line "Today is {{CURRENT_WEEKDAY}}, {{CURRENT_DATE}}." Running it again replaces the block,
so it is safe to repeat. If the file is missing nothing is changed. The change is written
into Open WebUI's database inside the container, after a timestamped copy of the database
(webui.db.bak-<time>-profile in the same data folder). Comment blocks (<!-- ... -->) in the
profile file are not sent. The text never changes between messages, so the model server's
prompt cache keeps working; run this again only when the profile changes.
"""
import argparse
import base64
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTAINER = 'ultron-open-webui-1'

REMOTE = r'''
import base64, json, os, re, sqlite3, time
START, END = '<!-- profile:start -->', '<!-- profile:end -->'
ANCHOR = 'Today is {{CURRENT_WEEKDAY}}, {{CURRENT_DATE}}.'
profile = base64.b64decode(os.environ['PROFILE_B64']).decode('utf-8') if os.environ.get('PROFILE_B64') else None
db_path = '/app/backend/data/webui.db'
block_re = re.compile(r'\n?' + re.escape(START) + r'.*?' + re.escape(END) + r'\n?', re.S)

def rewrite(system):
    base = block_re.sub(lambda m: '\n' if m.group(0).endswith('\n') else '', system)
    if profile is None:
        return base
    lines = base.split('\n')
    for i, line in enumerate(lines):
        if line.strip() == ANCHOR:
            lines[i + 1:i + 1] = [START] + profile.strip('\n').split('\n') + [END]
            return '\n'.join(lines)
    raise ValueError('anchor line not found')

c = sqlite3.connect(db_path)
rows = {r[0]: (r[1], json.loads(r[2])) for r in c.execute("select id, name, params from model where id in ('ultron','ultron-think','ultron-agent')")}
new = {}
for mid in ('ultron', 'ultron-think', 'ultron-agent'):
    if mid not in rows:
        print(f'{mid}: model not found, skipped'); continue
    params = rows[mid][1]
    old = params.get('system', '')
    try:
        s = rewrite(old)
    except ValueError as e:
        print(f'{mid}: {e}, skipped'); continue
    if s == old:
        print(f'{mid}: already up to date'); continue
    params['system'] = s
    new[mid] = params
if new:
    ts = time.strftime('%Y%m%d-%H%M%S')
    dst = f'/app/backend/data/webui.db.bak-{ts}-profile'
    d = sqlite3.connect(dst); c.backup(d); d.close()
    print('backup:', os.path.basename(dst))
    for mid, params in new.items():
        c.execute('update model set params=?, updated_at=? where id=?', (json.dumps(params), int(time.time()), mid))
        print(f'{mid}: updated, system prompt is now {len(params["system"])} characters')
    c.commit()
'''


def clean(text):
    out, i = [], 0
    while True:
        s = text.find('<!--', i)
        if s < 0:
            out.append(text[i:])
            break
        out.append(text[i:s])
        e = text.find('-->', s)
        if e < 0:
            break
        i = e + 3
    return '\n'.join(l.rstrip() for l in ''.join(out).strip().splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile', default=os.path.join(ROOT, 'compose', 'profile.md'))
    ap.add_argument('--remove', action='store_true')
    ap.add_argument('--force', action='store_true', help='apply even if [fill in] placeholders remain')
    a = ap.parse_args()

    env = {}
    if a.remove:
        print('Removing the profile block.')
    else:
        if not os.path.exists(a.profile):
            print(f'{a.profile} not found: nothing changed. Copy compose/profile.example.md to compose/profile.md, fill it in, and run again.')
            return 0
        text = clean(open(a.profile, encoding='utf-8-sig').read())
        if not text:
            print('The profile file is empty: nothing changed.')
            return 0
        if '[' in text and not a.force and any(p in text for p in ('[name]', '[what they do', '[other languages]', '[for example')):
            print('The profile still has template placeholders in [brackets]: nothing changed. Fill them in (or delete those lines).')
            return 1
        approx = len(text) // 4
        print(f'Profile: {len(text)} characters (about {approx} tokens).')
        if approx > 300:
            print('Warning: over 300 tokens. It is sent with every message.')
        env['PROFILE_B64'] = base64.b64encode(text.encode('utf-8')).decode()

    cmd = ['docker', 'exec', '-i']
    for k, v in env.items():
        cmd += ['-e', f'{k}={v}']
    cmd += [CONTAINER, 'python3', '-']
    p = subprocess.run(cmd, input=REMOTE.encode(), capture_output=True)
    sys.stdout.write(p.stdout.decode('utf-8', 'replace'))
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode('utf-8', 'replace'))
        return p.returncode
    return 0


sys.exit(main())
