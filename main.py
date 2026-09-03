#!/usr/bin/env python3
"""
Faceless short-form render engine v2.
Adds: slow-zoom motion, color grade, lower-third captions with natural phrasing,
hook overlay (first 2s), background music bed, no-repeat footage.
"""

import os, sys, json, subprocess, shutil, wave, struct, re, time, urllib.request, urllib.parse, urllib.error
import random
import scientific_media as SCI_MEDIA

W, H = 1080, 1920
ROOT = os.path.dirname(os.path.abspath(__file__))
# Bundled display font (fonts/Anton-Regular.ttf, SIL OFL — see fonts/OFL.txt).
# 2026-08-03 craft-audit finding: EVERY text element in EVERY video (captions,
# cover headline, stat-card numbers) was rendering in the Linux system-default
# DejaVu Sans/Serif -- the exact "looks like nobody designed this" tell a real
# editor would flag first. Anton is a bold condensed display face (the classic
# TikTok/Reels caption look), vendored into the repo so it renders correctly on
# a bare CI runner with no system font install step required. Used directly by
# path for drawtext (FONT); the ASS caption filter needs the font DIRECTORY
# (see the `fontsdir` on the `ass=` filter call) since libass resolves fonts by
# family name, not by file path.
FONT = os.path.join(ROOT, "fonts", "Anton-Regular.ttf")
FONTS_DIR = os.path.join(ROOT, "fonts")
WORK = os.path.join(ROOT, "work")
OUT  = os.path.join(ROOT, "out")
MUSIC = os.path.join(ROOT, "music.mp3")  # set per-profile below
PEXELS_KEY  = os.environ.get("PEXELS_API_KEY", "")
import profiles
PROFILE, PAGE = profiles.get_profile()
ELEVEN_VOICE = PROFILE["eleven_voice"]
MUSIC = os.path.join(ROOT, PROFILE.get("music", "music.mp3"))

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

USED_FOOTAGE_PATH = os.path.join(ROOT, f"used_footage_{PAGE}.json")
USED_FOOTAGE_CAP = 500  # oldest ids fall off once a channel has used this many clips
# Same file generate.py writes history to (memory_<page>.json). main.py never
# touched this before -- the final-QA verdict (audio-listening judge over the
# ASSEMBLED video) was written only to the ephemeral out/qa_report.json release
# asset and never fed back here, so a repeatedly-weak fact/domain (e.g. footage
# judged 9/10 mid-render but 4/10 by final QA) left no trace for future runs to
# learn from. See _persist_qa_to_memory.
MEMORY_PATH = os.path.join(ROOT, f"memory_{PAGE}.json")

_used_video_ids = set()   # in-run dedup (fast lookups) + prior runs' history, loaded at startup
_used_history = []        # ordered record, written back to disk so dedup survives across runs


def load_used_footage():
    try:
        with open(USED_FOOTAGE_PATH) as f:
            ids = json.load(f).get("ids", [])
    except Exception:
        ids = []
    _used_history.extend(ids)
    _used_video_ids.update(ids)


def save_used_footage():
    with open(USED_FOOTAGE_PATH, "w") as f:
        json.dump({"ids": _used_history[-USED_FOOTAGE_CAP:]}, f)


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd[:6]), "..." if len(cmd) > 6 else "")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1800:])
        raise RuntimeError("command failed")
    return r


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------- VOICE ----------
WORD_TIMINGS = []  # list of (word, start_s, end_s) from ElevenLabs char timestamps

def _chars_to_words(chars, starts, ends):
    words, cur, w_start = [], "", None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, w_start, prev_end)); cur = ""; w_start = None
        else:
            if not cur:
                w_start = st
            cur += ch; prev_end = en
    if cur:
        words.append((cur, w_start, prev_end))
    return words

# edge-tts speaks briskly by default; a mild slow-down reads calmer and gives
# the (now word-accurate) captions room to breathe. NOT a heavy slow-down —
# an earlier big slow-down bloated a video to ~55s and felt forced; this is a
# few percent under the previously-requested -5%, keeping a ~30s cut ~30-35s.
EDGE_RATE = "-5%"   # was -12%. Renders 66/67/68 came out 47-53s at -12% — too
                     # long for completion. -5% is still a calm, deliberate
                     # documentary cadence (not rushed) but trims a ~47s cut to
                     # ~43s while KEEPING the dense script (density of surprise is
                     # what makes the page bingeable — better to speak a rich
                     # script a touch faster than to gut it). Whisper re-aligns
                     # captions to the actual audio, so sync is unaffected by rate.

# ---------- SCENE TRANSITIONS (opt-in, OFF by default) ----------
# A short cross-dissolve between scenes reads smoother than a hard cut, BUT the
# caption timeline is anchored to the hard-cut audio boundaries (see build_ass /
# actual_durs), and an earlier audio-crossfade clipped the narrator at every cut
# — so this stays OFF by default and the proven hard-cut path (build_body_concat)
# remains the nightly default. When SCENE_XFADE>0, build_body_xfade cross-
# dissolves the VIDEO only (audio is still a clean hard-cut concat, never
# clipped) and, on any ffmpeg error, falls back to the hard-cut path so a render
# can never fail because of this. Flip the default on only after verifying a real
# render (needs LLM quota) looks right and stays caption-synced.
SCENE_XFADE = max(0.0, float(os.getenv("SCENE_XFADE", "0") or 0))
SCENE_XFADE_STYLE = os.getenv("SCENE_XFADE_STYLE", "fade")  # any ffmpeg xfade transition


def _xfade_offsets(durs, xf):
    """Offsets for a chained ffmpeg xfade over clips of the given durations.
    xfade i blends the accumulated video with clip i+1 starting at
    offset_i = (accumulated duration so far) - xf, and the accumulated duration
    after the blend grows by (dur_{i+1} - xf). Returns the list of N-1 offsets
    (empty for <2 clips). Pure arithmetic so the timeline math is unit-tested
    without ffmpeg."""
    offs, acc = [], (durs[0] if durs else 0.0)
    for k in range(1, len(durs)):
        offs.append(round(acc - xf, 3))
        acc += durs[k] - xf
    return offs


def _edge_tts_with_timings(text, voice, rate, out_mp3):
    """Synthesize with edge-tts via its Python API AND capture real per-word
    timing from WordBoundary events. Writes the mp3 to out_mp3 and returns
    [(word, start_s, end_s), ...] (offsets are in 100-ns units → seconds).
    Raises on failure so the caller can fall back to the CLI/estimate."""
    import asyncio
    import edge_tts
    boundaries = []  # (text, start_s, end_s, kind)

    async def _run():
        comm = edge_tts.Communicate(text, voice, rate=rate)
        with open(out_mp3, "wb") as f:
            async for chunk in comm.stream():
                ctype = chunk.get("type") if hasattr(chunk, "get") else None
                if ctype == "audio" and chunk.get("data"):
                    f.write(chunk["data"])
                elif ctype in ("WordBoundary", "SentenceBoundary"):
                    off = (chunk.get("offset") or 0) / 1e7
                    dur = (chunk.get("duration") or 0) / 1e7
                    boundaries.append((chunk.get("text", ""), off, off + dur, ctype))

    asyncio.run(_run())
    words = [(t, s, e) for (t, s, e, k) in boundaries if k == "WordBoundary"]
    sents = [(t, s, e) for (t, s, e, k) in boundaries if k == "SentenceBoundary"]
    # Instrumented: edge-tts's free endpoint has intermittently stopped emitting
    # WordBoundary metadata (audio still streams fine). Log exactly what came
    # back so we know whether real word timing is available this run or we're on
    # the estimate. If only sentence boundaries arrive, fall back to those —
    # anchoring each scene (one sentence) accurately still beats a pure guess.
    print(f"  edge-tts boundaries: {len(words)} word, {len(sents)} sentence")
    return words


# Local neural TTS (Piper): free, offline, no quota, and markedly more natural
# than edge-tts. The voice model is downloaded by render.yml to voices/voice.onnx
# (override with PIPER_MODEL). PIPER_LENGTH_SCALE sets pace: 1.0 = the model's
# natural speed (~fast); higher = slower/calmer. ~1.2 gives a deliberate
# documentary cadence. Word timings are NOT needed from Piper — whisper_align
# recovers them from the audio, same as for every other engine.
PIPER_MODEL = os.environ.get("PIPER_MODEL", os.path.join(ROOT, "voices", "voice.onnx"))
PIPER_LENGTH_SCALE = os.environ.get("PIPER_LENGTH_SCALE", "1.25")   # per-word pace (higher=slower)
PIPER_SENTENCE_SILENCE = os.environ.get("PIPER_SENTENCE_SILENCE", "0.35")  # pause between sentences (s)


def _piper_tts(text, out_mp3):
    """Synthesize with Piper -> WAV -> MP3. Returns True on success. Fully
    fail-safe: any missing model / piper error / bad output returns False so
    tts_full falls straight through to edge-tts and a render never breaks on TTS.
    length-scale gives a measured per-word pace; sentence-silence adds a short
    beat between sentences for documentary gravitas (so it reads calm, not rushed)."""
    if not os.path.exists(PIPER_MODEL):
        return False
    wav = out_mp3 + ".piper.wav"
    try:
        subprocess.run(["piper", "-m", PIPER_MODEL, "-f", wav,
                        "--length-scale", str(PIPER_LENGTH_SCALE),
                        "--sentence-silence", str(PIPER_SENTENCE_SILENCE)],
                       input=text, text=True, capture_output=True, timeout=180, check=True)
        if not (os.path.exists(wav) and os.path.getsize(wav) > 1000):
            return False
        run(["ffmpeg", "-y", "-i", wav, "-c:a", "libmp3lame", "-q:a", "3", out_mp3])
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 1000
    except Exception as e:  # noqa: BLE001
        print(f"  Piper TTS unavailable/failed ({e}); falling back to edge-tts")
        return False
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def tts_full(full_text, out_mp3, voice, rate):
    global WORD_TIMINGS
    el_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if el_key:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}/with-timestamps"
        headers = {"xi-api-key": el_key, "Content-Type": "application/json", "Accept": "application/json"}
        vs_full = dict(PROFILE["voice_settings"])
        # Try with the requested 'speed' setting; if this model rejects it, retry
        # once WITHOUT speed so we still get the chosen (deep) voice rather than
        # silently dropping to the edge-tts fallback voice.
        variants = [vs_full] + ([{k: v for k, v in vs_full.items() if k != "speed"}]
                                if "speed" in vs_full else [])
        for vi, vs in enumerate(variants):
            try:
                payload = json.dumps({"text": full_text, "model_id": "eleven_turbo_v2",
                                      "voice_settings": vs}).encode()
                req = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = json.loads(r.read().decode())
                import base64 as _b64
                with open(out_mp3, "wb") as f:
                    f.write(_b64.b64decode(data["audio_base64"]))
                al = data.get("alignment") or {}
                chars = al.get("characters", [])
                starts = al.get("character_start_times_seconds", [])
                ends = al.get("character_end_times_seconds", [])
                if chars and starts and ends:
                    WORD_TIMINGS = _chars_to_words(chars, starts, ends)
                    note = " [speed unsupported, dropped]" if "speed" not in vs and "speed" in vs_full else ""
                    print(f"  ElevenLabs SUCCESS ({len(WORD_TIMINGS)} word timings){note}")
                else:
                    print("  ElevenLabs SUCCESS (no timings)")
                if os.path.getsize(out_mp3) > 1000:
                    return True
            except urllib.error.HTTPError as e:
                body = e.read().decode()[:200]
                print(f"  ElevenLabs HTTP {e.code}: {body}")
                if vi == 0 and len(variants) > 1 and "speed" in body.lower():
                    print("  retrying ElevenLabs without the 'speed' setting")
                    continue
                break
            except Exception as e:
                print(f"  ElevenLabs failed: {e}")
                break
    # ---- FREE voices (used whenever ElevenLabs is absent or out of credits) ----
    # ORDER MATTERS and is the fix for the user's "robotic / choppy narrator"
    # complaint. ElevenLabs' 10k free credits/month get spent, so for most of the
    # month the FREE voice IS the product. edge-tts speaks with Azure NEURAL voices
    # that sound markedly more human/smooth than Piper's local model, it's free and
    # unlimited, and its slightly slower cadence (EDGE_RATE) also lifts a stubby
    # ~31s Piper read toward the ~38s watch-time sweet spot. So edge-tts is tried
    # FIRST now; Piper stays as the always-available OFFLINE fallback that
    # guarantees a render never breaks if edge-tts's free endpoint 403s or stops
    # streaming (the reliability reason it used to be first). VOICE_ENGINE lets the
    # user A/B by ear without a code change: "edge" (default order), "piper" (force
    # the local voice first), "auto" == "edge".
    def _try_edge():
        # Capture REAL per-word timing from edge-tts's WordBoundary events (the
        # Python API exposes them; the CLI --write-media does not) so captions +
        # scene cuts are word-accurate instead of a proportional guess that drifts
        # behind fast speech. Only trust the timings if their count is close to the
        # script's word count; otherwise fall through to the proportional estimate.
        try:
            wt = _edge_tts_with_timings(full_text, voice, EDGE_RATE, out_mp3)
            if os.path.getsize(out_mp3) > 1000:
                sw = len(full_text.split())
                if wt and abs(len(wt) - sw) <= max(3, 0.2 * sw):
                    WORD_TIMINGS[:] = wt
                    print(f"  edge-tts SUCCESS ({len(wt)} real word timings, rate {EDGE_RATE})")
                else:
                    WORD_TIMINGS[:] = []
                    print(f"  edge-tts SUCCESS (got {len(wt)} timings vs {sw} words — "
                          f"count mismatch, using proportional caption estimate)")
                return True
        except Exception as e:  # noqa: BLE001
            print("  edge-tts (python api) failed, trying CLI:", e)
        try:
            run(["edge-tts", f"--voice={voice}", f"--rate={EDGE_RATE}",
                 f"--text={full_text}", f"--write-media={out_mp3}"])
            if os.path.getsize(out_mp3) > 1000:
                WORD_TIMINGS[:] = []
                return True
        except Exception as e:  # noqa: BLE001
            print("  edge-tts failed:", e)
        return False

    def _try_piper():
        # Local neural TTS (Piper): free, offline, no quota. Clear WORD_TIMINGS so
        # the later whisper_align pass supplies the real per-word caption times.
        if _piper_tts(full_text, out_mp3):
            WORD_TIMINGS[:] = []
            print(f"  Piper SUCCESS (local neural voice, length-scale {PIPER_LENGTH_SCALE})")
            return True
        return False

    engine = os.environ.get("VOICE_ENGINE", "edge").strip().lower()
    free_order = [_try_piper, _try_edge] if engine == "piper" else [_try_edge, _try_piper]
    for _try in free_order:
        if _try():
            return True
    return False


def _align_words_by_content(script_words, heard):
    """Anchor each clean script word to the REAL spoken time of the matching
    whisper word, matching by CONTENT (difflib) rather than by position, so a
    single segmentation difference doesn't shift every later caption. For the few
    script words whisper didn't match (it dropped/merged them), interpolate a
    time linearly between the surrounding matched words. Returns
    [(script_word, start, end)] or [] if nothing could be matched."""
    import difflib
    if not script_words or not heard:
        return []

    def norm(w):
        return re.sub(r"[^a-z0-9]", "", w.lower())

    s_norm = [norm(w) for w in script_words]
    h_norm = [norm(h[0]) for h in heard]
    sm = difflib.SequenceMatcher(None, s_norm, h_norm, autojunk=False)
    s2h = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            s2h[a + k] = b + k
    if not s2h:
        return []
    # DIAGNOSTIC (2026-08-02, user-reported footage/narration timing drift on
    # render 203): a scene-cut boundary that lands on an INTERPOLATED word
    # (whisper never actually heard it -- e.g. it mis-transcribed an unusual
    # term) gets a linearly-guessed time, not a real spoken instant, and can
    # be off by hundreds of ms -- enough to read as "the clip changed before
    # the line." Print the real match rate so a future render's log can
    # confirm or rule this out instead of guessing at a fix.
    matched = len(s2h)
    if matched < len(script_words):
        print(f"  [align] {matched}/{len(script_words)} script words matched a real "
              f"whisper timestamp ({len(script_words) - matched} interpolated)")

    n = len(script_words)
    times = [None] * n  # (start, end) per script word
    for i in range(n):
        if i in s2h:
            hs = heard[s2h[i]]
            times[i] = (hs[1], hs[2])
    # interpolate unmatched words between their nearest matched neighbours
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        p = i - 1
        q = i
        while q < n and times[q] is None:
            q += 1
        left_end = times[p][1] if p >= 0 and times[p] else (times[q][0] if q < n and times[q] else 0.0)
        right_start = times[q][0] if q < n and times[q] else left_end + 0.3 * (q - i + 1)
        gap = max(q - i, 1)
        span = max(right_start - left_end, 0.0)
        step = span / gap if gap else 0.0
        for k in range(i, q):
            st = left_end + step * (k - i)
            en = left_end + step * (k - i + 1) if step > 0 else st + 0.25
            times[k] = (st, en)
        i = q
    return [(script_words[i], times[i][0], times[i][1]) for i in range(n)]


def whisper_align(mp3_path, script_text):
    """FREE forced alignment — the reliable caption-sync fix for the free voice.
    ElevenLabs returns exact char timings, but the free edge-tts fallback often
    returns NO word timing at all, so captions fell back to a proportional guess
    that drifts behind the real speech (the 'subtitles can't keep up' complaint).
    This transcribes the *actual synthesized audio* with faster-whisper (word
    timestamps) to recover the REAL per-word times, independent of the TTS
    engine's own (missing) metadata, then maps the known clean script words onto
    those real times by index. Returns [(word, start, end)] or [] on any failure
    (in which case the caller keeps the estimate). Verified locally on a real
    render's audio: aligned 91/91 words to true spoken instants."""
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # dependency missing -> keep estimate, never crash render
        print(f"  whisper align: unavailable ({e}); keeping caption estimate")
        return []
    try:
        model_name = os.environ.get("WHISPER_MODEL", "base")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segs, _ = model.transcribe(mp3_path, word_timestamps=True, language="en")
        heard = []
        for s in segs:
            for w in (s.words or []):
                heard.append((w.word.strip(), float(w.start), float(w.end)))
        if not heard:
            print("  whisper align: no words recovered; keeping estimate")
            return []
        script_words = script_text.split()
        # Map the CLEAN script words onto whisper's REAL times by CONTENT, not by
        # index. Index-alignment drifts the moment whisper's word segmentation
        # diverges from the script even once (e.g. it hears "42" + "degrees"
        # where the script has one token, or drops a filler word) — from that
        # point every caption is paired with the wrong word's time, which is the
        # persistent 'subtitles slightly off' complaint. Content-alignment keeps
        # each script word anchored to the instant that word is actually spoken,
        # and interpolates timing for the few words whisper missed.
        out = _align_words_by_content(script_words, heard)
        if not out:
            out = heard  # alignment produced nothing usable -> whisper's own words+times
        print(f"  whisper align: {len(out)} REAL word timings ({model_name} model, content-aligned)")
        return out
    except Exception as e:
        print(f"  whisper align failed ({e}); keeping caption estimate")
        return []


def split_audio(full_mp3, scenes, work_dir):
    total = ffprobe_dur(full_mp3)
    out, cursor = [], 0.0
    if WORD_TIMINGS:
        # exact: cut each scene where its last word actually ends, per the
        # same ElevenLabs timings the karaoke captions use — otherwise the
        # captions are word-perfect but the B-roll cut lands off-beat from
        # the words it's showing.
        word_i = 0
        for i, sc in enumerate(scenes):
            word_i += len(sc["voiceover"].split())
            last = (i == len(scenes) - 1) or word_i >= len(WORD_TIMINGS)
            seg_end = total if last else WORD_TIMINGS[word_i - 1][2]
            # Pad the cut a little PAST the last word's marked end, into the silent
            # gap before the next scene's first word. Cutting an MP3 with -c:a copy
            # rounds to the nearest ~26ms frame, which was shaving the tail off a
            # trailing word (the "will" in "...undone at will" got clipped). Landing
            # the cut in the inter-word silence means the rounding eats silence, not
            # speech — but never go past the next word's onset, which would clip IT.
            if not last and word_i < len(WORD_TIMINGS):
                next_start = WORD_TIMINGS[word_i][1]
                seg_end = min(next_start, seg_end + 0.18)
            seg = max(0.1, seg_end - cursor)
            p = os.path.join(work_dir, f"s{i+1}.mp3")
            run(["ffmpeg", "-y", "-i", full_mp3, "-ss", f"{cursor:.3f}", "-t", f"{seg:.3f}", "-c:a", "copy", p])
            out.append((p, seg)); cursor += seg
        return out
    # fallback: no exact timings available, split proportionally by word count
    tw = sum(len(s["voiceover"].split()) for s in scenes)
    for i, sc in enumerate(scenes):
        w = len(sc["voiceover"].split())
        seg = (w / tw) * total if tw else float(sc.get("duration", 3))
        if i == len(scenes) - 1:
            seg = total - cursor
        p = os.path.join(work_dir, f"s{i+1}.mp3")
        run(["ffmpeg", "-y", "-i", full_mp3, "-ss", f"{cursor:.3f}", "-t", f"{seg:.3f}", "-c:a", "copy", p])
        out.append((p, seg)); cursor += seg
    return out


def silent_track(secs, out_mp3):
    wav = out_mp3 + ".wav"; fr = 24000; n = int(fr * secs)
    with wave.open(wav, "w") as wv:
        wv.setnchannels(1); wv.setsampwidth(2); wv.setframerate(fr)
        wv.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    run(["ffmpeg", "-y", "-i", wav, out_mp3]); os.remove(wav)


# ---------- SCENE TIMING ----------
# Each scene is exactly as long as its OWN spoken audio segment (split_audio's
# cut on that scene's last word). No padding, no injected inter-scene silence,
# no minimum on-screen hold: natural pacing comes from the script's sentence
# length, not artificial gaps. An earlier "breathing-room pauses + minimum
# shot hold" pass bloated a ~30-40s script to ~55s ("talking too slow") and,
# because it shifted every word off the timeline WORD_TIMINGS is anchored to,
# desynced the captions from the narration. Removed.


def _prefix_starts(durs):
    """Cumulative start offset of each item: starts[i] = sum(durs[:i])."""
    starts, cursor = [], 0.0
    for d in durs:
        starts.append(cursor); cursor += d
    return starts


