"""Rewrites compose/.env in the order, sections and comments of compose/.env.example, keeping every value.

- Every variable in your .env keeps its exact value. Variables the example doesn't know are kept in a
  last section, "Other". Settings that are new in the example get the example's default when it is not a
  secret (e.g. CLOUD_PRIORITY, GEMINI_MODEL); new secrets are left empty for scripts\\gen-env.ps1 to fill.
- A backup is written first: compose/.env.bak-<date-time>. Values are never printed.
- The new file is checked before it replaces the old one: same values for every variable, or nothing is written.

    python scripts/tidy-env.py           # rewrite (with backup)
    python scripts/tidy-env.py --check   # only show what would change
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

COMPOSE = Path(__file__).resolve().parent.parent / "compose"
ENV, EXAMPLE = COMPOSE / ".env", COMPOSE / ".env.example"
LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse(path: Path) -> dict:
    """KEY -> raw value text (exactly as written after '='). Later lines win, like docker compose."""
    out = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def is_secret_placeholder(value: str) -> bool:
    return "change-me" in value or "<" in value or value == ""


def build(env: dict) -> tuple[list[str], list[str], list[str]]:
    lines, added, empty = [], [], []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = LINE.match(line.strip())
        if not m:
            lines.append(line)
            continue
        key, example = m.groups()
        if key in env:
            lines.append(f"{key}={env[key]}")
        elif is_secret_placeholder(example):
            lines.append(f"{key}=")
            empty.append(key)
        else:
            lines.append(f"{key}={example}")
            added.append(key)
    known = set(parse(EXAMPLE))
    extra = [k for k in env if k not in known]
    if extra:
        lines += ["", "# ============================================================ Other (not in .env.example)"]
        lines += [f"{k}={env[k]}" for k in extra]
    return lines, added, empty + [f"(kept, not in example) {k}" for k in extra]


def main():
    if not ENV.exists():
        sys.exit(f"{ENV} not found. To create it: scripts\\gen-env.ps1")
    env = parse(ENV)
    lines, added, notes = build(env)
    text = "\n".join(lines).rstrip("\n") + "\n"
    new = {}
    for line in lines:
        m = LINE.match(line.strip())
        if m:
            new[m.group(1)] = m.group(2)
    changed = [k for k in env if new.get(k) != env[k]]
    if changed:
        sys.exit(f"Refusing to write: these values would change: {', '.join(changed)}")
    print(f"{len(env)} variables kept with their values.")
    if added:
        print("Added with their default:", ", ".join(added))
    empty = [n for n in notes if not n.startswith("(kept")]
    if empty:
        print("New and empty (run scripts\\gen-env.ps1 to fill secrets):", ", ".join(empty))
    kept = [n for n in notes if n.startswith("(kept")]
    if kept:
        print("Not in .env.example, kept under 'Other':", ", ".join(k.split(") ")[1] for k in kept))
    if "--check" in sys.argv:
        print("Check only: nothing written.")
        return
    backup = ENV.with_name(f".env.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(ENV, backup)
    ENV.write_text(text, encoding="utf-8", newline="\n")
    print(f"Rewrote {ENV} (backup: {backup.name}).")


if __name__ == "__main__":
    main()
