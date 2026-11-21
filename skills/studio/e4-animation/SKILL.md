# Stage E4 — Animation (motion prompt for Wan 2.2, plus lip-sync)
**Purpose:** Turn each approved keyframe into one 5-second clip by writing a long, ordered motion prompt. **When:** Gate E4, after the user approved E3 (keyframes contact sheet and voice lines). **Inputs:** `episode.json` shot row (action, camera, dialogue, `mouth_on_screen`), the approved keyframe `keyframes/shot-NN.png`, `bible.json` (character look lines, location text), `audio/shot-NN.wav` for lip-sync shots. **Output:** `clips/shot-NN-takeK.mp4` (480×832, 81 frames, 16 fps, silent; lip-sync clips carry the dialogue), plus `clips/shot-NN-takeK.json` with prompt, seed, template, keyframe path. **Tool:** `python3 skills/comfyui/comfy.py run wan22_i2v image=<keyframe> prompt="<text>" seed=<n> width=480 height=832 length=81`. Run one shot at a time (~7.4 min each). Negative prompt is ignored (CFG 1.0): write exclusions in the positive prompt.

The image already carries the look, the scene and the style. The prompt carries **what moves, in what order, how fast, and what the camera does**. Never re-describe the picture at length; never invent new things that are not in the keyframe.

## Prompt formula
Write one paragraph, 100–150 words, slots in this order. Fill every slot.
1. **Subject anchor (15–35 words):** the character's look line from `bible.json`, word for word, then where they are and which way they face, copied from what the keyframe shows. Skip the style block: the keyframe holds the style.
2. **Start state (10–20 words):** the pose in the first frame, so the model starts from the image ("He starts mid-stride, body leaning left").
3. **Action beats (35–60 words):** 1 to 3 beats in time order with "First… then… finally…". Each beat: body part + strong verb + speed word + direction (left/right/toward camera/away from camera). Give each beat about 1.5–2 seconds. One main action per shot.
4. **Secondary motion (10–20 words):** hair, hoodie, laces, leaves, dust, shadows, background elements that already exist in the keyframe.
5. **Camera (8–20 words):** exactly one move, named and with speed: "fixed camera", "slow push-in", "camera tracks left alongside him at his speed", "camera pulls back slowly", "camera tilts up". Say what the framing stays on.
6. **Light (8–15 words):** the light already in the keyframe, stated as steady ("warm morning sunlight stays steady, shadows move with him").
7. **Positive exclusions (10–20 words):** "empty street with no other people, no signs or readable text, same outfit and hairstyle all the way through".

Motion words that work (the model reads plain English verbs): sprints, jogs, strides, hops, stumbles, skids to a stop, turns his head, glances over his shoulder, waves his right arm high overhead, swings both arms, nods twice, shrugs, leans forward, crouches, grabs, points, laughs, blinks. Speed words: quickly, briskly, slowly, smoothly, suddenly, in one fast motion. Intensity words: gently, energetically, with big exaggerated swings.

## Rules
1. **Check the keyframe first.** Open the keyframe and write the facing and pose you actually see. The video keeps the keyframe's facing and framing; a camera-facing keyframe makes the character move toward the camera whatever the prompt says.
2. **If the action needs a direction the keyframe lacks, stop and go back to E3.** Do not try to fix it with words ("runs away from camera" on a front-facing image failed in testing).
3. **Describe motion, not appearance.** The look line is the only appearance text; extra description drifts the identity.
4. **Use time order.** "First… then… finally…" makes beats happen in sequence instead of all at once **[verify: third-party guides]**.
5. **Use strong verbs with speed words.** The 4-step distilled LoRAs tend toward slow, small motion, so "sprints quickly" beats "moves" and "walks".
6. **One main action, one camera move.** Two actions or two camera moves in 5 s smear or get dropped.
7. **Name the direction of every movement** in screen terms (left, right, toward camera, away from camera, up, down).
8. **Anchor the camera to the subject** when it moves: "tracks alongside him", "keeps him centered in frame".
9. **Write exclusions positively.** CFG 1.0 ignores the negative prompt. Say "no other people", "no readable text", "plain clean hoodie".
10. **No signs, screens, book pages, shop fronts or vehicle lettering in view.** Text changes between frames and garbles. If the keyframe has a sign, go back to E3.
11. **Keep the cast to what the keyframe shows.** Say "he is the only person in the shot" to stop stray pedestrians.
12. **Never paraphrase bible text.** Copy look lines and location text verbatim (studio rule 3).
13. **Keep a record.** Save prompt, seed, template, keyframe next to the clip (studio rule 10).
14. **Redo one shot at a time.** Change one thing per retry: seed first, then the prompt (studio rule 2). Maximum 3 takes per shot, then ask the user.
15. **Lip-sync shots:** at most 2 per episode, close-ups only (see Lip-sync section).