# ---------- FOOTAGE (dedup, more results) ----------
def _http_json(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _pexels_candidates(query):
    """Return list of dicts: {id, w, h, url, desc, source} for unused portrait clips."""
    out = []
    if not PEXELS_KEY:
        return out
    try:
        q = urllib.parse.quote(query)
        data = _http_json(
            f"https://api.pexels.com/videos/search?query={q}&orientation=portrait&per_page=15&size=medium",
            {"Authorization": PEXELS_KEY, "User-Agent": BROWSER_UA})
        for v in data.get("videos", []):
            if v.get("id") in _used_video_ids:
                continue
            best = None
            for f in v.get("video_files", []):
                if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1280:
                    if best is None or abs((f.get("width") or 0) - W) < abs((best.get("width") or 0) - W):
                        best = f
            if best:
                # Pexels' API has no real description; the page-URL slug is the
                # closest thing to one, but its trailing numeric id is pure
                # noise for the Groq matcher below — strip it.
                slug = (v.get("url", "") or "").rstrip("/").split("/")[-1]
                slug = re.sub(r"-\d+$", "", slug)
                out.append({"id": v.get("id"), "url": best["link"],
                            "desc": slug.replace("-", " "), "source": "Pexels",
                            "image": v.get("image")})   # preview thumbnail for the vision judge
    except urllib.error.HTTPError as e:
        print(f"  Pexels HTTP {e.code}: {e.read().decode()[:160]}")
    except Exception as e:
        print("  Pexels failed:", e)
    return out


NASA_ITEM_LIMIT = 3       # was 6 -- each item costs a second network round trip
NASA_ITEM_TIMEOUT_S = 10  # small JSON manifests; no reason to allow the full 30s
NASA_BUDGET_S = 15        # hard wall-clock cap for the whole call: this is a fallback
                          # source, not worth stalling a render over. A render with the
                          # judge/rescue chain can call this several times per scene --
                          # unbounded, a slow/degraded NASA endpoint could stall a whole
                          # run (observed: one render ran 25+ min past its usual ~5 min
                          # with no other code path that could explain it).


def _nasa_candidates(query):
    """Second footage source, tried when Pexels has no portrait match. NASA's
    Image and Video Library is public domain (CC0) and its API is explicitly
    built for automated/embedded use (unlike Pixabay, which prohibits
    unattended API calls in its terms). Landscape-only footage, but for
    space/astro topics the real mission-footage relevance beats generic
    Pexels B-roll. Two-step API: search gives items + a manifest href per
    item; the manifest lists the actual mp4 files."""
    out = []
    deadline = time.time() + NASA_BUDGET_S
    try:
        q = urllib.parse.quote(query)
        data = _http_json(
            f"https://images-api.nasa.gov/search?q={q}&media_type=video",
            {"User-Agent": BROWSER_UA}, timeout=NASA_ITEM_TIMEOUT_S)
        items = ((data.get("collection") or {}).get("items") or [])[:NASA_ITEM_LIMIT]
        for item in items:
            if time.time() > deadline:
                print("  NASA budget exceeded, returning what we have")
                break
            meta = (item.get("data") or [{}])[0]
            nasa_id = meta.get("nasa_id")
            manifest_url = item.get("href")
            if not nasa_id or not manifest_url or nasa_id in _used_video_ids:
                continue
            try:
                files = _http_json(manifest_url, {"User-Agent": BROWSER_UA},
                                   timeout=NASA_ITEM_TIMEOUT_S)
            except Exception:
                continue
            mp4 = next((u for u in files if isinstance(u, str)
                        and u.lower().endswith(".mp4") and "thumb" not in u.lower()), None)
            if mp4:
                desc = f"{meta.get('title','')} {meta.get('description','')} " \
                       f"{' '.join(meta.get('keywords') or [])}"
                out.append({"id": nasa_id, "url": mp4, "desc": desc.strip()[:300], "source": "NASA"})
    except urllib.error.HTTPError as e:
        print(f"  NASA HTTP {e.code}: {e.read().decode()[:160]}")
    except Exception as e:
        print("  NASA failed:", e)
    return out


_LAST_GROQ_FAILED = False  # True when the most recent _groq_chat call failed at
                            # the TRANSPORT level (429/5xx/network/timeout) rather
                            # than returning a real (possibly empty) reply. Lets
                            # _groq_judge tell "judge is unreachable" (fall back to
                            # real footage, like no-key) from "judge answered but
                            # unparseably" (keep vetoing, avoids the belly-button bug).


# 2026-07: gemini-2.0-flash was 404'd by Google ("no longer available"). Moved to
# the current 2.5 family (works on a billed key). Env-overridable so a future
# deprecation is a one-variable fix. Used by both the vision footage judge and the
# text judge's Gemini fallback.
JUDGE_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest").split(",")[0].strip()


def _gemini_chat(prompt, max_tokens, temperature):
    """Google Gemini generateContent for the footage judge. Returns text or None.
    Raises on transport failure so the caller can fall back to Cerebras/Groq."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        # thinkingBudget=0: newer Gemini models otherwise burn the token budget
        # reasoning and return an empty/truncated answer for these tiny judge calls.
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max(max_tokens, 64),
                             "thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_GEMINI_MODEL}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key,
                 "User-Agent": "content-render/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]


_JUDGE_CONSEC_FAILS = 0   # consecutive transport failures of the footage judge
_JUDGE_CIRCUIT_OPEN = False  # once open, the judge stops making doomed calls


def _judge_note(ok):
    """Track judge health for the circuit breaker: a success closes it, 3
    back-to-back transport failures open it (stop making doomed calls)."""
    global _JUDGE_CONSEC_FAILS, _JUDGE_CIRCUIT_OPEN
    if ok:
        _JUDGE_CONSEC_FAILS = 0
    else:
        _JUDGE_CONSEC_FAILS += 1
        if _JUDGE_CONSEC_FAILS >= 3 and not _JUDGE_CIRCUIT_OPEN:
            _JUDGE_CIRCUIT_OPEN = True
            print("  [judge] circuit OPEN — footage judge rate-limited 3x in a row; "
                  "shipping the top stock clip for the rest of this run (no more doomed judge calls)")


_CEREBRAS_JUDGE_MODEL_CACHE = None


def _cerebras_judge_model():
    """The Cerebras model THIS key can use for the judge, discovered via
    /v1/models (cached). A hardcoded 'llama-3.3-70b' 404'd with 'you do not have
    access to it' on the free account, wasting a call per scene; discovery uses
    whatever the key is actually granted (preferring a 70B Llama), or None to
    skip Cerebras entirely — mirrors generate.py's cerebras_models()."""
    global _CEREBRAS_JUDGE_MODEL_CACHE
    if _CEREBRAS_JUDGE_MODEL_CACHE is not None:
        return _CEREBRAS_JUDGE_MODEL_CACHE or None
    key = os.environ.get("CEREBRAS_API_KEY", "")
    picked = ""
    if key:
        try:
            req = urllib.request.Request(
                "https://api.cerebras.ai/v1/models",
                headers={"Authorization": f"Bearer {key}", "User-Agent": "content-render/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ids = [m.get("id") for m in json.loads(r.read().decode()).get("data", []) if m.get("id")]
            ids.sort(key=lambda x: (0 if "70b" in x.lower() else 1, 0 if "llama" in x.lower() else 1, x))
            picked = ids[0] if ids else ""
        except Exception as e:  # noqa: BLE001
            print(f"  Cerebras /v1/models lookup failed ({e}); skipping Cerebras judge")
    _CEREBRAS_JUDGE_MODEL_CACHE = picked
    return picked or None


def _openai_compat_chat(url, key, model, prompt, max_tokens, temperature):
    """One judge call to any OpenAI-compatible chat endpoint (Groq, Cerebras).
    Returns the message content string. Raises on transport failure so the
    caller can fall through to the next provider."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature, "max_tokens": max_tokens
    }).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json",
                                          "User-Agent": "content-render/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        msg = json.loads(r.read().decode())["choices"][0]["message"]
    # Most models put the answer in "content"; some reasoning models (e.g.
    # Cerebras gpt-oss-*) return content=null with the text under "reasoning".
    # Fall back to that instead of KeyError-ing so the model is still usable.
    out = msg.get("content") or msg.get("reasoning") or ""
    if not out.strip():
        raise ValueError("empty content from model")
    return out


def _groq_chat(prompt, max_tokens=20, temperature=0, model="llama-3.1-8b-instant"):
    # PROVIDER ORDER FOR THE JUDGE IS DELIBERATELY ≠ GENERATION. The footage
    # judge fires 1-3 calls PER SCENE (~8-24 per render) — high volume, low
    # stakes. Gemini's tiny ~200/day bucket AND OpenRouter's small ~50/day bucket
    # are the two the quality-critical SCRIPT generation depends on, so the judge
    # NEVER touches either of them — that starvation is what made whole days fail
    # (run 95: judge fallbacks ate the generation buckets). The judge uses only
    # the GENEROUS / SEPARATE buckets: Groq (100k tokens/day) → Cerebras → then
    # the added Together/Fireworks/Mistral free buckets. If all of those are down
    # it just ships the top stock clip (footage judging fails open). This reserves
    # BOTH generation buckets fully and lifts sustainable videos/day on free tier.
    #
    # CIRCUIT BREAKER: after 3 back-to-back transport failures, the judge is
    # clearly down for this run (rate-limited) — stop calling it. Every further
    # call short-circuits to "unavailable" (ship the top stock clip), instead of
    # firing ~2-5 doomed calls per scene x every scene (~40 wasted calls that just
    # burn the quota and stall the render). Real judging resumes next run.
    global _LAST_GROQ_FAILED, _JUDGE_CONSEC_FAILS, _JUDGE_CIRCUIT_OPEN
    _LAST_GROQ_FAILED = False
    if _JUDGE_CIRCUIT_OPEN:
        _LAST_GROQ_FAILED = True   # signal "judge unavailable" → caller ships top clip
        return None
    groq_key = os.environ.get("GROQ_API_KEY", "")
    cere_key = os.environ.get("CEREBRAS_API_KEY", "")
    # NB: OPENROUTER_API_KEY and GEMINI_API_KEY are intentionally NOT read here —
    # the judge must never spend either bucket (both are reserved for generation).

    # 1) Groq FIRST — strongest generous free bucket (100k tokens/day); the tiny
    #    judge prompts (max_tokens=20) barely dent it, so it rarely runs out.
    if groq_key:
        try:
            out = _openai_compat_chat("https://api.groq.com/openai/v1/chat/completions",
                                      groq_key, JUDGE_MODEL, prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through to Cerebras
            print("  Groq judge call failed, trying Cerebras:", e)
    # 2) Cerebras — free, generous, separate bucket.
    cere_model = _cerebras_judge_model() if cere_key else None
    if cere_key and cere_model:
        try:
            out = _openai_compat_chat("https://api.cerebras.ai/v1/chat/completions",
                                      cere_key, cere_model, prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through to OpenRouter
            print("  Cerebras judge call failed, trying OpenRouter:", e)
    # 3) The ADDED free buckets — Together → Fireworks → Mistral. These extend the
    #    judge's capacity WITHOUT ever touching Gemini or OpenRouter (reserved
    #    wholly for generation). Absent/invalid keys are skipped; a bad key just
    #    falls through to the next bucket.
    added = [
        ("Together",  "https://api.together.xyz/v1/chat/completions",
         os.environ.get("TOGETHER_API_KEY", ""),  "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"),
        ("Fireworks", "https://api.fireworks.ai/inference/v1/chat/completions",
         os.environ.get("FIREWORKS_API_KEY", ""), "accounts/fireworks/models/llama-v3p3-70b-instruct"),
        ("Mistral",   "https://api.mistral.ai/v1/chat/completions",
         os.environ.get("MISTRAL_API_KEY", ""),   "mistral-small-latest"),
    ]
    for label, url, key, jmodel in added:
        if not key:
            continue
        try:
            out = _openai_compat_chat(url, key, jmodel, prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through to the next added bucket
            print(f"  {label} judge call failed:", e)
    # nothing worked — Gemini + OpenRouter are DELIBERATELY not used by the judge
    # (reserved for generation), so a judge outage simply ships the top stock clip.
    if groq_key or cere_key or any(k for _, _, k, _ in added):
        _LAST_GROQ_FAILED = True
        _judge_note(False)
    return None


JUDGE_MODEL = "llama-3.3-70b-versatile"  # relevance scoring is a judgment call, not
                                          # a cheap classification -- llama-3.1-8b-instant
                                          # scored an ocean-waves clip 9/10 against a
                                          # "humanity fits in a sugar cube" line in production


# Sentinels distinguishing WHY _groq_judge returned no numeric score, since
# fetch_clip must treat the two cases very differently:
#   NO_KEY     -- no GROQ_API_KEY at all, judging was never possible. Ship
#                 the first candidate (the old, still-correct behavior when
#                 there's no way to judge anything).
#   UNRESOLVED -- a key WAS present and the model WAS reachable, but neither
#                 the original call nor the retry returned a parseable
#                 verdict. This is the scene-7 bug: unresolved used to be
#                 treated identically to NO_KEY and auto-accepted as
#                 "first result", which is how a 4/10 clip shipped even
#                 though judging was available and the model just choked on
#                 formatting. Now it's treated as failing RELEVANCE_FLOOR --
#                 another requery round is tried, and if every round is
#                 exhausted the scene renders as a stat-card instead of an
#                 unverified clip.
#   JUDGE_UNAVAILABLE -- a key was present but the judge call itself failed at
#                 the transport level (Groq 429 rate-limit / 5xx / network) on
#                 both the call and its retry, so no verdict was ever produced.
#                 This is NOT the same as UNRESOLVED (model answered, garbled):
#                 the judge is simply DOWN, exactly like NO_KEY, so footage is
#                 shipped (top stock result) rather than rejected. Without this,
#                 a Groq rate-limit made every scene fail the judge -> text card
#                 -> the footage-starvation guard aborted the whole render, i.e.
#                 a transient Groq 429 silently killed otherwise-good videos.
NO_KEY = "no_key"
UNRESOLVED = "unresolved"
JUDGE_UNAVAILABLE = "judge_unavailable"


# ---------- VISION FOOTAGE JUDGE (paid Gemini) ----------
# The text judge reads a candidate's URL slug ("desc") — it never SEES the clip,
# so a slug that says "spider web" over a clip that's actually a dewy leaf still
# scores well. This judge sends the actual candidate THUMBNAILS to Gemini vision
# and picks the one that visually matches the scene. Best-effort + cost-capped:
# any failure returns None and the caller falls back to the text judge, so it can
# never break a render. Only Pexels candidates carry a thumbnail today.
VISION_JUDGE = os.environ.get("VISION_JUDGE", "1") != "0"
VISION_MAX_CANDS = int(os.environ.get("VISION_MAX_CANDS", "5"))
# HARD per-render budget on PAID Gemini vision calls. The judge re-searches per
# ambiguous scene, so a pathological render fired ~19 vision calls (run 112),
# each sending up to VISION_MAX_CANDS thumbnails to the paid key. This caps the
# only uncapped paid-Gemini cost per render; once spent, footage selection falls
# back to the FREE text judge (never breaks a render). Set 0 to disable the cap.
VISION_CALL_BUDGET = int(os.environ.get("VISION_CALL_BUDGET", "10"))
_VISION_CALLS = 0


def _gemini_vision_pick(intent, candidates):
    """Return (index_into_candidates, score 0-10) for the thumbnail that best
    matches `intent`, judged by Gemini vision — or None on any failure."""
    global _VISION_CALLS
    key = os.environ.get("GEMINI_API_KEY", "")
    if not (VISION_JUDGE and key):
        return None
    if VISION_CALL_BUDGET and _VISION_CALLS >= VISION_CALL_BUDGET:
        return None   # paid-vision budget spent this render — use the free text judge
    idxs = [i for i, c in enumerate(candidates) if c.get("image")][:VISION_MAX_CANDS]
    if len(idxs) < 2:
        return None   # nothing to compare visually — let the text judge handle it
    _VISION_CALLS += 1   # count an actual paid attempt against the budget
    import base64
    parts = [{"text": (f"Choosing stock footage for a science-video scene about: \"{intent}\". "
                       f"Below are {len(idxs)} candidate clip thumbnails, numbered from 0. Pick the "
                       f"ONE that most LITERALLY shows that subject (not just vaguely related). "
                       f"Scoring rules: 8-10 = the thumbnail clearly, literally shows the subject; "
                       f"4-7 = related/plausible but not exact; 0-3 = NONE of them really show it, "
                       f"or the best option is generic/off-topic. Score LOW (0-3) rather than force "
                       f"a stretch — a low score triggers a smarter re-search. Also penalize (cap at "
                       f"3) any thumbnail dominated by on-screen text/watermarks/logos, cartoons, 3D "
                       f"renders, or infographics; this channel needs REAL, clean footage. "
                       f"Return ONLY JSON: {{\"best\": <0-{len(idxs)-1}>, \"score\": <0-10 match>}}.")}]
    for n, i in enumerate(idxs):
        try:
            rq = urllib.request.Request(candidates[i]["image"], headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(rq, timeout=20) as r:
                raw = r.read()
        except Exception:
            return None   # a thumbnail wouldn't load — bail to the text judge
        parts.append({"text": f"Image {n}:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(raw).decode()}})
    # thinkingBudget=0 works fine for the TEXT-only judge (_gemini_chat above)
    # but 400s the API outright once the request carries image parts too --
    # render 203's log showed "[vision] judge unavailable (HTTP Error 400)" on
    # every single scene, live, while the plain-text judge in the same run
    # succeeded normally. A small POSITIVE budget (proven safe for generation
    # in generate.py's _call_gemini) is the fix: Gemini apparently won't fully
    # disable thinking on a multimodal request, only bound it. maxOutputTokens
    # MUST comfortably exceed thinkingBudget -- render 206 showed the next bug
    # this caused: 200 < 512 left ~0 tokens for the actual answer once
    # reasoning was spent, so the reply got cut off before any closing "}"
    # ("[vision] judge unavailable (no JSON in reply: ...)"). 1024 leaves
    # plenty of headroom above the 512-token thinking budget either way.
    body = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"temperature": 0, "maxOutputTokens": 1024,
                                            "thinkingConfig": {"thinkingBudget": 512}}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_GEMINI_MODEL}:generateContent"
    try:
        rq = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key,
                     "User-Agent": BROWSER_UA})
        with urllib.request.urlopen(rq, timeout=45) as r:
            data = json.loads(r.read().decode())
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        _match = re.search(r"\{.*\}", txt, re.S)
        if _match is None:
            print(f"  [vision] judge unavailable (no JSON in reply: {txt[:80]!r}); using text judge")
            return None
        m = json.loads(_match.group(0))
        best, score = int(m.get("best")), int(m.get("score"))
        if 0 <= best < len(idxs):
            print(f"  [vision] Gemini picked clip index {idxs[best]} (match {score}/10) by thumbnail")
            return idxs[best], max(0, min(10, score))
    except Exception as e:  # noqa: BLE001 - fall back to the text judge
        print(f"  [vision] judge unavailable ({e}); using text judge")
    return None


# ---------- FINAL HOLISTIC QA (post-render sanity check) ----------
# Everything above judges footage scene-by-scene DURING selection, against that
# scene's own intent — nothing looks at the ASSEMBLED video afterward. This is
# the automated version of the frame-by-frame manual review this channel has
# needed on every render so far: sample the finished, CAPTIONED video, hand it
# to Gemini vision with the full script, and get a holistic verdict logged
# right in the render output (and written to out/qa_report.json, shipped as a
# release asset) — so the assembled artifact itself is judged before a release.
# This is a QUALITY GATE, not merely a visibility tool. A confident bad verdict
# aborts, and so does missing/unparseable judge evidence while FINAL_QA is enabled:
# "we could not inspect the product" is an evidence failure, not permission to
# ship. The cron may retry later; consistency outranks cadence.
FINAL_QA = os.environ.get("FINAL_QA", "1") != "0"
FINAL_QA_FRAMES = int(os.environ.get("FINAL_QA_FRAMES", "8"))
# Hard publish gate: a CONFIDENT (judge actually ran + returned a number) low
# footage_matches_narration score aborts the render (mirrors the
# STAT_CARD_SCENES > MAX_STAT_CARDS gate). Deliberately stricter than the
# FLAG threshold used for the log line (6) -- this is the last line of
# defense before a release goes out, so it only fires on a clear, blatant
# mismatch (render 205/209 territory), not a borderline judge call.
# RAISED 4 -> 5 -> 6 (2026-08-02/03): real evidence from a pre-gate run that
# shipped uncaught -- footage_match=5/10, judge's own words "several clips
# like the starfield and night traffic are off-topic for human ancestry" --
# is a genuinely bad video, not a borderline one. The comparison below is
# strict-less-than (a floor: scores AT OR ABOVE it pass), so raising this to
# 5 was an off-by-one -- fm=5 < 5 is False, so that exact cited example
# would STILL have shipped. Caught live: the very next run that hit fm=5
# ("The Real Life Zombie Fungus" -- judge: "generic harvested mushrooms
# rather than cordyceps erupting from an ant") published right through the
# supposedly-raised gate. 6 is the value that actually blocks a 5.
FINAL_QA_ABORT_FLOOR = int(os.environ.get("FINAL_QA_ABORT_FLOOR") or "6")


# 2026-08-03: every "narration sounds clumsy/jumbled/doesn't make sense"
# complaint the user has caught has been caught the SAME way -- by actually
# LISTENING to a published video. Every mechanical fix shipped so far
# (question-hooks, stacked clauses, unnamed landmarks...) only guards the
# SPECIFIC phrasing shape it was written for; the next novel bad pattern
# sails through validate() untouched. This is the structural fix: the final
# QA judge below now gets the ACTUAL VOICE AUDIO, not just the text script --
# it LISTENS to the real narration the way a viewer (and the user) does, and
# scores whether it actually sounds natural, not whether it reads fine on
# paper. A narration_flow score below this floor aborts the publish exactly
# like a footage mismatch already does, so a bad-sounding video can no longer
# reach a release without a human having to catch it after the fact.
FINAL_QA_FLOW_FLOOR = int(os.environ.get("FINAL_QA_FLOW_FLOOR") or "6")

# Seconds to wait before the one retry on a transient final-QA call failure
# (see _final_qa_check) -- short and fixed, since this is a single post-render
# call, not the burst-RPM situation _gemini_retry_delay handles during generation.
FINAL_QA_RETRY_DELAY = int(os.environ.get("FINAL_QA_RETRY_DELAY") or "5")


def _qa_should_abort(qa_report):
    """True when enabled final-QA is unavailable, malformed, or below a floor.

    FINAL_QA=0 remains an explicit operator opt-out. Otherwise the assembled
    video must have usable artifact-level evidence before it can be considered
    successful. An unavailable reviewer is not evidence that the artifact is good.
    """
    if not FINAL_QA:
        return False
    if not qa_report.get("ran"):
        return True
    fm = qa_report.get("footage_matches_narration")
    if not isinstance(fm, (int, float)):
        return True
    if fm < FINAL_QA_ABORT_FLOOR:
        return True
    nf = qa_report.get("narration_flow")
    if qa_report.get("audio_judged") and not isinstance(nf, (int, float)):
        return True
    if isinstance(nf, (int, float)) and nf < FINAL_QA_FLOW_FLOOR:
        return True
    return False


def _qa_frame_timestamps(dur, n):
    """n evenly-spaced timestamps spanning `dur` seconds, inset 3% from each
    end so sampling never lands on a fade-in/fade-out black frame. Pure math
    (no ffmpeg), so it's testable without a real video. Returns [] for a
    degenerate duration/count so callers can treat that as 'nothing to do'."""
    if not dur or dur <= 0 or n <= 0:
        return []
    if n == 1:
        return [dur / 2]
    pad = dur * 0.03
    span = dur - 2 * pad
    return [pad + span * i / (n - 1) for i in range(n)]


def _extract_qa_frames(video, n, dest_dir):
    """Best-effort JPEG frame extraction at _qa_frame_timestamps(...) — returns
    whatever ffmpeg actually produced (may be short of `n` on a probe/seek
    failure); callers already treat 'fewer frames than expected' as fine."""
    dur = ffprobe_dur(video)
    times = _qa_frame_timestamps(dur, n)
    if not times:
        return []
    os.makedirs(dest_dir, exist_ok=True)
    paths = []
    for i, t in enumerate(times):
        p = os.path.join(dest_dir, f"qa_{i:02d}.jpg")
        try:
            run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-q:v", "3", p])
            if os.path.exists(p) and os.path.getsize(p) > 1000:
                paths.append(p)
        except Exception:  # noqa: BLE001 — skip a bad frame, keep going
            continue
    return paths


def _final_qa_check(video, m):
    """Holistic sanity check on the ASSEMBLED, captioned video.

    The function itself never raises and always writes out/qa_report.json, but
    its caller treats ran:false / malformed evidence as a failed quality gate
    while FINAL_QA is enabled. The caller requires usable artifact evidence as
    well as the numeric floors (FINAL_QA_ABORT_FLOOR / FINAL_QA_FLOW_FLOOR).
    The Gemini call itself gets ONE bounded retry (FINAL_QA_RETRY_DELAY) on
    failure before this still reports ran:false -- a transient hiccup no
    longer costs a whole aborted render, but exhausted evidence still fails
    closed exactly as before.

    2026-08-03: the judge now LISTENS to the actual voice track (full_vo.mp3,
    the raw TTS output from earlier in this same render — still on disk, WORK
    is only wiped at the top of main()), not just the text script. Every
    "sounds clumsy/jumbled" complaint the user has caught was caught by
    actually hearing it; validate()'s mechanical checks only ever guard the
    SPECIFIC phrasing shape they were written for, so a novel bad pattern
    sails through untouched. This closes that gap structurally instead of
    reactively: a script that reads fine on paper but sounds wrong out loud
    now gets caught by the pipeline itself, on every render, not just the
    ones a human happens to watch."""
    out_path = os.path.join(OUT, "qa_report.json")
    report = {"ran": False}
    try:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not (FINAL_QA and key):
            return report
        frames = _extract_qa_frames(video, FINAL_QA_FRAMES, os.path.join(WORK, "qa_frames"))
        if len(frames) < 3:
            print(f"[final-qa] skipped — only {len(frames)} frame(s) extracted")
            return report
        script = " ".join(s.get("voiceover", "") for s in m.get("scenes", []))
        import base64
        voice_mp3 = os.path.join(WORK, "full_vo.mp3")
        have_audio = os.path.exists(voice_mp3) and os.path.getsize(voice_mp3) > 1000
        audio_criterion = (
            f"5. narration_flow (0-10): LISTEN to the attached narration audio (not just the text "
            f"above). Does it actually sound natural, clear, and well-paced when SPOKEN, not just "
            f"when read? Score low if any word is confusing or ambiguous once heard, if a sentence "
            f"has too many clauses crammed together and rushes/jumbles, if the pacing feels uneven "
            f"or robotic, or if anything makes a listener think \"wait, what did that mean?\" on "
            f"first listen. This is independent of footage — judge the AUDIO alone.\n"
            if have_audio else "")
        _nf_json_field = ', "narration_flow": 0' if have_audio else ""
        parts = [{"text": (
            f"You are doing FINAL QUALITY CONTROL on a finished short-form science video, "
            f"sampled as {len(frames)} evenly-spaced frames across its full length, in order"
            f"{' plus its narration audio' if have_audio else ''}. "
            f"The full narration is: \"{script}\"\n\n"
            f"Judge the ASSEMBLED video, not the script. Answer honestly and strictly:\n"
            f"1. footage_matches_narration (0-10): across the frames, does what's ON SCREEN "
            f"actually match what the topic is about? Score low if you see an unrelated subject, "
            f"a generic/off-topic clip, or footage that contradicts the topic.\n"
            f"2. visual_variety (0-10): is there real variety across the frames, or does it look "
            f"like the same clip/color/composition repeated throughout?\n"
            f"3. caption_legible (0-10): are on-screen captions (if any are visible) readable, not "
            f"cut off, not overlapping other text? Use 10 if no captions are visible to judge.\n"
            f"4. biggest_issue: one short sentence naming the single worst concrete problem you "
            f"see, or \"none\" if it looks clean.\n"
            f"{audio_criterion}"
            f"Return ONLY JSON: {{\"footage_matches_narration\": 0, \"visual_variety\": 0, "
            f"\"caption_legible\": 0{_nf_json_field}, "
            f"\"biggest_issue\": \"...\"}}")}]
        for i, fp in enumerate(frames):
            parts.append({"text": f"Frame {i + 1}/{len(frames)}:"})
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(open(fp, "rb").read()).decode()}})
        if have_audio:
            parts.append({"text": "Narration audio:"})
            parts.append({"inline_data": {"mime_type": "audio/mpeg",
                                          "data": base64.b64encode(open(voice_mp3, "rb").read()).decode()}})
        # Same fix as _gemini_vision_pick: thinkingBudget=0 400s once the
        # request carries image parts (this call sends FINAL_QA_FRAMES of
        # them) -- render 203 confirmed live: "[final-qa] unavailable
        # (HTTPError: HTTP Error 400)" on every attempt. maxOutputTokens must
        # comfortably exceed thinkingBudget (render 206: 300 < 512 truncated
        # the reply before any closing "}" once reasoning ate the budget).
        body = json.dumps({"contents": [{"parts": parts}],
                           "generationConfig": {"temperature": 0, "maxOutputTokens": 1024,
                                                "thinkingConfig": {"thinkingBudget": 512}}}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_GEMINI_MODEL}:generateContent"
        rq = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key,
                     "User-Agent": BROWSER_UA})
        # BOUNDED RETRY (2026-09-03): fail-closed (PR #36) means ran:false now
        # ABORTS the whole release, so a single transient hiccup -- a dropped
        # connection, a 5xx, or Gemini occasionally replying with no parseable
        # JSON -- would waste an entire render on a problem that a retry fixes.
        # One extra attempt after a short fixed pause, then still fail closed
        # exactly as before if it ALSO fails -- this narrows what aborts to
        # genuinely unavailable evidence, without reopening fail-closed itself.
        verdict, last_err = None, None
        for _attempt in range(2):
            try:
                with urllib.request.urlopen(rq, timeout=60) as r:
                    data = json.loads(r.read().decode())
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
                _match = re.search(r"\{.*\}", txt, re.S)
                if _match is None:
                    raise ValueError(f"no JSON in reply: {txt[:80]!r}")
                verdict = json.loads(_match.group(0))
                break
            except Exception as e:  # noqa: BLE001 — retried once, then re-raised below
                last_err = e
                if _attempt == 0:
                    print(f"[final-qa] attempt 1 failed ({type(e).__name__}: {str(e)[:120]}) "
                          f"— retrying once in {FINAL_QA_RETRY_DELAY}s")
                    time.sleep(FINAL_QA_RETRY_DELAY)
        if verdict is None:
            raise last_err
        report = {"ran": True, "frames_sampled": len(frames), "audio_judged": have_audio, **verdict}
        fm = verdict.get("footage_matches_narration")
        vv = verdict.get("visual_variety")
        cl = verdict.get("caption_legible")
        nf = verdict.get("narration_flow")
        issue = verdict.get("biggest_issue", "")
        flag = "FLAG" if _qa_should_abort(report) else "ok"
        nf_part = f" flow={nf}/10" if have_audio else ""
        print(f"[final-qa] {flag} footage_match={fm}/10 variety={vv}/10 captions={cl}/10{nf_part} "
              f"issue={issue!r} ({len(frames)} frames sampled{', +audio' if have_audio else ''})")
    except Exception as e:  # noqa: BLE001 — report failure; caller enforces the gate
        print(f"[final-qa] unavailable ({type(e).__name__}: {str(e)[:150]})")
        report = {"ran": False, "error": str(e)[:200]}
    finally:
        try:
            json.dump(report, open(out_path, "w"), indent=2)
        except Exception:  # noqa: BLE001
            pass
    return report


def _persist_qa_to_memory(video_id, qa_report):
    """Write the final-QA verdict back into memory_<page>.json's history entry
    for this video, alongside the script-level `quality` rubric generate.py
    already stores there. Best-effort: a missing/malformed memory file or an
    entry not found (shouldn't happen -- generate.py always writes the entry
    before main.py runs) must never break the render."""
    if not video_id or not qa_report.get("ran"):
        return
    try:
        with open(MEMORY_PATH) as f:
            data = json.load(f)
        history = data.get("history", [])
        for h in history:
            if h.get("video_id") == video_id:
                h["final_qa"] = {
                    "footage_matches_narration": qa_report.get("footage_matches_narration"),
                    "visual_variety": qa_report.get("visual_variety"),
                    "caption_legible": qa_report.get("caption_legible"),
                    "narration_flow": qa_report.get("narration_flow"),
                    "biggest_issue": qa_report.get("biggest_issue", ""),
                    "audio_judged": qa_report.get("audio_judged", False),
                    "aborted": _qa_should_abort(qa_report),
                }
                with open(MEMORY_PATH, "w") as f:
                    json.dump(data, f, indent=2)
                return
    except Exception as e:  # noqa: BLE001 — best-effort, must never break the render
        print(f"[final-qa] could not persist to memory ({type(e).__name__}: {str(e)[:120]})")


def _groq_judge(intent, candidates, _allow_retry=True):
    """Pick the best-matching clip AND score its relevance 0-10, so a bad
    batch can be rejected outright instead of shipping the least-bad clip
    (the old picker could only choose among candidates, never veto them —
    which is how a belly-button macro ended up illustrating stomach acid).
    Returns (index, score) where score is an int 0-10, or the NO_KEY /
    UNRESOLVED sentinel above when no numeric score exists.

    One retry on an unparseable/empty reply: production logs showed three
    scenes in one render falling back to "first result" purely because the
    judge call returned something the regex couldn't parse -- not because
    the model actually judged the footage irrelevant. A single retry costs
    one extra Groq call only in that failure case."""
    if not os.environ.get("GROQ_API_KEY", ""):
        return 0, NO_KEY
    listing = "\n".join(f"{i}: {c['desc']}" for i, c in enumerate(candidates))
    txt = _groq_chat(
        f"A vertical short-form video scene narrates: \"{intent}\".\n"
        f"Candidate stock clips (index: description):\n{listing}\n"
        f"Pick the clip whose VISUAL SUBJECT best illustrates that narration.\n"
        f"Score it 0-10 using this rubric -- be strict, most stock-search results are "
        f"NOT a good fit and should score low:\n"
        f"0-2: different subject entirely, no visual connection to the narration. This INCLUDES "
        f"a clip showing a DIFFERENT animal, plant, object, or place than the one named (a stick "
        f"insect when the narration is about tree roots; a brick wall for fungus threads) — a "
        f"viewer instantly notices the mismatch, so score it low even if it shares a vague theme.\n"
        f"3-5: same broad theme but the wrong specific subject.\n"
        f"6-7: right general subject but a loose or generic shot of it.\n"
        f"8-10: the clip's actual visual subject directly matches what's narrated.\n"
        f"Reply with ONLY: index,score", model=JUDGE_MODEL)
    if txt:
        m = re.search(r"(\d+)\s*,\s*(\d+)", txt)
        if m:
            idx, score = int(m.group(1)), int(m.group(2))
            if 0 <= idx < len(candidates):
                return idx, min(score, 10)
    if _LAST_GROQ_FAILED:
        # The call didn't just return something unparseable -- it failed at the
        # transport level (429/5xx/network). Retrying immediately just burns
        # another rate-limited call; the judge is DOWN. Signal that so the
        # caller ships real footage (top result) instead of a text card.
        print("  judge: Groq unreachable (rate-limit/network) -- treating judge "
              "as unavailable, will ship top stock result")
        return 0, JUDGE_UNAVAILABLE
    if _allow_retry:
        print("  judge: unparseable/empty reply, retrying once...")
        return _groq_judge(intent, candidates, _allow_retry=False)
    print("  judge: unresolved after retry (key present, no parseable verdict) "
          "-- treating as below floor")
    return 0, UNRESOLVED


def _groq_requery(intent, failed_query):
    """When a search query returns nothing relevant, ask for replacements that
    a stock library can actually satisfy: concrete, filmable subjects."""
    txt = _groq_chat(
        f"A stock-video search for \"{failed_query}\" found nothing usable.\n"
        f"Suggest 2 alternative search queries (2-4 words each) for the SAME concrete subject "
        f"as \"{failed_query}\" — real, filmable things a videographer actually shoots (objects, "
        f"nature, people doing actions, weather, places). STAY ON THAT SUBJECT: do NOT switch to "
        f"a metaphor, figure of speech, or unrelated topic (e.g. keep a forest scene as forest "
        f"footage, never a literal city). No anatomical, microscopic, or abstract terms.\n"
        f"Reply with ONLY: query one | query two", max_tokens=30, temperature=0.4)
    if not txt:
        return []
    return [q.strip() for q in txt.split("|") if 1 <= len(q.strip().split()) <= 5][:2]



def _coverr_candidates(query):
    """Failover footage source. Dormant unless COVERR_API_KEY is set. Same shape as _pexels_candidates."""
    key = os.environ.get("COVERR_API_KEY", "")
    if not key:
        return []
    out = []
    try:
        q = urllib.parse.quote(query)
        data = _http_json(
            f"https://api.coverr.co/videos?query={q}&page_size=12",
            {"Authorization": f"Bearer {key}", "User-Agent": BROWSER_UA})
        for v in (data.get("hits") or data.get("videos") or []):
            vid = v.get("id")
            if vid in _used_video_ids:
                continue
            url = (v.get("urls") or {}).get("mp4") or v.get("mp4") or v.get("url")
            if url:
                out.append({"id": vid, "url": url, "desc": (v.get("title") or query), "source": "Coverr"})
    except Exception as e:
        print("  Coverr failed:", e)
    return out


def _gather_candidates(query):
    """Build the footage pool.

    Quality-first change: NASA SVS is not an outage fallback. For subjects that
    SVS can plausibly visualize (space/Earth/climate/atmosphere/ocean), its real
    scientific movies COMPETE with Pexels so the judge can choose authentic
    evidence instead of being forced to accept generic stock merely because
    Pexels returned something.
    """
    pexels = _pexels_candidates(query)
    if SCI_MEDIA.svs_relevant(query):
        try:
            svs = SCI_MEDIA.svs_candidates(query, used_ids=_used_video_ids, limit=3)
        except Exception as e:  # fully fail-soft; never let an external source break render
            print(f"  NASA SVS failed: {e}")
            svs = []
        if svs:
            print(f"  NASA SVS: {len(svs)} authentic scientific candidate(s) competing with stock")
            # Put authentic visualizations first for deterministic/keyword fast
            # paths, while retaining enough Pexels choices for a human-looking
            # shot when the scientific visualization is not the right beat.
            return svs + pexels[:8]

    return (pexels
            or _nasa_candidates(query)
            or _wikimedia_candidates(query)   # no key: archival/scientific clips
            or _archive_candidates(query)     # no key: Internet Archive documentary film
            or _coverr_candidates(query))     # Coverr dormant unless COVERR_API_KEY set


RELEVANCE_FLOOR = 4  # judge score below this = try a better query before settling.
                      # Was briefly 5, but combined with the stat-card fallback that
                      # made the judge reject SO much footage that whole videos
                      # collapsed into a slideshow of text cards (the "Crushing
                      # Pressure" video was 5 text cards in a row). A real, imperfect
                      # deep-sea clip beats another caption on a gradient -- 4 lets
                      # more genuine footage through, and MAX_STAT_CARDS below caps
                      # how many cards a single video can ever contain.
MAX_STAT_CARDS = 2   # a designed text card is a fine RARE accent, but a wall of them
                      # reads as cheap/broken. Once this many scenes have carded,
                      # every remaining weak scene takes its BEST-available real clip
                      # (fetch_clip accept_best=True) instead of carding again.
SOFT_VIDEO_FLOOR = 3  # "more VIDEO, fewer photos" (user ask): a MOVING clip that is at
                      # least roughly on-topic (judge >= this, just under RELEVANCE_FLOOR)
                      # beats a STATIC archival photo or a text card for a fast-paced feed.
                      # build_scene now prefers the best real video down to this score and
                      # only falls to a still/card when even the best video is below it
                      # (genuinely off-topic) — so photos become the rare exception, not a
                      # routine fallback. Set SOFT_VIDEO_FLOOR=RELEVANCE_FLOOR to disable.

FETCH_BUDGET_S = 45     # wall-clock cap for one fetch_clip() call (search + judge +
                        # requery rounds). Two rescue rounds instead of one means more
                        # network round trips per scene; bound it the same way
                        # NASA_BUDGET_S bounds its own fallback source, so a slow judge
                        #/search chain can't stall the whole render.
MAX_FETCH_QUERIES = 5   # original query + up to two requery rounds of ~2 queries each

JUDGE_SCORES = []      # every scene's best judged score this render (None excluded);
                        # printed as a min/avg summary at the end for quick QA of a run


def _clip_luma(path, stride=20, n=12):
    """(avg_luma, min_luma) sampled across the clip — every `stride`-th frame,
    up to `n` samples, so it spans ~8s instead of only the first fraction of a
    second. Returns (None, None) on any probe error (fully fail-safe: callers
    treat that as 'accept / no lift'). Luma is 0-255."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-vf",
             f"select='not(mod(n\\,{stride}))',"
             "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
             "-frames:v", str(n), "-f", "null", "-"],
            capture_output=True, text=True, timeout=20).stderr
        vals = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", out)]
        if not vals:
            return (None, None)
        return (sum(vals) / len(vals), min(vals))
    except Exception:
        return (None, None)


def _clip_too_dark(path, min_avg=24.0, min_floor=7.0):
    """True only if a clip is genuinely near-black — the "goes to a black
    screen" complaint. Rejects on a dark AVERAGE *or* a near-black STRETCH
    (min_floor): the run-105 lab clip passed the old average-only check but
    still had a ~2s black span under a caption. Dim-but-visible night/ocean/
    space clips are NOT rejected here — they're kept and brightened by
    `_shadow_lift_filter` instead, so science footage never collapses into a
    wall of text cards. Fail-safe: a probe error returns False (accept)."""
    avg, mn = _clip_luma(path)
    if avg is None:
        return False
    return avg < min_avg or mn < min_floor


def _shadow_lift_filter(avg_luma, target=58.0):
    """Pure helper (no ffmpeg) → an eq brightness/gamma snippet that lifts a
    dim clip toward `target` luma, or '' if it's already bright enough or
    unknown. Gamma does most of the work (opens shadows without washing out
    highlights); a small brightness nudge finishes it. Both are capped so a
    legitimately moody clip is made LEGIBLE, not flat/grey.

    Returns a snippet with a TRAILING comma and NO leading comma, because it is
    inserted between _motion_filter's output (which always ends in a comma) and
    the grade (which has no leading comma): `...lanczos,` + `eq=...,` + `eq=grade`.
    A leading comma here would double up (`,,`) and make ffmpeg fail the scene."""
    if avg_luma is None or avg_luma >= target:
        return ""
    deficit = (target - avg_luma) / target          # 0..1, bigger = darker
    gamma = 1.0 + min(0.55, deficit * 0.9)          # ≤1.55
    bright = min(0.10, deficit * 0.16)              # ≤0.10
    return f"eq=gamma={gamma:.3f}:brightness={bright:.3f},"


def _accept(chosen, dest, query, score):
    _download(chosen["url"], dest)
    if _clip_too_dark(dest):
        # skip near-black footage; the caller requeries for a brighter clip, and
        # if nothing brighter is found it falls back to a (now non-black) card.
        raise RuntimeError(f"clip too dark (near-black) — skipping for '{query}'")
    _used_video_ids.add(chosen["id"])
    _used_history.append(chosen["id"])
    tag = (f"judge {score}/10" if isinstance(score, int)
           else "keyword match (no LLM)" if score == KEYWORD_OK
           else "first (no judge key)")
    print(f"  {chosen['source']} SUCCESS ({tag}, id {chosen['id']}): {query}")
    return True


KEYWORD_OK = "keyword_match"   # accepted by the local keyword pre-check, no LLM call


def _relevance_words(text):
    """Content words (>2 chars, non-stopword) of a query or clip description,
    used for the zero-LLM footage relevance pre-check."""
    return {w for w in re.findall(r"[a-z]+", (text or "").lower())
            if len(w) > 2 and w not in _QUERY_STOPWORDS}


def _subject_word(query):
    """The query's SUBJECT — its first content word, in order (e.g. 'octopus' out
    of 'octopus blood vessels'). Every scene search_query is written subject-first
    ('octopus swimming ocean', 'tree communication'), so this reliably names the
    one animal/object/place the clip actually needs to show. Returns '' if the
    query has no content word at all."""
    for w in re.findall(r"[a-z]+", (query or "").lower()):
        if len(w) > 2 and w not in _QUERY_STOPWORDS:
            return w
    return ""


def _best_keyword_match(query, cands, min_overlap=0.5, min_shared=2):
    """Index of the candidate whose OWN description clearly matches the query
    SUBJECT by keyword overlap — or None if none clears the bar (ambiguous, so
    fall back to the LLM judge). This lets the common case (a specific query
    like 'ocean surface waves' returning a clip slugged 'ocean waves drone
    aerial') skip the LLM judge entirely, keeping footage OFF the quota critical
    path. It's conservative: it only accepts on a clear lexical match, so an
    off-topic clip (e.g. a 'dubai skyline' for a forest query) shares no words
    and still goes to the judge. Returns None when the query has too few content
    words to decide locally."""
    qw = _relevance_words(query)
    if len(qw) < 2:
        return None
    # SUBJECT REQUIRED: a candidate must name the query's actual subject (e.g.
    # 'octopus'), not just share OTHER words with it. Without this, a sea turtle
    # clip cleared "octopus swimming ocean" purely on "swimming"+"ocean" (frac
    # 0.67, shared 2) and shipped as an octopus video's HOOK shot with zero LLM
    # judge ever looking at it — the animal itself was never checked.
    subject = _subject_word(query)
    best_i, best_frac, best_shared = None, 0.0, 0
    for i, c in enumerate(cands):
        desc_words = _relevance_words(c.get("desc", ""))
        if subject and subject not in desc_words:
            continue
        shared = len(qw & desc_words)
        frac = shared / len(qw)
        if frac > best_frac or (frac == best_frac and shared > best_shared):
            best_i, best_frac, best_shared = i, frac, shared
    if best_i is not None and best_frac >= min_overlap and best_shared >= min_shared:
        return best_i
    return None


def fetch_clip(query, dest, intent=None, accept_best=False):
    """Search -> judge -> (if judged irrelevant) rewrite the query and retry, up
    to two rescue rounds, bounded by FETCH_BUDGET_S/MAX_FETCH_QUERIES so being
    picky can't stall the render. Nothing clearing RELEVANCE_FLOOR is no longer
    shipped anyway -- the old "ship the least-bad clip" fallback is exactly how
    a belly-button macro ended up illustrating stomach acid; now the caller
    renders a designed stat-card scene instead of a bad clip or a black card.

    A judge verdict of UNRESOLVED (key present, but no parseable score after
    the retry) is treated the same as a below-floor numeric score -- it does
    NOT auto-accept. Only NO_KEY (judging genuinely unavailable) still falls
    back to shipping the first candidate; that's the one case where there is
    no better option. Conflating the two used to mean an unresolved judge
    call silently shipped the first, unverified candidate (scene 7's bug).

    Returns (accepted: bool, best_score: int|None). best_score is the best
    NUMERIC judge score seen across all rounds (None if nothing was ever
    judged with a number), used both by the caller's stat-card decision and
    the end-of-render quality summary."""
    intent = intent or query
    best_score = None
    best_cand = None   # remember the best clip seen so a beyond-cap scene (accept_best)
    best_q = None      # can still use REAL footage instead of another text card
    queries = [query]
    deadline = time.time() + FETCH_BUDGET_S
    round_no = 0
    while round_no < len(queries) and round_no < MAX_FETCH_QUERIES:
        if time.time() > deadline:
            print("  fetch budget exceeded, stopping search")
            break
        q = queries[round_no]
        cands = _gather_candidates(q)
        if cands:
            # ZERO-LLM FAST PATH: if a candidate's own description clearly matches
            # the query subject, accept it WITHOUT an LLM judge call. This is the
            # common case and keeps footage off the quota critical path — the LLM
            # judge is now only spent on genuinely ambiguous scenes.
            ki = _best_keyword_match(q, cands)
            if ki is not None:
                try:
                    _accept(cands[ki], dest, q, KEYWORD_OK)
                    return True, best_score
                except Exception as e:  # too-dark / download failed → let the judge try
                    print(f"  keyword-matched clip unusable ({e}) — falling to judge")
            # VISION FIRST: let Gemini actually look at the thumbnails and pick the
            # visual match; fall back to the text (slug) judge if vision is off/fails.
            _vj = _gemini_vision_pick(intent, cands)
            idx, score = _vj if _vj is not None else _groq_judge(intent, cands)
            chosen = cands[idx]
            numeric = isinstance(score, int)
            if numeric and (best_score is None or score > best_score):
                best_score = score
                best_cand, best_q = chosen, q
            if score in (NO_KEY, JUDGE_UNAVAILABLE) or (numeric and score >= RELEVANCE_FLOOR):
                # NO_KEY / JUDGE_UNAVAILABLE: judging is impossible right now, so
                # ship the top stock result (Pexels' own ranking) rather than a
                # text card. A real, on-query clip beats a gradient card and
                # keeps a transient Groq 429 from aborting the whole render.
                try:
                    _accept(chosen, dest, q, score)
                    if best_score is not None:
                        JUDGE_SCORES.append(best_score)
                    return True, best_score
                except Exception as e:
                    print("  download failed:", e)
            elif score == UNRESOLVED:
                print(f"  judge unresolved for '{q}' — trying a better query")
            else:
                print(f"  weak match ({score}/10) for '{q}' — trying a better query")
        else:
            print(f"  no results for '{q}'")
        # rescue rounds: ask for stock-native rewrites, up to twice (after the
        # original query, and again after the first rescue round if still weak)
        if round_no < 2 and len(queries) < MAX_FETCH_QUERIES:
            for q2 in _groq_requery(intent, q):
                if q2 not in queries:
                    queries.append(q2)
        round_no += 1
    if best_score is not None:
        JUDGE_SCORES.append(best_score)
    # Prefer the best REAL VIDEO over a static photo/card: if we saw a clip that
    # was at least roughly on-topic (>= SOFT_VIDEO_FLOOR), ship it with motion
    # rather than freeze on an archival still. Only genuinely off-topic video
    # (below the soft floor) falls through to a still/card. This is the "more
    # video, fewer photos" preference — a moving clip beats a frozen image.
    if accept_best and best_cand is not None and (best_score is None or best_score >= SOFT_VIDEO_FLOOR):
        try:
            _accept(best_cand, dest, best_q, best_score)
            print(f"  accept-best ({best_score}/10) — a real moving clip beats a static photo/card")
            return True, best_score
        except Exception as e:  # noqa: BLE001 - fall through to card on download failure
            print("  accept-best download failed:", e)
    print(f"  No footage cleared the floor for '{query}' (best {best_score}/10)"
          if best_score is not None else f"  No footage found for '{query}'")
    return False, best_score


# ---------- PER-SCENE VIDEO (motion + color grade) ----------
# Zoom anchor presets for zoom_in/zoom_out (dead-center plus four off-center
# points). Previously zoom_in/zoom_out passed no x/y to zoompan at all, which
# defaults to 0,0 -- i.e. every "zoom" actually crept toward the top-left
# corner instead of the frame center. Fixed here, and cycled per scene so
# consecutive same-kind scenes don't play as pixel-identical zooms.
_ZOOM_ANCHORS = [
    ("(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),    # center
    ("(iw-iw/zoom)/2", "(ih-ih/zoom)*0.32"),  # upper third
    ("(iw-iw/zoom)*0.34", "(ih-ih/zoom)/2"),  # left-biased
    ("(iw-iw/zoom)*0.66", "(ih-ih/zoom)/2"),  # right-biased
    ("(iw-iw/zoom)/2", "(ih-ih/zoom)*0.68"),  # lower third
]

_last_motion_kind = None  # sequential across build_scene calls within one render


def _motion_filter(scene, frames, zspeed, idx=0, prev_kind=None):
    """Per-scene motion, driven by generate.py's scene['motion'] (zoom_in/zoom_out/
    pan/static) instead of always applying the same zoom-in — same field the LLM
    already picks for visual variety, previously ignored here.

    idx/prev_kind add deterministic variety: when this scene's motion kind
    repeats the previous scene's, the zoom anchor (or pan direction) is nudged
    so two back-to-back zoom_ins don't render as the identical move."""
    kind = scene.get("motion", "zoom_in")
    repeat = prev_kind is not None and kind == prev_kind
    anchor_i = (idx + (1 if repeat else 0)) % len(_ZOOM_ANCHORS)
    ax, ay = _ZOOM_ANCHORS[anchor_i]
    # SUPERSAMPLED KEN BURNS — fixes the "vibrating"/shaking zoom. zoompan rounds
    # its crop window to WHOLE pixels every frame, so at the final 1080x1920 each
    # frame lands a pixel or two off from a perfectly smooth path and the image
    # jitters. Render the move on a 2x canvas (2160x3840), where one pixel is half
    # the size, then lanczos-downscale to target: the integer steps collapse into
    # smooth sub-pixel motion. `static` has no motion so it skips the supersample.
    # COVER-then-crop (force_original_aspect_ratio=increase): scale so the frame
    # is at LEAST the target box in BOTH dimensions, then center-crop to exact.
    # The old `scale=-2:{H}` only guaranteed the HEIGHT — a source TALLER than
    # 9:16 (e.g. a 1080x2048 clip) then scaled to a width < the crop width, and
    # `crop` aborted the whole render with "Invalid too big size for width"
    # (run 108, "two metal paperclips"). increase+crop is aspect-ratio-safe for
    # any source shape (portrait, landscape, or odd).
    if kind == "static":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
    W2, H2 = W * 2, H * 2
    up = f"scale={W2}:{H2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W2}:{H2},"
    down = f"scale={W}:{H}:flags=lanczos,"
    if idx == 0:
        # HOOK PUNCH-IN: the first ~0.8s pushes in faster (1.03 -> 1.14) to stop a
        # scrolling viewer, then eases into a slow creep to 1.20. Any non-static
        # hook gets this energy regardless of the LLM's assigned motion. Same
        # supersampled path, so the faster move still renders smooth.
        hz = "if(lte(on,24),1.03+0.11*on/24,min(1.14+(on-24)*0.0006,1.20))"
        return up + f"zoompan=z='{hz}':x='{ax}':y='{ay}':d={frames}:s={W2}x{H2}:fps=30," + down
    if kind == "zoom_out":
        z = f"if(lte(on,3),1.12,max(zoom-{zspeed},1.06))"
        return up + f"zoompan=z='{z}':x='{ax}':y='{ay}':d={frames}:s={W2}x{H2}:fps=30," + down
    if kind == "pan":
        # fixed mild zoom, slide across the frame; direction flips on repeat
        # (or alternates by index) instead of always going left->right
        reverse = (idx % 2 == 1) if not repeat else (idx % 2 == 0)
        x_expr = (f"(iw-iw/zoom)*on/{frames}" if not reverse
                  else f"(iw-iw/zoom)*(1-on/{frames})")
        return (up + f"zoompan=z='1.09':x='{x_expr}':"
                     f"y='(ih-ih/zoom)/2':d={frames}:s={W2}x{H2}:fps=30," + down)
    z = f"if(lte(on,3),1.06,min(zoom+{zspeed},1.12))"  # zoom_in (default)
    return up + f"zoompan=z='{z}':x='{ax}':y='{ay}':d={frames}:s={W2}x{H2}:fps=30," + down


# ---------- TYPOGRAPHIC STAT-CARD SCENES ----------
# When fetch_clip can't find anything relevant, this renders a designed card
# instead: dark gradient background, huge bold centered text, the same
# Ken Burns motion as real footage, subtle vignette. Same W/H/fps/duration
# contract as build_scene's other two paths so concat doesn't care which one
# produced a given scene file.

STAT_CARD_PALETTES = [  # (c0, c1) passed to ffmpeg's `gradients` source filter
    ("#050414", "#1b1140"),  # near-black -> deep indigo
    ("#020617", "#0d2b3d"),  # near-black -> deep teal
    ("#0a0410", "#2e0f30"),  # near-black -> deep plum
    ("#04070a", "#123322"),  # near-black -> deep forest
    ("#0c0402", "#3a1508"),  # near-black -> deep ember
    ("#050505", "#232323"),  # near-black -> graphite
]


def _stat_card_text(scene):
    """Pick the text for the card: on_screen_text if it exists and is short
    enough to read as a headline, else a trimmed key phrase from the
    voiceover."""
    t = (scene.get("on_screen_text") or "").strip()
    if not t or len(t) > 42:
        # a "key phrase," not a paragraph -- cap word count so the card stays
        # a punchy headline instead of wrapping into a wall of text
        vo = (scene.get("voiceover") or "").strip()
        words = vo.split()
        t = " ".join(words[:7]) if words else t
    t = t.upper()
    # '%' trips ffmpeg drawtext's %{...} expansion syntax ("Stray % near ..")
    # and silently drops the text instead of erroring -- a card rendering
    # nothing but its background is worse than one that just spells PERCENT.
    t = t.replace("%", " PERCENT")
    t = re.sub(r"[^A-Z0-9 .,\-'!?]", "", t).strip()
    t = re.sub(r"\s+", " ", t)
    return t[:56] or "SCIENCE"


def _fit_text_block(text, max_w, max_h, max_fs=190, min_fs=54, step=4,
                     char_w_ratio=0.72, line_h_ratio=1.28):
    """Auto-wrap + auto-shrink: pick the largest fontsize (in `step`
    decrements) whose wrapped block fits within max_w x max_h, using a
    DejaVu Sans Bold average-advance-width ratio measured directly off real
    rendered frames via ffmpeg's `bbox` filter (see scratch notes) rather
    than a guess -- char_w_ratio=0.72 has margin above the ~0.66 average
    measured, so wraps err toward wrapping a little early rather than
    overflowing the frame. Falls back to the smallest size tried if nothing
    fits (long text is already truncated by _stat_card_text)."""
    words = text.split() or ["SCIENCE"]
    fallback = None
    for fs in range(max_fs, min_fs - 1, -step):
        max_chars = max(3, int(max_w / (fs * char_w_ratio)))
        lines, line = [], []
        for w in words:
            trial = " ".join(line + [w])
            if not line or len(trial) <= max_chars:
                line.append(w)
            else:
                lines.append(" ".join(line)); line = [w]
        if line:
            lines.append(" ".join(line))
        fallback = (fs, lines)
        widest = max((len(l) for l in lines), default=0)
        block_h = len(lines) * fs * line_h_ratio
        if block_h <= max_h and widest * fs * char_w_ratio <= max_w:
            return fs, lines
    return fallback


def _stat_card_safe_zone():
    """Pick a vertical center + max block height for the card's text that
    avoids the karaoke caption band. Captions render on top of every scene
    (stat-cards included) at PROFILE['cap_y'], which moves a lot per profile
    (top-positioned for dark_mystery, eye-level for science, lower-third for
    history_pov) -- a fixed centered placement collides with captions on
    some profiles. The existing footage-scene number-card overlay
    (_stat_overlay) sidesteps this the same way, at a fixed y=h*0.18; this
    picks whichever half of the frame is farther from the caption band and
    sizes the block to fit inside it."""
    cap_y = PROFILE.get("cap_y", H * 0.4)
    excl_half = PROFILE.get("cap_size", 120) * 1.3
    zone_top, zone_bot = cap_y - excl_half, cap_y + excl_half
    margin = H * 0.05
    top_span = max(0.0, zone_top - margin)
    bot_span = max(0.0, (H - margin) - zone_bot)
    if top_span >= bot_span:
        center, avail = margin + top_span / 2, top_span
    else:
        center, avail = zone_bot + bot_span / 2, bot_span
    max_h = max(H * 0.16, min(H * 0.42, avail * 0.92))
    return center, max_h


def _build_stat_card(scene, idx, seg_mp3, seg_dur, out_path, motion):
    """Render one typographic stat-card scene. Raises on any ffmpeg failure
    so the caller can fall back to a plain color card -- this must never be
    the reason a render dies."""
    text = _stat_card_text(scene)
    max_w = int(W * 0.86)
    center_y, max_h = _stat_card_safe_zone()
    fontsize, lines = _fit_text_block(text, max_w, max_h)
    txt_path = os.path.join(WORK, f"s{idx}_card.txt")
    with open(txt_path, "w") as f:
        f.write("\n".join(lines))

    c0, c1 = STAT_CARD_PALETTES[(idx - 1) % len(STAT_CARD_PALETTES)]
    line_h = fontsize * 1.28
    block_h = line_h * len(lines)
    accent_y = f"{center_y:.1f}+{block_h / 2:.1f}+34"

    vf = (
        f"{motion}"
        f"vignette=PI/5.2,"
        f"drawtext=textfile='{txt_path}':fontfile='{FONT}':fontsize={fontsize}:"
        f"fontcolor=white:borderw=10:bordercolor=black@0.75:line_spacing=18:"
        f"x=(w-tw)/2:y=({center_y:.1f})-(th/2):alpha='if(lt(t,0.3),t/0.3,1)',"
        f"drawbox=x=(iw-140)/2:y='{accent_y}':w=140:h=6:color=white@0.8:t=fill,"
        f"setsar=1"
    )
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i",
         f"gradients=s={W}x{H}:d={seg_dur:.3f}:r=30:c0={c0}:c1={c1}:type=radial:"
         f"speed=0.006:seed={1000 + idx}",
         "-i", seg_mp3, "-t", f"{seg_dur:.3f}",
         "-filter_complex", f"[0:v]{vf}[v]",
         "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", out_path])


