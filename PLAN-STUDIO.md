# Ultron Studio — AI animated story series for Instagram

Plan date: 2026-11-17 (first draft). Builds on the running stack ([PLAN.md](PLAN.md), [PLAN-PHASE2.md](PLAN-PHASE2.md), [README.md](README.md)) and the ComfyUI skill in `skills/comfyui/`.
Items marked **[verify]** come from research not confirmed on a primary source, or are untested on this PC. Nothing in this plan is built yet.

## 1. Goal

A self-hosted pipeline that turns a one-line idea into a finished vertical episode of an animated story series, ready to upload to Instagram Reels, at no cost.

- **Format:** one story series with recurring characters, stylized 3D cartoon look, English dialogue and background music.
- **Control:** you approve every gate from the Open WebUI chat (PC or phone). Nothing moves to the next gate without your sign-off.
- **Volume:** target 2 episodes a day, reached gradually (section 9).
- **Budget:** $0. Local models on this PC first; free cloud tiers or free platform credits only where they help, operated by you where automation would break a platform's terms. Paid final renders are a later decision, only if the optimised local result is too weak.
- **Publishing:** manual upload for now. The pipeline delivers the video, cover image and caption text.
- **Income:** Instagram's built-in payouts first; brand deals later.

## 2. The reference method and what changes here

The reference is the 10-gate method from an AI animator's handbook (public outline only; the PDF itself was not read). Its core rule: **lock every reference before anything moves**, because a mistake fixed in text costs minutes and a mistake found in a render costs renders.

| Gate | Reference tool | Here |
|---|---|---|
| 01 Story blueprint (5 beats) | Text | ULTRON (`ultron-think` or `ultron-agent`) |
| 02 Shotlist | Text | ULTRON, written into a fixed JSON format the runner can execute |
| 03 Style lock | Text file | One style block in the series bible, inserted by code into every prompt, never retyped by the model |
| 04 Character masters | Midjourney | Local image model (section 6) |
| 05 Vehicles and props | Midjourney | Same |
| 06 Location plates | Midjourney | Same |
| 07 Location sheets | GPT Image | `qwen_edit` (Qwen-Image-Edit 2511, installed) combining masters and plates |
| 08 Video | Seedance 2.5: 30 s multi-shot clips with sound, from references | Wan 2.2 image-to-video, **one shot at a time**, 2–5 s, 480p, 16 fps, silent. Lip-sync and audio are separate steps |
| 09 Edit | CapCut, Canva | ffmpeg, scripted (needs installing; not on this PC) |
| 10 Thumbnail and captions | GPT Image | Image model plus ULTRON for caption text |

The biggest difference is gate 08. Seedance makes long multi-shot clips with consistent characters and sound in one pass. Wan on a 12 GB card makes short silent shots from a single start frame. So this pipeline is **keyframe-first**: every shot's start frame is made as a still from the locked masters and approved before any video is rendered. Consistency comes from the stills, not from the video model.

## 3. Honest expectations

| Area | Expected on this PC |
|---|---|
| Story, shotlist, captions | Usable from the local models with a good series bible; you will edit at gate E1–E2 |
| Character consistency in stills | Good with `qwen_edit` and masters as references; better later with a character LoRA |
| Video quality | Clearly below Seedance: 480p source, short shots, occasional morphing. Upscaling and frame interpolation narrow the gap but do not close it |
| Dialogue | Natural-sounding English voices are realistic locally. Lip-sync is heavy on 12 GB and will be limited to a few close-ups per episode |
| Music | Usable background tracks from a local music model |
| Volume | 2 a day fits the measured GPU time; lip-sync speed is still unmeasured (section 9) |

The plan measures early (stages 0–2) whether the look is good enough before building the automation around it.

## 4. Series and episode format

Two changes from the reference method keep 2 episodes a day within reach on one GPU and one reviewer:

1. **Episodes of 20–30 seconds, 4–6 shots of 5 seconds (81 frames).** Shorter than the reference's 53 s film; this length suits Reels, and halves GPU time per post. 81 frames is the standard shot length (decided 2026-11-17: 49-frame clips were not smooth enough). The edit may still cut inside a shot or between two takes of it for a faster rhythm.
2. **Season gates done once, episode gates done per episode.** Characters, voices, locations, style and music are locked once per season and reused by every episode. That is most of the reference method's work, and it stops being a per-post cost.

