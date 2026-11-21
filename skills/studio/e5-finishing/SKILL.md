# Stage E5 — Finishing
**Purpose:** Turn the approved clips, dialogue and music into one 1080×1920 Reels video with captions. **When:** Gate E5, after E4 (all shots animated, rough cut approved). **Inputs:** `clips/shot-NN-takeK.mp4` (chosen takes in `episode.json`), `audio/shot-NN.wav` and each line's start offset, `music/mood-*.wav` chosen per episode, caption text from `episode.json` dialogue. **Output:** `final/episode-NN.mp4` (H.264 + AAC, 1080×1920, 30 fps, MP4, faststart), `final/captions.ass`, `final/finishing.json` (every step and setting). **Tool:** RIFE interpolation (ComfyUI, not yet a template), upscaler (model or ffmpeg), ffmpeg 7.x (not installed on this PC yet **[verify install]**). **Templates needed:** `rife_interpolate` and `upscale` ComfyUI templates do not exist yet. Until they exist, use ffmpeg `minterpolate` and `scale` only if the user accepts lower quality, or stop and report. All ffmpeg commands below are **[verify]**: they are untested here.

## Procedure
Do the steps in this order. Each step reads the previous step's files; keep every intermediate in `rough/`.
1. **Check inputs.** All shots present, 81 frames, 16 fps, 480×832; durations of audio lines known. Stop if a shot is missing.
2. **Trim.** Cut 0–3 frames from the start or end of a clip only if the shotlist says so (a cut inside a shot). Default: no trim.
3. **Interpolate 16 → 32 fps** with RIFE (x2) on every clip at 480×832 (cheaper than interpolating at 1080p). Output `rough/shot-NN-32.mp4`.
4. **Upscale.** Use an upscale model (2×) to 960×1664 if available, then ffmpeg `scale` with Lanczos to height 1920 and center-crop to 1080 wide (480×832 is slightly wider than 9:16, so about 28 px are cropped from the sides). Keep the crop centered on the character. Output 1080×1920 per clip.
5. **Join.** Concatenate clips in shot order, re-encoding to one codec and fps. Use a 0.25 s cross-fade only where `episode.json` says `transition: fade`; otherwise hard cuts. A cross-fade shortens the timeline by its length, so shift all later audio and caption times by the same amount.
6. **Build the dialogue track.** Place each `audio/shot-NN.wav` at its shot start plus 0.4 s (so speech starts after the cut), pad with silence to the full video length. Keep dialogue peaks near -3 dB.
7. **Mix music under dialogue.** Fade music in 0.5 s, fade out the last 1.5 s, trim to the video length. Set music at about -18 dB under the dialogue and use sidechain compression keyed by the dialogue (ratio about 6:1, fast attack about 20 ms, release about 300 ms), so music rises in gaps and dips under speech. Then loudness-normalize the mix to about -14 LUFS, true peak at most -1.5 dB **[verify target]**.
8. **Burn captions.** Generate `captions.ass` from the script lines; time each line from the dialogue start to start plus audio length (exactly the audio durations, no speech recognition). Burn in with the ffmpeg `subtitles`/`ass` filter (libass).
9. **Export.** H.264 (libx264), yuv420p, 30 fps (drop the extra frames from 32 fps with the `fps` filter), CRF about 18 or 10–12 Mbps cap, AAC 192 kbps at 48 kHz, `+faststart`, length at most 90 s (episodes are 20–30 s). Instagram re-encodes to H.264, so do not upload larger than 1080×1920.
10. **Review** with the checklist below and show the user the final file. Do not delete intermediates until the post is made.

### Caption style rules
- **Safe zone:** keep captions inside the center area, clear of the top about 250 px and bottom about 350 px (third-party figures; some sources say the safe area is 1080×1420) **[verify]**. Place the caption block vertically centered near y = 1250 px on the 1920 px frame, bottom edge no lower than y = 1500.
- **Size:** font height at least 56 px (about 4.5 % of video width at 1080 px), bold sans-serif, white fill, 4–6 px black outline plus soft shadow.
- **Length:** maximum 2 lines of 28–32 characters; 3–6 words per caption on fast lines; split a line at a comma or breath.
- **Timing:** each caption stays at least 1.0 s, at most 4 s; no caption crosses a cut unless the speech does.
- **Content:** spoken words only, in the same spelling as the script (not the TTS respelling); no speaker names unless two speakers are hard to tell apart (then a color per character, defined in the bible).
- **Do not** put captions over the character's face or mouth; if they do overlap, move the block up by 150 px for that shot only.

