"""Runs one Open Terminal tool call inside the sandbox container, the way Open WebUI does.

Reads {"name": <operationId>, "params": {...}} from stdin, finds the route in the terminal's own
/openapi.json, sends path and query parameters where the spec declares them (empty optional query
values are skipped, as in Open WebUI's execute_tool_server) and the rest as the JSON body, and prints
the response as one JSON line. Copied into the container by run_eval.py; uses only the standard
library and the container's own OPEN_TERMINAL_API_KEY, so no key leaves the container.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:8000'
HDR = {'Authorization': 'Bearer ' + os.environ.get('OPEN_TERMINAL_API_KEY', ''), 'X-User-Id': 'eval'}


def call(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return json.dumps({'error': f'HTTP error {e.code}: {e.read().decode("utf-8", "replace")}'})
    except Exception as e:  # connection problems
        return json.dumps({'error': str(e)})


def main():
    spec = json.load(sys.stdin)
    name, params = spec['name'], dict(spec.get('params') or {})
    oa = json.loads(call(urllib.request.Request(BASE + '/openapi.json', headers=HDR), 20))
    route = None
    for path, methods in oa['paths'].items():
        for method, op in methods.items():
            if isinstance(op, dict) and op.get('operationId') == name:
                route = (path, method.lower(), op)
    if not route:
        print(json.dumps({'error': f'No matching route found for operationId: {name}'}))
        return
    path, method, op = route
    query, declared = {}, set()
    for p in op.get('parameters', []):
        declared.add(p['name'])
        if p['name'] not in params:
            continue
        v = params[p['name']]
        if p['in'] == 'path':
            path = path.replace('{' + p['name'] + '}', urllib.parse.quote(str(v), safe=''))
        elif p['in'] == 'query' and v is not None and not (v == '' and not p.get('required')):
            query[p['name']] = v
    url = BASE + path + ('?' + urllib.parse.urlencode(query, doseq=True) if query else '')
    if method in ('post', 'put', 'patch', 'delete'):
        body = {k: v for k, v in params.items() if k not in declared}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method.upper(),
                                     headers={**HDR, 'Content-Type': 'application/json'})
    else:
        req = urllib.request.Request(url, method=method.upper(), headers=HDR)
    # the terminal waits up to 300 s itself; allow a little more
    sys.stdout.write(call(req, 330).strip() + '\n')


if __name__ == '__main__':
    main()