### Season gates (once per season, or when something new is introduced)

| Gate | Output | Your sign-off |
|---|---|---|
| S1 Series bible | Premise, characters (look, personality, voice description), world, tone, episode formula, hook rules | Text |
| S2 Style lock | Style block, negative prompt, image model and settings, 4 test images | Pick the look |
| S3 Character masters | Per character: full body front, three-quarter, side, plus an expression sheet; plain background | Images |
| S4 Voices | One reference voice clip per character, plus 3 test lines each | Listen |
| S5 Locations and props | Empty location plates under the same light; one master per recurring prop | Images |
| S6 Music palette | Theme track plus 3–4 mood variants (tense, funny, warm, action) | Listen |

### Episode gates

| Gate | Output | Your sign-off |
|---|---|---|
| E1 Story | 5 beats, hook in the first 2 seconds, ending that sets up the next episode | Text |
| E2 Script and shotlist | Per shot (5 s each): location, characters, action, camera, dialogue line, whether the speaker's mouth is on screen | Text table |
| E3 Keyframes and voice lines | One start frame per shot (contact sheet: one image with all shots numbered), all dialogue audio | Contact sheet; redo single shots |
| E4 Rough cut | All shots animated, lip-synced close-ups, joined at low resolution with dialogue | Watch; redo single shots |
| E5 Final | Upscaled, 1080×1920, interpolated frame rate, music under dialogue, burned-in captions | Watch |
| E6 Post pack | Cover image, caption text, hashtags | Text and image |

**Repair, don't re-roll:** every redo targets one shot (or one line of audio) and keeps the rest.

**Dialogue staging rule (enforced in E2):** at most 2 shots per episode show a speaking mouth. Other lines play over wide shots, backs, reactions or off-screen. Lip-sync is the slowest and least reliable step on this hardware.

### Daily rhythm at 2 episodes a day

- **Once a week:** approve the next 14 stories (E1) and shotlists (E2) in one sitting.
- **Each morning (about 15–20 minutes):**
  - Approve the finals (E5–E6) of today's 2 episodes, then upload them.
  - Approve the keyframes (E3) of tomorrow's 2 episodes.
- **Each night:** render video, lip-sync, music and assembly for tomorrow's 2 episodes.

## 5. Design

```
You (Open WebUI, PC or phone)
      │
ULTRON ── creative work and gate approvals (story, shotlist, prompts, captions)
      │
      │  Studio tool (Open WebUI tool, like tools/google_calendar.py)
      │  create series/episode · show gate · approve · redo shot N · status
      ▼
Studio service (host, Python, localhost only)
      │  gate state machine, job queue, render windows
      │  reads/writes the project folders
      ├─► GPU broker (existing) ── unload chat model / free ComfyUI VRAM
      ├─► ComfyUI Desktop :8188 ── image, video, lip-sync, music, upscale templates
      ├─► Audio tools (host Python venv) ── text-to-speech
      └─► ffmpeg ── join, mix, captions, export
```

| Piece | Choice | Why |
|---|---|---|
| Orchestrator | ULTRON for creative and approval steps only | Small local models lose track over long tool chains; and the chat model is unloaded during every render, so it cannot supervise a night of rendering |
| Runner | A deterministic host-side service with a queue | Survives chat sessions, runs overnight, retries, and records every take |
| Chat interface | An Open WebUI tool rather than the sandbox terminal | Works with any of the three model names, and from the phone |
| ComfyUI access | Templates in `skills/comfyui/workflows/` through the same validation as `comfy.py` | Known graphs only; no arbitrary graph submission |
| Text-to-speech | Separate Python venv on the host, not a ComfyUI custom node | Keeps ComfyUI's dependencies untouched; TTS models are small |
| Assembly | ffmpeg | Free, scriptable; captions come straight from the script, so no speech recognition is needed |
| n8n | Not used for now | Only worth adding later for scheduling and auto-posting |

### Project folder (inside the agent workspace, so ULTRON can read it)

```
studio/
  series/<series-id>/
    bible.json          premise, characters, style block, voices, locations, music
    masters/            locked character, prop and location images
    voices/             reference clip per character
    music/              theme and mood variants
    episodes/<nn-slug>/
      episode.json      story, shotlist, gate status, takes per shot, chosen take
      keyframes/  audio/  clips/  rough/  final/  post/
```

