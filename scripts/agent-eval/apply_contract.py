"""Puts the planning contract (contract.txt) into the ultron-agent system prompt.

    python scripts/agent-eval/apply_contract.py            add or refresh the contract
    python scripts/agent-eval/apply_contract.py --remove   take it out again (back to pure ReAct)
    python scripts/agent-eval/apply_contract.py --print    print the current prompt, no change

The contract goes between <!-- planning:start --> and <!-- planning:end --> at the END of the
prompt, so it sits after the <!-- profile:start/end --> block that apply-profile.py puts right
after the date line. The two scripts do not touch each other's block. The change is written into
Open WebUI's database inside the container after a timestamped copy (webui.db.bak-<time>-planning
in the same data folder). The text is static, so the model server's prompt cache keeps working.
"""
import base64
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONTAINER = 'ultron-open-webui-1'

REMOTE = r'''
import base64, json, os, re, sqlite3, time
START, END = '<!-- planning:start -->', '<!-- planning:end -->'
mode = os.environ['MODE']
text = base64.b64decode(os.environ['TEXT_B64']).decode('utf-8').strip('\n') if os.environ.get('TEXT_B64') else ''
c = sqlite3.connect('/app/backend/data/webui.db')
row = c.execute("select params from model where id='ultron-agent'").fetchone()
params = json.loads(row[0])
old = params.get('system', '')
if mode == 'print':
    print(old); raise SystemExit
block_re = re.compile(r'\n*' + re.escape(START) + r'.*?' + re.escape(END) + r'\n*', re.S)
base = block_re.sub('\n', old).rstrip('\n')
new = base if mode == 'remove' else base + '\n' + START + '\n' + text + '\n' + END
if new == old:
    print('already up to date'); raise SystemExit
ts = time.strftime('%Y%m%d-%H%M%S')
dst = f'/app/backend/data/webui.db.bak-{ts}-planning'
d = sqlite3.connect(dst); c.backup(d); d.close()
print('backup:', os.path.basename(dst))
params['system'] = new
c.execute("update model set params=?, updated_at=? where id='ultron-agent'", (json.dumps(params), int(time.time())))
c.commit()
print(f'ultron-agent: system prompt is now {len(new)} characters')
'''


def main():
    args = sys.argv[1:]
    env = dict(os.environ)
    if '--print' in args:
        env['MODE'] = 'print'
    elif '--remove' in args:
        env['MODE'] = 'remove'
    else:
        env['MODE'] = 'add'
        with open(os.path.join(HERE, 'contract.txt'), encoding='utf-8') as f:
            env['TEXT_B64'] = base64.b64encode(f.read().encode('utf-8')).decode()
    cmd = ['docker', 'exec', '-i', '-e', 'MODE', '-e', 'TEXT_B64', CONTAINER, 'python3', '-']
    r = subprocess.run(cmd, input=REMOTE.encode('utf-8'), env=env, capture_output=True)
    sys.stdout.write(r.stdout.decode('utf-8', 'replace'))
    if r.returncode:
        sys.stderr.write(r.stderr.decode('utf-8', 'replace')[-800:])
        sys.exit(r.returncode)


if __name__ == '__main__':
    main()
