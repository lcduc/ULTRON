# Stage S5 — Locations and props
**Purpose:** Make empty location plates under one lighting setup, one master image per recurring prop, and the description lines that go into the bible.
**When:** Season gate 5. After approved character masters (S3) and voices (S4).
**Inputs:** `bible.json`: `style_block`, `world`, list of locations and recurring props; `style.json`.
**Output:** `locations/<id>/plate.png` (9:16), optional `locations/<id>/plate_reverse.png`, `locations/<id>/desc.txt`; `props/<id>/master.png`, `props/<id>/desc.txt`; each image with a prompt/seed/template `.txt`. Description lines are copied into `bible.json` under `locations[].description` and `props[].description`.
**Tool:** Plates and masters: the chosen text-to-image template from S2 (`comfy.py run <t2i template> prompt=... width=... height=...`). Variants of an approved plate (other angle, other time of day): `comfy.py run qwen_edit image=locations/<id>/plate.png prompt="..."`.

## Prompt formula
**Location plate (90–130 words), slots in order:**
1. Style block, word for word.
2. Shot: "Wide establishing shot, eye level, vertical 9:16 frame", plus where the camera looks.
3. Location description line (20–40 words, from the bible, word for word).
4. Time of day and weather: "mid-morning, clear sky".
5. Light: sun direction and quality: "low sun from the right, long soft shadows to the left".
6. Empty rule: "the street is empty: no people, no animals, no moving vehicles".
7. Free foreground: "open clear ground in the lower middle of the frame".
8. Exclusions: "no signs, no text, no license plates, no logos".

**Prop master (50–80 words):** style block; "A single object on a plain flat light-grey background, centered, whole object in frame, three-quarter view, soft even studio light:"; the prop (shape, size against a hand or knee, two colours, material); "no text, no labels".

## Rules
1. Fix one sun direction and time of day for the whole set. Reason: shots cut together, and mismatched shadows look wrong.
2. Write emptiness as a positive scene ("the street is empty"). Reason: negative prompts do nothing at CFG 1.0 or on Turbo models.
3. Keep the lower third open. Reason: characters are added there in E3, and clutter makes the edit fail.
4. No signs, shop names, license plates, posters or screens. Reason: text comes out garbled. If a story needs one, add it in E5 as an overlay.
5. Use concrete nouns with colours and counts ("red-brick houses with white window frames"). Reason: "pretty suburb" gives a different place every time.
6. Make a second angle only after the first is approved, and make it with `qwen_edit` on the plate ("same street, camera turned to look the other way"). Reason: keeps materials and light.
7. At most 2 plates per location (main and reverse). Reason: every extra plate must stay consistent.
8. Show the whole prop with space around it. Reason: cropped props get completed wrongly.
9. Give held props a size in words ("palm-sized", "as long as a forearm"). Reason: the model has no scale otherwise.
10. Make the bible line by removing time, light and shot words from the plate prompt. Reason: the bible line is reused in shots with different light.
11. Save prompt, seed and template beside each file. Reason: studio rule 10.

## Worked example
Weak: `a street`

Strong plate prompt, Maple Street, morning:
```
3D animated feature film still, stylized cartoon proportions, large expressive eyes, soft rounded shapes, smooth clean materials, warm soft global illumination, gentle shadows, rich saturated colors, simple clean textures, shallow depth of field. Wide establishing shot, eye level, vertical 9:16 frame, the camera looks straight down the road with houses on both sides. A quiet suburban street of red-brick houses with white window frames, green lawns and young trees, wide grey asphalt road, parked cars along one side. Mid-morning, clear blue sky with a few small white clouds. Low sun from the right, long soft shadows falling to the left across the lawns and road. The street is empty: no people, no animals, no moving vehicles. Open clear asphalt in the lower middle of the frame. No signs, no text, no license plates, no logos.
```
Bible description line (used word for word in later shots):
`a quiet suburban street of red-brick houses with white window frames, green lawns and young trees, wide grey asphalt road, parked cars along one side`

Prop master example (bus stop bench):
```
<style block>. A single object on a plain flat light-grey background, centered, whole object in frame, three-quarter view, soft even studio light: a wooden park bench with a curved green-painted metal frame and light pine slats, two seats wide, knee-high. No text, no labels.
```

## Self-check before asking for approval
- [ ] Every plate in the set shows the same sun direction and time of day.
- [ ] No people, animals, signs, text or license plates.
- [ ] The lower middle of each plate is open.
- [ ] Style matches the S2 pick (view a plate beside the S2 image).
- [ ] Each prop is whole in frame on grey, no text.
- [ ] Description lines are 20–40 words, contain no time, light or shot words, and are saved to the bible.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| People or cars appear | Scene implies traffic ("busy") | State "empty" and remove "busy", "bustling" | S5 plate |
| Shadows fall different ways across plates | Sun slot missing | Add the sun slot to every plate and redo the odd one | S5 plate |
| Sign text appears | Prompt mentions shops or signs | Remove those nouns; add "no signs, no text" | S5 plate |
| Reverse angle looks like another place | Generated from scratch | Edit from the approved plate with `qwen_edit` | S5 plate |
| Prop differs between shots | Described by words only | Use the master (see Template needed); add size words | S5 prop |
| Plate too cluttered for characters | Many foreground objects | Add the open-ground slot and reduce items | S5 plate |

**Template needed:** `qwen_edit` takes one image. Placing a prop master or a plate together with a character in one edit needs `qwen_edit` with 2–3 input images (the TextEncodeQwenImageEditPlus node accepts multiple images). That template does not exist yet; until then props appear by description only.

## Sources
- https://huggingface.co/Qwen/Qwen-Image (9:16 is 928x1664; detailed descriptive prompts)
- https://github.com/QwenLM/Qwen-Image (rewrite rules: positive wording, state spatial relations and composition, under 200 words)
- https://huggingface.co/Tongyi-MAI/Z-Image-Turbo (guidance 0, so no negative prompt)
- https://fal.ai/learn/devs/z-image-turbo-prompt-guide (community: constraints go in the positive prompt) **[verify]**
