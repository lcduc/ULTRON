# Stage S6 — Music palette
**Purpose:** Make one theme track and 3–4 instrumental mood variants for the whole season. **When:** Gate S6, after S5 (locations and props) is approved. **Inputs:** `bible.json` (tone, premise, world, character personalities). **Output:** `music/theme.wav`, `music/mood-tense.wav`, `mood-funny.wav`, `mood-warm.wav`, `mood-action.wav` (stereo, 44.1 kHz or the model's native rate, each 40–60 s, loopable-ish with a clean ending), plus `music/palette.json` with tags, seed, duration, template per file. **Tool:** ACE-Step 1.5 in ComfyUI (Template Library → Audio; duration set in the `EmptyAceStep1.5LatentAudio` node, batch size 4–8). **Template needed:** no `ace_step` template exists in `skills/comfyui/workflows/` yet; until it is built (Stage 3), write the tag prompts and stop. Model status: not installed **[verify version in ComfyUI 0.45.5]**.

## Prompt formula
Tags are one comma-separated line (ACE-Step "tags" field), 12–25 tags in this order, then lyrics set to instrumental.
1. **Genre and style (2–3 tags):** "children's cartoon score, playful orchestral pop".
2. **Mood (2–3 tags):** "cheerful, curious, bouncy".
3. **Instruments (3–5 tags):** "pizzicato strings, glockenspiel, marimba, light woodwinds, soft hand claps".
4. **Tempo and rhythm (2 tags):** a number and a feel: "120 bpm, steady groove".
5. **Texture and production (2–3 tags):** "clean mix, warm, light reverb, no vocals".
6. **Role in the video (1–2 tags):** "background music for a short animated video, gentle, leaves room for dialogue".
7. **Lyrics field:** `[inst]` alone (some builds use `[instrumental]`); optional structure `[intro] [verse] [outro]` is not needed for instrumentals **[verify which tag the ComfyUI 1.5 text node honors]**.

Mood variants share slots 1, 3 and 5 with the theme (same instruments) and change slots 2 and 4:
| Variant | Mood tags | Tempo | Dynamics |
|---|---|---|---|
| Theme | cheerful, adventurous, memorable melody | 120 bpm | Full, ends cleanly |
| Tense | suspenseful, mysterious, creeping | 90 bpm | Sparse, low strings, soft pulse |
| Funny | quirky, mischievous, sneaky | 110 bpm | Staccato, bassoon, pizzicato |
| Warm | gentle, tender, hopeful | 80 bpm | Piano, soft strings, slow |
| Action | energetic, driving, chase | 150 bpm | Drums, brass stabs, fast strings |

## Rules
1. **Instrumental only.** Vocals clash with dialogue and cannot be lip-synced; write `no vocals` in the tags and `[inst]` in lyrics.
2. **Keep the mid-range open.** Prefer light instruments and a soft melody; dense mid-range music masks speech (see e5 ducking).
3. **One shared instrument set per season.** Reuse slots 1, 3, 5 so the variants sound like one series.
4. **Generate 40–60 s, not 120 s.** Episodes are 20–30 s; official advice is 90–120 s for consistency and longer needs batches, but short clips cost less; trim and fade in e5. If a 45 s clip is unstable, make 90 s and cut **[verify]**.
5. **Batch 4–8 and pick the best.** The ComfyUI blog says output is inconsistent; choose by listening.
6. **Name tempo as a number** ("120 bpm") and style in plain words; do not name artists or songs (copyright, and the model may imitate).
7. **Record each file's tags, seed, duration and template** in `palette.json`.
8. **Run ACE-Step alone on the GPU;** it needs several GB and system RAM is the binding limit on this PC (PLAN-STUDIO section 9).
9. **Licence:** ACE-Step 1.5 repository is MIT and ACE-Step v1 is Apache-2.0 (commercial use allowed); confirm the model card for the exact weights downloaded and for generated-audio terms **[verify]**. Instagram's licensed music library cannot be added through the API.
10. **Level:** export music files at about -16 LUFS, peak at or below -1 dB; e5 lowers them further under speech.
11. **Do not start the next gate** until the user listened to all variants and approved.

## Worked example
Weak: `happy music for kids cartoon` (no instruments, no tempo, may produce vocals).

Strong, theme for the Milo / Maple Street series:
```
tags: children's cartoon score, playful orchestral pop, cheerful, adventurous, curious, memorable melody, pizzicato strings, glockenspiel, marimba, light woodwinds, soft hand claps, 120 bpm, steady bouncy groove, clean warm mix, light reverb, no vocals, background music for a short animated video, leaves room for dialogue
lyrics: [inst]
duration: 45 s   batch_size: 6   seed: 2026
```
Tense variant: replace slot 2 with `suspenseful, mysterious, creeping`, slot 4 with `90 bpm, slow pulse`, keep the instruments but add `low cellos, sparse`. Warm variant: `gentle, tender, hopeful, 80 bpm`, add `soft piano`.

## Self-check before asking for approval
- [ ] Theme plus the variants requested in the bible exist as files and play without clipping.
- [ ] All tracks are instrumental (no sung or hummed words).
- [ ] All tracks share instruments and production so they sound like one series.
- [ ] Each file is 40–60 s with a clean ending (or a note on how e5 fades it).
- [ ] `palette.json` has tags, seed, duration, template for each file.
- [ ] Licence status stated; **[verify]** items listed for the user.
- [ ] Template status stated honestly if ACE-Step is not yet installed.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Vocals or humming appear | Lyrics field empty or tags suggest song | `[inst]` alone, add `no vocals`, drop "song" | S6 |
| Muddy, busy track | Too many instruments or mid-range heavy | Cut instruments to 3–4, add `sparse, light` | S6 |
| Does not match mood | Tags too generic | Add specific instruments, a bpm, 2 mood words | S6 |
| Tracks sound unrelated | Different instrument sets | Reuse slots 1, 3, 5 | S6 |
| Ending cuts off | Fixed duration | Generate longer and fade out in e5 | S6 / E5 |
| Inconsistent quality between seeds | Known model behavior | Batch 6–8, pick best | S6 |
| Model or node missing | Not installed | Report **Template needed**; do not fake | Stage 3 |

## Sources
- ComfyUI blog, ACE-Step 1.5 (tags, structure markers, 90–120 s advice, batch size, limits): https://blog.comfy.org/p/ace-step-15-is-now-available-in-comfyui
- ComfyUI docs, ACE-Step v1 (comma tags, section tags, Apache-2.0): https://docs.comfy.org/tutorials/audio/ace-step/ace-step-v1
- ACE-Step 1.5 repository (10 s–10 min, MIT, VRAM tiers): https://github.com/ace-step/ACE-Step-1.5
- `[inst]` / `[instrumental]` tag usage: secondary tutorials, https://techtactician.com/local-ai-generated-music-comfyui-ace-step-setup-tutorial/ **[verify]**