## Rules
1. **Interpolate before upscaling.** RIFE on 480p is faster and gives fewer artifacts than on 1080p.
2. **Upscale to exactly 1080×1920 and crop, never stretch.** Stretching distorts faces.
3. **Use one frame rate end to end.** Mixed rates make audio drift; convert once at export.
4. **Time captions from the audio files, not from guesses.** The script is already the text.
5. **Keep dialogue 12–18 dB above music.** Intelligibility on a phone speaker comes first.
6. **No music with vocals under dialogue** (S6 rule 1).
7. **Never overwrite a source clip.** Write new files to `rough/` and `final/`.
8. **Record every command and setting** in `finishing.json`.
9. **Any change to one shot reruns only that shot's steps, then the join and the mix** (repair, don't re-roll).
10. **Check the first 2 seconds:** hook visible, caption readable, no black frame.

## Worked example
Episode 01 (Milo and the bus), 5 shots, 25 s, music `mood-action.wav`, dialogue in shots 2 and 4.
Weak: join the clips, drop the music at full volume, captions in default small font at the very bottom.
Strong:
```
1. rife x2 each clip -> rough/shot-01-32.mp4 ... shot-05-32.mp4          (16 -> 32 fps)
2. upscale 2x then scale to 1920 high, crop to 1080 wide (center)         -> rough/shot-NN-1080.mp4
3. join in order; hard cuts except 0.25 s fade between shots 4 and 5      -> rough/joined.mp4 (24.75 s)
4. dialogue.wav: shot-02 line at 5.4 s, shot-04 line at 15.4 s (shot starts at 5.0 and 15.0, +0.4 s; the fade is after shot 4, so only shot 5 shifts by 0.25 s)
5. music: mood-action, fade in 0.5 s, fade out 1.5 s, -18 dB, sidechain keyed by dialogue; loudnorm -14 LUFS
6. captions.ass: "Wait for me!" 5.4-6.8 s, "I can't believe it, it actually worked!" 15.4-18.2 s; 64 px bold white, black outline, centered at y=1250
7. export H.264 yuv420p 30 fps CRF 18, AAC 192k 48 kHz, faststart -> final/episode-01.mp4
```
Example ffmpeg sketches, all **[verify]**: scale/crop `-vf "scale=-2:1920:flags=lanczos,crop=1080:1920"`; fade `xfade=transition=fade:duration=0.25:offset=<t>`; ducking `[music][dialog]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300`; loudness `loudnorm=I=-14:TP=-1.5:LRA=11`; captions `-vf "ass=final/captions.ass"`; export `-c:v libx264 -pix_fmt yuv420p -r 30 -crf 18 -c:a aac -b:a 192k -movflags +faststart`.

## Self-check before asking for approval
- [ ] Final file is 1080×1920, H.264/AAC, 30 fps, under 90 s, plays on the phone.
- [ ] No stretched faces; crop is centered on the character.
- [ ] Dialogue is clearly audible over music; music fades in and out.
- [ ] Every caption matches the spoken words and the audio timing within 0.2 s.
- [ ] Captions are 56 px or larger, 2 lines max, inside the safe zone, not over the mouth.
- [ ] No black frames, no audio clicks at the cuts, no sync drift at the end.
- [ ] `finishing.json` lists all commands; all **[verify]** items reported.

## Failures and fixes
| Symptom | Cause | Fix | Gate to return to |
|---|---|---|---|
| Audio drifts from picture | Mixed frame rates or lost cross-fade offset | One fps; recompute offsets | E5 |
| Captions off by a second | Cross-fade shortened the timeline | Shift times by the fade lengths | E5 |
| Captions covered by Instagram UI | Too low | Move up; keep out of bottom 350 px | E5 |
| Dialogue hard to hear | Music too loud | Lower music to -20 dB, stronger sidechain | E5 |
| Faces look stretched | Scaled instead of cropped | Scale to height, then crop | E5 |
| Ghosting after interpolation | RIFE on fast motion | Skip interpolation for that shot (use 16 fps duplicated to 32) | E5 or E4 |
| Hard flicker in a clip | Bad take | Redo that shot only | E4 |
| ffmpeg not found | Not installed | Report; user installs ffmpeg | Stage 0 |
| Washed colors | Wrong pixel format | `-pix_fmt yuv420p` and Rec.709 tags | E5 |

## Sources
- Reels specs from third-party guides (1080×1920, 9:16, H.264, 8–15 Mbps, safe areas differ): https://argil.ai/blog/instagram-reel-size-e350f , https://socialrails.com/blog/instagram-reel-dimensions **[verify against Meta's help center]**
- Instagram Creators blog (no numeric spec found): https://creators.instagram.com/blog
- Maximum Reel length (90 s here; Meta has allowed longer) **[verify]**; loudness target -14 LUFS **[verify]**; ffmpeg filter options **[verify]**: https://ffmpeg.org/ffmpeg-filters.html
- RIFE and upscale templates: not built yet.
