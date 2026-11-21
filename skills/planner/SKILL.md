# Skill: Planner (for tasks of 3 or more steps)

Use this skill when a request needs 3 or more separate steps (generate, then edit, then animate; write, run, fix, and so on). For 1 or 2 steps, skip it and just do the work.

## Rules

1. Always go through the helper: `python3 /home/user/workspace/skills/planner/plan.py <command>`. Do not edit `PLAN.md` by hand; it is rewritten from `plan.json` after every command.
2. Plan first, with at most 6 steps. Write each step as `"do X || done when Y"`, where Y is something you can check with a command (a file exists, a command prints a value).
3. Show the plan to the user in chat, then go on. If the request starts with "plan only", stop here and wait.
4. Work on one step at a time: `start`, do the work, run the check, then `done` or `fail`.
5. A failed step may be retried 2 times with a fix. On the third failure the helper prints `LIMIT`. Then `replan` (at most 2 per task) or stop and `report`.
6. `replan` keeps the finished steps and replaces the rest. Give the reason in one line.
7. Ask the user and wait for an answer before: deleting files, starting a GPU job that will take more than 10 minutes, or installing anything outside the sandbox.
8. If you are unsure where you are (after a long step, or after an error), run `show`.
9. Finish with `report`, then tell the user what is done, what is not, the last error and the suggested next move. Name the output files.

## Commands

| Command | Purpose |
|---|---|
| `plan.py new <slug> --goal "..." --step "do X \|\| done when Y" ...` | Create the plan (1 to 6 steps). Saved in `/home/user/workspace/tasks/<slug>/` |
| `plan.py show` | Print the plan and the next step |
| `plan.py start <n>` | Mark step n as in progress |
| `plan.py done <n> --note "..."` | Step n is finished; the note says what it produced |
| `plan.py fail <n> --error "..."` | Step n failed; counts the retry |
| `plan.py replan --reason "..." --step "..." ...` | Replace the unfinished steps |
| `plan.py report` | Summary to give the user |

The last plan created is the current one, so you do not repeat the slug.

## Example

```
python3 /home/user/workspace/skills/planner/plan.py new bookshop --goal "Rainy bookshop image, then a snowy edit" \
  --step "Generate the rainy image || a new png exists in outputs/" \
  --step "Edit it to a snowy night || a second png exists in outputs/" \
  --step "Report both file paths || paths named in the answer"
python3 .../plan.py start 1
... do the work and check it ...
python3 .../plan.py done 1 --note "outputs/ultron_sdxl_00031_.png"
```
