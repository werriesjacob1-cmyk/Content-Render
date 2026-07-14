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
    try:
        run(["edge-tts", f"--voice={voice}", f"--rate={rate}",
             f"--text={full_text}", f"--write-media={out_mp3}"])
        if os.path.getsize(out_mp3) > 1000:
            return True
    except Exception as e:
        print("  edge-tts failed:", e)
    return False


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


# ---------- SCENE PLAN ----------
# Each scene is exactly as long as its OWN spoken audio segment (split_audio's
# cut on that scene's last word). No padding, no injected inter-scene silence,
# no minimum on-screen hold: natural pacing comes from the script's sentence
# length, not artificial gaps. An earlier "breathing-room pauses + minimum
# shot hold" pass bloated a ~30-40s script to ~55s ("talking too slow") and,
# because it shifted every word off the timeline WORD_TIMINGS is anchored to,
# desynced the captions from the narration. Removed.
CROSSFADE_S = 0.3    # xfade duration between scene clips (visual soft cut only)


def compute_scene_plan(segments):
    """segments: split_audio's output [(speech_mp3_path, speech_dur), ...],
    cut back-to-back on the full_vo.mp3 timeline WORD_TIMINGS is anchored to.
    Returns one dict per scene; shot_dur == speech_dur (no padding at all), so
    the on-screen duration equals exactly the spoken audio for that scene."""
    plan, cursor = [], 0.0
    for path, speech_dur in segments:
        plan.append({"speech_path": path, "speech_dur": speech_dur,
                     "orig_start": cursor, "lead": 0.0, "trail": 0.0,
                     "shot_dur": speech_dur})
        cursor += speech_dur
    return plan


def compute_new_starts(shot_durs, fade):
    """Start time of each scene's own clip (its local t=0) on the FINAL
    concatenated timeline, given the crossfade duration actually used to
    build that timeline (0.0 if the plain hard-cut concat demuxer was used
    instead of the xfade chain -- see build_body_xfade's fallback)."""
    starts, prefix = [], 0.0
    for i, d in enumerate(shot_durs):
        starts.append(prefix - i * fade)
        prefix += d
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


def _groq_chat(prompt, max_tokens=20, temperature=0, model="llama-3.1-8b-instant"):
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature, "max_tokens": max_tokens
        }).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                     data=body,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json",
                                              "User-Agent": "content-render/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())["choices"][0]["message"]["content"]
    except Exception as e:
        print("  Groq call failed:", e)
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
NO_KEY = "no_key"
UNRESOLVED = "unresolved"


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
        f"A stock-video search for \"{failed_query}\" found nothing that fits this narration: "
        f"\"{intent}\".\n"
        f"Suggest 2 alternative search queries (2-4 words each) describing CONCRETE things "
        f"videographers actually film: real objects, people doing actions, nature, weather, "
        f"machines, food, cities. No anatomical, microscopic, or abstract terms.\n"
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
            or _coverr_candidates(query))  # Coverr dormant unless COVERR_API_KEY set


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
            if score == NO_KEY or (numeric and score >= RELEVANCE_FLOOR):
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