## Worked example
Shot 3, Maple Street. Keyframe (approved in E3): Milo seen from the side in a medium-wide shot, facing the left of the frame, mid-stride, leaning forward, right arm raised. The bus is not yet in frame.

**Weak (what failed):**
`the boy runs toward the bus, waving one arm, camera tracks alongside him, morning sunlight`

**Strong (final text sent to `wan22_i2v`):**
```
Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces, seen from the side on the grey asphalt road of a quiet suburban street, facing the left of the frame. He starts mid-stride with his body leaning forward. First he sprints quickly to the left in long fast strides, his right arm waving high overhead. Then, after about two seconds, he glances back over his shoulder toward the camera with a wide grin while still running left. Finally he leans forward and speeds up, both sneakers lifting off the ground between strides. His orange hair bounces and his hoodie flaps behind him, and fallen leaves stir on the asphalt. The camera tracks to the left alongside him at his running speed, keeping him centered in the frame. Warm morning sunlight stays steady and his shadow moves along the road beside him. He is the only person in the shot, the street is empty with no other people, no signs and no readable text, and his outfit and hairstyle stay the same all the way through.
```
Why it works: look line verbatim (identity anchor); direction matches the keyframe; three timed beats; named camera move; the exclusions cover the stray pedestrian and the garbled sign.

**Dialogue shot example (lip-sync, close-up):** keyframe: Milo's head and shoulders, facing the camera, mouth slightly open. Prompt for S2V/InfiniteTalk (short, because the audio drives the face): `Milo, [look line], faces the camera in a close-up and talks to someone just beside the camera. He nods slightly, raises his eyebrows, and blinks naturally. His shoulders move gently as he speaks. Fixed camera, steady warm light, plain background unchanged, no other people.`

## Lip-sync section (Gate E4, shots with `mouth_on_screen: true`)
- **Models (planned, not installed; pick in Stage 2):** Wan 2.2 S2V 14B, or InfiniteTalk on Wan 2.1 I2V 14B 480P. **Template needed:** `wan22_s2v` or `infinitetalk` ComfyUI template does not exist yet. Until it does, say so and mark the shot "lip-sync pending"; never fake it by running `wan22_i2v` on a talking keyframe.
- **Inputs:** the keyframe (reference image), the dialogue wav from S4/E3 (clean speech only, no music), an optional short text prompt.
- **Prompt role:** the audio drives the mouth. The prompt describes head and body behavior, expression and camera only. Do not write the spoken words.
- **Length:** Wan S2V works in 77-frame chunks (about 4.8 s at 16 fps); frames = audio seconds × 16. Keep every lip-sync line at or under 4.5 s of audio (about 10–13 spoken words) so one chunk covers it. InfiniteTalk accepts longer audio but we do not need it.
- **Settings to start with:** S2V with Lightning LoRA: 4 steps, CFG 1.0, but the ComfyUI docs warn the LoRA is not trained for S2V and costs motion and quality, so test the 20-step, CFG 6.0 setting on one clip and keep the faster one only if it looks fine. InfiniteTalk: text guide about 5 and audio guide 3–5 without a speed LoRA; about 1 and 2 with one; audio guide higher gives tighter lip-sync. Low-memory switch: `--num_persistent_param_in_dit 0` or fp8 weights.
- **12 GB fit:** unmeasured **[verify]**. The official README examples assume 80 GB; the ComfyUI S2V template uses fp8 14B weights, and GGUF is not documented **[verify]**. Plan on 2× the time of a normal shot.
- **Cartoon tips:** front or slight three-quarter view; face fills a third or more of the frame; mouth clearly visible and not covered by hands; a neutral, slightly open mouth in the keyframe; stylized characters need large, simple mouth shapes, so ask for "talks clearly with a wide open mouth on stressed words" only if the first take is mumbly **[verify]**; no fast head turns.
- **Check:** play with sound; the mouth must open on loud syllables and close in pauses; if it floats or the identity shifts, redo with another seed, then shorten the line.