STAT_CARD_SCENES = 0  # count of scenes rendered as typographic cards this render,
                       # for the end-of-render quality summary


ARCHIVAL_SCENES = 0  # scenes rendered from an Openverse archival still this render


def _openverse_image(query, dest):
    """Fetch a Creative-Commons / public-domain STILL from Openverse (Hubble,
    NASA, microscopy, archival photography) for a scene where stock VIDEO failed.
    A real archival image with Ken Burns motion beats a gradient text card AND
    gives the page a documentary/scientific look that generic-stock pages don't
    have (idea 3 in PLATFORM.md). Downloads a jpg to `dest`; returns True on
    success, never raises. No API key required."""
    try:
        q = urllib.parse.quote(query.strip()[:80])
        # category=photograph EXCLUDES illustrations / diagrams / infographics —
        # an ungated archival search returned a busy "collision of a protosolar
        # mass" infographic for a GPS video (run 112). We only ever want a real
        # photo here; if there's no photo the caller falls through to Wikimedia /
        # AI image / a clean stat-card, all of which beat a random diagram.
        url = (f"https://api.openverse.org/v1/images/?q={q}"
               f"&license_type=commercial&category=photograph&page_size=8&mature=false")
        req = urllib.request.Request(url, headers={"User-Agent": "content-render/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        for res in (data.get("results") or []):
            img = res.get("url") or res.get("thumbnail")
            if not img:
                continue
            try:
                ireq = urllib.request.Request(img, headers={"User-Agent": "content-render/1.0"})
                with urllib.request.urlopen(ireq, timeout=20) as ir:
                    blob = ir.read()
                if len(blob) > 8000:  # skip tiny/placeholder images
                    with open(dest, "wb") as f:
                        f.write(blob)
                    return True
            except Exception:
                continue
    except Exception as e:
        print(f"  openverse lookup failed ({e})")
    return False


_INATURALIST_OK_LICENSES = {"cc0", "cc-by"}


def _inaturalist_safe_photo_url(photo):
    """Pure helper (no network): given one photo dict from the iNaturalist API,
    return a full-size download URL if — and only if — that SPECIFIC photo's own
    license_code is commercial-safe, else None. Most iNaturalist observations are
    cc-by-nc (non-commercial); the API's `photo_license` query filter is not
    trusted alone here (defense against it being imperfectly enforced) — every
    candidate is re-checked photo-by-photo. Also upgrades the API's tiny 'square'
    thumbnail URL to the 'large' size (same S3 path, filename swapped)."""
    if (photo.get("license_code") or "").lower() not in _INATURALIST_OK_LICENSES:
        return None
    square = photo.get("url") or ""
    if not square:
        return None
    return square.replace("square.jpg", "large.jpg").replace("square.jpeg", "large.jpeg")


def _inaturalist_image(query, dest):
    """FIRST archival-STILL source, tried before Openverse/Wikimedia: iNaturalist,
    a citizen-science biodiversity platform, no API key, explicitly built for
    automated/app use (unlike Pixabay, whose terms prohibit unattended calls —
    see _archive_candidates). For our animal-heavy topic bank (most facts are a
    specific species), a real species-verified observation photo beats a generic
    keyword-matched Openverse/Wikimedia result or an AI guess — this is the
    difference between an actual pistol shrimp and stock library's best guess at
    'shrimp'. Non-animal/plant topics simply return no results and fall through
    to the next source, so this is a pure addition, never a regression.

    2026-08-03: live-tested before building this — most iNaturalist observations
    are cc-by-nc (non-commercial, unusable on a monetized channel), so the
    `photo_license` query param is NOT trusted alone; each candidate photo's own
    `license_code` is re-checked before download (defense against the query
    filter being imperfectly enforced). Downloads a jpg to `dest`; returns True
    on success, never raises."""
    try:
        q = urllib.parse.quote(query.strip()[:80])
        url = ("https://api.inaturalist.org/v1/observations"
               f"?q={q}&photos=true&photo_license=cc0,cc-by&per_page=10&order_by=votes")
        req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        for res in (data.get("results") or []):
            for p in (res.get("photos") or []):
                img = _inaturalist_safe_photo_url(p)
                if not img:
                    continue
                try:
                    ireq = urllib.request.Request(img, headers={"User-Agent": WIKI_UA})
                    with urllib.request.urlopen(ireq, timeout=20) as ir:
                        blob = ir.read()
                    if len(blob) > 8000:  # skip tiny/placeholder images
                        with open(dest, "wb") as f:
                            f.write(blob)
                        return True
                except Exception:
                    continue
    except Exception as e:
        print(f"  iNaturalist image lookup failed ({e})")
    return False


# Wikimedia Commons requires a descriptive User-Agent identifying the tool (a
# generic/absent UA gets 403'd per their API etiquette policy).
WIKI_UA = "content-render/1.0 (https://github.com/werriesjacob1-cmyk/content-render)"
WIKI_MAX_VIDEO_BYTES = 60 * 1024 * 1024  # skip full-length archival films; we only
                                         # need a few loopable seconds per scene


def _wikimedia_image(query, dest):
    """Second archival-STILL source alongside Openverse. Wikimedia Commons is the
    largest free/public-domain media library there is — real Hubble frames,
    microscopy, scientific diagrams, historical photographs — exactly the kind of
    imagery that makes a science page look like a documentary instead of the same
    stock B-roll everyone else uses. No API key. Downloads a scaled (<=1280px)
    thumbnail so we never pull a 40MP original. Returns True on success."""
    try:
        q = urllib.parse.quote(f"{query.strip()[:80]} filetype:bitmap")
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               f"&generator=search&gsrsearch={q}&gsrnamespace=6&gsrlimit=8"
               "&prop=imageinfo&iiprop=url|mime&iiurlwidth=1280")
        data = _http_json(url, {"User-Agent": WIKI_UA}, timeout=20)
        pages = ((data.get("query") or {}).get("pages") or {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            img = info.get("thumburl") or (info.get("url") if mime in ("image/jpeg", "image/png") else None)
            if not img:
                continue
            try:
                ireq = urllib.request.Request(img, headers={"User-Agent": WIKI_UA})
                with urllib.request.urlopen(ireq, timeout=20) as ir:
                    blob = ir.read()
                if len(blob) > 8000:  # skip tiny/placeholder images
                    with open(dest, "wb") as f:
                        f.write(blob)
                    return True
            except Exception:
                continue
    except Exception as e:
        print(f"  wikimedia image lookup failed ({e})")
    return False


def _wikimedia_candidates(query):
    """No-key VIDEO source (Wikimedia Commons). Public-domain / CC archival and
    scientific clips (mission footage, nature, microscopy, historical film) that
    generic stock libraries don't carry — a distinctiveness lever. Files are
    .webm/.ogv/.mp4 (all ffmpeg-decodable); skips anything over
    WIKI_MAX_VIDEO_BYTES so a full-length film can't stall the render or fill the
    disk. Bounded like the NASA source."""
    out = []
    deadline = time.time() + 15
    try:
        q = urllib.parse.quote(f"{query.strip()[:80]} filetype:video")
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               f"&generator=search&gsrsearch={q}&gsrnamespace=6&gsrlimit=10"
               "&prop=imageinfo&iiprop=url|mime|size")
        data = _http_json(url, {"User-Agent": WIKI_UA}, timeout=15)
        pages = ((data.get("query") or {}).get("pages") or {})
        for page in pages.values():
            if time.time() > deadline:
                break
            pid = page.get("pageid")
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime", "")
            vurl = info.get("url")
            size = info.get("size") or 0
            if (not vurl or pid in _used_video_ids or not mime.startswith(("video/", "application/ogg"))
                    or (size and size > WIKI_MAX_VIDEO_BYTES)):
                continue
            title = (page.get("title") or "").replace("File:", "")
            out.append({"id": pid, "url": vurl, "desc": title[:200], "source": "Wikimedia"})
    except urllib.error.HTTPError as e:
        print(f"  Wikimedia HTTP {e.code}: {e.read().decode()[:160]}")
    except Exception as e:
        print("  Wikimedia failed:", e)
    return out


ARCHIVE_MAX_VIDEO_BYTES = 45 * 1024 * 1024  # Internet Archive holds full-length
                                            # films; only take a small derivative
                                            # (we loop a few seconds anyway)
ARCHIVE_ITEM_LIMIT = 5      # metadata round-trips are the cost; cap how many items
ARCHIVE_BUDGET_S = 18       # hard wall-clock cap for the whole source (like NASA)


def _archive_candidates(query):
    """No-key VIDEO source: the Internet Archive (archive.org). Public-domain /
    openly-licensed archival & documentary film that stock libraries simply don't
    have — the strongest 'we don't look like every other faceless page' lever.
    Two-step API like NASA: advancedsearch gives movie identifiers, then each
    item's metadata lists its files; we pick the SMALLEST real .mp4 under
    ARCHIVE_MAX_VIDEO_BYTES (IA also stores multi-GB masters, so size-gating is
    mandatory — an unbounded pick would stall the render or fill the disk).
    Bounded by ARCHIVE_BUDGET_S so a slow item can't hang the run."""
    out = []
    deadline = time.time() + ARCHIVE_BUDGET_S
    try:
        q = urllib.parse.quote(f"{query.strip()[:80]} AND mediatype:movies")
        url = (f"https://archive.org/advancedsearch.php?q={q}"
               "&fl[]=identifier&fl[]=title&rows=8&output=json")
        docs = (_http_json(url, {"User-Agent": WIKI_UA}, timeout=12)
                .get("response", {}).get("docs", []))
        for doc in docs[:ARCHIVE_ITEM_LIMIT]:
            if time.time() > deadline:
                break
            ident = doc.get("identifier")
            if not ident or ident in _used_video_ids:
                continue
            try:
                meta = _http_json(f"https://archive.org/metadata/{ident}",
                                  {"User-Agent": WIKI_UA}, timeout=10)
            except Exception:
                continue
            # smallest playable mp4 within the size cap (h.264 derivatives are
            # small; masters are huge and get skipped)
            best = None
            for f in meta.get("files", []):
                name = f.get("name", "")
                if not name.lower().endswith(".mp4"):
                    continue
                size = int(f.get("size", 0) or 0)
                if size == 0 or size > ARCHIVE_MAX_VIDEO_BYTES:
                    continue
                if best is None or size < best[1]:
                    best = (name, size)
            if best:
                out.append({
                    "id": ident,
                    "url": f"https://archive.org/download/{ident}/{urllib.parse.quote(best[0])}",
                    "desc": (doc.get("title") or query)[:200],
                    "source": "Archive",
                })
    except urllib.error.HTTPError as e:
        print(f"  Archive HTTP {e.code}: {e.read().decode()[:160]}")
    except Exception as e:
        print("  Archive failed:", e)
    return out


_QUERY_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "at", "is", "are", "was", "were", "be", "and",
    "but", "or", "so", "that", "this", "these", "those", "it", "its", "as", "by", "for", "with",
    "from", "into", "your", "you", "we", "our", "their", "they", "not", "even", "more", "most",
    "than", "then", "when", "where", "why", "how", "what", "which", "can", "could", "would",
    "will", "just", "only", "about", "over", "under", "up", "down", "out", "same", "one", "two",
    "here", "there", "part", "thing", "things", "actually", "really", "very",
    # non-visual fillers/adverbs/light-verbs that leak in and make un-searchable
    # queries (e.g. 'underground threads almost'); keep only concrete nouns
    "almost", "all", "also", "both", "each", "many", "much", "some", "any", "none", "every",
    "lives", "live", "lived", "fine", "made", "make", "makes", "making", "use", "used", "using",
    "know", "known", "knows", "never", "always", "still", "like", "such", "being", "been",
    "have", "has", "had", "does", "did", "done", "goes", "going", "went", "come", "comes",
    "came", "take", "takes", "took", "give", "gives", "gave", "keep", "become", "becomes",
    "seem", "seems", "look", "looks", "feel", "think", "means", "without", "within", "around",
    "across", "through", "because", "while", "during", "before", "after", "since", "until",
    "again", "once", "could", "should", "might", "must", "also", "them", "who", "whom",
}


def _keywords_from_text(text, k=3):
    """Pull the k most salient (longest, non-stopword) words from a scene's
    voiceover to seed a fresh footage search — a scene that lazily reused an
    earlier scene's query gets a query that reflects what THIS scene is about."""
    words = re.findall(r"[A-Za-z][A-Za-z-]+", (text or "").lower())
    cand = [w for w in words if w not in _QUERY_STOPWORDS and len(w) > 3]
    # keep original order but prefer longer/rarer words; de-dup preserving order
    seen, ordered = set(), []
    for w in sorted(cand, key=len, reverse=True):
        if w not in seen:
            seen.add(w); ordered.append(w)
    return " ".join(ordered[:k])


def _diversify_scene_queries(scenes):
    """Guarantee every scene searches for a VISUALLY DISTINCT subject. The LLM is
    told to do this, but a rate-limited/near-miss script sometimes repeats a
    search_query (run 53: scenes 2 AND 6 both 'sunlight water droplets', so the
    end lingered ~20s on the same footage). When a query repeats an earlier
    scene's, rebuild it from that scene's own voiceover keywords; if that still
    collides or is empty, fall back to the on_screen_text. Purely additive — a
    script with already-distinct queries is left untouched."""
    seen = {}
    for i, sc in enumerate(scenes, 1):
        q = (sc.get("search_query") or "").strip()
        key = q.lower()
        if key and key not in seen:
            seen[key] = i
            continue
        # duplicate (or empty) — derive a fresh, scene-specific query
        alt = _keywords_from_text(sc.get("voiceover", ""))
        if not alt or alt.lower() in seen:
            alt = (sc.get("on_screen_text") or alt or q).strip()
        if alt and alt.lower() != key:
            print(f"  [footage] scene {i} query '{q}' duplicated scene {seen.get(key)} "
                  f"— diversified to '{alt}'")
            sc["search_query"] = alt
            seen[alt.lower()] = i
        else:
            seen[key] = seen.get(key, i)


def _diversify_scene_motions(scenes):
    """Force at least one 'pan' into a video whose LLM-picked motions never use
    one (2026-08-03 craft-audit finding: 8 sampled real manifests included one
    with 7 scenes as [zoom_in,zoom_out,zoom_out,zoom_in,zoom_out,zoom_out,
    zoom_in] -- zoom-only for the entire ~40s). generate.py's validate() only
    replaces an INVALID motion value; a valid-but-monotonous set passes
    straight through untouched, and _motion_filter's own repeat-avoidance only
    nudges the zoom ANCHOR on a repeat, never the move itself. Skips scene 1
    (the hook gets its own punch-in treatment regardless of 'motion') and the
    last scene (the payoff shouldn't rest on a pan). Purely additive — a
    script that already varies motion is left untouched."""
    if not isinstance(scenes, list) or len(scenes) < 5:
        return
    if any(sc.get("motion") == "pan" for sc in scenes):
        return
    i = max(1, min(len(scenes) - 2, (len(scenes) * 2) // 3))
    old = scenes[i].get("motion")
    scenes[i]["motion"] = "pan"
    print(f"  [motion] scene {i + 1} had no 'pan' anywhere in this video's motion "
          f"sequence (was all zoom/static) — diversified scene {i + 1} from "
          f"'{old}' to 'pan'")


# ---------- AI-GENERATED ILLUSTRATIONS, FREE FIRST (Pollinations), PAID FALLBACK (Imagen) ----------
# When real footage AND archival stills both fail for a scene, generate an EXACT,
# on-topic vertical image instead of dropping to a plain text card — the single
# biggest fix for "the footage doesn't match what's being said". Best-effort:
# any failure (no billing, safety block, wrong model, network) falls back to
# the stat card, so it can never break a render. Whole pipeline is already
# AI-disclosed per platform.
AI_IMAGE = os.environ.get("AI_IMAGE", "1") != "0"

# Pollinations.ai (Flux model) is a genuinely free image API — no per-call
# billing, unlike Imagen below. 2026-08-03: tried FIRST so a weak-footage
# scene no longer has to spend Gemini billing just to get an on-topic
# illustration; Imagen only fires now if Pollinations is unset/fails/capped.
# Requires a free API key (enter.pollinations.ai, $0, just an account) —
# gated on the key rather than trying the anonymous no-key tier, because
# Pollinations' own docs say anonymous requests are watermarked, and a
# watermark burned into a published video is a real, visible defect.
POLLINATIONS_KEY = os.environ.get("POLLINATIONS_API_KEY", "")
MAX_POLLINATIONS_IMAGES = int(os.environ.get("MAX_POLLINATIONS_IMAGES", "6"))
POLLINATIONS_SCENES = 0


def _illustration_prompt(scene):
    """Shared prompt for both AI-illustration providers: anchors on the
    scene's literal SUBJECT (search_query), same reasoning as the footage
    judge and _fal_prompt — a metaphorical voiceover line must not pull an
    off-topic image. No text/watermark/logo, so it reads as real footage."""
    subject = (scene.get("search_query") or scene.get("voiceover") or "").strip()
    if not subject:
        return ""
    return (f"Photorealistic cinematic vertical photograph, documentary science style: "
            f"{subject}. Dramatic natural lighting, shallow depth of field, ultra-detailed, "
            f"realistic, no text, no words, no captions, no watermark, no logo.")


def _pollinations_can_spend():
    return bool(POLLINATIONS_KEY) and POLLINATIONS_SCENES < MAX_POLLINATIONS_IMAGES


def _pollinations_image(scene, dest):
    """Generate a relevant 9:16 image for a scene via Pollinations.ai (Flux),
    completely free. Returns True on success (bytes written to dest), False on
    any failure so the caller falls through to paid Imagen, then the stat
    card. Cost-capped at MAX_POLLINATIONS_IMAGES/video (Pollinations is free,
    but a per-video cap keeps behavior symmetric with the paid path and
    avoids hammering a shared free service)."""
    global POLLINATIONS_SCENES
    if not _pollinations_can_spend():
        return False
    prompt = _illustration_prompt(scene)
    if not prompt:
        return False
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt) +
           f"?width=1080&height=1920&model=flux&nologo=true&seed={random.randint(1, 1_000_000)}")
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {POLLINATIONS_KEY}", "User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(dest, "wb") as f:
            f.write(data)
        # ffmpeg content-sniffs the image format from magic bytes regardless of
        # the .png extension on `dest`, so a JPEG-encoded response is fine here.
        ok = os.path.exists(dest) and os.path.getsize(dest) > 5000
        if ok:
            POLLINATIONS_SCENES += 1
        return ok
    except Exception as e:  # noqa: BLE001 - best-effort; falls through to paid Imagen / stat card
        print(f"  Pollinations image gen unavailable ({e})")
        return False


AI_IMAGE_MODEL = os.environ.get("AI_IMAGE_MODEL", "imagen-3.0-generate-002")
MAX_AI_IMAGES = int(os.environ.get("MAX_AI_IMAGES", "4"))   # per-video cost cap
AI_IMAGE_SCENES = 0


def _gemini_image(scene, dest):
    """Generate a relevant 9:16 image for a scene via Imagen on the paid Gemini
    tier. Returns True on success (bytes written to dest), False on any failure so
    the caller falls through to the stat card. Cost-capped at MAX_AI_IMAGES/video."""
    global AI_IMAGE_SCENES
    key = os.environ.get("GEMINI_API_KEY", "")
    if not (AI_IMAGE and key) or AI_IMAGE_SCENES >= MAX_AI_IMAGES:
        return False
    prompt = _illustration_prompt(scene)
    if not prompt:
        return False
    body = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "9:16"},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{AI_IMAGE_MODEL}:predict"
    try:
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key,
                     "User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        preds = data.get("predictions") or []
        b64 = preds[0].get("bytesBase64Encoded") if preds else None
        if not b64:
            return False
        import base64
        with open(dest, "wb") as f:
            f.write(base64.b64decode(b64))
        ok = os.path.exists(dest) and os.path.getsize(dest) > 5000
        if ok:
            AI_IMAGE_SCENES += 1
        return ok
    except Exception as e:  # noqa: BLE001 - best-effort; fall back to stat card
        print(f"  AI image gen unavailable ({e})")
        return False


