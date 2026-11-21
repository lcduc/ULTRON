# Stage S4 — Voices
**Purpose:** Give every speaking character one fixed, distinct English voice, as a reference clip plus settings per emotion. **When:** Gate S4, after the user approved S3 (character masters); also when a new speaking character is introduced. **Inputs:** `bible.json` characters (age, personality, `voice_description`), approved masters. **Output:** `voices/<character>.wav` (reference clip, mono, 24 kHz or higher, 8–15 s), `voices/<character>-test-N.wav` (3 test lines), and a `voice` object in `bible.json`: `{"ref": "voices/milo.wav", "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "seed": 1234, "notes": "..."}`. **Tool:** Chatterbox TTS in the host Python venv (original English model, `ChatterboxTTS.generate(text, audio_prompt_path, exaggeration, cfg_weight, temperature)`); fallback F5-TTS. **Template needed:** the TTS wrapper and venv do not exist yet (built in Stage 3); until then, write the voice design and test lines and stop.

## Prompt formula
Slots for the **voice design card** (one per character, 60–100 words, goes into `bible.json` as `voice_description`):
1. **Age and sound (10 words):** "a 14-year-old boy, light, slightly husky voice".
2. **Pitch and pace (10 words):** "medium-high pitch, quick pace, rushes when excited".
3. **Energy and personality (15 words):** "eager, curious, a bit anxious, rarely flat".
4. **Accent (5 words):** "neutral American English".
5. **Contrast with the others (15 words):** "higher and faster than Grandpa, lighter than the narrator".
6. **Reference line (30 words):** the exact sentence read for the reference clip, neutral emotion, normal speed, full sentences with varied sounds.
7. **Default settings:** exaggeration, cfg_weight, seed.

Settings per emotion (Chatterbox, starting points; defaults are 0.5 and 0.5). Only the defaults and the advice in the first three rows are from the README; the rest are starting values to tune by ear **[verify]**:
| Emotion | exaggeration | cfg_weight | Note |
|---|---|---|---|
| Neutral, calm | 0.5 | 0.5 | Default |
| Dramatic, expressive | 0.7+ | 0.3 | README advice |
| Fast reference speaker | 0.5 | 0.3 | README: improves pacing |
| Excited, shouting | 0.8 | 0.3 | Higher exaggeration speeds speech up; low cfg slows it down |
| Sad, tired, quiet | 0.35 | 0.5 | Short sentences, commas |
| Worried, nervous | 0.6 | 0.4 | Broken phrases with "..." |
| Funny, playful | 0.65 | 0.4 | Short punchy lines |

## Rules
1. **Make the voice contrast.** Two characters must differ in pitch or pace at once, or the listener cannot tell who talks.
2. **Never clone a real person's voice.** Use your own voice, a consenting person you have recorded, or a voice generated from scratch (below). Legal and platform risk.
3. **Build a voice from scratch like this:** generate the same neutral line 8 times with no reference clip at different seeds and exaggeration 0.4–0.6, pick the best, then use that file as the reference clip. This keeps the voice invented and repeatable **[verify: default voice output quality]**.
4. **Reference clip: 8–15 seconds of clean speech** (the README example uses about 10 s), one speaker, no music, no echo, no breaths cut off, mono, 24 kHz or higher, level around -3 dB peak. Noise and room sound are copied into every line.
5. **Read the reference line in the neutral emotion.** Emotion in the clip leaks into every line; emotion is then added with the settings.
6. **Keep the reference clip in English.** The clip's language and accent carry over (README); English-only here.
7. **Lock the seed and settings per character** in `bible.json`; never change the reference clip mid-season, or the voice drifts.
8. **Generate each line 3 times (3 seeds) and keep the best.** Output varies between runs.
9. **Change emotion with settings and punctuation, not with adjectives in the text.** The model reads the words aloud; "she said angrily" is spoken.
10. **Test with 3 lines per character**: neutral, excited, sad. Ask the user to listen before approving.
11. **Do not use Chatterbox-Turbo tags ([laugh], [cough])** unless the Turbo model is installed **[verify]**; write "Ha!" or "Haha" as text instead.
12. **Every output is watermarked** by Resemble's Perth watermark (imperceptible); do not try to remove it.

### Line-writing rules for TTS (apply in E2/E3)
- 8–13 words per line for a 5 s shot; at most 4.5 s of audio when the mouth is on screen.
- Short sentences, commas for breaths, "..." for hesitation, one "!" at most; never ALL CAPS (spelled out or shouted unpredictably).
- Spell numbers and symbols as words ("twelve", "a quarter past eight"); no emojis, no stage directions in the text.
- Contractions ("I'm", "don't") sound natural; avoid long or invented names; if a name is mispronounced, respell it ("Mye-lo").
- Leave 0.3 s of silence before and after each line in the audio file.

## Worked example
Weak: `Milo voice: kid voice, excited.` Reference clip: a TTS default sentence "hello".

Strong (Milo's card in `bible.json`):
```
voice_description: "Milo is a 14-year-old boy with a light, slightly husky voice, medium-high pitch and a quick pace that rushes when he is excited. He sounds eager, curious and a little anxious, never flat, in neutral American English. He is higher and faster than Grandpa Joe and lighter than the narrator."
reference_line: "Okay, so my name is Milo, and every morning I run to the bus stop on Maple Street, because if I miss it, I have to walk all the way to school, and that takes forever."
voice: {"ref": "voices/milo.wav", "exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "seed": 41872}
test_lines: ["Wait for me!", "I can't believe it, it actually worked!", "I... I think I lost it."]
```
Test line 2 uses exaggeration 0.8, cfg 0.3; line 3 uses 0.35, cfg 0.5. The shot line "Wait! The bus is leaving!" (5 words, 2 s) is the right length for a running shot with no mouth on screen.

## Self-check before asking for approval
- [ ] Each speaking character has a voice card with all 7 slots.
- [ ] Voices differ from each other in pitch or pace.
- [ ] No real person's voice was cloned.
- [ ] Reference clip is 8–15 s, clean, neutral, saved in `voices/`, and the settings and seed are in `bible.json`.
- [ ] 3 test lines per character were generated and play without clicks or cut-offs.
- [ ] All shot lines in `episode.json` are under 13 words and follow the line rules.
- [ ] Template/wrapper status stated honestly if the TTS venv is not built.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Voice differs between lines | Different seed, noisy reference | Fixed reference, 3 seeds, pick best; clean the clip | S4 |
| Speech too fast when excited | High exaggeration speeds delivery | Lower cfg_weight to 0.3, or exaggeration 0.7 | S4 |
| Monotone | Low exaggeration, long sentences | Raise exaggeration to 0.65+, split the line | S4 |
| Reads stage directions aloud | Directions in text | Remove them; use settings | E2/E3 |
| Wrong accent | Reference clip accent leaks | New English reference clip; cfg_weight lower | S4 |
| Mispronounced name | Unusual spelling | Respell phonetically in the TTS text only (captions keep the real spelling) | E3 |
| Chatterbox not installable (retired Aug 2026, unmaintained) or poor quality | Upstream retired **[verify]** | Pin a version; fallback F5-TTS; check its model licence for commercial use (weights reported non-commercial) **[verify]** | S4 |

## Sources
- Chatterbox README (parameters, tips, MIT licence, Perth watermark, retired notice): https://github.com/resemble-ai/chatterbox
- Chatterbox model card: https://huggingface.co/ResembleAI/chatterbox
- Temperature default 0.8, 8–15 s clip, per-emotion values, F5-TTS licence: not confirmed on a primary source **[verify]**.
