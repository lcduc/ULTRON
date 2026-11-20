"""Runs INSIDE the open-webui container (docker exec -i ... python3 - < this file).

Voice timing with the same settings Open WebUI uses: Kokoro text-to-speech over
the internal network, then faster-whisper (model from audio.stt.whisper_model,
int8, CPU, download_root = WHISPER_MODEL_DIR, beam_size 5) on the clip.
Whisper is loaded in a fresh process here: "cold" = model load + first
transcription, "warm" = later transcriptions on the loaded model.
Prints one line: BENCH_JSON:<json>.
"""
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.request

KOKORO = 'http://kokoro:8880/v1/audio/speech'
CLIP_TEXT = 'Remind me to call my mother tomorrow evening, and add milk and eggs to the shopping list.'
SENTENCE = 'Sure, I have added the reminder for tomorrow evening.'


def tts(text, fmt):
    body = json.dumps({'model': 'kokoro', 'voice': 'am_michael', 'input': text, 'response_format': fmt}).encode()
    req = urllib.request.Request(KOKORO, data=body, headers={'Content-Type': 'application/json'})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        first = r.read(1)
        t_first = time.perf_counter() - t0
        data = first + r.read()
    return data, t_first, time.perf_counter() - t0


def main():
    out = {}
    model_name = json.loads(sqlite3.connect('file:/app/backend/data/webui.db?mode=ro', uri=True).execute(
        "select value from config where key='audio.stt.whisper_model'").fetchone()[0])
    out['whisper_model'] = model_name

    # TTS: one sentence, mp3 (what the browser plays). First request of the run also warms Kokoro, so time 3.
    t = []
    for _ in range(3):
        _, first, total = tts(SENTENCE, 'mp3')
        t.append((first, total))
    out['tts_sentence_s'] = {'first_byte_median': round(statistics.median(x[0] for x in t), 2),
                             'total_median': round(statistics.median(x[1] for x in t), 2),
                             'runs': [round(x[1], 2) for x in t]}

    wav, _, _ = tts(CLIP_TEXT, 'wav')
    path = '/tmp/bench-clip.wav'
    with open(path, 'wb') as f:
        f.write(wav)
    # Kokoro streams the WAV, so the header length is not reliable: 24 kHz, 16-bit, mono.
    out['clip_seconds'] = round((len(wav) - 44) / 48000.0, 2)

    t0 = time.perf_counter()
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device='cpu', compute_type=os.environ.get('WHISPER_COMPUTE_TYPE', 'int8'),
                         download_root=os.environ.get('WHISPER_MODEL_DIR'), local_files_only=True)
    load = time.perf_counter() - t0

    def run():
        t0 = time.perf_counter()
        segs, _ = model.transcribe(path, beam_size=5, vad_filter=False, language=None, multilingual=False)
        text = ''.join(s.text for s in list(segs)).strip()
        return time.perf_counter() - t0, text

    first, text = run()
    warm = [run()[0] for _ in range(3)]
    out['stt'] = {'model_load_s': round(load, 2), 'first_transcribe_s': round(first, 2),
                  'cold_total_s': round(load + first, 2),
                  'warm_median_s': round(statistics.median(warm), 2), 'warm_runs': [round(x, 2) for x in warm],
                  'transcript': text}
    os.remove(path)
    print('BENCH_JSON:' + json.dumps(out), flush=True)


main()