# ---------- AI VIDEO GAP-FILL (fal.ai) ----------
# The footage-RELEVANCE safety net. When a scene's best stock clip is off-topic
# (judge score below FAL_RELEVANCE_FLOOR) or nothing was found at all, generate an
# ON-TOPIC AI *video* clip instead of showing a generic/irrelevant stock clip —
# the render-160 "girl petting a rabbit / ocean waves for a Pluto video" bug. A
# moving AI clip that MATCHES the narration beats a real clip that doesn't, and
# beats a still. Strictly cost-bounded: fires ONLY on weak scenes (topics with
# good stock spend $0) and is capped at FAL_MAX_CLIPS per video. No FAL_KEY => the
# whole feature is a no-op, so free-tier behaviour is byte-for-byte unchanged.
FAL_KEY = os.environ.get("FAL_KEY", "") or os.environ.get("FAL_API_KEY", "")
# cheap/fast text-to-video default; env-overridable so the model can change with
# no code edit (fal slugs move). Body is just {"prompt":...} so it stays
# model-agnostic — the render scales/crops the clip to 9:16 like any stock clip.
# `or default` (not get-default) so an UNSET GitHub Variable — which arrives as an
# empty string "", not as absent — falls back instead of crashing int("") at import.
FAL_VIDEO_MODEL = os.environ.get("FAL_VIDEO_MODEL") or "fal-ai/ltx-video"
FAL_MAX_CLIPS = int(os.environ.get("FAL_MAX_CLIPS") or "2")            # per-video hard cost cap
FAL_RELEVANCE_FLOOR = int(os.environ.get("FAL_RELEVANCE_FLOOR") or "5")  # stock score < this = replace
FAL_VIDEO_SCENES = 0
# fal clips are synthetic media with two observed failure modes that mechanical
# checks cannot prove away: wrong-subject hallucinations and garbled baked-in text.
# If the safety judge is unavailable, paying for more unreviewable clips in this
# render is both lower-quality AND wasted spend. One failed safety check opens this
# render-local circuit; stock/archival/still fallbacks remain available.
_FAL_SAFETY_UNAVAILABLE = False


