# Skill: ComfyUI (image generation on this PC)

Use this skill when the user asks to generate, edit or animate images with ComfyUI.

## Rules

1. Always go through the helper: `python3 /home/user/workspace/skills/comfyui/comfy.py <command>`.
   Do not call the ComfyUI API directly and do not install anything into ComfyUI.
2. Run **one job at a time** and wait for it to finish. Each job takes over the GPU:
   the chat model is unloaded while it runs and reloads afterwards.
3. Start with `comfy.py status`. If ComfyUI is not reachable, stop and ask the user to
   start ComfyUI Desktop. Do not retry in a loop.
4. Only use workflows listed by `comfy.py workflows`, and only the parameters each one lists.
5. Model and LoRA names must match `comfy.py models` exactly.
6. If a run fails, read the `error` and `details` fields, fix the parameter that caused it,
   and retry once. If it fails again, report the error to the user.
7. When a run succeeds, tell the user the output file paths from the `files` field and
   display the image.

## Commands

| Command | Purpose |
|---|---|
| `comfy.py status` | Is ComfyUI up, queue length, GPU memory |
| `comfy.py workflows` | Available workflow templates with their parameters |
| `comfy.py models [folder]` | Model files, e.g. `comfy.py models loras` |
| `comfy.py run <workflow> key=value ...` | Run a template. Quote values with spaces: `prompt="a red fox in snow"` |
| `comfy.py upload <file>` | Copy an image from the workspace into ComfyUI's input folder |

Outputs are saved to `/home/user/workspace/outputs/`.

## Typical session

```
python3 /home/user/workspace/skills/comfyui/comfy.py status
python3 /home/user/workspace/skills/comfyui/comfy.py workflows
python3 /home/user/workspace/skills/comfyui/comfy.py run sdxl_txt2img prompt="portrait photo of an old fisherman, golden hour" width=832 height=1216
```

## Chaining workflows (pipelines)

To chain steps, run them one after another and pass the output file of one step as the
image parameter of the next:

```
python3 .../comfy.py run sdxl_txt2img prompt="a woman reading in a cafe"
python3 .../comfy.py run qwen_edit image=outputs/<file from step 1> prompt="make it night time, warm lamp light"
```

## Animating an image (video)

`wan22_i2v` turns one still image into a short mp4 (16 fps). It is slow: expect several minutes
per clip, so run one at a time and tell the user it is working. Describe the motion in the
prompt, not the picture. `length` must be 4n+1 (49 is about 3 s, 81 about 5 s). Use 81 (the default) for finished shots; 49 only for quick tests.
Use `width=832 height=480` for landscape; the default is portrait 480x832.

```
python3 .../comfy.py run sdxl_txt2img prompt="a woman reading in a cafe" width=832 height=1216
python3 .../comfy.py run wan22_i2v image=outputs/<file from step 1> prompt="she turns a page and looks up, slow push-in" length=81
```

## Adding a workflow template

A template is a JSON file in `skills/comfyui/workflows/` with three keys:

- `description`: one line.
- `params`: each parameter maps to one node input: `{"node": "<node id>", "input": "<input name>", "type": "str|int|float|seed|image", ...}`.
  Optional: `required`, `min`, `max`, `choices`, `model_folder` (value must exist in that ComfyUI model folder), `help`.
- `graph`: the workflow exported from ComfyUI with **File > Export (API)**.

The skills folder is read-only inside the sandbox; templates are added on the host.
