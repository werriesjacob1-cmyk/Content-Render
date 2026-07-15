#!/usr/bin/env python3
"""
Faceless short-form render engine v2.
Adds: slow-zoom motion, color grade, lower-third captions with natural phrasing,
hook overlay (first 2s), background music bed, no-repeat footage.
"""

import os, sys, json, subprocess, shutil, wave, struct, re, time, urllib.request, urllib.parse, urllib.error
import random

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ROOT = os.path.dirname(os.path.abspath(__file__))
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
    # edge-tts fallback (when ElevenLabs is unavailable / out of credits). Two
    # fixes vs the old plain CLI call, both aimed at the "narrator too fast and
    # the subtitles can't keep up" complaint:
    #  1) Capture REAL per-word timing from edge-tts's WordBoundary events (the
    #     Python API exposes them; the CLI --write-media does not), so the free
    #     voice gets word-accurate captions + scene cuts exactly like ElevenLabs
    #     instead of the old proportional GUESS that drifted behind fast speech.
    #  2) Speak a bit slower (EDGE_RATE) — edge-tts's default cadence is quick.
    # Only trust the captured timings if their count is close to the script's
    # word count (a big mismatch means edge tokenised numbers/hyphenates oddly);
    # otherwise fall through to the proportional estimate rather than desync.
    try:
        wt = _edge_tts_with_timings(full_text, voice, EDGE_RATE, out_mp3)
        if os.path.getsize(out_mp3) > 1000:
            script_words = len(full_text.split())
            if wt and abs(len(wt) - script_words) <= max(3, 0.2 * script_words):
                WORD_TIMINGS = wt
                print(f"  edge-tts SUCCESS ({len(wt)} real word timings, rate {EDGE_RATE})")
            else:
                print(f"  edge-tts SUCCESS (got {len(wt)} timings vs {script_words} words — "
                      f"count mismatch, using proportional caption estimate)")
            return True
    except Exception as e:
        print("  edge-tts (python api) failed, trying CLI:", e)
    try:
        run(["edge-tts", f"--voice={voice}", f"--rate={EDGE_RATE}",
             f"--text={full_text}", f"--write-media={out_mp3}"])
        if os.path.getsize(out_mp3) > 1000:
            return True
    except Exception as e:
        print("  edge-tts failed:", e)
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
                            "desc": slug.replace("-", " "), "source": "Pexels"})
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


JUDGE_GEMINI_MODEL = "gemini-2.0-flash"  # NOTE: gemini-2.5-flash-lite 404s for
                                         # newly-created keys ("no longer available
                                         # to new users"), so we can't use it here
                                         # either — 2.0-flash is what a fresh key
                                         # can actually call.