def _fal_can_spend():
    """True iff fal can BOTH generate and verify another clip this render.

    A paid synthetic clip is only useful when its independent Gemini vision safety
    check can run. No Gemini key / VISION_JUDGE disabled / a safety-check outage
    therefore disables fal BEFORE spending; after one runtime judge failure the
    render-local circuit prevents repeatedly paying for clips we cannot verify.
    """
    return (bool(FAL_KEY)
            and FAL_VIDEO_SCENES < FAL_MAX_CLIPS
            and VISION_JUDGE
            and bool(os.environ.get("GEMINI_API_KEY", ""))
            and not _FAL_SAFETY_UNAVAILABLE)


# Camera/lighting descriptors per VIBE (see VIBE_TWEAKS above) so the AI hero
# shots — the two clips in every video actually made FOR that video, not found
# on a stock site — visibly carry the topic's mood instead of defaulting to
# one generic "cinematic footage" look regardless of subject. This is where
# vibe should show up most: a hero shot is bespoke already, so it's the
# cheapest place to make the mood-match land.
VIBE_PROMPT_STYLE = {
    "chaotic":  "fast erratic handheld camera motion, high energy, intense saturated lighting",
    "tense":    "slow creeping camera push-in, tight framing, dim moody lighting, suspenseful atmosphere",
    "visceral": "extreme close-up detail, raw tactile texture, slightly unsettling intimate framing",
    "eerie":    "slow drifting camera, desaturated cold light, misty atmosphere, quiet unsettling stillness",
    "peaceful": "slow gentle drift, soft warm natural light, calm serene atmosphere",
    "awe":      "sweeping majestic camera movement, epic scale, golden dramatic lighting",
}
CURRENT_VIBE = "awe"   # set by _apply_vibe() at the top of main(); read here, not threaded
                        # through every function signature (same pattern as _last_motion_kind).

# How hard each caption word's overshoot-bounce pop punches, per vibe (see
# _event() in the ASS-caption builder below) — chaotic/visceral topics get a
# snappier, bigger overshoot; peaceful/eerie topics get a gentler one, so the
# captions themselves carry the mood, not just the footage/grade. Deliberately
# does NOT touch the over-wide-word auto-shrink branch (fs_over in _event) —
# that one already caps its own overshoot at exactly 100% by design, to avoid
# shoving a long word off the no-wrap frame (a real regression to not reopen).
CAPTION_INTENSITY = {"chaotic": 1.4, "tense": 1.15, "visceral": 1.2,
                      "eerie": 0.75, "peaceful": 0.65, "awe": 1.0}

# The 5th and final vibe-matched piece: the music bed itself. Deliberately
# NOT a new track library (none exists to draw from tonight) -- this tunes the
# mix filter applied to whatever track is already playing (committed
# music_science.mp3, MUSIC_URL, or the synthesized pad), the same way a real
# mix engineer rides EQ/level per scene mood. Kept conservative on purpose:
# only volume + a single highpass/lowpass, no reverb/echo effects that could
# sound bad without a human ear tuning them live.
VIBE_MUSIC_FX = {
    "chaotic":  {"vol_mult": 1.15, "extra": "highpass=f=90"},
    "tense":    {"vol_mult": 1.05, "extra": "highpass=f=60"},
    "visceral": {"vol_mult": 1.05, "extra": ""},
    "eerie":    {"vol_mult": 0.88, "extra": "lowpass=f=3200"},
    "peaceful": {"vol_mult": 0.85, "extra": "lowpass=f=4200"},
    "awe":      {"vol_mult": 1.0,  "extra": ""},
}


def _vibe_music_filter():
    """ffmpeg audio-filter fragment (no brackets/labels — caller wraps it) for
    the music bed, scaled by CURRENT_VIBE: chaotic/tense brighten and sit a
    touch louder; peaceful/eerie warm (lowpass) and sit a touch quieter, so the
    MIX itself carries the mood, not just footage/grade/captions. 'awe' is
    volume-only, functionally identical to the pre-vibe behavior (same value,
    just always explicitly formatted). Pure/testable."""
    fx = VIBE_MUSIC_FX.get(CURRENT_VIBE, VIBE_MUSIC_FX["awe"])
    parts = [f"volume={PROFILE['music_vol'] * fx['vol_mult']:.4f}"]
    if fx["extra"]:
        parts.append(fx["extra"])
    return ",".join(parts)


# 2026-08-03 craft-audit finding: the intro sting was BIT-FOR-BIT IDENTICAL on
# every single video regardless of vibe, the one piece of sound design that
# never varied with mood at all (the music bed, captions, and grade all do).
# Combined with the old flat music mix, the audio identity of the whole
# catalog was close to indistinguishable except for the spoken words. Same
# root frequency pair (a fifth apart, matching the original 98/147 Hz "awe"
# cue exactly so that vibe is unchanged/non-regressive), scaled up for
# tense/chaotic/visceral topics (a brighter, more alert cue) and down for
# eerie/peaceful ones (a deeper, calmer cue), with the lowpass cutoff moving
# the same direction so a brighter sting also reads less muffled.
VIBE_STING_FX = {
    "chaotic":  {"freq_mult": 1.55, "lowpass": 2200},
    "tense":    {"freq_mult": 1.30, "lowpass": 1800},
    "visceral": {"freq_mult": 1.15, "lowpass": 1500},
    "eerie":    {"freq_mult": 0.85, "lowpass": 900},
    "peaceful": {"freq_mult": 0.90, "lowpass": 1000},
    "awe":      {"freq_mult": 1.00, "lowpass": 1200},
}


def _vibe_sting_freqs():
    """(root_hz, fifth_hz, lowpass_hz) for the intro sting, scaled by
    CURRENT_VIBE off the original 98/147/1200 'awe' baseline (147/98 = 1.5,
    a perfect fifth, preserved at every scale so it never sounds detuned).
    Pure/testable."""
    fx = VIBE_STING_FX.get(CURRENT_VIBE, VIBE_STING_FX["awe"])
    root = 98.0 * fx["freq_mult"]
    return root, root * 1.5, fx["lowpass"]


def _fal_prompt(scene):
    """Cinematic text-to-video prompt built from the scene's literal SUBJECT
    (search_query, NOT the metaphorical voiceover — the same anchoring rule that
    keeps stock footage on-topic), styled by the video's CURRENT_VIBE so the
    two AI hero shots carry the topic's mood, with explicit no-text/no-watermark
    guards. Pure/testable."""
    subject = (scene.get("search_query") or scene.get("voiceover") or "").strip()
    style = VIBE_PROMPT_STYLE.get(CURRENT_VIBE, VIBE_PROMPT_STYLE["awe"])
    return (f"{subject}. Realistic cinematic footage, {style}, natural lighting, high detail, "
            f"no text, no words, no captions, no watermark, no logo.")


def _fal_clip_verdict(verdict):
    """Pure helper (no network): given the parsed vision-check JSON
    ({"score": 0-10, "garbled_text": bool}), decide whether to accept the
    clip. Returns (accept: bool, reason: str) -- reason is a human-readable
    rejection cause when accept is False, else ''. Two INDEPENDENT failure
    modes checked here: a low relevance score, OR hallucinated on-screen text
    regardless of score -- a clip can be perfectly on-subject and still be
    unusable because of garbled text baked into the frame (see
    _fal_clip_relevant's docstring for the real render that exposed this)."""
    score = int(verdict.get("score", 10))
    if score < FAL_RELEVANCE_FLOOR:
        return False, f"{score}/10 relevance"
    if bool(verdict.get("garbled_text", False)):
        return False, "garbled/hallucinated text detected in frame"
    return True, ""