## Self-check before asking for approval
- [ ] The prompt is 100–150 words, all 7 slots filled, one paragraph.
- [ ] Look line copied word for word from `bible.json`.
- [ ] Facing and direction in the prompt match the keyframe I looked at.
- [ ] 1–3 timed beats, each with verb, speed and direction.
- [ ] Exactly one camera move, named.
- [ ] No sign, screen, book or lettering in view or in the prompt.
- [ ] Exclusions are written positively; the cast is limited to the keyframe cast.
- [ ] Clip is 81 frames at 480×832; prompt, seed, template saved beside it.
- [ ] Identity, outfit, and hair match the master across all 5 s; no stray people; no morphing hands or feet.
- [ ] Lip-sync shots: at most 2 in the episode; audio at most 4.5 s.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Character moves toward the camera instead of the stated direction | Keyframe faces the camera; video keeps keyframe facing | New keyframe showing the correct facing and lean | E3 |
| Motion is slow or floaty | 4-step distillation; weak verbs | Strong verbs plus "quickly", fewer beats; try another seed; test motion-fix LoRAs (see Template changes) **[verify]** | E4 |
| Only the first beat happens | Too many beats for 5 s | Cut to 2 beats, about 2 s each | E4 |
| Stray pedestrian or extra car appears | Empty space in the keyframe invites invention | "He is the only person in the shot, empty street, no parked or passing people"; or fill the space in the keyframe | E4, then E3 |
| Sign or shirt text flickers | Text in keyframe or prompt | Remove text from keyframe | E3 |
| Face or outfit drifts late in the clip | Long action, big motion, camera too close | Calmer action, wider shot, repeat look line | E4 |
| Hands or legs distort | Fast complex limb motion | Simpler action (one arm wave, not both arms and a jump) | E4 |
| Camera does the wrong thing | Two camera instructions, or vague wording | One move, "fixed camera" if unsure | E4 |
| Lip-sync mouth floats or does not match | Audio too long or noisy; face too small | Shorter line, clean wav, tighter close-up | E3 (new close-up) or E4 |
| Lip-sync template missing | Not built yet | Report "Template needed", skip the shot or reframe as a no-mouth shot | E2 |

## Template changes recommended (not made here)
- `wan22_i2v` is the right base. Add an optional `lora_strength` param only if testing shows it helps; do not lower the 4-step LoRA strength (blurry, broken motion **[verify]**).
- Test the community "motion fix" lightx2v pair (strength 1.0, 4 steps) against the current LoRAs on the Milo run shot **[verify]**.
- Template needed: `wan22_s2v` / `infinitetalk`, audio input param, frames derived from audio length.

## Sources
- Wan 2.2 official repository (prompt extension, S2V inputs, VRAM): https://github.com/Wan-Video/Wan2.2
- Alibaba Model Studio prompt guide (I2V = motion + camera; camera vocabulary): https://help.aliyun.com/en/model-studio/text-to-video-prompt
- Wan 2.2 Lightning (4 steps, no CFG, known issues): https://github.com/ModelTC/Wan2.2-Lightning
- ComfyUI Wan 2.2 S2V docs (77-frame chunks, Lightning warning): https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v
- InfiniteTalk: https://github.com/MeiGen-AI/InfiniteTalk
- Community slow-motion fix LoRAs (not primary): https://huggingface.co/rzgar/Wan2.2_I2V_LightX2V_Slow-Mo_Fix
- Time-order beats, 100–150 word length: third-party guides, e.g. https://www.veed.io/learn/wan-2-2-prompting-guide **[verify]**
