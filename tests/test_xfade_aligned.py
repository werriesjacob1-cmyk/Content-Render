"""The dissolve must keep every scene boundary on the AUDIO timeline (the old chained xfade drifted
the picture ahead by (N-1)*xf). Pure offset math always; the render check needs ffmpeg and skips without."""
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "x")
import main as M


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        raise AssertionError(label)


def test_offsets_pure():
    durs = [2.0, 2.5, 3.0, 2.0]
    offs = M._xfade_aligned_offsets(durs, 0.25)
    check(offs == [1.75, 4.25, 7.25], f"offset k = end of scene k minus xf ({offs})")
    check(M._xfade_aligned_offsets([4.0], 0.25) == [] and M._xfade_aligned_offsets([], 0.25) == [], "0/1 scene -> no offsets")
    classic = M._xfade_offsets(durs, 0.25)
    check(classic[-1] < offs[-1], "the classic chain drifts early; the aligned one does not")


def test_manifest_xfade():
    check(M.manifest_xfade({"xfade": 0.25}) == 0.25, "0.25 accepted")
    check(M.manifest_xfade({}) == 0.0 and M.manifest_xfade({"xfade": "x"}) == 0.0, "absent/garbage -> 0")
    check(M.manifest_xfade({"xfade": 5}) == 0.0 and M.manifest_xfade({"xfade": 0.01}) == 0.0, "out of range -> 0")


def _pixel(video, t):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", video, "-frames:v", "1",
                          "-vf", "crop=2:2:100:100", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return tuple(out[:3])


def test_render_alignment():
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("SKIP no ffmpeg")
        return
    tmp = tempfile.mkdtemp()
    colors, durs, files = ["red", "green", "blue"], [2.0, 2.5, 3.0], []
    for i, (c, d) in enumerate(zip(colors, durs)):
        f = os.path.join(tmp, f"s{i}.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={c}:s=360x640:r=30:d={d}",
                        "-f", "lavfi", "-i", f"sine=frequency={300+100*i}:duration={d}", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", f], check=True)
        files.append(f)
    out = os.path.join(tmp, "body.mp4")
    M.build_body_xfade(files, out, xf=0.25)
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                                 capture_output=True, text=True).stdout)
    check(abs(total - sum(durs)) < 0.12, f"output as long as the audio ({total:.2f}s vs {sum(durs):.2f}s)")
    r = _pixel(out, 1.0); g = _pixel(out, 2.3); b = _pixel(out, 4.9)
    check(r[0] > 150 and r[1] < 90, f"scene 0 is red before the first boundary {r}")
    check(g[1] > 100 and g[0] < 90, f"scene 1 is already fully green just after the 2.0s boundary {g}")
    check(b[2] > 150 and b[0] < 90, f"scene 2 is blue after the 4.5s boundary (not 0.5s early) {b}")
    mid = _pixel(out, 1.9)
    check(mid[0] > 40 and mid[1] > 40, f"the last 0.25s of scene 0 is a real dissolve, not a cut {mid}")


if __name__ == "__main__":
    test_offsets_pure(); test_manifest_xfade(); test_render_alignment()
    print("ALL PASS")