Every generated file records its prompt, seed, model and template, so any shot can be re-rendered exactly or varied deliberately.

### Showing work for approval

- Images: contact sheets returned into the chat, so they show on the phone.
- Video: Open WebUI may not play mp4 inside a chat **[verify]**. Fallback: a small read-only review page served by the Studio service and published through Tailscale next to the chat UI, never to the internet.

### GPU scheduling

One model on the GPU at a time, as now. The Studio service calls the broker's *release* before a batch and *reclaim* after it.

| Window | Jobs | Effect on chat |
|---|---|---|
| Night (e.g. 01:00–08:00) | Video, lip-sync, upscale, music for the next day | ULTRON unavailable |
| Daytime, on demand | Keyframes and voice lines for a gate you are reviewing (short) | ULTRON pauses for a few minutes, then reloads |
| Daytime, idle | Text gates (story, shotlist, captions) | Normal chat |

## 6. Model stack

| Job | Model | Status | Disk (approx.) |
|---|---|---|---|
| Image edit, keyframes, location sheets | Qwen-Image-Edit 2511 Q4 + Lightning 4-step LoRA | Installed | — |
| Stylized text-to-image (masters, plates) | Candidates: Qwen-Image Q4 GGUF (shares the installed text encoder and VAE), Z-Image Turbo, or an SDXL 3D-cartoon checkpoint. `RealVisXL` (installed) is photoreal and does not fit the look | Pick in stage 1 **[verify sizes, fit in 12 GB]** | 6–12 GB |
| Image-to-video | Wan 2.2 I2V 14B Q4 + lightx2v 4-step LoRAs | Installed | — |
| First-and-last-frame video (controlled shots) | Same Wan 2.2 I2V models with the first/last-frame node | New template only **[verify node]** | — |
| Lip-sync | Wan 2.2 S2V 14B GGUF, or InfiniteTalk on Wan 2.1 | Pick in stage 2 **[verify fit and speed on 12 GB]** | 10–15 GB |
| Text-to-speech with fixed character voices | Kokoro-82M installed 2026-11-18 (venv `F:/UltronStudio/tts-venv`) as a stopgap; the user judged it clearly less natural than ElevenLabs. Stage 2 runs a blind bake-off on the same lines: Dia (dialogue, laughs and sighs), Orpheus (emotion tags), Chatterbox (voice cloning; reported unmaintained), IndexTTS2 (emotion control). Check each licence for commercial use; F5-TTS weights are reportedly non-commercial. ElevenLabs' free tier is likely non-commercial too | Stage 2 **[verify licences]** | 2–8 GB |
| Music | ACE-Step (native in ComfyUI) | Stage 2 **[verify version and licence]** | 5–8 GB |
| Frame interpolation 16 → 32 fps | RIFE | Stage 3 | < 1 GB |
| Upscale to 1080×1920 | A 2× or 4× upscale model, or ffmpeg scaling | Stage 3 | < 1 GB |
| Sound effects (optional) | MMAudio | Later | 4–6 GB |

Expected new disk use: about 35–50 GB of models plus about 1 GB of working files per episode. F: has 87 GB free; C: has 15 GB, so everything goes on F:.

**Licences to confirm before posting for money [verify]:** Wan 2.2 and Qwen-Image are released under Apache 2.0; check the image checkpoint, TTS, music and lip-sync model licences for commercial use. Clone only voices you have the right to use (your own, or voices generated from scratch), never a real person's.

## 7. Build stages

### Stage 0 — benchmarks (done 2026-11-17 except ffmpeg; results in section 9)

1. Time and record peak VRAM for: `sdxl_txt2img` at 832×1216; `qwen_edit`; `wan22_i2v` at 480×832 with 49 and 81 frames.
2. Note whether the chat model reloads cleanly after each job.
3. Install ffmpeg on the host.

Accept when: every template runs, and the times are recorded in section 9.

### Stage 1 — look test (decides the style)

1. Install 1–2 stylized image models; write a style block.
2. Make one character master (front, three-quarter, side), one location plate.
3. Make 4 keyframes of that character in that location with `qwen_edit`; animate 3 of them.
4. Upscale and interpolate one clip to 1080×1920 at 32 fps.

Accept when: you judge the 3 clips good enough to post. If not, try the next image model or adjust before building anything else.

### Stage 2 — audio test

