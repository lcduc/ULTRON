#!/usr/bin/env python3
"""Task planner bookkeeping for the agent. Python 3 standard library only.

Plans live in <root>/<slug>/plan.json (source of truth) and <root>/<slug>/PLAN.md (rendered
from it). <root> is /home/user/workspace/tasks, or $PLAN_ROOT. The skills folder is read-only
in the sandbox, so nothing is written next to this script.

  plan.py new <slug> --goal "..." --step "do X || done when Y" ...   (1 to 6 steps)
  plan.py show [slug]
  plan.py start <n>
  plan.py done <n> [--note "..."]
  plan.py fail <n> --error "..."        3rd failure of a step: LIMIT: replan or stop
  plan.py replan --reason "..." --step "..." ...   keeps finished steps; max 2 per task
  plan.py report
Put --task <slug> before the command to use another plan; otherwise the last one created is used.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.environ.get('PLAN_ROOT', '/home/user/workspace/tasks')
MAX_STEPS = 6
MAX_FAILS = 3        # the third failure of one step ends its retries
MAX_REPLANS = 2
MARK = {'pending': ' ', 'active': '>', 'done': 'x', 'failed': '!', 'dropped': '-'}


def die(msg):
    print('ERROR: ' + msg)
    sys.exit(1)


def slugify(s):
    out = ''.join(c if c.isalnum() else '-' for c in s.lower()).strip('-')
    while '--' in out:
        out = out.replace('--', '-')
    return out[:40] or 'task'


def paths(slug):
    d = os.path.join(ROOT, slug)
    return d, os.path.join(d, 'plan.json'), os.path.join(d, 'PLAN.md')


def current_slug(arg=None):
    if arg:
        return slugify(arg)
    p = os.path.join(ROOT, '.current')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return f.read().strip()
    die('no plan yet. Create one with: plan.py new <slug> --goal "..." --step "do X || done when Y"')


def load(slug):
    _, pj, _ = paths(slug)
    if not os.path.exists(pj):
        die(f"no plan named '{slug}'")
    with open(pj, encoding='utf-8') as f:
        return json.load(f)


def parse_step(text):
    if '||' in text:
        do, check = [x.strip() for x in text.split('||', 1)]
    else:
        do, check = text.strip(), ''
    if not do:
        die('empty step')
    return {'do': do, 'check': check, 'status': 'pending', 'fails': 0, 'last_error': '', 'note': ''}


def line(i, s):
    t = f"[{MARK[s['status']]}] {i}. {s['do']}"
    if s['check']:
        t += f"  (done when: {s['check']})"
    if s['status'] == 'done' and s['note']:
        t += f"  -> {s['note']}"
    if s['status'] in ('failed', 'active') and s['fails']:
        t += f"  [failed {s['fails']}x: {s['last_error'][:120]}]"
    return t


def next_step(p):
    for i, s in enumerate(p['steps'], 1):
        if s['status'] in ('pending', 'active', 'failed'):
            return i
    return None


def render(p):
    out = [f"PLAN {p['slug']}  replans {p['replans']}/{MAX_REPLANS}", f"Goal: {p['goal']}"]
    out += [line(i, s) for i, s in enumerate(p['steps'], 1) if s['status'] != 'dropped']
    for h in p['history']:
        out.append('Replan ' + h)
    n = next_step(p)
    out.append(f'Next: step {n}' if n else 'All steps done. Run: plan.py report')
    return '\n'.join(out)


def save(p):
    d, pj, pm = paths(p['slug'])
    os.makedirs(d, exist_ok=True)
    p['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(pj + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(p, f, indent=1, ensure_ascii=False)
    os.replace(pj + '.tmp', pj)
    with open(pm, 'w', encoding='utf-8') as f:
        f.write('# Plan: ' + p['slug'] + '\n\n' + render(p) + '\n')
    with open(os.path.join(ROOT, '.current'), 'w', encoding='utf-8') as f:
        f.write(p['slug'])


def step_no(p, n):
    if not 1 <= n <= len(p['steps']) or p['steps'][n - 1]['status'] == 'dropped':
        die(f'no step {n}. Steps: 1..{len(p["steps"])}')
    return p['steps'][n - 1]


def cmd_new(a):
    slug = slugify(a.slug)
    if not a.step:
        die('give at least one --step "do X || done when Y"')
    if len(a.step) > MAX_STEPS:
        die(f'at most {MAX_STEPS} steps. Merge steps and try again')
    if os.path.exists(paths(slug)[1]) and not a.force:
        die(f"plan '{slug}' exists. Use another slug, or add --force to overwrite")
    os.makedirs(ROOT, exist_ok=True)
    p = {'slug': slug, 'goal': a.goal, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
         'replans': 0, 'history': [], 'steps': [parse_step(s) for s in a.step]}
    save(p)
    print(render(p))


def cmd_show(a):
    print(render(load(current_slug(a.slug or a.task))))


def cmd_start(a):
    p = load(current_slug(a.task))
    s = step_no(p, a.n)
    if s['status'] == 'done':
        die(f'step {a.n} is already done')
    s['status'] = 'active'
    save(p)
    print(render(p))


def cmd_done(a):
    p = load(current_slug(a.task))
    s = step_no(p, a.n)
    s['status'] = 'done'
    s['note'] = a.note or ''
    save(p)
    print(render(p))


def cmd_fail(a):
    p = load(current_slug(a.task))
    s = step_no(p, a.n)
    s['fails'] += 1
    s['last_error'] = a.error
    s['status'] = 'failed'
    save(p)
    print(render(p))
    if s['fails'] >= MAX_FAILS:
        if p['replans'] >= MAX_REPLANS:
            print('LIMIT: stop and report (step failed 3 times and no replans left). Run: plan.py report')
        else:
            print('LIMIT: replan or stop (step failed 3 times). Run: plan.py replan --reason "..." --step "..."')
    else:
        print(f'Retry step {a.n} with a fix ({MAX_FAILS - s["fails"]} tries left).')


def cmd_replan(a):
    p = load(current_slug(a.task))
    if p['replans'] >= MAX_REPLANS:
        print('LIMIT: stop and report (no replans left). Run: plan.py report')
        return
    if not a.step:
        die('give the new remaining steps with --step "do X || done when Y"')
    kept = [s for s in p['steps'] if s['status'] == 'done']
    if len(kept) + len(a.step) > MAX_STEPS:
        die(f'at most {MAX_STEPS} steps in total ({len(kept)} done already)')
    for s in p['steps']:
        if s['status'] not in ('done', 'dropped'):
            s['status'] = 'dropped'
    p['steps'] = kept + [parse_step(x) for x in a.step]
    p['replans'] += 1
    p['history'].append(f"{p['replans']}: {a.reason}")
    save(p)
    print(render(p))
    if p['replans'] >= MAX_REPLANS:
        print('Note: that was the last replan allowed.')


def cmd_report(a):
    p = load(current_slug(a.task))
    live = [s for s in p['steps'] if s['status'] != 'dropped']
    done = [s for s in live if s['status'] == 'done']
    left = [s for s in live if s['status'] != 'done']
    out = [f"REPORT {p['slug']}: {len(done)} of {len(live)} steps done, {p['replans']} replan(s).", f"Goal: {p['goal']}"]
    for s in done:
        out.append(f"  done: {s['do']}" + (f" -> {s['note']}" if s['note'] else ''))
    for s in left:
        out.append(f"  NOT done: {s['do']}" + (f" (last error: {s['last_error']})" if s['last_error'] else ''))
    for h in p['history']:
        out.append('  replan ' + h)
    out.append('Tell the user: what is done, what is not, the last error, and the suggested next move.')
    print('\n'.join(out))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='plan.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--task', help='plan slug to use instead of the current one')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('new')
    s.add_argument('slug')
    s.add_argument('--goal', required=True)
    s.add_argument('--step', action='append')
    s.add_argument('--force', action='store_true')
    s.set_defaults(f=cmd_new)
    s = sub.add_parser('show')
    s.add_argument('slug', nargs='?')
    s.set_defaults(f=cmd_show)
    s = sub.add_parser('start')
    s.add_argument('n', type=int)
    s.set_defaults(f=cmd_start)
    s = sub.add_parser('done')
    s.add_argument('n', type=int)
    s.add_argument('--note')
    s.set_defaults(f=cmd_done)
    s = sub.add_parser('fail')
    s.add_argument('n', type=int)
    s.add_argument('--error', required=True)
    s.set_defaults(f=cmd_fail)
    s = sub.add_parser('replan')
    s.add_argument('--reason', required=True)
    s.add_argument('--step', action='append')
    s.set_defaults(f=cmd_replan)
    s = sub.add_parser('report')
    s.set_defaults(f=cmd_report)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == '__main__':
    main()
