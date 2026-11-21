#!/usr/bin/env python3
"""Kokoro TTS batch tool. Run with the venv python:

  F:/UltronStudio/tts-venv/Scripts/python.exe tts_kokoro.py lines.json out_dir

lines.json: [{"id": "s4_mia_1", "voice": "af_heart", "text": "...", "speed": 1.0}]
Writes out_dir/<id>.wav (24 kHz mono, 16-bit) and prints JSON with durations.
Voice id prefix: a = American, b = British; f/m = female/male.
"""
import json
import os
import sys

SR = 24000


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    lines = json.load(open(sys.argv[1], encoding="utf-8"))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipes = {}
    results = []
    for ln in lines:
        voice = ln.get("voice", "af_heart")
        lang = voice[0]  # 'a' American, 'b' British
        if lang not in pipes:
            pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
        chunks = [np.asarray(a, dtype="float32") for _, _, a in
                  pipes[lang](ln["text"], voice=voice, speed=float(ln.get("speed", 1.0)))]
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
        path = os.path.join(out_dir, ln["id"] + ".wav")
        sf.write(path, audio, SR, subtype="PCM_16")
        results.append({"id": ln["id"], "file": path.replace("\\", "/"), "voice": voice,
                        "duration_s": round(len(audio) / SR, 3)})
    print(json.dumps({"ok": True, "sample_rate": SR, "lines": results}, indent=1))


if __name__ == "__main__":
    main()
