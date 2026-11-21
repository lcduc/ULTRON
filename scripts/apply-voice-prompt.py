"""Sets Open WebUI's voice-call instructions (Admin Settings -> Interface -> Voice mode prompt)
to scripts/voice-prompt.txt, through the admin API, keeping every other task setting as it is.

    python scripts/apply-voice-prompt.py           # apply
    python scripts/apply-voice-prompt.py --reset   # back to Open WebUI's built-in prompt

Needs ULTRON_API_KEY (an admin's API key) in compose/.env or the environment.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = 'http://127.0.0.1:3000/api/v1/tasks'


def api_key():
    if os.environ.get('ULTRON_API_KEY'):
        return os.environ['ULTRON_API_KEY']
    for line in (ROOT / 'compose' / '.env').read_text(encoding='utf-8').splitlines():
        if line.startswith('ULTRON_API_KEY='):
            return line.split('=', 1)[1].strip()
    sys.exit('ULTRON_API_KEY missing (compose/.env or environment)')


def call(path, key, body=None):
    req = urllib.request.Request(BASE + path, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    key = api_key()
    config = call('/config', key)
    prompt = '' if '--reset' in sys.argv else (ROOT / 'scripts' / 'voice-prompt.txt').read_text(encoding='utf-8').strip()
    config['ENABLE_VOICE_MODE_PROMPT'] = True
    config['VOICE_MODE_PROMPT_TEMPLATE'] = prompt
    after = call('/config/update', key, config)
    print('voice prompt:', 'built-in default' if not after.get('VOICE_MODE_PROMPT_TEMPLATE') else f"{len(after['VOICE_MODE_PROMPT_TEMPLATE'])} chars from voice-prompt.txt")


if __name__ == '__main__':
    main()