def build_scene(scene, idx, seg_mp3, seg_dur):
    global _last_motion_kind, STAT_CARD_SCENES
    raw = os.path.join(WORK, f"s{idx}_raw.mp4")
    # Once MAX_STAT_CARDS scenes have already carded, force this scene to take
    # its best real clip instead of adding to a wall of text cards.
    have, score = fetch_clip(scene["search_query"], raw,
                              intent=scene.get("voiceover", scene["search_query"]),
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
    OFF unless PROFILE.get('motion_graphics') is True. Fully optional + safe."""
    if not PROFILE.get("motion_graphics"):
        return ""
    import re as _re
    text = f"{scene.get('on_screen_text','')} {scene.get('voiceover','')}"
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

def build_ass(scenes, plan, new_starts, path):
    """plan/new_starts (from compute_scene_plan/compute_new_starts) describe
    how each scene's speech got shifted by the breathing-gap/min-hold padding
    and, later, the crossfade concat's duration-collapsing -- both must be
    accounted for here or captions drift out of sync with the words as soon
    as any padding/crossfade is added between scenes."""
    events = []
    # per-scene start-of-speech on the FINAL rendered timeline, and how far
    # that is from where the scene's speech started on the ORIGINAL
    # back-to-back full_vo.mp3 timeline WORD_TIMINGS is anchored to
    shifts = [new_starts[i] + plan[i]["lead"] - plan[i]["orig_start"] for i in range(len(plan))]
    if WORD_TIMINGS:
        # exact: drive captions from ElevenLabs word timings, shifted per-scene
        word_i = 0
        for i, sc in enumerate(scenes):
            n_words = len(sc["voiceover"].split())
            shift = shifts[i] if i < len(shifts) else (shifts[-1] if shifts else 0.0)
            for w, st, en in WORD_TIMINGS[word_i:word_i + n_words]:
                if re.sub(r"[^A-Za-z0-9]", "", w):
                    events.append(_event(st + shift, en + shift, w))
            word_i += n_words
        # any leftover words beyond the scenes' combined word count (rare
        # mismatch) -- keep them, shifted by the last scene's offset
        if word_i < len(WORD_TIMINGS) and shifts:
            for w, st, en in WORD_TIMINGS[word_i:]:
                if re.sub(r"[^A-Za-z0-9]", "", w):
                    events.append(_event(st + shifts[-1], en + shifts[-1], w))
    else:
        # fallback: estimate by word length within each scene's SPEECH span
        # only (not the padded shot_dur, which includes silence) so words
        # don't get spread out over the breathing gap / hold padding
        for i, sc in enumerate(scenes):
            words = sc["voiceover"].split()
            if not words:
                continue
            speech_dur = plan[i]["speech_dur"]
            clock = new_starts[i] + plan[i]["lead"]
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
    voice = m.get("render", {}).get("voice", "en-US-GuyNeural")
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
    full_script = " ".join(s["voiceover"] for s in m["scenes"])
    full_mp3 = os.path.join(WORK, "full_vo.mp3")
    if not tts_full(full_script, full_mp3, voice, rate):
        silent_track(sum(float(s.get("duration", 3)) for s in m["scenes"]), full_mp3)

    segments = split_audio(full_mp3, m["scenes"], WORK)
    plan = compute_scene_plan(segments)

    scene_files, durations = [], []
    for i, (sc, item) in enumerate(zip(m["scenes"], plan), 1):
        print(f"[scene {i}/{len(m['scenes'])}] {sc['search_query']} "
              f"(speech {item['speech_dur']:.2f}s)")
        scene_files.append(build_scene(sc, i, item["speech_path"], item["shot_dur"]))
        durations.append(item["shot_dur"])

    if JUDGE_SCORES:
        print(f"[quality] judge scores: min {min(JUDGE_SCORES)}/10, "
              f"avg {sum(JUDGE_SCORES) / len(JUDGE_SCORES):.1f}/10 "
              f"across {len(JUDGE_SCORES)} scene(s) scored; "
              f"{STAT_CARD_SCENES} stat-card scene(s)")
    else:
        print(f"[quality] no judge scores recorded this render (no GROQ key / no "
              f"candidates found); {STAT_CARD_SCENES} stat-card scene(s)")

    save_used_footage()  # persist before the render steps below, in case one of them fails

    # concat: clean HARD CUTS on exact word-timing boundaries. Each scene's
    # audio is its full, uncut spoken segment; concatenating them back-to-back
    # reproduces the original full_vo timeline exactly, so no word is ever
    # crossfaded/clipped at a scene change (the old acrossfade overlapped and
    # cut off the end of each sentence). fade_used=0: captions map 1:1 to the
    # original WORD_TIMINGS with no offset.
    body = os.path.join(WORK, "body.mp4")
    fade_used = 0.0
    build_body_concat(scene_files, body)
    print(f"[concat] hard-cut concat OK ({len(scene_files)} scenes, no audio crossfade)")
    new_starts = compute_new_starts(durations, fade_used)

    # captions (karaoke) + hook title card (first 2.6s, top) — the docstring
    # always promised a hook overlay but none was ever rendered; the written
    # hook only existed in the audio. Burning it in gives scrollers a reason
    # to stop before the voiceover even registers.
    ass = os.path.join(WORK, "captions.ass")
    build_ass(m["scenes"], plan, new_starts, ass)
    body_dur = ffprobe_dur(body)
    fade_out_start = max(0.0, body_dur - 0.3)
    hook_filter = ""
    hook_text = re.sub(r"[^A-Za-z0-9 ,.?!'\-]", "", m.get("hook", "")).strip()
    if hook_text:
        # wrap to ~3-4 words per line; textfile= avoids drawtext escaping entirely
        words = hook_text.upper().split()
        lines, line = [], []
        for w in words:
            line.append(w)
            if len(" ".join(line)) >= 16:
                lines.append(" ".join(line)); line = []
        if line:
            lines.append(" ".join(line))
        hook_path = os.path.join(WORK, "hook.txt")
        with open(hook_path, "w") as hf:
            hf.write("\n".join(lines[:4]))
        hook_filter = (f",drawtext=textfile='{hook_path}':fontfile='{FONT}':fontsize=72:"
                       f"fontcolor=white:borderw=6:bordercolor=black:box=1:boxcolor=black@0.45:"
                       f"boxborderw=18:line_spacing=14:x=(w-tw)/2:y=h*0.12:"
                       f"enable='between(t,0,2.6)':alpha='if(lt(t,0.15),t/0.15,if(gt(t,2.3),(2.6-t)/0.3,1))'")
    captioned = os.path.join(WORK, "captioned.mp4")
    run(["ffmpeg", "-y", "-i", body,
         "-vf", (f"ass='{ass}',fade=t=in:st=0:d=0.2,"
                 f"fade=t=out:st={fade_out_start:.2f}:d=0.3" + hook_filter),
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", captioned])

    # background music bed (optional)
    final = os.path.join(OUT, "final.mp4")
    if os.path.exists(MUSIC):
        print("[music] mixing bed under voice...")
        crf = random.choice(["19", "20", "21"])
        # normalize=0: amix's default (normalize=1) auto-attenuates ALL inputs by
        # ~1/N to guard against clipping, which here means narration itself gets
        # quietly cut by ~6dB (2 inputs) the moment music is present -- verified
        # locally: mean_volume dropped from -21.1dB (narration alone) to -27.0dB
        # with normalize left on, vs -21.0dB (matching narration alone) with it
        # off. music_vol is already tuned per-profile to sit ~18-20dB under the
        # voice, so amix doesn't need to do any additional balancing on top.
        run(["ffmpeg", "-y", "-i", captioned, "-stream_loop", "-1", "-i", MUSIC,
             "-filter_complex",
             f"[1:a]volume={PROFILE['music_vol']}[m];"
             f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-map_metadata", "-1",
             "-c:v", "libx264", "-crf", crf, "-preset", "medium",
             "-c:a", "aac", "-shortest", final])
    else:
        print("[music] no music.mp3 found — skipping")
        crf = random.choice(["19", "20", "21"])
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
                   "cta_style": m.get("cta_style", "")}, f, indent=2)
    print("DONE ->", final, f"({ffprobe_dur(final):.1f}s)")


if __name__ == "__main__":
    main()
