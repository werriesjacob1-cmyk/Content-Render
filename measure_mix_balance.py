#!/usr/bin/env python3
"""How far under the narration does the music bed sit? An objective check on a render.

    python measure_mix_balance.py out/final.mp4

Decodes the audio, measures loudness in 0.25 s windows, and reports the gap between
the loudest windows (narration) and the quietest windows (the bed on its own, in the
pauses). A bed that sits ~16 dB or more under the voice reads as background; under
~13 dB it competes with the narration.

IT IS AN APPROXIMATION, and says so. The quietest windows can include breaths and
room tone, and the music cannot be separated from the voice once mixed. Use it to
compare renders and to catch a regression, not as a precise dB figure. It was written
after a render measured ~11 dB of separation against a documented 18-20 dB and the
user independently said the music was too loud -- the two agreed.

Needs ffmpeg on PATH. No other dependencies.
"""
from __future__ import annotations

import array
import math
import subprocess
import sys
import tempfile
import wave

WINDOW_S = 0.25
OK_SEPARATION_DB = 16.0      # target: bed sits about this far under the voice
LOUD_SEPARATION_DB = 13.0    # below this the bed competes with the narration


def window_levels_db(samples, sample_rate, window_s=WINDOW_S):
    """RMS level in dBFS for each consecutive window of 16-bit samples."""
    win = max(1, int(sample_rate * window_s))
    out = []
    for i in range(0, len(samples) - win + 1, win):
        seg = samples[i:i + win]
        rms = math.sqrt(sum(v * v for v in seg) / len(seg)) / 32768.0
        out.append(20.0 * math.log10(rms) if rms > 0 else -99.0)
    return out


def mix_balance(levels_db):
    """Pure. {'speech_db','gap_db','separation_db','verdict'} from window levels."""
    if len(levels_db) < 8:
        raise ValueError("audio too short to judge (need at least 2 seconds)")
    s = sorted(levels_db)
    pick = lambda p: s[int(p * (len(s) - 1))]
    speech, gap = pick(0.90), pick(0.10)
    sep = speech - gap
    if sep >= OK_SEPARATION_DB:
        verdict = "OK: the bed sits well under the narration"
    elif sep >= LOUD_SEPARATION_DB:
        verdict = "BORDERLINE: the bed is fairly present"
    else:
        verdict = "TOO LOUD: the bed competes with the narration"
    return {"speech_db": round(speech, 1), "gap_db": round(gap, 1),
            "separation_db": round(sep, 1), "verdict": verdict}


def measure_file(path):
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "wav", tmp.name], check=True)
        w = wave.open(tmp.name)
        x = array.array("h")
        x.frombytes(w.readframes(w.getnframes()))
        return mix_balance(window_levels_db(x, w.getframerate()))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    r = measure_file(sys.argv[1])
    print(f"narration ~{r['speech_db']} dBFS | bed alone ~{r['gap_db']} dBFS | "
          f"separation {r['separation_db']} dB\n{r['verdict']}")
