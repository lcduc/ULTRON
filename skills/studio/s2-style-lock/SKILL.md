# Stage S2 — Style lock
**Purpose:** Write the style block, choose the image model and settings, and get the user to pick a look from 4 test images.
**When:** Season gate 2. Start only after the user approved the series bible (S1).
**Inputs:** `bible.json` (premise, tone, characters' rough look, world). `studio/SKILL.md` (example style block).
**Output:** `style.json` in the project folder: `{"style_block": "...", "model": "...", "template": "...", "width": 0, "height": 0, "steps": 0, "cfg": 0, "sample_prompts": [...], "chosen_image": "path", "seed": 0}`. Also the 4 test images in `style/test_1.png` ... `test_4.png`, each with its prompt and seed next to it. Copy the style block into `bible.json` field `style_block`.
**Tool:** `comfy.py run <template> ...` one job at a time. The text-to-image template is **not chosen yet** (see Template needed).

## Prompt formula
The style block is one comma-separated line of 25–40 words. Fill these slots in this order:
1. **Medium:** "3D animated feature film still" (never a studio or film name).
2. **Proportions:** "stylized cartoon proportions, large expressive eyes, soft rounded shapes".
3. **Materials:** "smooth clean materials, simple clean textures".
4. **Light:** "warm soft global illumination, gentle shadows".
5. **Color:** "rich saturated colors" plus the palette mood from the bible.
6. **Lens:** "shallow depth of field".

A test prompt for one image is: **style block + scene** (one character look line, pose, simple setting, light). Target 60–110 words per test prompt. Use the same style block word for word in all four.

## Rules
1. Never name a studio, film, artist or franchise. Describe the look with nouns the model can draw. Reason: own look, no copyright risk, and names pull in unrelated details.
2. Never write the words "photorealistic", "realistic" or "photo" in the block. Reason: they fight the cartoon look; one mixed signal ("photorealistic cartoon") makes the model split the difference.
3. Describe, do not praise. No "beautiful", "stunning", "masterpiece". Reason: undrawable words add nothing.
4. Put exclusions in the positive prompt ("simple clean textures", "no text"). Reason: Z-Image Turbo, Qwen-Image Lightning and `qwen_edit` run without effective CFG, so negative prompts are ignored.
5. Test with one character and one setting, not a crowd. Reason: you are judging the look, not the composition.
6. Use all 4 test prompts with different content: a close face, a full-body action pose, a wide street scene, a night or indoor scene. Reason: a style that only works in daylight close-ups will break later.
7. Use the 9:16 size for tests (see settings). Reason: this is the delivery format.
8. Change only the seed between retries of the same prompt. Reason: you can tell what caused a difference.
9. Present all 4 images side by side with prompt, model and seed. Ask which look to keep, then stop. Reason: studio gate rule 1.
10. After the pick, re-run the chosen prompt once with a new seed to confirm the look repeats. Reason: a lucky seed is not a style.
11. If the user wants a change, edit one slot (for example "softer materials") and redo only that. Reason: repair, don't re-roll.

## Model and settings (candidates, none confirmed for this PC)
| Candidate | Settings from the model card | Notes |
|---|---|---|
| Qwen-Image (GGUF Q4) | 50 steps, CFG 4.0 in the model card; 9:16 is 928x1664 | Best for long prompts and clean text-free scenes. Slow at 50 steps. A Lightning LoRA for fewer steps exists **[verify]** |
| Z-Image Turbo | about 9 steps (8 forwards), CFG 0 (guidance off), 1024-class sizes | Fast. No negative prompt. Prompt language and length advice is community-only **[verify]** |
| Stylized SDXL checkpoint | 28 steps, CFG 5 (our `sdxl_txt2img` defaults) | Uses the existing template and a negative prompt. Short prompts (under 77 tokens matter most) |

Test all that are installed with the same 4 prompts and compare. Qwen-Image and Z-Image like full-sentence descriptions; SDXL likes comma tags.

**Template needed:** `qwen_image_txt2img` and/or `zimage_turbo_txt2img` (UNET GGUF loader, text encoder, VAE, KSampler, 9:16 latent). Until one exists, only `sdxl_txt2img` works, and its default checkpoint (RealVisXL) is photoreal and not suitable. Tell the user which template is missing instead of using RealVisXL.

## Worked example
Weak: `a cartoon boy running to the bus`

Strong test prompt 2 (full-body action), using the example cast:
```
3D animated feature film still, stylized cartoon proportions, large expressive eyes, soft rounded shapes, smooth clean materials, warm soft global illumination, gentle shadows, rich saturated colors, simple clean textures, shallow depth of field. Full-body shot, eye level, vertical 9:16 frame. Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces, runs toward the left of the frame with his body leaning forward, one arm swinging, mouth open in a happy shout, feet off the ground. Setting: a quiet suburban street of red-brick houses with white window frames, green lawns and young trees, wide grey asphalt road, parked cars along one side, morning. Low sun from the right throws long soft shadows to the left. The street is empty. No text, no signs, no logos.
```
(about 120 words. Test prompts 1, 3, 4 change the shot, pose and setting only; the style sentence is identical.)

## Self-check before asking for approval
- [ ] Style block is 25–40 words, one line, no studio names, no "photo" or "realistic".
- [ ] All 4 images use the identical style block text.
- [ ] The 4 images cover close-up, full-body action, wide scene, night or interior.
- [ ] Each image has its prompt, model, steps, CFG and seed recorded.
- [ ] No text or logos appear in any image (zoom in on signs and clothes).
- [ ] The confirm run with a new seed looks like the same style.
- [ ] `style.json` is written and the block is copied into `bible.json`.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Faces look realistic or plasticky | Model is photoreal, or "realistic" in prompt | Remove the word; switch to a stylized model | S2 |
| Style differs a lot between the 4 images | Block too short, or scene text dominates | Lengthen the block with materials and light slots; shorten the scene part | S2 |
| Garbled letters on shirts or signs | Models cannot spell | Add "no text" and remove sign or shirt wording from the scene | S2 |
| Everything looks like a named studio | Style words too generic | Use own nouns: materials, proportions, light, palette | S2 |
| Colors washed out on Lightning or Turbo models | Distilled model drift | Add "rich saturated colors", name 2–3 palette colors | S2 |
| Pick changed later in the season | New look chosen after S3 | Restart S3 for every character | S3 |

## Sources
- https://huggingface.co/Qwen/Qwen-Image (steps 50, CFG 4.0, resolutions, prompt as one detailed description)
- https://github.com/QwenLM/Qwen-Image (enhancer rules: expand detail, state style, under 200 words, positive wording)
- https://huggingface.co/Tongyi-MAI/Z-Image-Turbo (about 9 steps, guidance 0)
- https://fal.ai/learn/devs/z-image-turbo-prompt-guide (community: no negative prompt, avoid mixed style words) **[verify]**
- https://developer.civitai.com/orchestration/recipes/zimage (community: CFG 1 disables negative) **[verify]**