def _fal_clip_relevant(scene, clip_path):
    """Single-frame Gemini vision check: does a fal.ai-generated clip actually
    show what it was asked for, AND is it free of hallucinated on-screen text?
    Text-to-video generation can hallucinate a completely unrelated subject
    even on a successful, well-formed API response (see the darkness check
    above and _fal_video's caller for why a 200 response alone proves nothing
    about CONTENT). It can ALSO hallucinate garbled, nonsensical text/writing
    baked into an otherwise on-topic frame -- a real render shipped an
    accepted 'ice floating water' hero shot (right subject, would have scored
    well on relevance alone) with garbled pseudo-Cyrillic text burned across
    the middle of the frame, directly under the caption. The two checks are
    independent: a clip can be perfectly on-subject and still be unusable
    because of hallucinated text, so this rejects on EITHER failure, not just
    a low relevance score. This safety check FAILS CLOSED for the synthetic clip:
    if judging is unavailable/broken/unparseable, reject this fal clip and let the
    caller fall back to real stock / archival / still / card. That is deliberately
    different from aborting the whole render: an unverified AI clip is optional,
    while the project's consistency-over-cadence rule says known synthetic-media
    risk must not silently become trusted media. Reuses the same bounded-thinking-
    budget fix as _gemini_vision_pick/_final_qa_check."""
    global _FAL_SAFETY_UNAVAILABLE
    key = os.environ.get("GEMINI_API_KEY", "")
    if not (VISION_JUDGE and key):
        _FAL_SAFETY_UNAVAILABLE = True
        return False
    frame_path = os.path.join(WORK, f"_fal_check_{os.path.basename(clip_path)}.jpg")
    try:
        run(["ffmpeg", "-y", "-i", clip_path, "-ss", "1.0", "-frames:v", "1", frame_path])
        if not os.path.exists(frame_path):
            _FAL_SAFETY_UNAVAILABLE = True
            print("  [fal] safety check produced no frame — rejecting clip and disabling fal for this render")
            return False
        intent = _footage_intent(scene)
        import base64
        parts = [
            {"text": (f"Does this image LITERALLY show: \"{intent}\"? Score 0-10 -- "
                      f"8-10 = clearly, literally shows the subject; 4-7 = related but "
                      f"not an exact match; 0-3 = a completely different, unrelated "
                      f"subject.\n"
                      f"Separately: does the image contain any GARBLED, nonsensical, or "
                      f"unreadable text/writing/lettering baked into the footage itself "
                      f"(not a caption overlay -- text that is PART of the scene, e.g. on "
                      f"a sign, screen, or floating across the frame)? This is a known "
                      f"AI-video-generation artifact and makes a clip unusable even if the "
                      f"subject is otherwise correct.\n"
                      f"Return ONLY JSON: {{\"score\": <0-10>, \"garbled_text\": true|false}}.")},
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(open(frame_path, "rb").read()).decode()}},
        ]
        # maxOutputTokens must comfortably exceed thinkingBudget (see the
        # identical fix + explanation in _gemini_vision_pick above -- a
        # budget smaller than the thinking allowance truncates the reply
        # before any closing "}").
        body = json.dumps({"contents": [{"parts": parts}],
                           "generationConfig": {"temperature": 0, "maxOutputTokens": 1024,
                                                "thinkingConfig": {"thinkingBudget": 512}}}).encode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE_GEMINI_MODEL}:generateContent"
        req = urllib.request.Request(url, data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key,
                     "User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        txt = data["candidates"][0]["content"]["parts"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            _FAL_SAFETY_UNAVAILABLE = True
            print("  [fal] safety judge returned no parseable JSON — rejecting clip and disabling fal for this render")
            return False
        verdict = json.loads(m.group(0))
        accept, reason = _fal_clip_verdict(verdict)
        if not accept:
            print(f"  [fal] vision check: {reason} against {intent!r} -- rejecting")
            return False
        return True
    except Exception as e:  # noqa: BLE001 - reject only this optional synthetic clip
        _FAL_SAFETY_UNAVAILABLE = True
        print(f"  [fal] safety check unavailable ({e}); rejecting clip and disabling fal for this render")
        return False
    finally:
        try:
            os.remove(frame_path)
        except Exception:  # noqa: BLE001
            pass


def _fal_video(scene, dest):
    """Generate an on-topic AI video clip for a scene via fal.ai. Returns True on
    success (a playable clip written to dest), False on any failure so the caller
    keeps its stock/still/card fallback. Cost-capped by _fal_can_spend()."""
    global FAL_VIDEO_SCENES
    if not _fal_can_spend():
        return False
    subject = (scene.get("search_query") or scene.get("voiceover") or "").strip()
    if not subject:
        return False
    body = json.dumps({"prompt": _fal_prompt(scene)}).encode()
    try:
        req = urllib.request.Request(
            f"https://fal.run/{FAL_VIDEO_MODEL}", data=body,
            headers={"Authorization": f"Key {FAL_KEY}",
                     "Content-Type": "application/json", "User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=240) as r:
            data = json.loads(r.read().decode())
        # fal t2v models return {"video":{"url":...}} or {"videos":[{"url":...}]}
        vid = data.get("video") if isinstance(data.get("video"), dict) else None
        url = vid.get("url") if vid else None
        if not url:
            vids = data.get("videos") or []
            url = vids[0].get("url") if vids and isinstance(vids[0], dict) else None
        if not url:
            print("  [fal] reply had no video url — falling back")
            return False
        _download(url, dest)
        if (ffprobe_dur(dest) or 0) < 0.5:
            return False
        # SANITY CHECK before shipping a paid clip: a generation can succeed at
        # the API level (a playable file comes back) yet be garbage -- a black/
        # near-blank frame from a glitched or safety-filtered generation. Reuse
        # the same luma probe that already guards stock footage rather than a
        # new vision call (cheap, already proven, no extra latency/cost). The
        # spend still counts against FAL_MAX_CLIPS either way (the API call
        # already happened — money was spent) so a run of bad generations can't
        # retry past the per-video budget; it just falls back to real stock
        # instead of shipping something broken.
        FAL_VIDEO_SCENES += 1
        if _clip_too_dark(dest):
            print(f"  [fal] clip for '{subject[:40]}' came back too dark/broken "
                  f"({FAL_VIDEO_SCENES}/{FAL_MAX_CLIPS} spent) — falling back to stock")
            return False
        # RELEVANCE CHECK (2026-08-02, render 205): unlike stock footage --
        # which is always vision/text-judged before shipping -- a fal clip
        # was accepted UNCONDITIONALLY (score hardcoded to 10 at the call
        # site), because a successful API response only proves the model
        # generated SOMETHING, not that it generated the right SUBJECT.
        # Text-to-video hallucinates: asked for "naked mole rat close up,"
        # render 205 got a boat on water, then an unrelated human silhouette,
        # and shipped it as the PAYOFF scene with nothing to catch it. Same
        # spend-already-counts-either-way reasoning as the darkness check
        # above -- this is a paid clip either way; only whether it SHIPS
        # changes.
        if not _fal_clip_relevant(scene, dest):
            print(f"  [fal] clip for '{subject[:40]}' didn't match the subject "
                  f"({FAL_VIDEO_SCENES}/{FAL_MAX_CLIPS} spent) — falling back to stock")
            return False
        print(f"  [fal] AI video clip {FAL_VIDEO_SCENES}/{FAL_MAX_CLIPS} for "
              f"'{subject[:40]}' via {FAL_VIDEO_MODEL}")
        return True
    except Exception as e:  # noqa: BLE001 — best-effort; keep the stock/still fallback
        print(f"  [fal] AI video unavailable ({e}) — falling back")
        return False


def _footage_intent(scene):
    """What the footage judge + rescue requery match candidates against. LEADS
    with the scene's search_query (the literal, filmable subject the generator
    chose) and only then adds the voiceover for nuance. This matters most on the
    hook: a metaphorical line ("your walk through the woods is actually a trip
    through a city") otherwise made the judge reject the correct forest clip and
    requery on the metaphor word — shipping a literal Dubai skyline over a forest
    video (run 66). Anchoring on the subject keeps selection on-topic while the
    voiceover still informs which on-subject clip fits best."""
    subject = (scene.get("search_query") or "").strip()
    vo = (scene.get("voiceover") or "").strip()
    if subject and vo:
        return f"{subject}. {vo}"
    return subject or vo


# ---------- MULTI-CLIP SCENES (cut between several clips inside one beat) ----------
# The "more clips / more movement / constant flashing of different scenes"
# feedback: a scene used to hold ONE looped clip for its whole 5-7s, which reads
# as static. Now a long scene is split into 2-4 sub-clips that hard-cut on beat,
# each with its own Ken-Burns move, while the narration audio stays one
# continuous, word-synced take (captions are unaffected — they anchor to the
# scene boundary + word timings, which don't change). Fully env-gated and
# fail-safe: on ANY error the scene renders exactly as before (one clip).
SCENE_MULTICLIP = os.getenv("SCENE_MULTICLIP", "1") != "0"
CLIP_SECONDS    = float(os.getenv("CLIP_SECONDS", "1.9"))   # target on-screen time per clip
MAX_SUBCLIPS    = int(os.getenv("MAX_SUBCLIPS", "6"))        # cap distinct clips per scene
_MULTICLIP_MOTIONS = ["zoom_in", "pan", "zoom_out"]          # cycled so no two cuts move alike


# ---------- VIBE-MATCHED PACING/GRADE (mood-matched cutting, not one constant rhythm) ----------
# Every video used to get the SAME cut speed and color grade regardless of
# subject — a violent-eruption video cut at the identical rhythm as a sleeping-
# dolphin video. generate.py tags each manifest with a 'vibe' (_normalize_vibe,
# always one of VIBES below) picked to match how the topic actually FEELS; this
# layers a small delta on top of the PAGE's own grade/pacing (profiles.py) —
# additive, not a replacement — so the page's identity (font, voice, base
# color) stays intact while chaotic and peaceful topics on the SAME page no
# longer render identically. zoom/clip/subclip deltas track published short-
# form retention guidance (faster, more varied cuts read as chaotic/tense;
# fewer, longer holds read as calm) filtered through this channel's own
# analytics pattern (concrete/visceral topics already outperform passive ones —
# the pacing should reinforce that feeling, not fight it).
VIBE_TWEAKS = {
    #              contrast  saturation  brightness  zoom_mult  clip_mult  subclip_bonus
    "chaotic":  {"contrast": 0.10, "saturation": 0.12, "brightness": 0.00, "zoom_mult": 1.35, "clip_mult": 0.70, "subclip_bonus": 2},
    "tense":    {"contrast": 0.08, "saturation": 0.00, "brightness": -0.02, "zoom_mult": 1.15, "clip_mult": 0.85, "subclip_bonus": 1},
    "visceral": {"contrast": 0.06, "saturation": 0.08, "brightness": -0.01, "zoom_mult": 1.20, "clip_mult": 0.80, "subclip_bonus": 1},
    "eerie":    {"contrast": 0.02, "saturation": -0.10, "brightness": -0.04, "zoom_mult": 0.75, "clip_mult": 1.25, "subclip_bonus": -1},
    "peaceful": {"contrast": -0.04, "saturation": -0.06, "brightness": 0.02, "zoom_mult": 0.60, "clip_mult": 1.40, "subclip_bonus": -2},
    # 2026-08-03 craft-audit finding: "awe" was ALL ZEROS -- a true no-op, not a
    # deliberate "epic wonder" choice, and 3 of the last 8 real manifests landed
    # on it, so roughly a third of recent videos got ZERO grade/pacing variation
    # from this entire system despite it working correctly on every other vibe.
    # Gave it its own modest identity instead: a touch more contrast for a
    # cinematic look, a slightly slower/bigger zoom and longer holds ("sweeping
    # majestic" per the fal-prompt description above) — distinct from flat
    # baseline but nowhere near as extreme as "chaotic" or "peaceful".
    "awe":      {"contrast": 0.04, "saturation": 0.02, "brightness": 0.00, "zoom_mult": 1.10, "clip_mult": 1.10, "subclip_bonus": 0},
}


def _apply_vibe(vibe):
    """Mutate PROFILE['grade']/['zoom_speed'] and CLIP_SECONDS/MAX_SUBCLIPS in
    place for THIS render, based on the manifest's vibe tag. Called once at the
    top of main(), before any scene is built, so every scene in the video picks
    up the same mood-matched pacing/grade. Chains an EXTRA small eq= filter
    after the page's own grade (ffmpeg composes sequential eq= filters) rather
    than parsing/replacing it, so a page's base look is never lost — only
    nudged. Unknown/missing vibe -> the 'awe' entry, all deltas zero (identical
    to pre-vibe behavior). Returns (clip_seconds, max_subclips) for easy
    testing without needing to re-read the mutated globals."""
    global CLIP_SECONDS, MAX_SUBCLIPS, CURRENT_VIBE
    CURRENT_VIBE = vibe if vibe in VIBE_TWEAKS else "awe"
    t = VIBE_TWEAKS.get(vibe, VIBE_TWEAKS["awe"])
    PROFILE["grade"] = PROFILE["grade"] + (
        f",eq=contrast={1 + t['contrast']:.3f}:saturation={1 + t['saturation']:.3f}:"
        f"brightness={t['brightness']:.3f}")
    PROFILE["zoom_speed"] = PROFILE["zoom_speed"] * t["zoom_mult"]
    CLIP_SECONDS = max(0.9, CLIP_SECONDS * t["clip_mult"])
    MAX_SUBCLIPS = max(2, min(8, MAX_SUBCLIPS + t["subclip_bonus"]))
    print(f"  [vibe] '{vibe}' -> clip {CLIP_SECONDS:.2f}s, max {MAX_SUBCLIPS} subclips/scene, "
          f"zoom x{t['zoom_mult']}, grade contrast{t['contrast']:+.2f}/sat{t['saturation']:+.2f}")
    return CLIP_SECONDS, MAX_SUBCLIPS


def _subclip_plan(seg_dur, target_secs, max_subclips):
    """Split a scene of `seg_dur` seconds into as-even-as-possible sub-clip
    durations so the video CUTS between different clips instead of holding one.
    Count = clamp(round(seg_dur / target_secs), 1, max_subclips); durations sum
    EXACTLY to seg_dur (rounding slack lands on the last piece). A single-element
    list means 'no sub-cutting' (short scene) — the caller renders as before.
    Pure/fail-safe: bad inputs return a single full-length segment."""
    try:
        seg_dur = float(seg_dur); target_secs = float(target_secs)
    except (TypeError, ValueError):
        return [seg_dur]
    if seg_dur <= 0 or target_secs <= 0 or int(max_subclips) < 1:
        return [max(0.0, seg_dur)]
    n = max(1, min(int(round(seg_dur / target_secs)), int(max_subclips)))
    if n <= 1:
        return [round(seg_dur, 3)]
    base = round(seg_dur / n, 3)
    return [base] * (n - 1) + [round(seg_dur - base * (n - 1), 3)]


def _variant_queries(q):
    """A few FREE query variants of a scene's search query, to widen the distinct-
    clip pool (more real VIDEO packed into each scene). The full phrase first, then
    its broader single content words — a broad noun ('turtle') returns many more
    stock clips than a 3-word phrase ('pond turtle swimming'), so pooling across
    them multiplies how many distinct clips the multi-clip cutter can find, at zero
    cost. Pure/testable."""
    q = (q or "").strip()
    if not q:
        return []
    words = list(_relevance_words(q))                    # content words, >2 chars, non-stopword
    variants = [q] + sorted(words, key=len, reverse=True)  # phrase, then broadest words
    seen, out = set(), []
    for v in variants:
        vl = v.lower().strip()
        if vl and vl not in seen:
            seen.add(vl); out.append(v)
    return out[:4]


def _extra_scene_clips(scene, need, exclude_ids, dest_prefix):
    """Download up to `need` ADDITIONAL distinct, non-dark clips for a scene so
    build_scene can cut between several clips. Now pools candidates across a few
    FREE query VARIANTS (full phrase + broader words) instead of a single query —
    so narrow topics that used to run out of distinct clips (and recycle or fall to
    stills) now find many more real clips to pack in. NO extra LLM judge calls;
    on-topic via a shared subject word with the scene query. Returns local file
    paths (may be short/empty; caller reuses the primary clip for empty slots).
    Fully fail-safe: any error yields whatever was gathered so far."""
    paths = []
    if need <= 0:
        return paths
    q = scene.get("search_query", "") or scene.get("voiceover", "")
    subject = _subject_word(q)
    seen = set(exclude_ids)
    # Build a pooled, de-duplicated candidate list across the query variants. Stop
    # early once we have plenty to choose from (need*4) to bound network work.
    pool = []
    for vq in _variant_queries(q):
        try:
            for c in (_gather_candidates(vq) or []):
                cid = c.get("id")
                if cid is None or cid in seen:
                    continue
                # ON-SUBJECT, not just on-theme: require the query's actual SUBJECT
                # word (e.g. 'octopus'), not any shared word. The old check accepted
                # a candidate sharing ANY content word with the query — but generic
                # modifiers like "close", "ocean", "swimming", "blood", "handling"
                # show up in totally unrelated stock (a sea turtle for "octopus
                # swimming ocean"; a lipstick tube for "octopus blood vessels"; an
                # orange being cut for "octopus close up") because THEY share a
                # word too, just not the subject. No subject word (rare) = no
                # filter, same as before.
                if subject and subject not in _relevance_words(c.get("desc", "")):
                    continue  # keep sub-clips on-subject
                seen.add(cid)          # provisional: don't pool the same id twice
                pool.append(c)
        except Exception:  # noqa: BLE001 — a bad query/source, try the next variant
            continue
        if len(pool) >= need * 4:
            break
    for c in pool:
        if len(paths) >= need:
            break
        p = f"{dest_prefix}_{len(paths)}.mp4"
        try:
            _download(c["url"], p)
            if _clip_too_dark(p):
                continue
            _used_video_ids.add(c["id"]); _used_history.append(c["id"])
            paths.append(p)
        except Exception:  # noqa: BLE001 — skip a bad clip, keep going
            continue
    return paths


def build_scene(scene, idx, seg_mp3, seg_dur):
    global _last_motion_kind, STAT_CARD_SCENES, ARCHIVAL_SCENES
    raw = os.path.join(WORK, f"s{idx}_raw.mp4")
    have, score, fal_filled = False, None, False

    # HERO SHOT (footage_mode == "ai", set by generate.py's _assign_footage_mode
    # on the hook + payoff scenes — the two beats that matter most): try a
    # purpose-built AI clip made FOR this exact line BEFORE ever spending a
    # stock search on it, instead of only reaching for AI as a rescue when
    # stock comes back weak. A bespoke shot beats a generic "roughly relevant"
    # stock clip on the shots that actually decide whether someone keeps
    # watching. Falls straight through to the normal stock flow below if fal
    # is unavailable/unkeyed/fails — zero behavior change for a render with no
    # fal key, and the shared FAL_MAX_CLIPS budget (_fal_can_spend()) still
    # bounds total spend across hero shots AND the gap-fill rescue below.
    if scene.get("footage_mode") == "ai" and _fal_can_spend():
        fal_raw = os.path.join(WORK, f"s{idx}_hero.mp4")
        if _fal_video(scene, fal_raw):
            raw, have, score, fal_filled = fal_raw, True, 10, True
            print(f"  [fal] hero shot for scene {idx} ({scene['search_query']!r})")

    # Once MAX_STAT_CARDS scenes have already carded, force this scene to take
    # its best real clip instead of adding to a wall of text cards.
    # accept_best=True ALWAYS: prefer the best real (moving) clip down to
    # SOFT_VIDEO_FLOOR before ever falling to a static photo or text card, so the
    # feed is video-first (user ask: "more videos, not just photos"). fetch_clip's
    # own soft-floor guard still blocks genuinely off-topic video.
    if not have:
        have, score = fetch_clip(scene["search_query"], raw,
                                  intent=_footage_intent(scene), accept_best=True)

    # AI-VIDEO GAP-FILL (fal.ai): the relevance safety net. If the best stock clip
    # is off-topic (weak judge score) OR nothing was found, and a paid fal key is
    # available under the per-video cap, replace it with an ON-TOPIC AI video clip
    # (render-160 fix: no more girl-and-rabbit / ocean-waves on a Pluto video). A
    # fal-filled scene renders as ONE strong on-topic clip (no multi-clip mixing
    # with off-topic stock sub-clips). Falls straight through if fal is off/fails.
    if ((not have) or (score is not None and score < FAL_RELEVANCE_FLOOR)) and _fal_can_spend():
        fal_raw = os.path.join(WORK, f"s{idx}_fal.mp4")
        if _fal_video(scene, fal_raw):
            raw, have, score, fal_filled = fal_raw, True, 10, True
            print("  [fal] using on-topic AI video in place of weak/absent stock footage")

    out = os.path.join(WORK, f"s{idx}.mp4")
    frames = max(1, round(seg_dur * 30))

    # motion (Ken Burns zoom/pan, varies per scene.motion) + cinematic color grade
    zspeed = PROFILE["zoom_speed"]
    kind = scene.get("motion", "zoom_in")
    motion = _motion_filter(scene, frames, zspeed, idx=idx, prev_kind=_last_motion_kind)
    _last_motion_kind = kind
    grade = PROFILE["grade"]
    stat = _stat_overlay(scene, seg_dur)

    if have:
        # Lift dim-but-kept footage so no frame reads as a black screen under
        # the caption (the run-105 dark-lab scene). Measured once here; a pure,
        # capped eq snippet opens the shadows before the cinematic grade.
        _avg, _mn = _clip_luma(raw)
        lift = _shadow_lift_filter(_avg)
        if lift:
            print(f"  [grade] lifting dim clip (avg luma {_avg:.0f}) for legibility")

        # MULTI-CLIP: on a long scene, cut between several different clips instead
        # of holding one (the "more clips / constant flashing" note). Wrapped so
        # ANY failure falls straight through to the single-clip render below — a
        # render can never break because of this.
        plan = _subclip_plan(seg_dur, CLIP_SECONDS, MAX_SUBCLIPS) if (SCENE_MULTICLIP and not fal_filled) else [seg_dur]
        # Gather the DISTINCT extra clips first. Multi-cut ONLY if we actually got a
        # second distinct clip — cutting between sub-clips of the SAME source is just
        # the one photo panned three different ways (user: "at 25s it pans left, zooms
        # out, zooms in, fades right on the same Moon photo — that's not a cut"). With
        # a single source, hold it under ONE smooth motion instead of faking cuts.
        try:
            extra = _extra_scene_clips(scene, max(0, len(plan) - 1),
                                       set(_used_video_ids), os.path.join(WORK, f"s{idx}_sub"))
        except Exception:  # noqa: BLE001 — never let footage gathering break a render
            extra = []
        sources = [raw] + extra
        if len(plan) > 1 and len(sources) >= 2:
            try:
                parts = []
                _lift_cache = {raw: lift}   # per-SOURCE lift: a dark sub-clip needs its
                for j, d in enumerate(plan):
                    src = sources[j % len(sources)]   # cycle if we got fewer distinct clips
                    # own brightness lift — reusing the primary's lift left dark
                    # sub-clips (moody/black-background footage) reading as a black
                    # screen mid-scene (the "went black at 10s" bug).
                    if src not in _lift_cache:
                        _savg, _ = _clip_luma(src)
                        _lift_cache[src] = _shadow_lift_filter(_savg)
                    slift = _lift_cache[src]
                    part = os.path.join(WORK, f"s{idx}_p{j}.mp4")
                    pf = max(1, round(d * 30))
                    pmotion = _motion_filter({**scene, "motion": _MULTICLIP_MOTIONS[j % len(_MULTICLIP_MOTIONS)]},
                                             pf, zspeed, idx=idx + j, prev_kind=None)
                    pstat = stat if j == 0 else ""   # number card once, on the first cut only
                    run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, "-t", f"{d:.3f}",
                         "-filter_complex", f"[0:v]{pmotion}{slift}{grade}{pstat},setsar=1[v]",
                         "-map", "[v]", "-r", "30", "-pix_fmt", "yuv420p",
                         "-an", "-c:v", "libx264", part])
                    parts.append(part)
                listf = os.path.join(WORK, f"s{idx}_concat.txt")
                with open(listf, "w") as f:
                    for p in parts:
                        f.write(f"file '{os.path.abspath(p)}'\n")
                sv = os.path.join(WORK, f"s{idx}_v.mp4")
                run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", sv])
                run(["ffmpeg", "-y", "-i", sv, "-i", seg_mp3, "-map", "0:v", "-map", "1:a",
                     "-t", f"{seg_dur:.3f}", "-r", "30", "-pix_fmt", "yuv420p",
                     "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
                print(f"  multi-clip scene: {len(parts)} cuts across {seg_dur:.1f}s "
                      f"({len(sources)} distinct clip(s))")
                return out
            except Exception as e:  # noqa: BLE001 — never break a render
                print(f"  multi-clip render failed ({e}) — falling back to single clip")

        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", raw, "-i", seg_mp3,
             "-t", f"{seg_dur:.3f}",
             "-filter_complex", f"[0:v]{motion}{lift}{grade}{stat},setsar=1[v]",
             "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
        return out

    # ARCHIVAL STILL fallback (idea 3): stock VIDEO failed for this scene — before
    # dropping to a text card, try a real Creative-Commons archival/scientific
    # image (Openverse) and Ken-Burns it. A genuine Hubble/microscopy/archival
    # photo looks like a documentary, not a gradient card, AND it means a
    # Pexels-video outage no longer forces the all-text-card failure mode. These
    # do NOT count as stat cards (they're real imagery), so they don't trip the
    # footage-starvation abort.
    if PROFILE.get("archival_stills", True):
        img = os.path.join(WORK, f"s{idx}_img.jpg")
        # Search the still sources on the scene's literal SUBJECT (search_query),
        # not the raw voiceover — same reason as the footage intent above: a
        # metaphorical line must not pull an off-topic archival image.
        _q = scene.get("search_query", "") or scene.get("voiceover", "")
        # Three free/no-key still sources. iNaturalist tried FIRST: for the many
        # scenes whose subject is a specific animal/plant species (most of the
        # topic bank), a real species-verified observation beats a generic
        # keyword search — it simply returns nothing for non-biological topics
        # and falls through. Then Openverse (CC aggregator), then Wikimedia
        # Commons (the largest public-domain science library — Hubble,
        # microscopy, diagrams, historical photos). Any one gives a documentary
        # look no generic-stock page has.
        still_provider = None

        # EXACT SCIENTIFIC STRUCTURE before generic image search: when the scene
        # is explicitly about a small molecule/chemical, PubChem can show the
        # actual 2D/3D structure. That is materially better evidence than a
        # generic lab beaker, pills, or blue "molecule" stock illustration.
        if SCI_MEDIA.pubchem_relevant(_q):
            _pc_img = os.path.join(WORK, f"s{idx}_pubchem.png")
            try:
                _pc_name = SCI_MEDIA.pubchem_image(_q, _pc_img)
            except Exception as e:
                print(f"  PubChem failed: {e}")
                _pc_name = None
            if _pc_name:
                img = _pc_img
                still_provider = f"PubChem ({_pc_name})"

        if not still_provider and _inaturalist_image(_q, img):
            still_provider = "iNaturalist"
        elif not still_provider and _openverse_image(_q, img):
            still_provider = "Openverse"
        elif not still_provider and _wikimedia_image(_q, img):
            still_provider = "Wikimedia"
        if still_provider:
            try:
                run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", seg_mp3,
                     "-t", f"{seg_dur:.3f}", "-r", "30",
                     "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
                     "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
                     "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
                ARCHIVAL_SCENES += 1
                print(f"  archival still scene ({still_provider} CC image + Ken Burns)")
                return out
            except Exception as e:
                print(f"  archival still render failed ({e}) — falling back to card")

    # AI ILLUSTRATION: before dropping to a plain text card, generate an EXACT,
    # on-topic vertical image for this scene and Ken-Burns it — turns the
    # least-relevant scenes (no real footage) from a boring card into a
    # matching visual. Counts as real imagery (not a stat card), so it also
    # relaxes the footage-starvation abort. FREE Pollinations tried first;
    # paid Imagen only fires if Pollinations is unset/fails/capped. Any
    # failure of both falls through to the stat card.
    if AI_IMAGE:
        ai_img = os.path.join(WORK, f"s{idx}_ai.png")
        provider = None
        if _pollinations_image(scene, ai_img):
            provider = "Pollinations (free)"
        elif _gemini_image(scene, ai_img):
            provider = "Imagen (paid)"
        if provider:
            try:
                run(["ffmpeg", "-y", "-loop", "1", "-i", ai_img, "-i", seg_mp3,
                     "-t", f"{seg_dur:.3f}", "-r", "30",
                     "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
                     "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
                     "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
                ARCHIVAL_SCENES += 1
                print(f"  AI-generated illustration scene ({provider} + Ken Burns)")
                return out
            except Exception as e:  # noqa: BLE001
                print(f"  AI image render failed ({e}) — falling back to card")

    # No clip cleared RELEVANCE_FLOOR (or there were zero results). Render a
    # designed typographic stat-card scene instead of shipping the least-bad
    # clip or a flat color card. Must never crash the render: any failure
    # here falls back to the original plain color card.
    try:
        _build_stat_card(scene, idx, seg_mp3, seg_dur, out, motion)
        STAT_CARD_SCENES += 1
        tag = f"best {score}/10 below floor" if score is not None else "no candidates"
        print(f"  stat-card scene ({tag})")
        return out
    except Exception as e:
        print(f"  stat-card render failed ({e}) — falling back to color card")

    # Ultimate fallback (footage + archival still + stat-card all failed). This
    # used to be near-black (0x0a0a0a) — which is exactly the "goes to a black
    # screen at 39s" the user caught on the Oregon video. A fallback scene must
    # still look INTENTIONAL, never like dead air, so use a visible dark-slate
    # background (YAVG ~45, clearly a designed colour, not a broken black frame).
    # `color` is kept as the primitive here because this path only runs after the
    # gradient-based stat card already failed, so it must not depend on gradients.
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x1b2b3c:s={W}x{H}:d={seg_dur:.3f}:r=30",
         "-i", seg_mp3, "-map", "0:v", "-map", "1:a",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
    return out


# ---------- KARAOKE CAPTIONS (word-by-word, eye level, ASS format) ----------

def _stat_overlay(scene, seg_dur):
    """Return an ffmpeg drawtext snippet for an animated number card, or '' if none/disabled.
    OFF unless PROFILE.get('motion_graphics') is True. Fully optional + safe.

    The number is drawn ONLY when those exact digits are actually SPOKEN in
    this scene's voiceover -- so the card always has context (the narrator is
    saying the number the moment it pops on). It deliberately does NOT read
    on_screen_text: the murmuration render had scene voiceover 'nearest seven
    neighbors' (word 'seven', no digit) but on_screen_text 'Watch 7 neighbors',
    which fired a big contextless '7' on screen. Parsing the voiceover only
    means a spelled-out 'seven' shows nothing, and a real spoken figure like
    '400 million years' still gets its card."""
    if not PROFILE.get("motion_graphics"):
        return ""
    import re as _re
    text = scene.get("voiceover", "")
    m = _re.search(r"(\d[\d,\.]*\s?(?:%|x|mph|m-?per-?hour|times|million|billion|degrees|tons?)?)", text)
    if not m:
        return ""
    num = m.group(1).strip().replace(":", " ").replace("'", "")
    num = _re.sub(r"[^0-9A-Za-z%,\. ]", "", num)[:14]
    if not num:
        return ""
    # pop-in: grow font for first 0.3s via enable + a stepped fontsize using two drawtexts is complex;
    # keep it robust: one bold card, fade in quickly, upper third, with a translucent box.
    return (f",drawtext=text='{num}':fontfile='{FONT}':fontsize=140:fontcolor=white:"
            f"borderw=8:bordercolor=black:box=1:boxcolor=black@0.35:boxborderw=24:"
            f"x=(w-tw)/2:y=h*0.18:alpha='if(lt(t,0.2),t/0.2,1)'")


def _ass_t(t):
    cs = int(round(t * 100))
    h = cs // 360000; cs %= 360000
    m = cs // 6000;   cs %= 6000
    s = cs // 100;    cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def _ass_header():
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{PROFILE["cap_font"]},{PROFILE["cap_size"]},{PROFILE["cap_primary"]},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,8,{PROFILE["cap_outline"]},5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# The core keyword's words (uppercased, alnum-only, >2 chars), set per render in
# main() so captions can pop them in the accent colour. Empty = no keyword pop.
_KEYWORD_TOKENS = set()


def _event(start, end, word):
    clean = re.sub(r"[{}\\]", "", word).upper()
    # KEYWORD POP: if this word is one of the video's core keyword words, render it
    # in the profile's accent colour (a warm gold) instead of white — brands the
    # page and pulls the eye to the word that matters. Matches on the bare alnum so
    # trailing punctuation ("SMELL." vs "SMELL") still hits.
    accent = ""
    bare = re.sub(r"[^A-Z0-9]", "", clean)
    if bare and bare in _KEYWORD_TOKENS and PROFILE.get("cap_accent"):
        accent = f"\\c{PROFILE['cap_accent']}"
    # AUTO-SHRINK over-wide words: WrapStyle 2 = no wrap, so a single long word
    # (e.g. "TRANSDIFFERENTIATION") ran off both edges of the frame. Estimate the
    # word's rendered width and, only when it would exceed the safe width, drop the
    # font size for THIS word just enough to fit. Normal-length words are untouched.
    base_fs = int(PROFILE.get("cap_size", 120))
    est_w = len(clean) * 0.64 * base_fs
    fs_over = ""
    if est_w > 980:
        fs_over = f"\\fs{max(58, int(base_fs * 980.0 / est_w))}"
    # KINETIC POP: each word SNAPS on with an overshoot bounce (small -> past 100%
    # -> settle) instead of a hard cut, so the captions carry energy even over a
    # calm clip (the "make it POP" ask). \an5 + \pos scales from the word's own
    # centre so it stays put. Three tiers:
    #   - keyword word: a bigger bounce that SETTLES slightly large (104%) + gold,
    #     so the word that matters really pops;
    #   - normal word: a snappy bounce back to 100%;
    #   - over-wide word (auto-shrunk): a gentle grow only, so a big scale can't
    #     shove it off the no-wrap frame.
    # VIBE-MATCHED POP: how far past 100% each overshoot peak scales, per the
    # video's CURRENT_VIBE (CAPTION_INTENSITY above) — a chaotic/visceral topic
    # snaps harder, a peaceful/eerie one barely overshoots at all. The over-wide
    # (fs_over) tier is deliberately left untouched: it already caps its own
    # overshoot at exactly 100% by design, to avoid shoving a long word off the
    # no-wrap frame — not something to reopen for a caption-energy nicety.
    ci = CAPTION_INTENSITY.get(CURRENT_VIBE, 1.0)
    if fs_over:
        pop = "\\fscx82\\fscy82\\t(0,110,\\fscx100\\fscy100)"
    elif accent:
        ov, settle = min(150, 100 + round(20 * ci)), min(120, 100 + round(4 * ci))
        pop = f"\\fscx64\\fscy64\\t(0,90,\\fscx{ov}\\fscy{ov})\\t(90,175,\\fscx{settle}\\fscy{settle})"
    else:
        ov = min(150, 100 + round(10 * ci))
        pop = f"\\fscx58\\fscy58\\t(0,90,\\fscx{ov}\\fscy{ov})\\t(90,160,\\fscx100\\fscy100)"
    tag = (f"{{\\pos(540,{PROFILE['cap_y']})\\an5\\fad(30,0){fs_over}{pop}{accent}}}")
    return f"Dialogue: 0,{_ass_t(start)},{_ass_t(end)},Pop,,0,0,0,,{tag}{clean}"

# ON-SCREEN HOOK HEADLINE — a big, bold, curiosity-gap TITLE burned into the TOP
# of the frame for the first few seconds. On TikTok the eye reads before the ear
# hears, so a punchy top headline ("THIS ANIMAL CAN'T DIE") is one of the biggest
# scroll-stoppers there is — separate zone from the eye-level karaoke captions, so
# they never clash. Text comes from the manifest's `hook_headline` (a short ALL-
# CAPS line the generator writes); if absent, no headline is drawn (never a bad
# mechanical one). Tunable via HEADLINE_SECONDS / HEADLINE_Y.
HEADLINE_SECONDS = float(os.environ.get("HEADLINE_SECONDS", "3.0"))
HEADLINE_Y = int(os.environ.get("HEADLINE_Y", "300"))

def _headline_event(text):
    """One top-anchored ASS event: the hook headline, shown for the first
    HEADLINE_SECONDS with a quick fade. Auto-shrinks to fit the frame width so a
    long headline never runs off the edges. Returns the Dialogue line or None."""
    clean = re.sub(r"[{}\\]", "", str(text or "")).upper().strip()
    if not clean:
        return None
    base_fs = int(PROFILE.get("cap_size", 120))
    hl_fs = int(base_fs * 1.15)                      # a touch bigger than captions
    est_w = len(clean) * 0.60 * hl_fs
    if est_w > 1000:                                 # fit within the safe width
        hl_fs = max(50, int(1000.0 / (len(clean) * 0.60)))
    # \an8 = top-centre anchor; bold; quick fade in/out so it doesn't hard-blink.
    tag = (f"{{\\an8\\pos(540,{HEADLINE_Y})\\fs{hl_fs}\\b1\\fad(150,250)}}")
    return f"Dialogue: 0,{_ass_t(0.0)},{_ass_t(max(0.5, HEADLINE_SECONDS))},Pop,,0,0,0,,{tag}{clean}"


# Short function words that read as a weak caption frame when shown alone
# ("OF", "THE", "A"). They ride along with an adjacent word instead — see
# _group_function_words. NOT dropped: the word still appears, just grouped.
_CAPTION_FUNCTION_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "is", "it", "as", "or",
    "and", "by", "for", "its", "so", "up", "no", "if", "we", "be",
}


def _group_function_words(word_times, max_chars=15):
    """Merge a lone short function word into an adjacent caption frame so no
    frame is just 'OF'/'THE'/'A' — WITHOUT dropping any word. Both words show in
    the merged frame and it spans both their spoken windows, so coverage stays
    word-for-word (the thing the user asked for) while killing the weak
    single-function-word frames. A function word attaches FORWARD to the word it
    leads into (articles/prepositions -> their noun); a trailing one attaches
    backward. Skipped when the merged text would be too wide for the no-wrap
    one-word style (max_chars), so a caption never overflows the frame."""
    n = len(word_times)
    if n < 2:
        return list(word_times)
    out = []
    i = 0
    while i < n:
        w, st, en = word_times[i]
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        is_fn = bare in _CAPTION_FUNCTION_WORDS
        if is_fn and i + 1 < n:
            w2, st2, en2 = word_times[i + 1]
            if len(w) + 1 + len(w2) <= max_chars:
                out.append((f"{w} {w2}", min(st, st2), max(en, en2)))
                i += 2
                continue
        if is_fn and out and i + 1 >= n:          # trailing function word
            pw, pst, pen = out[-1]
            if len(pw) + 1 + len(w) <= max_chars:
                out[-1] = (f"{pw} {w}", min(pst, st), max(pen, en))
                i += 1
                continue
        out.append((w, st, en))
        i += 1
    return out


# Captions are nudged a touch LATER than the word's raw onset. ElevenLabs' word
# "start" marks the phoneme onset, which lands a hair BEFORE the ear registers
# the word — so word-perfect timing still reads as "the subtitle is ahead of the
# narrator" (the user's "he's behind the subtitles" note). A small lead-in delay
# makes the caption appear WITH the voice (the eye is happy to trail the ear,
# never to lead it). Tunable via CAPTION_DELAY_MS; 0 restores raw onset timing.
CAPTION_DELAY_S = max(0.0, float(os.environ.get("CAPTION_DELAY_MS", "110"))) / 1000.0


def build_ass(scenes, segments, actual_durs, path, headline=""):
    """Place every word's caption at the SAME instant it is actually spoken in
    the final concatenated audio.

    With no padding and clean hard-cut concat, the final audio is just the
    per-scene spoken segments joined back-to-back, so a word maps to its raw
    ElevenLabs WORD_TIMINGS start -- corrected ONLY for the tiny per-scene cut
    rounding between each segment's REQUESTED length (seg_dur, the boundary
    WORD_TIMINGS is anchored to) and the segment's ACTUALLY-rendered length
    (actual_durs, ffprobed off the built scene clips). That correction is the
    scene's shift:
        shift_i = final_start_i - orig_start_i
    where orig_start_i = sum of requested seg_durs before scene i (original
    full_vo timeline) and final_start_i = sum of actual scene durations before
    scene i (assembled-audio timeline). No pause/crossfade offsets exist
    anymore, so shift_i is only ever a few ms of cut rounding.

    segments:    split_audio output [(speech_mp3_path, seg_dur), ...]
    actual_durs: ffprobe duration of each rendered scene clip (or seg_dur if a
                 scene clip couldn't be probed)."""
    events = []
    seg_durs = [d for _, d in segments]
    orig_starts = _prefix_starts(seg_durs)
    final_starts = _prefix_starts(actual_durs)
    # DIAGNOSTIC (2026-08-02, user-reported footage/narration timing drift):
    # this docstring's own claim ("only ever a few ms of cut rounding") has
    # never actually been measured on a real render. If a scene's REQUESTED
    # duration (seg_dur, what the audio segment was cut to) and its ACTUAL
    # rendered duration (footage build, ffprobed) disagree by more than a
    # frame or two, video and audio at that scene boundary genuinely drift
    # apart -- print it so the next render's log can confirm or rule this out.
    _max_drift = max((abs(a - b) for a, b in zip(seg_durs, actual_durs)), default=0.0)
    if _max_drift > 0.05:
        print(f"  [sync] max per-scene requested-vs-rendered duration drift: {_max_drift:.3f}s")

    def _shift(i):
        j = min(i, len(orig_starts) - 1, len(final_starts) - 1)
        if j < 0:
            return 0.0
        return final_starts[j] - orig_starts[j]

    # One caption per spoken word, EXCEPT a lone short function word rides along
    # with its neighbour (_group_function_words) so there's no weak 'OF'/'THE'
    # frame. An earlier version was read as "the subtitles don't pick up every
    # word" because it DROPPED the function word; this one keeps every word (both
    # show in the merged frame), so coverage stays word-for-word and tightly
    # synced while the lone-function-word frames are gone.
    def _emit(word_times):
        for w, st, en in _group_function_words(word_times):
            events.append(_event(st + CAPTION_DELAY_S, en + CAPTION_DELAY_S, w))

    if WORD_TIMINGS:
        # exact: drive captions from ElevenLabs word timings, per-scene shift
        word_i = 0
        for i, sc in enumerate(scenes):
            n_words = len(sc["voiceover"].split())
            shift = _shift(i)
            wt = [(w, st + shift, en + shift)
                  for w, st, en in WORD_TIMINGS[word_i:word_i + n_words]
                  if re.sub(r"[^A-Za-z0-9]", "", w)]
            _emit(wt)
            word_i += n_words
        # any leftover words beyond the scenes' combined word count (rare
        # mismatch) -- keep them, shifted by the last scene's offset
        if word_i < len(WORD_TIMINGS):
            shift = _shift(len(scenes) - 1)
            wt = [(w, st + shift, en + shift)
                  for w, st, en in WORD_TIMINGS[word_i:]
                  if re.sub(r"[^A-Za-z0-9]", "", w)]
            _emit(wt)
    else:
        # fallback (no ElevenLabs timings): estimate by word length within each
        # scene's actual audio span, anchored at the scene's real start on the
        # assembled timeline.
        for i, sc in enumerate(scenes):
            words = sc["voiceover"].split()
            if not words:
                continue
            speech_dur = actual_durs[i] if i < len(actual_durs) else (
                seg_durs[i] if i < len(seg_durs) else 3.0)
            clock = final_starts[i] if i < len(final_starts) else 0.0
            weights = [max(2, len(re.sub(r"[^A-Za-z0-9]", "", w))) for w in words]
            total = sum(weights) or 1
            wt = []
            for w, wght in zip(words, weights):
                wd = speech_dur * wght / total
                wt.append((w, clock, clock + wd)); clock += wd
            _emit(wt)
    # Prepend the top-of-frame hook headline (first few seconds) if one was written.
    hl = _headline_event(headline)
    if hl:
        events.insert(0, hl)
    with open(path, "w") as f:
        f.write(_ass_header() + "\n".join(events) + "\n")


# ---------- CONCAT: clean hard cuts on exact word-timing boundaries ----------
# Scenes are joined with the concat demuxer: a plain, sample-accurate hard cut
# at each scene's word boundary. Each scene's audio is its FULL spoken segment,
# so no sentence is ever clipped at a transition. (An earlier acrossfade/xfade
# chain overlapped the tail of one scene's audio with the head of the next,
# which cut off the narrator every time the slide changed -- the exact user
# complaint. A visual crossfade is not worth cutting a single spoken word.)
def build_body_concat(scene_files, out_path):
    """Hard-cut concat demuxer: joins scene clips back-to-back with no audio
    crossfade, reproducing the original full_vo timeline exactly."""
    listfile = os.path.join(WORK, "list.txt")
    with open(listfile, "w") as lf:
        for f in scene_files:
            lf.write(f"file '{os.path.abspath(f)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", out_path])


def build_body_xfade(scene_files, out_path, xf=None, style=None):
    """OPT-IN smoother join (SCENE_XFADE>0): cross-dissolve the VIDEO between
    scenes while the AUDIO is a plain hard-cut concat (never overlapped, so no
    spoken word is ever clipped — the failure that retired the old acrossfade).

    The xfade chain shortens the video by (N-1)*xf vs the audio, so the held
    final frame is padded back out (tpad) to keep the video at least as long as
    the audio; ffmpeg's -shortest then trims to the audio. On ANY failure this
    raises, and main() falls back to build_body_concat — this can never break a
    render. Returns nothing; writes out_path."""
    xf = SCENE_XFADE if xf is None else xf
    style = SCENE_XFADE_STYLE if style is None else style
    n = len(scene_files)
    if n < 2 or xf <= 0:
        return build_body_concat(scene_files, out_path)
    durs = [ffprobe_dur(f) for f in scene_files]
    # every clip must be longer than the dissolve or the offsets go negative
    if any(d <= xf + 0.05 for d in durs):
        raise RuntimeError(f"a scene is too short for a {xf}s dissolve ({durs})")
    offs = _xfade_offsets(durs, xf)
    inputs = []
    for f in scene_files:
        inputs += ["-i", f]
    # video: chained xfade;  audio: hard-cut concat of every scene's own segment
    vfilters, prev = [], "[0:v]"
    for k in range(1, n):
        label = f"[vx{k}]"
        vfilters.append(f"{prev}[{k}:v]xfade=transition={style}:duration={xf}:"
                        f"offset={offs[k-1]}{label}")
        prev = label
    pad = round((n - 1) * xf + 0.1, 3)  # restore length lost to the overlaps
    vfilters.append(f"{prev}tpad=stop_mode=clone:stop_duration={pad}[vout]")
    aconcat = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    filtergraph = ";".join(vfilters + [aconcat])
    run(["ffmpeg", "-y", *inputs, "-filter_complex", filtergraph,
         "-map", "[vout]", "-map", "[aout]", "-shortest",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", out_path])


# ---------- COVER / THUMBNAIL ----------
# Every finished video ships with a designed cover so the profile grid never
# shows a black frame (the "no one clicks a black tile" problem). Built off the
# CLEAN pre-caption body video with ffmpeg drawtext (no new dependency, same
# path as the stat-cards), so it can't clash with the burned-in captions. Fully
# fail-safe: any error just skips the cover and the video still ships.

def _cover_headline(m):
    """Short ALL-CAPS hook for the cover: the manifest's hook_headline if the
    generator wrote one, else a trimmed uppercase title. Pure/testable."""
    h = (m.get("hook_headline") or "").strip()
    if not h:
        h = (m.get("title") or "SCIENCE").strip()
    return h.upper()[:60]


def _frame_stats(png):
    """(mean luma, mean saturation) of an image via ffmpeg signalstats, 0-255
    each, or (None, None). Saturation is a cheap proxy for 'visually interesting'
    — a vivid subject scores far above a flat gray texture."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", png, "-vf",
             "signalstats,metadata=print", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True, timeout=20).stderr
        y = re.search(r"YAVG=([0-9.]+)", out)
        s = re.search(r"SATAVG=([0-9.]+)", out)
        return (float(y.group(1)) if y else None,
                float(s.group(1)) if s else None)
    except Exception:  # noqa: BLE001
        return (None, None)


def _pick_cover_frame(video, dest):
    """Extract the best-looking frame from the clean body video: sample across
    the middle of the clip and, among frames bright enough to pop on the grid
    (not near-black, not blown out), take the most COLORFUL one — a vivid subject
    beats a flat gray texture. Falls back to the brightest if none qualify.
    Returns dest or None."""
    dur = ffprobe_dur(video) or 0
    if dur <= 0:
        return None
    bright, colorful = None, None   # (score, path)
    for frac in (0.16, 0.26, 0.36, 0.46, 0.56, 0.66, 0.76, 0.86):
        cand = os.path.join(WORK, f"cover_cand_{int(frac*100)}.png")
        try:
            run(["ffmpeg", "-y", "-ss", f"{dur*frac:.2f}", "-i", video,
                 "-frames:v", "1", cand])
        except Exception:  # noqa: BLE001
            continue
        y, sat = _frame_stats(cand)
        if y is None:
            continue
        if bright is None or -abs(y - 125) > bright[0]:
            bright = (-abs(y - 125), cand)
        if 55 <= y <= 205 and sat is not None:        # well-exposed → rank by colorfulness
            if colorful is None or sat > colorful[0]:
                colorful = (sat, cand)
    pick = colorful or bright
    if pick is None:
        return None
    shutil.copyfile(pick[1], dest)
    return dest


def make_cover(video, m, dest):
    """Write a designed cover JPG (best clean frame + the hook headline burned
    on, yellow accent on the last line, channel handle at the bottom). Never
    raises — returns True on success, False (and skips) on any problem."""
    try:
        src = _pick_cover_frame(video, os.path.join(WORK, "cover_src.png"))
        if not src:
            print("  [cover] no usable frame — skipping"); return False
        fs, lines = _fit_text_block(_cover_headline(m), int(W * 0.88), int(H * 0.30),
                                    max_fs=118, min_fs=60)
        line_h = fs * 1.26
        top = int(H * 0.13)
        band_h = int(top + line_h * len(lines) + 70)
        filters = [f"drawbox=x=0:y=0:w=iw:h={band_h}:color=black@0.45:t=fill"]
        for i, l in enumerate(lines):
            lf = os.path.join(WORK, f"cover_l{i}.txt")
            with open(lf, "w") as f:
                f.write(l)
            color = "#FFD400" if (len(lines) > 1 and i == len(lines) - 1) else "white"
            filters.append(
                f"drawtext=textfile='{lf}':fontfile='{FONT}':fontsize={fs}:"
                f"fontcolor={color}:borderw=9:bordercolor=black:"
                f"x=(w-tw)/2:y={int(top + i*line_h)}")
        handle = os.getenv("CHANNEL_HANDLE", "").strip()
        if handle:
            hf = os.path.join(WORK, "cover_handle.txt")
            with open(hf, "w") as f:
                f.write(handle)
            filters.append(
                f"drawtext=textfile='{hf}':fontfile='{FONT}':fontsize=46:"
                f"fontcolor=white:borderw=6:bordercolor=black:x=(w-tw)/2:y=h-130")
        run(["ffmpeg", "-y", "-i", src, "-vf", ",".join(filters),
             "-frames:v", "1", "-q:v", "3", dest])
        print(f"  [cover] wrote {dest} ({len(lines)} line(s), fs {fs})")
        return True
    except Exception as e:  # noqa: BLE001 — a cover is a nice-to-have, never fatal
        print(f"  [cover] generation failed ({e}) — skipping (video still ships)")
        return False


def _seamless_loop_bed(src, dst, xf=1.5):
    """Rewrite `src` into a track that loops with NO audible restart, for the
    -stream_loop -1 mix in main() (2026-08-03 craft-audit finding: the committed
    music_*.mp3 beds are short ~8s loops — ffprobe confirms music_science.mp3 =
    8.05s — so a ~40s video restarts the track audibly ~5 times with a hard
    jump at every seam, the classic "amateur" tell). Standard crossfade-loop
    technique: split the track into head (first xf sec), tail (last xf sec) and
    mid (everything between); crossfade tail-into-head to build a `seam`, then
    output mid+seam as ONE loop unit. This loops perfectly because `mid` starts
    exactly where the original `head` ends, and `seam` ends with the original
    `head` at full volume — so mid->seam->mid->seam... is continuous audio with
    no jump, not just a shorter loop with the same click.

    Each piece is rendered to its OWN temp file with a separate ffmpeg pass
    (rather than one filter_complex with atrim branches sharing one input) —
    acrossfade fed two branches split from the same source stalls/produces zero
    frames in this ffmpeg build; independently-decoded files don't have that
    problem. `xf` is clamped to the *actual* decoded head/tail duration (mp3
    frame-boundary seeking can shave a little off the requested trim) with a
    safety margin, since acrossfade silently emits nothing if `d` exceeds
    either input's real length. Fails open: any error, or a track too short to
    safely crossfade, returns `src` unchanged (old hard-loop behaviour) —
    never blocks the render."""
    try:
        d = ffprobe_dur(src) or 0
        xf = min(xf, d / 4.0)
        if d <= xf * 3 or xf < 0.2:
            return src  # too short to crossfade safely — loop as-is
        tail_start = d - xf
        head_wav = dst + ".head.wav"
        tail_wav = dst + ".tail.wav"
        mid_wav  = dst + ".mid.wav"
        seam_wav = dst + ".seam.wav"
        run(["ffmpeg", "-y", "-i", src, "-filter_complex",
             f"[0:a]atrim=0:{xf:.3f},asetpts=PTS-STARTPTS[o]", "-map", "[o]", head_wav])
        run(["ffmpeg", "-y", "-i", src, "-filter_complex",
             f"[0:a]atrim={tail_start:.3f}:{d:.3f},asetpts=PTS-STARTPTS[o]", "-map", "[o]", tail_wav])
        run(["ffmpeg", "-y", "-i", src, "-filter_complex",
             f"[0:a]atrim={xf:.3f}:{tail_start:.3f},asetpts=PTS-STARTPTS[o]", "-map", "[o]", mid_wav])
        # clamp the crossfade length to what actually got decoded, minus a
        # safety margin, so acrossfade never receives d >= either input's length
        real_xf = min(xf, (ffprobe_dur(head_wav) or 0), (ffprobe_dur(tail_wav) or 0)) - 0.05
        if real_xf < 0.2:
            return src
        run(["ffmpeg", "-y", "-i", tail_wav, "-i", head_wav, "-filter_complex",
             f"[0:a][1:a]acrossfade=d={real_xf:.3f}:c1=tri:c2=tri[o]", "-map", "[o]", seam_wav])
        run(["ffmpeg", "-y", "-i", mid_wav, "-i", seam_wav, "-filter_complex",
             "[0:a][1:a]concat=n=2:v=0:a=1[o]", "-map", "[o]", dst])
        ok = (ffprobe_dur(dst) or 0) > 1.0
        for tmp in (head_wav, tail_wav, mid_wav, seam_wav):
            try:
                os.remove(tmp)
            except OSError:
                pass
        if ok:
            print(f"  [music] built a seamless {ffprobe_dur(dst):.1f}s loop unit "
                  f"(was a hard {d:.1f}s loop with an audible restart)")
            return dst
    except Exception as e:  # noqa: BLE001 — never block the render over this
        print(f"  [music] seamless-loop build failed ({e}) — looping raw track")
    return src


# ---------- MUSIC BED ----------
def _ensure_music_bed(duration):
    """Path to a music bed so every video has one instead of dead silence (the
    #1 'it doesn't POP' fix). Prefers a committed royalty-free `music.mp3` — drop
    your own energetic track there for maximum energy, or point MUSIC_URL at a
    CC0 track. If none exists, synthesize a warm, license-safe cinematic pad with
    ffmpeg (an open A-chord — root/fifth/octave — softly swelling, lowpassed and
    quiet). Not a jingle: it sits ~18 dB under the voice and adds warmth/tension
    a silent track can't. Returns None only if synthesis fails (then: silence).

    Priority: MUSIC_URL (paste a royalty-free link via the repo Variable — wins so
    you can swap tracks without committing a file) > committed per-profile track >
    synthesized pad."""
    url = os.getenv("MUSIC_URL", "").strip()
    if url:
        dst = os.path.join(WORK, "music_url.mp3")
        try:
            _download(url, dst)
            bd = ffprobe_dur(dst) or 0
            if bd > 1.0:
                print(f"[music] using MUSIC_URL track ({bd:.0f}s): {url[:60]}")
                if bd < (duration or 40):
                    return _seamless_loop_bed(dst, os.path.join(WORK, "music_url_loop.mp3"))
                return dst
            print("[music] MUSIC_URL did not fetch usable audio — falling back")
        except Exception as e:  # noqa: BLE001
            print(f"[music] MUSIC_URL fetch failed ({e}) — falling back")
    if os.path.exists(MUSIC):
        if (ffprobe_dur(MUSIC) or 0) < (duration or 40):
            return _seamless_loop_bed(MUSIC, os.path.join(WORK, "music_bed_loop.mp3"))
        return MUSIC
    bed = os.path.join(WORK, "bed.wav")
    d = max(4.0, float(duration or 40) + 1.0)
    try:
        run(["ffmpeg", "-y",
             "-f", "lavfi", "-i", f"sine=frequency=110:duration={d:.2f}",       # A2 root
             "-f", "lavfi", "-i", f"sine=frequency=164.81:duration={d:.2f}",    # E3 fifth
             "-f", "lavfi", "-i", f"sine=frequency=220:duration={d:.2f}",       # A3 octave
             "-filter_complex",
             "[0:a]volume=0.5[a0];[1:a]volume=0.30[a1];[2:a]volume=0.22[a2];"
             "[a0][a1][a2]amix=inputs=3:normalize=0,"
             "tremolo=f=0.12:d=0.35,highpass=f=55,lowpass=f=520,"
             "afade=t=in:d=1.8,afade=t=out:st={fo:.2f}:d=1.5[b]".format(fo=max(0.0, d - 1.6)),
             "-map", "[b]", bed])
        return bed
    except Exception as e:  # noqa: BLE001 — a bed is a nice-to-have, never fatal
        print(f"[music] procedural bed synthesis failed ({e}) — no bed this run")
        return None


# ---------- CUT WHOOSHES (rhythm/punch on scene changes) ----------
# Cut whooshes OFF by default — the user found them distracting ("not sure I like
# it") and, with the same-photo fake-cuts removed, there are far fewer real cuts to
# punctuate anyway. Opt back in per-render with SFX_CUTS=1.
SFX_CUTS = os.getenv("SFX_CUTS", "0") != "0"
# Sidechain-duck the music bed under the voice (see the final mix in main()).
# ON by default, unlike SFX_CUTS — this is a standard, near-universal mixing
# technique (not a stylistic add-on the user might dislike the way the cut
# whooshes turned out to be). Kept env-gated for an easy A/B or rollback.
MUSIC_DUCK = os.getenv("MUSIC_DUCK", "1") != "0"


def _make_cut_whooshes(cut_times, total_dur, dest):
    """A silent track with a short, SUBTLE whoosh at each scene-cut time, mixed
    into the final audio so cuts have rhythm/punch (the "make it POP" ask).
    License-safe — an ffmpeg pink-noise burst, no sample. Env-gated (SFX_CUTS)
    and fail-safe: any build error just skips the whooshes (never breaks a
    render). Returns dest or None."""
    cuts = [t for t in (cut_times or []) if 0.15 < t < float(total_dur) - 0.15]
    if not cuts:
        return None
    whoosh = os.path.join(WORK, "whoosh.wav")
    try:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.28:c=pink:a=0.5",
             "-af", "bandpass=f=1300:width_type=h:w=2000,afade=t=in:d=0.04,"
             "afade=t=out:st=0.09:d=0.19,volume=0.6", whoosh])
        inputs = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={float(total_dur)+0.5:.2f}"]
        fparts, labels = [], ["[0:a]"]
        for i, t in enumerate(cuts, start=1):
            inputs += ["-i", whoosh]
            ms = int(t * 1000)
            fparts.append(f"[{i}:a]adelay={ms}|{ms}[w{i}]")
            labels.append(f"[w{i}]")
        fparts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0[o]")
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fparts), "-map", "[o]", dest])
        return dest
    except Exception as e:  # noqa: BLE001
        print(f"  [sfx] cut-whoosh build failed ({e}) — skipping")
        return None


# ---------- MAIN ----------
def main():
    mpath = sys.argv[1] if len(sys.argv) > 1 else "manifest.json"
    with open(mpath) as f:
        m = json.load(f)
    global voice, rate
    # Prefer the PROFILE's edge_voice (a deeper, more documentary-sounding free
    # voice — en-GB-RyanNeural for science) over the manifest's generic default.
    # The manifest is written by generate.py with a fixed "en-US-GuyNeural"; the
    # profile is where the channel's intended voice lives. This makes the free
    # fallback voice sound closer to the deep read the channel wants (the paid
    # ElevenLabs voice is still used first whenever credits are available).
    voice = PROFILE.get("edge_voice") or m.get("render", {}).get("voice", "en-US-GuyNeural")
    rate  = m.get("render", {}).get("rate", "-5%")
    _apply_vibe(m.get("vibe", "awe"))

    for d in (WORK, OUT):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)

    load_used_footage()
    print(f"[footage] {len(_used_video_ids)} clip ids excluded from prior runs")

    print("[voice] full track...")
    # Always synthesize the concatenated per-scene voiceovers, not m["script"]
    # (a separately-written field the LLM doesn't guarantee matches the scenes
    # word-for-word) — this is what split_audio's word-timing cuts and the
    # karaoke captions both key off of, so TTS/captions/scene-cuts must all
    # measure the same text or they drift out of sync with each other.
    # Join scene voiceovers into one narration for TTS, ENSURING each scene ends
    # with sentence-final punctuation. The model often writes scene lines with no
    # trailing period ("...the same size", "...were closer"), so the TTS engine
    # runs every sentence together with no beat — exactly the "no pause between
    # sentences, sounds rushed" complaint. A terminal '.' makes both ElevenLabs
    # and edge-tts insert a natural sentence pause. This changes only the spoken
    # text's punctuation, not the words, so per-scene word counts (and thus the
    # caption/scene-cut word indexing) are unchanged.
    def _terminate(vo):
        vo = (vo or "").strip()
        return vo if vo[-1:] in ".!?…:" else vo + "."
    full_script = " ".join(_terminate(s["voiceover"]) for s in m["scenes"])
    full_mp3 = os.path.join(WORK, "full_vo.mp3")
    if not tts_full(full_script, full_mp3, voice, rate):
        silent_track(sum(float(s.get("duration", 3)) for s in m["scenes"]), full_mp3)

    # CAPTION-SYNC FIX (free): if the TTS engine gave no real word timings
    # (edge-tts frequently returns none), recover them by forced-aligning the
    # actual audio with whisper, instead of shipping the drifting proportional
    # estimate. This is what keeps subtitles locked to the narrator on the free
    # voice. ElevenLabs already provides exact timings, so this only runs on the
    # free fallback, and it fails safe (keeps the estimate) if whisper is absent.
    global WORD_TIMINGS
    if not WORD_TIMINGS:
        aligned = whisper_align(full_mp3, full_script)
        if aligned:
            WORD_TIMINGS = aligned

    # each scene's on-screen duration == its own spoken segment (no padding)
    segments = split_audio(full_mp3, m["scenes"], WORK)

    _diversify_scene_queries(m["scenes"])
    _diversify_scene_motions(m["scenes"])

    scene_files = []
    for i, (sc, (seg_path, seg_dur)) in enumerate(zip(m["scenes"], segments), 1):
        print(f"[scene {i}/{len(m['scenes'])}] {sc['search_query']} (speech {seg_dur:.2f}s)")
        scene_files.append(build_scene(sc, i, seg_path, seg_dur))

    if JUDGE_SCORES:
        print(f"[quality] judge scores: min {min(JUDGE_SCORES)}/10, "
              f"avg {sum(JUDGE_SCORES) / len(JUDGE_SCORES):.1f}/10 "
              f"across {len(JUDGE_SCORES)} scene(s) scored; "
              f"{STAT_CARD_SCENES} stat-card, {ARCHIVAL_SCENES} archival-still scene(s)")
    else:
        print(f"[quality] no judge scores recorded this render (no GROQ key / no "
              f"candidates found); {STAT_CARD_SCENES} stat-card, "
              f"{ARCHIVAL_SCENES} archival-still scene(s)")

    # FOOTAGE-STARVATION GUARD. MAX_STAT_CARDS is a *design* cap (a rare text
    # card is a fine accent), but it only holds when Pexels actually returns
    # clips to fall back to. When Pexels itself is unavailable (free-tier
    # rate-limit/quota exhausted, network) it returns ZERO candidates for every
    # scene, best_cand stays None, accept_best can't rescue, and EVERY scene
    # silently becomes a text card — an all-slideshow video with no real
    # footage (the turtle render: 10/10 cards, unwatchable). That must NOT be
    # published. Same principle as generate.py's abort-on-failure: degrade to
    # NO video, never to a broken one. Exit non-zero so the workflow's release
    # step (success-only) never ships a footage-starved slideshow; the daily
    # cron simply tries again once the quota resets.
    if STAT_CARD_SCENES > MAX_STAT_CARDS:
        print(f"ERROR: {STAT_CARD_SCENES}/{len(m['scenes'])} scenes fell back to "
              f"text cards (> MAX_STAT_CARDS={MAX_STAT_CARDS}). Real footage was "
              f"unavailable (Pexels rate-limit/quota or no relevant results). "
              f"Aborting so a no-footage slideshow is never published — retry "
              f"after the stock-footage quota resets.")
        sys.exit(1)

    save_used_footage()  # persist before the render steps below, in case one of them fails

    # concat: clean HARD CUTS on exact word-timing boundaries. Each scene's
    # audio is its full, uncut spoken segment; concatenating them back-to-back
    # reproduces the original full_vo timeline, so no word is ever
    # crossfaded/clipped at a scene change (the old acrossfade overlapped and
    # cut off the end of each sentence).
    body = os.path.join(WORK, "body.mp4")
    if SCENE_XFADE > 0:
        try:
            build_body_xfade(scene_files, body)
            print(f"[concat] xfade join OK ({len(scene_files)} scenes, "
                  f"{SCENE_XFADE}s video dissolve, audio hard-cut)")
        except Exception as e:  # noqa: BLE001 - never let a transition break a render
            print(f"[concat] xfade failed ({e}); falling back to hard-cut concat")
            build_body_concat(scene_files, body)
            print(f"[concat] hard-cut concat OK ({len(scene_files)} scenes, no audio crossfade)")
    else:
        build_body_concat(scene_files, body)
        print(f"[concat] hard-cut concat OK ({len(scene_files)} scenes, no audio crossfade)")

    # captions (karaoke) + hook title card (first 2.6s, top) — the docstring
    # always promised a hook overlay but none was ever rendered; the written
    # hook only existed in the audio. Burning it in gives scrollers a reason
    # to stop before the voiceover even registers.
    #
    # Caption sync: each word maps to its raw ElevenLabs WORD_TIMINGS, corrected
    # per-scene only for the few-ms cut rounding between the requested segment
    # length and the actually-rendered scene audio (ffprobed below).
    actual_durs = [ffprobe_dur(f) for f in scene_files]
    # scene-cut boundaries (cumulative, excluding the final end) for the cut SFX
    cut_times, _acc = [], 0.0
    for _d in actual_durs[:-1]:
        _acc += (_d or 0.0)
        cut_times.append(_acc)
    # keyword-pop: tokenize the video's core keyword so _event can render those
    # words in the accent colour (>2 chars only, so "of"/"in" don't pop everywhere)
    global _KEYWORD_TOKENS
    _KEYWORD_TOKENS = {re.sub(r"[^A-Z0-9]", "", w.upper())
                       for w in re.findall(r"[A-Za-z0-9']+", m.get("keyword", ""))
                       if len(w) > 2}
    ass = os.path.join(WORK, "captions.ass")
    # NO on-screen hook headline burned over the video: it rendered at the TOP
    # while the karaoke captions ran in the MIDDLE = two sets of subtitles at once
    # (user feedback — the exact "double caption" complaint). The hook_headline now
    # lives ONLY on the cover thumbnail (make_cover), where it belongs.
    build_ass(m["scenes"], segments, actual_durs, ass, headline="")
    body_dur = ffprobe_dur(body)
    # ENDING HOLD (2026-08-03 craft-audit finding): the fade-out used to start
    # 0.3s before the LAST WORD's own audio ended — the payoff line got zero
    # beat to land before cutting to black, the "no intentional ending" tell a
    # real editor would flag. tpad clones the final video frame and apad appends
    # silence to the voice track for ENDING_HOLD extra seconds (the music bed,
    # mixed in later from a separately-looped input, naturally keeps playing
    # under the hold), then a slightly longer, gentler fade runs across that
    # held tail instead of stacking right on top of the final spoken word.
    ENDING_HOLD = float(os.getenv("ENDING_HOLD_SECONDS", "0.7"))
    padded_dur = body_dur + ENDING_HOLD
    fade_dur = min(0.6, ENDING_HOLD + 0.2)
    fade_out_start = max(0.0, padded_dur - fade_dur)
    # NO separate hook title-card. It used to burn the hook text across the top
    # for the first 2.6s, but now that the karaoke captions are word-synced they
    # already show the hook one word at a time — the card on top read as TWO sets
    # of subtitles at once (user feedback on Unseen Oceans). Just the karaoke
    # captions now.
    captioned = os.path.join(WORK, "captioned.mp4")
    # NO fade-IN from black: a fade-from-black makes frame 0 a black frame, and
    # video pickers/schedulers (Publer, TikTok upload, etc.) use frame 0 as the
    # thumbnail — so every video looked like an identical black tile in the queue
    # and the user couldn't tell them apart (user feedback 2026-07-22). Starting
    # hard on the first footage frame fixes the thumbnail AND recovers the ~0.2s
    # of black at the top (every fraction counts for retention). Keep the fade-OUT
    # at the end — the last frame isn't used as a thumbnail.
    run(["ffmpeg", "-y", "-i", body,
         "-vf", (f"tpad=stop_mode=clone:stop_duration={ENDING_HOLD:.2f},"
                 f"ass='{ass}':fontsdir='{FONTS_DIR}',"
                 f"fade=t=out:st={fade_out_start:.2f}:d={fade_dur:.2f}"),
         "-af", f"apad=pad_dur={ENDING_HOLD:.2f}",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", captioned])

    # SOUND DESIGN — signature intro sting (subtle brand mark). Generated with
    # ffmpeg (no external asset): two low partials a fifth apart with a soft
    # swell, lowpassed and quiet (~-25 dB peak, verified) so it reads as a
    # calm "we're beginning" cue matching the channel identity, not a jingle.
    # Frequencies/lowpass now scale with CURRENT_VIBE (_vibe_sting_freqs) —
    # was hardcoded 98/147/1200 regardless of mood, the one sound-design
    # element that never varied at all. Plays once under the opening ~1s.
    # Profile-gated (sfx).
    sting = None
    if PROFILE.get("sfx", True):
        sting = os.path.join(WORK, "sting.wav")
        try:
            f1, f2, lp = _vibe_sting_freqs()
            run(["ffmpeg", "-y", "-f", "lavfi", f"-i", f"sine=frequency={f1:.2f}:duration=1.0",
                 "-f", "lavfi", "-i", f"sine=frequency={f2:.2f}:duration=1.0",
                 "-filter_complex",
                 "[0:a]volume=0.6[a0];[1:a]volume=0.35[a1];"
                 "[a0][a1]amix=inputs=2:normalize=0,afade=t=in:d=0.08,"
                 f"afade=t=out:st=0.55:d=0.45,volume=0.5,lowpass=f={lp}[s]",
                 "-map", "[s]", sting])
        except Exception as e:
            print("  [sfx] sting generation failed, skipping:", e)
            sting = None

    # Unified audio mix: voice + (optional music bed) + (optional intro sting),
    # amix normalize=0 so narration keeps its level (music_vol is pre-tuned to sit
    # ~18-20 dB under the voice; the sting is short and quiet). Handles any subset.
    final = os.path.join(OUT, "final.mp4")
    # Keep final.mp4 SMALL (~5MB) so Publer's "Upload Media from URL" (Zapier) can
    # fetch it within its ~30-second action timeout. A ~14MB file was timing out
    # and returning an EMPTY media id, which made Publer's "Create Post" fail with
    # "Document(s) not found for class Media::Base with id(s) ." (empty id). Capping
    # the bitrate to ~1 Mbps (=~5MB for a ~40s video) downloads in a few seconds;
    # TikTok/Reels/Shorts re-encode every upload anyway, so the visible-quality hit
    # is negligible while the post now actually succeeds. Override with UPLOAD_MAXRATE.
    crf = "27"
    _vbv_max = os.environ.get("UPLOAD_MAXRATE", "1000k")
    VBV = ["-maxrate", _vbv_max, "-bufsize", "2000k"]
    ff_inputs, filt, labels, idx = ["-i", captioned], [], ["[0:a]"], 1
    bed_path = _ensure_music_bed(padded_dur)
    if bed_path:
        print(f"[music] mixing bed under voice ({os.path.basename(bed_path)}, vibe={CURRENT_VIBE})")
        ff_inputs += ["-stream_loop", "-1", "-i", bed_path]
        if MUSIC_DUCK:
            # SIDECHAIN DUCKING (2026-08-03 craft-audit finding): the mix used to
            # be a flat, constant music_vol for the ENTIRE runtime — the same
            # level whether the narrator was mid-sentence or between scenes, the
            # classic "amateur" mix tell (real editors duck the bed under voice).
            # sidechaincompress keys the music's gain off the VOICE track ([0:a]):
            # it ducks a few extra dB while the narrator is actually talking and
            # lets the bed breathe back up to its tuned baseline in the gaps
            # between lines, instead of one dead-flat level throughout.
            filt.append(f"[{idx}:a]{_vibe_music_filter()}[m_raw]")
            filt.append(f"[m_raw][0:a]sidechaincompress=threshold=0.05:ratio=6:"
                        f"attack=25:release=400:makeup=1[m]")
        else:
            filt.append(f"[{idx}:a]{_vibe_music_filter()}[m]")
        labels.append("[m]"); idx += 1
    else:
        print("[music] no bed this run — narration only")
    if sting:
        print("[sfx] mixing signature intro sting")
        ff_inputs += ["-i", sting]
        labels.append(f"[{idx}:a]"); idx += 1
    whoosh_track = _make_cut_whooshes(cut_times, body_dur,
                                      os.path.join(WORK, "whooshes.wav")) if SFX_CUTS else None
    if whoosh_track:
        n = len([t for t in cut_times if 0.15 < t < body_dur - 0.15])
        print(f"[sfx] mixing {n} subtle cut whooshes")
        ff_inputs += ["-i", whoosh_track]
        filt.append(f"[{idx}:a]volume=1.0[wf]")
        labels.append("[wf]"); idx += 1
    # Final loudness normalization to the social-media standard (~-14 LUFS
    # integrated, -1.5 dBTP true peak). Without it, output loudness drifts with
    # the voice/music levels, so some videos land quiet and get turned UP by the
    # platform (raising noise) while others get turned down — inconsistent and
    # unprofessional. loudnorm makes every video hit the same loudness the feed
    # expects, with headroom so it never clips.
    _LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if len(labels) > 1:
        filt.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:"
                    f"dropout_transition=0:normalize=0,{_LOUDNORM}[a]")
        run(["ffmpeg", "-y", *ff_inputs, "-filter_complex", ";".join(filt),
             "-map", "0:v", "-map", "[a]", "-map_metadata", "-1",
             "-c:v", "libx264", "-crf", crf, *VBV, "-preset", "medium",
             "-c:a", "aac", "-b:a", "96k", "-shortest", final])
    else:
        run(["ffmpeg", "-y", "-i", captioned, "-map_metadata", "-1",
             "-c:v", "libx264", "-crf", crf, *VBV, "-preset", "medium",
             "-af", _LOUDNORM, "-c:a", "aac", "-b:a", "96k", "-pix_fmt", "yuv420p", final])

    with open(os.path.join(OUT, "post.json"), "w") as f:
        # video_id (if present) is the key generate.py's performance-memory
        # scaffold expects in perf_<page>.json — carry it through so whoever
        # posts this video can record real engagement against the right id.
        # keyword and cta_style are carried through the same way for
        # repackage.py's write_platform_text() (search-keyword fallback for
        # captions, and cta_style so the CTA-rotation save-worthiness overhaul
        # in generate.py is visible in post-ready metadata, not just logs).
        json.dump({"title": m["title"], "captions": m["captions"], "hashtags": m["hashtags"],
                   "video_id": m.get("video_id", ""), "keyword": m.get("keyword", ""),
                   "cta_style": m.get("cta_style", ""),
                   # hook + domain feed funnel.py (topic-matched affiliate angle,
                   # pinned comment, newsletter blurb — see repackage.py).
                   "hook": m.get("hook", ""), "domain": m.get("domain", ""),
                   # vibe carried through so record_perf can log it alongside real
                   # engagement in perf_<page>.json — without this, "does the vibe
                   # system actually help" is unanswerable once data comes in.
                   "vibe": m.get("vibe", "")}, f, indent=2)
    # COVER: designed thumbnail off the CLEAN video (no burned captions) so the
    # profile grid shows a bold hook, never a black tile. Prefer the FIRST scene's
    # footage — the hook is always anchored to the video's primary SUBJECT, so the
    # cover is on-topic (render-160 fix: the old picker scanned the whole video and
    # chose the most colorful frame, landing a vivid OCEAN clip on a PLUTO video).
    # Falls back to the full body if scene 1 yields no usable frame. Never fatal.
    cover_src = scene_files[0] if scene_files else body
    if not make_cover(cover_src, m, os.path.join(OUT, "cover.jpg")) and cover_src is not body:
        make_cover(body, m, os.path.join(OUT, "cover.jpg"))
    qa_report = _final_qa_check(final, m)
    _persist_qa_to_memory(m.get("video_id", ""), qa_report)
    if _qa_should_abort(qa_report):
        fm, nf = qa_report.get("footage_matches_narration"), qa_report.get("narration_flow")
        reasons = []
        if not qa_report.get("ran"):
            reasons.append(f"final QA unavailable ({qa_report.get('error', 'judge did not run')})")
        elif not isinstance(fm, (int, float)):
            reasons.append("footage_matches_narration score missing/malformed")
        elif fm < FINAL_QA_ABORT_FLOOR:
            reasons.append(f"footage_matches_narration={fm}/10 (< {FINAL_QA_ABORT_FLOOR})")
        if qa_report.get("audio_judged") and not isinstance(nf, (int, float)):
            reasons.append("narration_flow score missing/malformed")
        elif isinstance(nf, (int, float)) and nf < FINAL_QA_FLOW_FLOOR:
            reasons.append(f"narration_flow={nf}/10 (< {FINAL_QA_FLOW_FLOOR})")
        print(f"ERROR: final assembled-video QA did not clear the publish bar: "
              f"{'; '.join(reasons)} — issue={qa_report.get('biggest_issue', '')!r}. "
              f"Aborting rather than release an unverified or demonstrably weak artifact; "
              f"consistency over cadence.")
        sys.exit(1)
    print("DONE ->", final, f"({ffprobe_dur(final):.1f}s)")


if __name__ == "__main__":
    main()