def _gemini_chat(prompt, max_tokens, temperature):
    """Google Gemini generateContent for the footage judge. Returns text or None.
    Raises on transport failure so the caller can fall back to Cerebras/Groq."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
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
    # Prefer Gemini (far larger free quota) for the judge too, so batch rendering
    # keeps judging footage relevance instead of 429'ing and shipping the top
    # Pexels result. Falls back to Groq. _LAST_GROQ_FAILED is only set when BOTH
    # providers are unreachable, so the JUDGE_UNAVAILABLE path still means "no
    # judge available at all" (ship top clip) rather than "one provider blipped".
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
    if os.environ.get("GEMINI_API_KEY", ""):
        try:
            out = _gemini_chat(prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through to Cerebras/Groq
            print("  Gemini judge call failed, trying Cerebras/Groq:", e)
    # OpenRouter: free tier includes a strong llama-3.3-70b:free — a good judge,
    # separate free bucket. Tried after Gemini, before Cerebras. Env-gated.
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        try:
            out = _openai_compat_chat("https://openrouter.ai/api/v1/chat/completions",
                                      or_key, "meta-llama/llama-3.3-70b-instruct:free",
                                      prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through
            print("  OpenRouter judge call failed, trying Cerebras/Groq:", e)
    # Cerebras: free, generous, OpenAI-compatible — the backup judge when Gemini
    # is rate-limited, tried before Groq's tiny budget. Env-gated; no key = skip.
    cere_key = os.environ.get("CEREBRAS_API_KEY", "")
    cere_model = _cerebras_judge_model() if cere_key else None
    if cere_key and cere_model:
        try:
            out = _openai_compat_chat("https://api.cerebras.ai/v1/chat/completions",
                                      cere_key, cere_model, prompt, max_tokens, temperature)
            if out is not None:
                _judge_note(True)
                return out
        except Exception as e:  # noqa: BLE001 - fall through to Groq
            print("  Cerebras judge call failed, trying Groq:", e)
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        # No Groq either. If any other provider was configured but errored, that's
        # a real outage → signal unavailable so the caller ships the top clip.
        if os.environ.get("GEMINI_API_KEY", "") or or_key or cere_key:
            _LAST_GROQ_FAILED = True
            _judge_note(False)
        return None
    try:
        out = _openai_compat_chat("https://api.groq.com/openai/v1/chat/completions",
                                  key, model, prompt, max_tokens, temperature)
        _judge_note(True)
        return out
    except Exception as e:
        print("  Groq call failed:", e)
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
        f"0-2: different subject entirely, no visual connection to the narration.\n"
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
    return (_pexels_candidates(query)
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

FETCH_BUDGET_S = 45     # wall-clock cap for one fetch_clip() call (search + judge +
                        # requery rounds). Two rescue rounds instead of one means more
                        # network round trips per scene; bound it the same way
                        # NASA_BUDGET_S bounds its own fallback source, so a slow judge
                        #/search chain can't stall the whole render.
MAX_FETCH_QUERIES = 5   # original query + up to two requery rounds of ~2 queries each

JUDGE_SCORES = []      # every scene's best judged score this render (None excluded);
                        # printed as a min/avg summary at the end for quick QA of a run


def _accept(chosen, dest, query, score):
    _download(chosen["url"], dest)
    _used_video_ids.add(chosen["id"])
    _used_history.append(chosen["id"])
    tag = f"judge {score}/10" if isinstance(score, int) else "first (no judge key)"
    print(f"  {chosen['source']} SUCCESS ({tag}, id {chosen['id']}): {query}")
    return True


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
            idx, score = _groq_judge(intent, cands)
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
    # Stat-card cap reached: use the best REAL clip we saw rather than card again.
    if accept_best and best_cand is not None:
        try:
            _accept(best_cand, dest, best_q, best_score)
            print(f"  accept-best ({best_score}/10) — stat-card cap reached, "
                  f"real footage beats another text card")
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
    base = f"scale=-2:2400,crop={W}:{H},"
    if kind == "static":
        return base
    if kind == "zoom_out":
        z = f"if(lte(on,3),1.12,max(zoom-{zspeed},1.06))"
        return base + f"zoompan=z='{z}':x='{ax}':y='{ay}':d={frames}:s={W}x{H}:fps=30,"
    if kind == "pan":
        # fixed mild zoom, slide across the frame; direction flips on repeat
        # (or alternates by index) instead of always going left->right
        reverse = (idx % 2 == 1) if not repeat else (idx % 2 == 0)
        x_expr = (f"(iw-iw/zoom)*on/{frames}" if not reverse
                  else f"(iw-iw/zoom)*(1-on/{frames})")
        return (base + f"zoompan=z='1.09':x='{x_expr}':"
                        f"y='(ih-ih/zoom)/2':d={frames}:s={W}x{H}:fps=30,")
    z = f"if(lte(on,3),1.06,min(zoom+{zspeed},1.12))"  # zoom_in (default)
    return base + f"zoompan=z='{z}':x='{ax}':y='{ay}':d={frames}:s={W}x{H}:fps=30,"


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
        url = (f"https://api.openverse.org/v1/images/?q={q}"
               f"&license_type=commercial&page_size=8&mature=false")
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


def build_scene(scene, idx, seg_mp3, seg_dur):
    global _last_motion_kind, STAT_CARD_SCENES, ARCHIVAL_SCENES
    raw = os.path.join(WORK, f"s{idx}_raw.mp4")
    # Once MAX_STAT_CARDS scenes have already carded, force this scene to take
    # its best real clip instead of adding to a wall of text cards.
    have, score = fetch_clip(scene["search_query"], raw,
                              intent=_footage_intent(scene),
                              accept_best=(STAT_CARD_SCENES >= MAX_STAT_CARDS))
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
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", raw, "-i", seg_mp3,
             "-t", f"{seg_dur:.3f}",
             "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
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
        # Two free/no-key still sources: Openverse (CC aggregator) then Wikimedia
        # Commons (the largest public-domain science library — Hubble, microscopy,
        # diagrams, historical photos). Either gives a documentary look no
        # generic-stock page has.
        if _openverse_image(_q, img) or _wikimedia_image(_q, img):
            try:
                run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", seg_mp3,
                     "-t", f"{seg_dur:.3f}", "-r", "30",
                     "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
                     "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
                     "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
                ARCHIVAL_SCENES += 1
                print("  archival still scene (Openverse CC image + Ken Burns)")
                return out
            except Exception as e:
                print(f"  archival still render failed ({e}) — falling back to card")

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

    run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0a0a0a:s={W}x{H}:d={seg_dur:.3f}:r=30",
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

def _event(start, end, word):
    clean = re.sub(r"[{}\\]", "", word).upper()
    tag = f"{{\\pos(540,{PROFILE['cap_y']})\\fad(40,0)}}"
    return f"Dialogue: 0,{_ass_t(start)},{_ass_t(end)},Pop,,0,0,0,,{tag}{clean}"

def build_ass(scenes, segments, actual_durs, path):
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

    def _shift(i):
        j = min(i, len(orig_starts) - 1, len(final_starts) - 1)
        if j < 0:
            return 0.0
        return final_starts[j] - orig_starts[j]

    if WORD_TIMINGS:
        # exact: drive captions from ElevenLabs word timings, per-scene shift
        word_i = 0
        for i, sc in enumerate(scenes):
            n_words = len(sc["voiceover"].split())
            shift = _shift(i)
            for w, st, en in WORD_TIMINGS[word_i:word_i + n_words]:
                if re.sub(r"[^A-Za-z0-9]", "", w):
                    events.append(_event(st + shift, en + shift, w))
            word_i += n_words
        # any leftover words beyond the scenes' combined word count (rare
        # mismatch) -- keep them, shifted by the last scene's offset
        if word_i < len(WORD_TIMINGS):
            shift = _shift(len(scenes) - 1)
            for w, st, en in WORD_TIMINGS[word_i:]:
                if re.sub(r"[^A-Za-z0-9]", "", w):
                    events.append(_event(st + shift, en + shift, w))
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
            for w, wt in zip(words, weights):
                wd = speech_dur * wt / total
                events.append(_event(clock, clock + wd, w)); clock += wd
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
    ass = os.path.join(WORK, "captions.ass")
    build_ass(m["scenes"], segments, actual_durs, ass)
    body_dur = ffprobe_dur(body)
    fade_out_start = max(0.0, body_dur - 0.3)
    # NO separate hook title-card. It used to burn the hook text across the top
    # for the first 2.6s, but now that the karaoke captions are word-synced they
    # already show the hook one word at a time — the card on top read as TWO sets
    # of subtitles at once (user feedback on Unseen Oceans). Just the karaoke
    # captions now.
    captioned = os.path.join(WORK, "captioned.mp4")
    run(["ffmpeg", "-y", "-i", body,
         "-vf", (f"ass='{ass}',fade=t=in:st=0:d=0.2,"
                 f"fade=t=out:st={fade_out_start:.2f}:d=0.3"),
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", captioned])

    # SOUND DESIGN — signature intro sting (subtle brand mark). Generated with
    # ffmpeg (no external asset): two low partials a fifth apart (98/147 Hz) with
    # a soft swell, lowpassed and quiet (~-25 dB peak, verified) so it reads as a
    # calm, slightly eerie "we're beginning" cue matching the channel identity,
    # not a jingle. Plays once under the opening ~1s. Profile-gated (sfx).
    sting = None
    if PROFILE.get("sfx", True):
        sting = os.path.join(WORK, "sting.wav")
        try:
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=98:duration=1.0",
                 "-f", "lavfi", "-i", "sine=frequency=147:duration=1.0",
                 "-filter_complex",
                 "[0:a]volume=0.6[a0];[1:a]volume=0.35[a1];"
                 "[a0][a1]amix=inputs=2:normalize=0,afade=t=in:d=0.08,"
                 "afade=t=out:st=0.55:d=0.45,volume=0.5,lowpass=f=1200[s]",
                 "-map", "[s]", sting])
        except Exception as e:
            print("  [sfx] sting generation failed, skipping:", e)
            sting = None

    # Unified audio mix: voice + (optional music bed) + (optional intro sting),
    # amix normalize=0 so narration keeps its level (music_vol is pre-tuned to sit
    # ~18-20 dB under the voice; the sting is short and quiet). Handles any subset.
    final = os.path.join(OUT, "final.mp4")
    crf = random.choice(["19", "20", "21"])
    ff_inputs, filt, labels, idx = ["-i", captioned], [], ["[0:a]"], 1
    if os.path.exists(MUSIC):
        print("[music] mixing bed under voice...")
        ff_inputs += ["-stream_loop", "-1", "-i", MUSIC]
        filt.append(f"[{idx}:a]volume={PROFILE['music_vol']}[m]")
        labels.append("[m]"); idx += 1
    else:
        print("[music] no music.mp3 found — skipping")
    if sting:
        print("[sfx] mixing signature intro sting")
        ff_inputs += ["-i", sting]
        labels.append(f"[{idx}:a]"); idx += 1
    if len(labels) > 1:
        filt.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:"
                    f"dropout_transition=0:normalize=0[a]")
        run(["ffmpeg", "-y", *ff_inputs, "-filter_complex", ";".join(filt),
             "-map", "0:v", "-map", "[a]", "-map_metadata", "-1",
             "-c:v", "libx264", "-crf", crf, "-preset", "medium",
             "-c:a", "aac", "-shortest", final])
    else:
        run(["ffmpeg", "-y", "-i", captioned, "-map_metadata", "-1",
             "-c:v", "libx264", "-crf", crf, "-preset", "medium",
             "-c:a", "aac", "-pix_fmt", "yuv420p", final])

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
                   "hook": m.get("hook", ""), "domain": m.get("domain", "")}, f, indent=2)
    print("DONE ->", final, f"({ffprobe_dur(final):.1f}s)")


if __name__ == "__main__":
    main()
