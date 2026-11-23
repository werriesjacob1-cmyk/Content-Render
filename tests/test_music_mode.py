"""Music bed choice: pure parsing, and the generated ambient pad is the right length and never silent."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
import main as M


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise AssertionError(label)


check(M.manifest_music({"music": "off"}, env="") == "off", "manifest music=off")
check(M.manifest_music({"music": "Ambient"}, env="") == "ambient", "case-insensitive")
check(M.manifest_music({}, env="ambient") == "ambient", "env fallback when the manifest is silent")
check(M.manifest_music({"music": "loop"}, env="off") == "loop", "manifest beats env")
check(M.manifest_music({"music": "jazz"}, env="") is None and M.manifest_music({}, env="") is None, "unknown/absent -> legacy default")

M.WORK = tempfile.mkdtemp()
check(M._ensure_music_bed(30.0, "off") is None, "off returns no bed")
p = M._ensure_music_bed(12.0, "ambient")
import soundfile as sf, numpy as np
x, sr = sf.read(p)
check(abs(len(x) / sr - 13.0) < 0.2 and x.ndim == 2 and x.shape[1] == 2, f"ambient pad is stereo and {len(x)/sr:.1f}s for a 12s video")
check(float(np.sqrt(np.mean(x ** 2))) > 0.02 and float(np.max(np.abs(x))) < 0.8, "audible but never clipping")
a = x[: int(3 * sr)]; b = x[int(6 * sr): int(9 * sr)]
check(float(np.mean(np.abs(a - b))) > 1e-3, "does not repeat itself (3 s windows 6 s apart differ)")
print("ALL PASS")
