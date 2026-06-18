#!/usr/bin/env python3
"""
Faceless short-form render engine v2.
Adds: slow-zoom motion, color grade, lower-third captions with natural phrasing,
hook overlay (first 2s), background music bed, no-repeat footage.
"""

import os, sys, json, subprocess, shutil, wave, struct, re, urllib.request, urllib.parse, urllib.error
import random

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(ROOT, "work")
OUT  = os.path.join(ROOT, "out")
MUSIC = os.path.join(ROOT, "music.mp3")  # set per-profile below
PEXELS_KEY  = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
import profiles
PROFILE, PAGE = profiles.get_profile()
ELEVEN_VOICE = PROFILE["eleven_voice"]
MUSIC = os.path.join(ROOT, PROFILE.get("music", "music.mp3"))

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_used_video_ids = set()   # dedup footage across scenes


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
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}/with-timestamps"
            headers = {"xi-api-key": el_key, "Content-Type": "application/json", "Accept": "application/json"}
            payload = json.dumps({
                "text": full_text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": PROFILE["voice_settings"]
            }).encode()
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
                print(f"  ElevenLabs SUCCESS ({len(WORD_TIMINGS)} word timings)")
            else:
                print("  ElevenLabs SUCCESS (no timings)")
            if os.path.getsize(out_mp3) > 1000:
                return True
        except urllib.error.HTTPError as e:
            print(f"  ElevenLabs HTTP {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            print(f"  ElevenLabs failed: {e}")
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
    tw = sum(len(s["voiceover"].split()) for s in scenes)
    out, cursor = [], 0.0
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


# ---------- FOOTAGE (dedup, more results) ----------
def _http_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _pexels_candidates(query):
    """Return list of dicts: {id, w, h, url, desc} for unused portrait clips."""
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
                out.append({"id": v.get("id"), "url": best["link"],
                            "desc": (v.get("url", "") or "").rstrip("/").split("/")[-1].replace("-", " ")})
    except urllib.error.HTTPError as e:
        print(f"  Pexels HTTP {e.code}: {e.read().decode()[:160]}")
    except Exception as e:
        print("  Pexels failed:", e)
    return out


def _groq_pick(intent, candidates):
    """Ask Groq to pick the index of the best-matching clip. Returns int or None."""
    key = os.environ.get("GROQ_API_KEY", "")
    if not key or len(candidates) < 2:
        return None
    listing = "\n".join(f"{i}: {c['desc']}" for i, c in enumerate(candidates))
    prompt = (f"A short video scene needs B-roll matching this idea: \"{intent}\".\n"
              f"Here are stock clips (index: description):\n{listing}\n"
              f"Reply with ONLY the index number of the clip that best matches the idea visually.")
    try:
        body = json.dumps({
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 5
        }).encode()
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",
                                     data=body,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json",
                                              "User-Agent": "content-render/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = json.loads(r.read().decode())["choices"][0]["message"]["content"]
        m = re.search(r"\d+", txt)
        if m:
            idx = int(m.group())
            if 0 <= idx < len(candidates):
                return idx
    except Exception as e:
        print("  Groq pick failed:", e)
    return None



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
                out.append({"id": vid, "url": url, "desc": (v.get("title") or query)})
    except Exception as e:
        print("  Coverr failed:", e)
    return out


def fetch_clip(query, dest, intent=None):
    cands = _pexels_candidates(query)
    if not cands:
        cands = _coverr_candidates(query)  # failover source (dormant unless COVERR_API_KEY set)
    if not cands:
        print(f"  No footage: {query} — color card")
        return False
    pick = _groq_pick(intent or query, cands)
    chosen = cands[pick] if pick is not None else cands[0]
    try:
        _download(chosen["url"], dest)
        _used_video_ids.add(chosen["id"])
        tag = "Groq-matched" if pick is not None else "first"
        print(f"  Pexels SUCCESS ({tag}, id {chosen['id']}): {query}")
        return True
    except Exception as e:
        print("  download failed:", e)
        return False


# ---------- PER-SCENE VIDEO (motion + color grade) ----------
def build_scene(scene, idx, seg_mp3, seg_dur):
    raw = os.path.join(WORK, f"s{idx}_raw.mp4")
    have = fetch_clip(scene["search_query"], raw, intent=scene.get("voiceover", scene["search_query"]))
    out = os.path.join(WORK, f"s{idx}.mp4")
    frames = max(1, int(seg_dur * 30))

    # slow zoom-in (Ken Burns) + cinematic color grade (contrast, slight teal shadows, mild saturation)
    zspeed = PROFILE["zoom_speed"]
    motion = (f"scale=-2:2400,crop={W}:{H},"
              f"zoompan=z='if(lte(on,3),1.06,min(zoom+{zspeed},1.12))':d={frames}:s={W}x{H}:fps=30,")
    grade = PROFILE["grade"]
    stat = _stat_overlay(scene, seg_dur)

    if have:
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", raw, "-i", seg_mp3,
             "-t", f"{seg_dur:.3f}",
             "-filter_complex", f"[0:v]{motion}{grade}{stat},setsar=1[v]",
             "-map", "[v]", "-map", "1:a", "-r", "30", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-c:a", "aac", "-shortest", out])
    else:
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

def build_ass(scenes, durations, path):
    events = []
    if WORD_TIMINGS:
        # exact: drive captions straight from ElevenLabs word timings
        for w, st, en in WORD_TIMINGS:
            if re.sub(r"[^A-Za-z0-9]", "", w):
                events.append(_event(st, en, w))
    else:
        # fallback: estimate by word length within each scene
        clock = 0.0
        for sc, dur in zip(scenes, durations):
            words = sc["voiceover"].split()
            if not words:
                clock += dur; continue
            weights = [max(2, len(re.sub(r"[^A-Za-z0-9]", "", w))) for w in words]
            total = sum(weights) or 1
            for w, wt in zip(words, weights):
                wd = dur * wt / total
                events.append(_event(clock, clock + wd, w)); clock += wd
    with open(path, "w") as f:
        f.write(_ass_header() + "\n".join(events) + "\n")


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

    print("[voice] full track...")
    full_script = m.get("script", " ".join(s["voiceover"] for s in m["scenes"]))
    full_mp3 = os.path.join(WORK, "full_vo.mp3")
    if not tts_full(full_script, full_mp3, voice, rate):
        silent_track(sum(float(s.get("duration", 3)) for s in m["scenes"]), full_mp3)

    segments = split_audio(full_mp3, m["scenes"], WORK)

    scene_files, durations = [], []
    for i, (sc, (seg_mp3, seg_dur)) in enumerate(zip(m["scenes"], segments), 1):
        print(f"[scene {i}/{len(m['scenes'])}] {sc['search_query']}")
        scene_files.append(build_scene(sc, i, seg_mp3, seg_dur)); durations.append(seg_dur)

    # concat
    listfile = os.path.join(WORK, "list.txt")
    with open(listfile, "w") as lf:
        for f in scene_files:
            lf.write(f"file '{os.path.abspath(f)}'\n")
    body = os.path.join(WORK, "body.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", body])

    # captions (lower third) + hook overlay (first 2s, top)
    ass = os.path.join(WORK, "captions.ass")
    build_ass(m["scenes"], durations, ass)
    body_dur = ffprobe_dur(body)
    fade_out_start = max(0.0, body_dur - 0.3)
    captioned = os.path.join(WORK, "captioned.mp4")
    run(["ffmpeg", "-y", "-i", body,
         "-vf", (f"ass='{ass}',fade=t=in:st=0:d=0.2,"
                 f"fade=t=out:st={fade_out_start:.2f}:d=0.3"),
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", captioned])

    # background music bed (optional)
    final = os.path.join(OUT, "final.mp4")
    if os.path.exists(MUSIC):
        print("[music] mixing bed under voice...")
        crf = random.choice(["19", "20", "21"])
        run(["ffmpeg", "-y", "-i", captioned, "-stream_loop", "-1", "-i", MUSIC,
             "-filter_complex",
             f"[1:a]volume={PROFILE['music_vol']}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
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
        json.dump({"title": m["title"], "captions": m["captions"], "hashtags": m["hashtags"]}, f, indent=2)
    print("DONE ->", final, f"({ffprobe_dur(final):.1f}s)")


if __name__ == "__main__":
    main()
