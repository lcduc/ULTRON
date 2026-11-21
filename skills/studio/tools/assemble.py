#!/usr/bin/env python3
"""Assemble finished clips, dialogue, music and captions into one Reels video.
Standard library + ffmpeg/ffprobe only.

  python assemble.py manifest.json

Manifest (relative paths resolve against the manifest's folder):
{"output": "final.mp4",
 "clips":    [{"file": "shot1.mp4", "in": 0.0, "out": 5.0}],       # out optional = to end
 "dialogue": [{"file": "line1.wav", "start": 1.2, "gain_db": 0}],  # start = seconds on the final timeline
 "music":    {"file": "music.wav", "gain_db": -16, "duck_db": -8, "fade_in": 0.5, "fade_out": 1.5},
 "captions": [{"start": 1.2, "end": 3.0, "text": "No, no, no."}],
 "width": 1080, "height": 1920, "fps": 30}
All keys but output and clips are optional. Clips are cut hard, scaled to cover
width x height (Lanczos) and centre-cropped. Music drops by duck_db while any
dialogue line plays (smooth 0.15 s ramps). Export: H.264 High, yuv420p, CRF 18,
AAC 192 kbps 48 kHz stereo, +faststart. Captions are burned from an .ass file
written next to the output (<output name>.ass).
"""
import json
import os
import shutil
import subprocess
import sys

FFMPEG_FALLBACK = ("C:/Users/VNNIT/AppData/Local/Microsoft/WinGet/Packages/"
                   "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0.2-full_build/bin")
RAMP = 0.15  # seconds, duck attack/release


def tool(name):
    p = shutil.which(name)
    if p:
        return p
    p = os.path.join(FFMPEG_FALLBACK, name + ".exe")
    if os.path.isfile(p):
        return p
    sys.exit(f"{name} not found; install ffmpeg (winget install Gyan.FFmpeg)")


def run(cmd, cwd=None):
    shown = " ".join(f'"{c}"' if (" " in c or any(ch in c for ch in ";[]'(),")) else c for c in cmd)
    print("$ " + shown, flush=True)
    subprocess.run(cmd, check=True, cwd=cwd)


def probe_duration(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def wrap(text, width=24, max_lines=2):
    words = text.replace("\n", " ").split()
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:  # rebalance into max_lines by word count
        half = (len(words) + 1) // 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
        print(f"warning: caption too long for {max_lines} lines of {width} chars: {text!r}")
    return lines


def write_ass(path, caps, W, H):
    esc = lambda s: s.replace("\\", "").replace("{", "(").replace("}", ")")
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,420,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = "".join(f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Default,,0,0,0,,"
                 + "\\N".join(esc(l) for l in wrap(c["text"])) + "\n" for c in caps)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(head + ev)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    mpath = os.path.abspath(sys.argv[1])
    base = os.path.dirname(mpath)
    m = json.load(open(mpath, encoding="utf-8"))
    P = lambda p: os.path.abspath(p if os.path.isabs(p) else os.path.join(base, p))
    W, H, FPS = int(m.get("width", 1080)), int(m.get("height", 1920)), m.get("fps", 30)
    out = P(m["output"])
    workdir = os.path.dirname(out)
    os.makedirs(workdir, exist_ok=True)

    inputs, vf, vlabels, total = [], [], [], 0.0
    for i, c in enumerate(m["clips"]):
        f = P(c["file"])
        t0 = float(c.get("in", 0.0))
        t1 = float(c["out"]) if c.get("out") is not None else probe_duration(f)
        inputs += ["-i", f]
        vf.append(f"[{i}:v]trim=start={t0}:end={t1},setpts=PTS-STARTPTS,fps={FPS},"
                  f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1[v{i}]")
        vlabels.append(f"[v{i}]")
        total += t1 - t0
    n = len(vlabels)
    vf.append("".join(vlabels) + f"concat=n={n}:v=1:a=0[vcat]")

    caps = m.get("captions") or []
    ass_name = os.path.splitext(os.path.basename(out))[0] + ".ass"
    if caps:
        write_ass(os.path.join(workdir, ass_name), caps, W, H)
        vf.append(f"[vcat]ass={ass_name}[vout]")  # relative name, ffmpeg runs with cwd=workdir (avoids drive-letter escaping)
    else:
        vf.append("[vcat]null[vout]")

    # audio
    af, amix_in, idx, lines = [], [], n, []
    for d in m.get("dialogue") or []:
        f = P(d["file"])
        s = float(d.get("start", 0.0))
        lines.append((s, s + probe_duration(f)))
        inputs += ["-i", f]
        ms = int(round(s * 1000))
        af.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms},"
                  f"volume={float(d.get('gain_db', 0))}dB,apad=whole_dur={total:.3f}[d{idx}]")
        amix_in.append(f"[d{idx}]")
        idx += 1
    dlg = None
    if amix_in:
        af.append("".join(amix_in) + f"amix=inputs={len(amix_in)}:normalize=0:duration=longest,atrim=0:{total:.3f}[dlg]")
        dlg = "[dlg]"
    mus = m.get("music")
    mlabel = None
    if mus:
        inputs += ["-i", P(mus["file"])]
        duck = float(mus.get("duck_db", 0))
        fi, fo = float(mus.get("fade_in", 0)), float(mus.get("fade_out", 0))
        chain = (f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                 f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={float(mus.get('gain_db', -16))}dB")
        if duck and lines:
            # ramp envelope: 1 while a line plays (with RAMP in/out), else 0
            terms = [f"clip(min((t-{s - RAMP:.3f})/{RAMP},({e + RAMP:.3f}-t)/{RAMP}),0,1)" for s, e in lines]
            env = terms[0]
            for t in terms[1:]:
                env = f"max({env},{t})"
            chain += f",volume='pow(10,{duck}*{env}/20)':eval=frame"
        if fi:
            chain += f",afade=t=in:st=0:d={fi}"
        if fo:
            chain += f",afade=t=out:st={max(total - fo, 0):.3f}:d={fo}"
        af.append(chain + "[mus]")
        mlabel = "[mus]"
    parts = [x for x in (dlg, mlabel) if x]
    if len(parts) == 2:
        af.append(f"{dlg}{mlabel}amix=inputs=2:normalize=0:duration=longest,atrim=0:{total:.3f}[aout]")
    elif len(parts) == 1:
        af.append(f"{parts[0]}anull[aout]")
    else:
        af.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")

    cmd = [tool("ffmpeg"), "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(vf + af),
           "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
           "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", out]
    run(cmd, cwd=workdir)
    print(json.dumps({"ok": True, "output": out.replace("\\", "/"), "duration_s": round(total, 3)}))


if __name__ == "__main__":
    main()
