# Stage S3 — Character masters
**Purpose:** Write each character's look line and make full-body reference images (front, three-quarter, side, back) and an expression sheet on a plain background.
**When:** Season gate 3. After the user approved the style lock (S2).
**Inputs:** `bible.json`: `style_block`, each character's rough description; `style.json` (model, size, steps, CFG).
**Output:** Per character, in `characters/<name>/`: `look.txt` (the look line, also saved to `bible.json` as `look`), `front.png`, `three_quarter.png`, `side.png`, `back.png`, and `expr_happy.png`, `expr_sad.png`, `expr_angry.png`, `expr_surprised.png`, `expr_scared.png`, `expr_thinking.png`. Each image has a `.txt` beside it with prompt, seed, template. One view per image, never several views in one image.
**Tool:** Front master: the chosen text-to-image template from S2 (`comfy.py run <t2i template> prompt=... width=... height=...`). Other views and expressions: `comfy.py run qwen_edit image=characters/<name>/front.png prompt="..." megapixels=1.0`.

## Prompt formula
**A. Look line (25–45 words, fixed feature order):** `Name, a N-year-old noun, build, eyes, skin marks, hair (colour first, then shape), top with colour and "no print", legwear, shoes (with colour of laces or soles)`.

**B. Front master, text-to-image (70–110 words), slots in order:** style block; "Full-body character reference, front view, standing straight, arms relaxed at the sides, feet visible, head to shoes in frame, vertical 9:16 frame"; the look line word for word; "neutral calm expression, looking at the viewer"; "plain flat light-grey background, soft even studio light, only a small soft contact shadow under the feet, no props, no text".

**C. Other views, qwen_edit (30–70 words), slots in order:** turn instruction; keep list; framing ("full body from head to shoes in frame"); background ("plain flat light-grey background, soft even studio light").

## Rules
1. Keep the look line in the fixed feature order and never reorder it. Reason: the same order makes every later prompt comparable and easy to copy.
2. Give every clothing item a colour, and write "with no print" on tops. Reason: models invent prints and logos, and the text comes out garbled.
3. Choose features that stay visible at a distance: hair colour and shape, one colour per garment, shoe colour. Reason: tiny details (a necklace, a watch) drift between shots.
4. One outfit per look line. Reason: a second outfit is a second character master.
5. Always write "full body, head to shoes in frame, feet visible". Reason: a half-body source made the model invent legs and shoes (test finding).
6. Use "plain flat light-grey background" in every master. Reason: it cuts out easily and later edits do not copy a scene into the keyframe.
7. Make the front view first and get it approved before the others. Reason: every other view is edited from it.
8. Make three-quarter, side, back and expressions with `qwen_edit` on the front image, not with new text-to-image runs. Reason: edits keep identity; fresh generations give a new face.
9. Write the turn as a direct instruction ("Rotate the character to a full side profile view, facing left") and then a keep list ("Keep the same face, hair, outfit, colours and proportions"). Reason: Qwen edit prompts work best as direct, specific instructions that state what stays.
10. Write everything positively ("plain light-grey background"). Reason: `qwen_edit` runs at CFG 1.0, so the negative prompt is ignored.
11. For the back view write "seen from behind, the back of the head and the back of the hoodie visible, face not visible". Reason: the model otherwise shows the face.
12. Make the expression sheet as 6 separate `qwen_edit` runs with "only change the facial expression". Reason: six faces in one image drift apart; single images can be redone one at a time.
13. Do not ask for a multi-view turnaround sheet in one image. Reason: not tested on our models and the model may alter each pose **[verify]**.
14. Save prompt, seed and template beside every image. Reason: studio rule 10.

## Worked example
Weak: `a boy with orange hair, turnaround`

Look line (about 32 words), saved to the bible:
```
Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces
```
Front master prompt (text-to-image):
```
3D animated feature film still, stylized cartoon proportions, large expressive eyes, soft rounded shapes, smooth clean materials, warm soft global illumination, gentle shadows, rich saturated colors, simple clean textures, shallow depth of field. Full-body character reference, front view, standing straight, arms relaxed at his sides, feet visible, head to shoes in frame, vertical 9:16 frame. Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces. Neutral calm expression, looking at the viewer. Plain flat light-grey background, soft even studio light, only a small soft contact shadow under the feet, no props, no text.
```
Side view (`qwen_edit`, image = `front.png`):
```
Rotate the character to a full side profile view, facing left, standing straight with arms relaxed. Keep the same face, freckles, messy spiky orange hair, olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces, the same proportions and the same colours. Full body from head to shoes in frame. Plain flat light-grey background, soft even studio light.
```
Three-quarter: same text, first sentence replaced by "Turn the character about 45 degrees to his right so he is seen in a three-quarter view, looking slightly past the viewer." Back: first sentence "Show the character from behind, the back of the head and the back of the hoodie visible, face not visible." The rest stays identical.

Expression (`qwen_edit`, image = `front.png`):
```
Only change the facial expression: Milo's eyebrows lift high, his eyes open wide and round, and his mouth opens in a small round surprised shape. Keep the body, pose, outfit, hair, colours and the plain light-grey background exactly the same.
```

## Self-check before asking for approval
- [ ] Look line is 25–45 words, in fixed order, every garment has a colour, no prints or text.
- [ ] Front, three-quarter, side, back are all full body with feet visible.
- [ ] Face, hair, outfit colours and proportions match across all four views (view them in one row).
- [ ] Background is plain light grey in every image.
- [ ] All 6 expressions look like the same character.
- [ ] Prompt, seed and template saved beside each image; look line copied to `bible.json`.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Legs or shoes invented, body cut off | Half-body source or no "feet visible" | Regenerate the front with the full-body slot; edit only from a full-body front | S3 front |
| Hoodie shows a logo or letters | "no print" missing | Add "plain ... with no print"; if it persists, change the garment in the bible | S1 look, then S3 |
| Side view has a different face | Edit prompt too short or no keep list | Add the keep list; retry with a new seed | S3 view |
| Back view shows the face | Instruction too weak | Use the exact back wording (rule 11) | S3 view |
| Floor or shadow pattern appears | Background not specified | Add "plain flat light-grey background, only a small soft contact shadow" | S3 view |
| Small details (laces) change | Details too small to hold | Enlarge them in the look line, or drop them | S1 look |
| Image looks photoreal | Wrong text-to-image model | Return to S2 | S2 |

**Template needed:** none for S3. (`qwen_edit` with 2–3 input images would allow "use this front image for identity and this one for style" but the current template takes one image.)

## Sources
- https://huggingface.co/Qwen/Qwen-Image-Edit-2511 (identity preservation, new viewpoints listed as a use)
- https://huggingface.co/Qwen/Qwen-Image-Edit-2509 (facial identity under pose change)
- https://github.com/QwenLM/Qwen-Image (edit rewrite rules: direct specific instructions, preserve identity traits, subtle expression changes)
- https://help.scenario.com/en/articles/generate-character-turnarounds/ (community: fixed description, plain background, named views) **[verify]**
- Local test findings (identity held over two scenes; half-body made legs)