1. Two character voices with Chatterbox; 5 lines each with different emotions.
2. One lip-synced close-up with each candidate (S2V, InfiniteTalk); record time and VRAM.
3. One 30-second ACE-Step track in the series mood.

Accept when: you pick the voices, the lip-sync model and the music approach.

### Stage 3 — templates and Studio service

1. New ComfyUI templates: stylized text-to-image, first/last-frame video, lip-sync, music, interpolation, upscale.
2. The bible and episode JSON formats, with validation.
3. The Studio service: gate state machine, queue, render windows, broker calls, takes per shot, timeout and retry once.
4. The TTS venv and its wrapper.

Accept when: one episode's E3–E4 run end to end from a hand-written `episode.json`.

### Stage 4 — assembly

1. ffmpeg join with short cross-fades where the shotlist asks for them.
2. Dialogue on top of music, with the music lowered under speech.
3. Captions burned in from the script lines, timed from the audio file lengths, readable at phone size and clear of Instagram's interface areas.
4. Export 1080×1920, H.264, AAC, within Instagram's upload limits **[verify current specs]**.
5. Cover image and caption text (E6).

### Stage 5 — chat interface

1. The Studio tool in Open WebUI: create series, run a gate, show its output, approve, redo shot N with a note, status of the queue.
2. A Studio skill file describing the gate order and rules for the model.
3. The review page for video, if chat playback does not work.

### Stage 6 — pilot season

1. Season gates S1–S6 for one series.
2. Three episodes end to end; record every time and every redo.
3. Ramp: 1 episode a day for a week, then 2 a day if section 9 allows.

### Later (not in scope until the pilot works)

- A character LoRA per main character, trained on the approved masters, if consistency is the weak point **[verify training on 12 GB]**.
- A remote render backend on a free tier (section 8) for overflow.
- Auto-posting through the Instagram API (needs a Professional account linked to a Facebook Page, a Meta developer app, and a public URL for each video). Note that Instagram's licensed music cannot be added through the API.
- Paid final renders, if you decide the local result is too weak.

## 8. Free cloud options (optional, not needed for the pilot)

Free tiers change often; each is **[verify]** before use.

| Option | Use | Limits and caveats |
|---|---|---|
| Modal | ComfyUI on larger GPUs through an API, for higher-resolution finals | Monthly free credit on the starter plan; runs out after a few GPU hours |
| Kaggle notebooks | Headless batch renders started through the Kaggle API | Weekly GPU quota; older GPUs, not faster than the 3060 |
| Hugging Face ZeroGPU Spaces | Occasional single jobs | Very small daily quota |
| Free credits on Kling, Hailuo, Seedance-based sites and similar | Hero shots, done by you in the browser | Web-only; automating these sites would break their terms |
| Google Colab free tier | Not used | Its terms restrict unattended use |

## 9. Throughput budget

### Stage 0 benchmarks (measured 2026-11-17, ComfyUI 0.45.5, RTX 3060 12 GB, 32 GB RAM)

Each job ran through `comfy.py` with the GPU broker (chat model unloaded before, ComfyUI VRAM freed after). "First run" includes loading models from disk; "repeat" has them in the Windows file cache.

| Job | First run | Repeat | Peak VRAM | Peak system RAM in use |
|---|---|---|---|---|
| `sdxl_txt2img` 832×1216 | 39 s | 31 s | 9.4 GB | 18.0 GB |
| `qwen_edit` (one keyframe, ~1 MP) | 130 s | 82 s | 11.6 GB | 30.3 GB |
| `wan22_i2v` 480×832, 49 frames (3 s) | 267 s | — | 11.0 GB | 31.7 GB |
| `wan22_i2v` 480×832, 81 frames (5 s) | 444 s | — | 10.9 GB | 31.8 GB |

- Wan cost is linear in length: about **5.4 s per frame, or about 87 s of GPU per second of video**.
- **System RAM is the binding limit**, not VRAM: Qwen edit and Wan use nearly all 32 GB. Nothing else heavy should run during a render window.
- Quality notes from the test shots:
  - The character's identity held across two `qwen_edit` scenes and across 5 s of Wan video.
  - Text and logos come out garbled ("SCHOK BUS"). Rule: no text or logos on characters; keep signs out of shots.
  - Wan kept the keyframe's facing: asked to run "toward the bus" from a keyframe facing the camera, the character ran toward the camera. Keyframes must already set up the action's direction.
  - A half-body master made the model invent legs and shoes per shot. Masters must be full body.

