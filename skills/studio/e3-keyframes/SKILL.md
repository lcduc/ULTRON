# Stage E3 — Keyframes
**Purpose:** Make one start image per shot, with the character already facing and posed for the action, and review them on one contact sheet.
**When:** Episode gate 3. After the user approved the shotlist (E2).
**Inputs:** `episode.json` shot table (location, characters, action, camera, direction of motion); `bible.json` (`style_block`, character `look`, location `description`); `characters/<name>/*.png` masters; `locations/<id>/plate.png`.
**Output:** `episodes/<ep>/keyframes/shot_<NN>.png` (9:16) plus `shot_<NN>.txt` (prompt, seed, template, input images); `contact_sheet.png` with numbered shots. `episode.json` gets `keyframe` path per shot.
**Tool:** Today: `comfy.py run qwen_edit image=<character master or plate> prompt="..." megapixels=1.0` (one input image, about 85 s each). **Template needed:** `qwen_edit` with 2 input images (character master as image 1, location plate as image 2). The node supports it, our template does not.

## Prompt formula
Two routes. Route B is the one to use today.

**Route A (needs the 2-image template), 70–120 words, slots in order:** (1) "Picture 1 is the character, Picture 2 is the location" **[verify wording; the model card only refers to subjects by description]**; (2) placement: "Place [Name] from Picture 1 into the scene of Picture 2"; (3) shot size and angle; (4) character look line, word for word; (5) pose, facing, expression, position in frame; (6) light matching the plate; (7) "keep the character's face, hair and clothes exactly as in Picture 1 and keep the location as in Picture 2"; (8) positive exclusions.

**Route B (one image, today), 70–120 words:** use the character master as the input and write the location in words: (1) shot size, angle, 9:16; (2) "Change the background to" + the bible location line word for word + time of day and light; (3) pose, facing and position in frame; (4) look line word for word; (5) keep list: "keep the face, freckles, hair, hoodie and sneakers exactly the same"; (6) positive exclusions: "empty street, no other people, no text".

## Rules
1. Start from the character master, never from the previous keyframe. Reason: edits of edits lose identity.
2. Copy the look line and location line word for word from the bible. Reason: studio rule 3.
3. Write the pose as a freeze-frame of the first moment of the action, with facing direction ("facing left, body leaning forward, left foot lifted"). Reason: the video model keeps the keyframe's pose and facing and builds the action from it (test finding).
4. Facing equals direction of travel in the shotlist. A character who runs left faces left in the keyframe. Reason: a wrong-way start gives a turn-around in the video, or none.
5. Compose for 9:16: subject centred or on one third, leave the empty side in the direction of travel ("open space on the left"). Reason: room to move in; the video model does not move the camera on its own.
6. Keep head-to-shoes in frame for full-body shots, and say so. Reason: cropped bodies get legs invented.
7. Keep to one or two characters per shot. Reason: more characters mix their looks.
8. Give light direction that matches the location plate ("low sun from the right"). Reason: all shots of a location must match.
9. No text, signs, or logos; write "plain hoodie with no print" and "no signs". Reason: text is garbled.
10. Do not use words for mood alone ("dramatic"); say what the face and body do ("eyebrows raised, mouth open"). Reason: undrawable words are ignored.
11. Never ask for motion blur or "running animation". It is a still frame. Reason: blur carries into the video.
12. Make all keyframes, then build the contact sheet (one image, shots in a row, number on each; no helper exists yet, ask the user or the Studio service to assemble it) and show it once. Reason: studio gate rule 1; the user judges the set.
13. Redo only the rejected shots, with a new seed and one changed slot. Reason: repair, don't re-roll.
14. Record prompt, seed, template and input image beside each keyframe. Reason: studio rule 10.

## Worked example
Shot: Milo runs to the left along Maple Street to catch the bus, medium-wide, morning.
Weak: `a boy running to the bus`

Strong prompt, Route B (`qwen_edit`, image = `characters/milo/front.png`):
```
Change the background and pose. Medium-wide shot, eye level, vertical 9:16 frame, Milo seen full body from head to shoes in the centre-right of the frame with open space on the left. Setting: a quiet suburban street of red-brick houses with white window frames, green lawns and young trees, wide grey asphalt road, parked cars along one side, mid-morning, clear sky. Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces, is caught in the first stride of a run, facing left in side view, body leaning forward, left leg lifted and bent, right arm swinging forward, eyes wide and mouth open in an urgent shout. Low sun from the right, soft shadows falling to the left. Keep his face, freckles, hair, hoodie, jeans and sneakers exactly the same as the input image. The street is empty: no other people, no signs, no text, no logos.
```
(about 150 words; the prompt can run longer than the 120 target when the look and location lines are long. Do not cut the bible lines to shorten it.)

Route A version differs only in slots 1–2 and 7: `Picture 1 is Milo, Picture 2 is the street. Place Milo from Picture 1 into the street of Picture 2. ... Keep Milo's face, hair and clothes exactly as in Picture 1 and the street exactly as in Picture 2.`

## Self-check before asking for approval
- [ ] Every shot has a keyframe at 9:16 with prompt/seed/template saved.
- [ ] Facing direction matches the shotlist's direction of travel in every shot.
- [ ] Pose shows the start of the action, not the middle or end.
- [ ] Character looks match the masters in face, hair and clothes colours (compare with the front master).
- [ ] Location, light direction and time of day match the plates and each other.
- [ ] No text, logos, extra people, missing legs or extra fingers.
- [ ] Contact sheet is one image with shot numbers, in shot order.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Face or hair differs from master | Start image was not the master, or keep list missing | Restart from the master; add the keep list | E3 shot |
| Character faces the wrong way | Facing not written | Add "facing left in side view" and the leaning; fix in this shot only | E3 shot |
| Legs or shoes invented or cut off | Full-body slot missing | Add "full body from head to shoes in frame"; use a full-body master | E3 shot |
| Background is the grey of the master | Background instruction too weak | Start with "Change the background to"; describe the location in full | E3 shot |
| Location looks different between shots | Route B describes it only in words | Request the 2-image template; keep the line word for word | E3, then template |
| Garbled text on a bus or sign | Prompt mentions sign, bus lettering | Remove; add "no text" (the bus side stays blank) | E3 shot |
| Video later shows the wrong action | Keyframe pose static or neutral | Redo keyframe with the action's first-moment pose | E3 shot, then E4 |
| Edit looks soft or off after few steps | Lightning 4-step trade-off | Retry with another seed; keep prompts specific **[verify]** | E3 shot |

## Sources
- https://huggingface.co/Qwen/Qwen-Image-Edit-2511 (multi-image list input, multi-person consistency, drift reduction)
- https://huggingface.co/Qwen/Qwen-Image-Edit-2509 (best with 1–3 input images; person+scene combination; pose changes)
- https://github.com/QwenLM/Qwen-Image (rewriting strongly recommended for edits; multi-image prompts say which image each element comes from; "replace Y with X" phrasing)
- https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit (ComfyUI workflow, about 1 MP scaling)
- https://github.com/ModelTC/Qwen-Image-Lightning (2511 has a 4-step LoRA; Edit-specific quality notes absent)
- Local test findings (identity held; facing and pose set the video action; half-body invents legs)