### Per-episode estimate (5 shots of 81 frames, 2 with lip-sync, about 25 s)

| Step | Basis | GPU time |
|---|---|---|
| Keyframes: 5 shots × 1.5 takes | 7.5 × ~85 s, plus one cold load | ~12 min |
| Voice lines | Small models, can run on the CPU | ~0 GPU |
| Video: 3 shots × 1.5 takes, 81 frames | 4.5 × 7.4 min | ~33 min |
| Lip-sync: 2 shots × 1.5 takes, 5 s | Unmeasured; assumed 2× a Wan shot (~15 min) | ~45 min **[verify in stage 2]** |
| Music | Unmeasured | ~5 min **[verify]** |
| Interpolate, upscale, assemble | Unmeasured | ~15 min **[verify]** |
| **Total** | | **~1.8 h** |

**Go/no-go for 2 episodes a day:** total GPU time for 2 episodes must fit inside a 7-hour night window with 1 hour to spare. At ~3.6 h for two, the measured parts pass; the lip-sync measurement in stage 2 decides it.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Local video quality too low to grow an audience | Stage 1 look test before any building; later, paid or free-credit final renders for key shots |
| Characters drift between shots | Masters as references for every keyframe; short shots; first/last-frame shots; character LoRA later |
| The local model writes weak stories or hooks | Strong series bible and episode formula; you edit at E1–E2; draft stories elsewhere if needed |
| ULTRON unavailable while rendering | Render windows at night; daytime jobs kept short |
| Reach limits on AI or "unoriginal" content | Original characters and stories, not reposted material; label AI content as Instagram requires; consistent series rather than mass output |
| Payout programmes not open to this account or country | Check *Professional dashboard → Monetization* early; cross-post to Facebook |
| Third-party ComfyUI custom nodes (lip-sync, interpolation) run arbitrary code | Install only widely used nodes, pin versions, update ComfyUI first, keep it on localhost |
| Disk fills up | Keep only the chosen take of each shot after an episode is posted |

## 11. What needs you

| Stage | Needs you |
|---|---|
| 0 Benchmarks | Start ComfyUI Desktop on port 8188 |
| 1 Look test | Judge the look; choose the image model |
| 2 Audio test | Choose voices, lip-sync model, music |
| 3–5 Build | Admin login to install the Studio tool in Open WebUI |
| 6 Pilot | The series idea (or approve one ULTRON proposes); every gate sign-off; uploads |
| Any time | Check payout eligibility in the Instagram app |

## 12. Results so far (2026-11-18)

### Style
- The first look (SDXL front image restyled to 3D cartoon by `qwen_edit`) was rejected by the user as generic and ugly. The reference animator's look is painterly 2D anime-film illustration (gouache texture, flat shading, elongated fashion proportions), not 3D cartoon.
- **Masters now come from ChatGPT image generation (free tier, done by hand by the user)** from prompts in the series' `MASTER-PROMPTS.md`. ChatGPT clearly beat Gemini on painterly texture. Cast sheet, turnarounds and one 9:16 scene of the new leads (Theo, Celine) are in `Ultron-Workspace/studio/series/test-saturday/masters/`.

### Video: same style, three engines
| Shot | Dreamina (Seedance, free tier, by hand) | Local Wan 2.2 (Q4, 4-step, 480p) |
|---|---|---|
| Theo alone, hand through hair, laugh, push-in | Excellent: style, identity and every beat kept. 1280×720 landscape, visible "Dreamina AI" watermark, has an audio track | Unfair test (tall master cropped, head cut off early); face drifted to a generic younger face |
| Theo and Celine walking on the rooftop, full body | Not tested | **Good:** style and both identities stable, natural walk, beats followed; camera move barely happened. 6.6 min per take |

- Local `qwen_edit` keyframes keep identity but lose the gouache texture (they come out as clean webtoon) and ignore framing such as "waist up".
- Working split: ChatGPT for masters and key frames; local Wan for medium and wide shots; Dreamina credits for close-ups, faces and hero shots. Open: Dreamina's daily free allowance, a 9:16 output option and where its watermark sits.
- Finishing pipeline proven on one clip: RIFE 16→32 fps (12 s), Lanczos upscale to 1080×1920, light grain.
