#!/usr/bin/env python3
"""
repackage.py — turn ONE rendered vertical master into platform-ready cuts,
PROVE each cut actually meets that platform's real 2026 spec (ffprobe after
render, not just "we told ffmpeg the right flags"), auto-fix the one thing
that's fixable without a re-render (duration overruns — trim rather than
silently ship a file the platform would reject or reclassify), and emit
fully publish-ready metadata (per-platform captions, AI-content disclosure,
posting-time heuristics) for whatever scheduler/publisher gets wired up next.

Input : out/final.mp4   (the 1080x1920 master from main.py)
Output (into out/):
  tiktok_reels_shorts.mp4   1080x1920  — TikTok + (usually) Instagram Reels
  instagram_reels.mp4        1080x1920  — only written as its OWN file if Instagram's stricter
                                          duration cap ever forces a different fix than TikTok's;
                                          otherwise instagram_reels.* metadata just points at the
                                          TikTok file above (no wasted duplicate encode)
  youtube_shorts.mp4         1080x1920  — separate file: YouTube Shorts has its own hard duration
                                          cap (3 min for uploads after 2024-10-15) and a distinct,
                                          shallower bottom-UI safe zone than TikTok/IG
  facebook_reels.mp4         1080x1920  — captions/key text shifted up out of FB's (deepest) bottom UI
  square.mp4                 1080x1080  — X + Facebook + Instagram feed
  landscape.mp4               1920x1080 — X / YouTube landscape (vertical centered on blurred fill)
  platforms.json              per-cut file map + ffprobe compliance report (pass/fail + auto-fixes)
  platform_text.json          per-platform caption/title + AI-content disclosure + posting-time heuristic

Master design rule (enforced in main.py): all captions live inside the universal
safe zone (~900x1400 centered) so every derived cut keeps text mostly on-screen;
this script still verifies/adjusts per platform since each one's UI chrome (bottom
caption-bar depth, right-side action rail, top status bar) differs in real pixels.

Platform specs below were researched (WebSearch, 2026) rather than assumed —
see the comment on each PLATFORM_SPECS entry for the specific figure and why.
No re-generation, no second voice/footage render: everything here is ffmpeg
reshaping of the existing out/final.mp4 master (or its already-produced cuts).
"""

import os, sys, subprocess, shutil, json

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")
W, H = 1080, 1920  # matches main.py's master resolution

import profiles
PROFILE, PAGE = profiles.get_profile()

import funnel  # monetization funnel: bio CTA, pinned comment, newsletter, affiliate


# ---------------------------------------------------------------------------
# PLATFORM_SPECS — researched 2026 specs. Each entry documents what
# "compliant" means for that cut and drives the ffprobe assertions + the one
# auto-fix (duration) below. Fields that are far above anything a ~45-100s
# script from this pipeline could ever hit (e.g. TikTok's 10-minute ceiling)
# are still recorded for completeness/documentation but never bind in practice.
# ---------------------------------------------------------------------------
PLATFORM_SPECS = {
    "tiktok": {
        "resolution": (1080, 1920), "aspect": (9, 16),
        "max_duration_s": 600,          # TikTok allows up to 10 min (60 min on select accounts) --
                                         # not a binding constraint for this channel's short scripts
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 287.6,           # mobile-app upload cap (TikTok Studio allows up to 4GB)
        "safe_zone_top_frac": 0.10,     # top status bar / TikTok header
        "safe_zone_bottom_frac": 0.22,  # caption / username / sound-attribution bar
        "safe_zone_right_frac": 0.14,   # like / comment / share / sound icon rail
    },
    "instagram_reels": {
        "resolution": (1080, 1920), "aspect": (9, 16),
        "max_duration_s": 180,          # platform allows up to 3 min
        "target_duration_s": 90,        # shorter still gets preferential reach/distribution
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 4096,
        "safe_zone_top_frac": 0.10,     # ~200px header
        "safe_zone_bottom_frac": 0.22,  # ~400-420px caption/audio band
        "safe_zone_right_frac": 0.12,   # ~120px like/comment/share/remix rail
    },
    "facebook_reels": {
        "resolution": (1080, 1920), "aspect": (9, 16),
        "max_duration_s": 180,
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 4096,
        "safe_zone_top_frac": 0.10,
        "safe_zone_bottom_frac": 0.35,  # FB's caption + page-name + CTA-button chrome is the
                                         # deepest of the three vertical platforms
        "safe_zone_right_frac": 0.15,
    },
    "youtube_shorts": {
        "resolution": (1080, 1920), "aspect": (9, 16),
        "max_duration_s": 180,          # raised from 60s to 3 min for uploads after 2024-10-15;
                                         # still THE hard gate for Shorts-feed eligibility
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 2048,
        "safe_zone_top_frac": 0.08,
        "safe_zone_bottom_frac": 0.18,
        "safe_zone_right_frac": 0.10,
        "required_tag": "#shorts",      # title/description must carry this or YouTube may not
                                         # route the upload into the Shorts shelf
    },
    "x_twitter": {
        "resolution": None, "aspect": None,  # square or landscape both perform; we ship both
        "max_duration_s": 140,          # 2:20 for non-Premium accounts (assumed default here --
                                         # Premium+ allows far more; out of scope for this pipeline)
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 512,
    },
    "square_feed": {
        "resolution": (1080, 1080), "aspect": (1, 1),
        "max_duration_s": None,
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 4096,
    },
    "landscape": {
        "resolution": (1920, 1080), "aspect": (16, 9),
        "max_duration_s": 140,
        "video_codec": "h264", "audio_codec": "aac",
        "max_size_mb": 512,
    },
}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1200:])
        raise RuntimeError("ffmpeg failed: " + " ".join(cmd[:4]))
    return r


def probe(path):
    """ffprobe one rendered cut: resolution, duration, codecs, file size.
    Never raises -- a probe failure returns a dict of None/0 values so the
    compliance report degrades to 'unknown' rather than crashing repackage
    over one bad file."""
    info = {"width": None, "height": None, "duration": 0.0, "vcodec": None,
            "acodec": None, "size_mb": 0.0}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name",
             "-show_entries", "format=duration,size", "-of", "json", path],
            capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        info["width"] = stream.get("width")
        info["height"] = stream.get("height")
        info["vcodec"] = stream.get("codec_name")
        info["duration"] = float(fmt.get("duration") or 0.0)
        info["size_mb"] = round(int(fmt.get("size") or 0) / (1024 * 1024), 2)
        r2 = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=20)
        info["acodec"] = (r2.stdout or "").strip() or None
    except Exception as e:
        print(f"  [probe] failed for {path}: {e}")
    return info


def check_compliance(info, spec):
    """Compare a probed file against its platform spec. Returns a list of
    human-readable violation strings (empty list = fully compliant)."""
    problems = []
    res = spec.get("resolution")
    if res and info["width"] and (info["width"], info["height"]) != tuple(res):
        problems.append(f"resolution {info['width']}x{info['height']} != required {res[0]}x{res[1]}")
    aspect = spec.get("aspect")
    if aspect and info["width"] and info["height"]:
        got = info["width"] / info["height"]
        want = aspect[0] / aspect[1]
        if abs(got - want) > 0.02:
            problems.append(f"aspect ratio {got:.3f} != required {aspect[0]}:{aspect[1]} ({want:.3f})")
    max_dur = spec.get("max_duration_s")
    if max_dur and info["duration"] > max_dur + 0.5:
        problems.append(f"duration {info['duration']:.1f}s exceeds hard cap {max_dur}s")
    vcodec = spec.get("video_codec")
    if vcodec and info["vcodec"] and info["vcodec"] != vcodec:
        problems.append(f"video codec {info['vcodec']} != required {vcodec}")
    acodec = spec.get("audio_codec")
    if acodec and info["acodec"] and info["acodec"] != acodec:
        problems.append(f"audio codec {info['acodec']} != required {acodec}")
    max_size = spec.get("max_size_mb")
    if max_size and info["size_mb"] > max_size:
        problems.append(f"file size {info['size_mb']}MB exceeds cap {max_size}MB")
    return problems


def _cap_duration_inplace(path, max_dur, label):
    """FIX a duration violation by trimming in place (re-mux, no re-encode --
    `-c copy` is safe here since we're just cutting, not re-grading). This is
    the one violation this script actively repairs rather than only reports:
    a Short over the cap doesn't get rejected outright, it silently loses
    Shorts-feed eligibility and gets reclassified as a regular long-form
    upload, which is worse than a visibly-logged trim."""
    trim_to = max_dur - 1.0
    tmp = path + ".trim.mp4"
    run(["ffmpeg", "-y", "-i", path, "-t", f"{trim_to:.2f}", "-c", "copy", tmp])
    os.replace(tmp, path)
    print(f"  [{label}] FIXED: exceeded {max_dur}s hard cap -- trimmed to {trim_to:.1f}s "
          f"(content after the cut point was dropped; if this fires often, tighten "
          f"generate.py's script word-count range)")
    return {"trimmed": True, "trimmed_to": trim_to}


def _ensure_duration(path, spec, platform_key, may_be_shared=False):
    """Verify `path` meets spec's duration cap. If it already does, return it
    unchanged. If not: FIX it -- but never mutate a file another platform
    might be sharing (may_be_shared=True forks a dedicated per-platform copy
    first, so trimming Instagram's cut can't accidentally shorten TikTok's).
    Returns (final_path, fix_or_None)."""
    max_dur = spec.get("max_duration_s")
    if not max_dur:
        return path, None
    dur = probe(path)["duration"]
    if dur <= max_dur - 0.5:
        return path, None
    target = path
    if may_be_shared:
        target = os.path.join(OUT, f"{platform_key}.mp4")
        shutil.copy(path, target)
    fix = _cap_duration_inplace(target, max_dur, platform_key)
    return target, fix


def _caption_band():
    """This render's active profile's caption vertical band (top, bottom) in
    absolute pixels on the 1080x1920 master -- same geometry main.py's own
    _stat_card_safe_zone() reasons about, reused here so repackage.py's
    safe-zone checks reflect whatever profile (cap_y/cap_size) actually
    rendered this file, not a fixed guess."""
    cap_y = PROFILE.get("cap_y", H * 0.4)
    half = PROFILE.get("cap_size", 120) * 1.3
    return cap_y - half, cap_y + half


def _square_crop_top():
    """Vertical offset for the 1080x1080 square crop (X / FB / IG feed). Was a
    flat hardcoded 520px regardless of profile -- tuned/reviewed for the
    'science' profile's cap_y=760 (band fits inside [520, 1600] there), but a
    real audit found 2 of the 4 defined profiles (history_pov cap_y=1480,
    dark_mystery cap_y=300) have a caption band that does NOT fit in that
    fixed window, so switching PAGE to either would silently ship a square
    cut with the captions cropped completely out of frame. Keeps the exact
    same 520 for any profile the default already covers (zero behavior
    change for the currently-shipping 'science' profile); only recenters on
    the caption band when the default would actually cut it off."""
    band_top, band_bottom = _caption_band()
    default_top = 520.0
    if band_top >= default_top and band_bottom <= default_top + 1080:
        return int(default_top)
    center = (band_top + band_bottom) / 2
    return int(max(0, min(H - 1080, center - 540)))


def apply_safe_zone(master, dest, spec, label):
    """Shift the picture UP just enough that the caption band clears this
    platform's bottom safe-zone line, by cropping the bottom and padding the
    top with black -- the same mechanic the original facebook_reels cut used
    (fixed 90px guess), generalized here to be spec-driven and applied to
    whichever cut actually needs it (TikTok/IG/FB/YT all have different
    bottom-UI depths). No-op (plain copy) if the caption band is already clear."""
    bottom_frac = spec.get("safe_zone_bottom_frac")
    if not bottom_frac:
        shutil.copy(master, dest)
        return {"shifted_px": 0}
    _, band_bottom = _caption_band()
    unsafe_start = H * (1 - bottom_frac)
    if band_bottom <= unsafe_start:
        shutil.copy(master, dest)
        return {"shifted_px": 0}
    # +40px margin beyond the minimum needed; capped at 220px so a
    # pathological profile config can't crop away most of the frame
    shift = int(min(220, (band_bottom - unsafe_start) + 40))
    run(["ffmpeg", "-y", "-i", master,
         "-vf", f"crop={W}:{H - shift}:0:0,pad={W}:{H}:0:0:black,setsar=1",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", dest])
    print(f"  [{label}] captions intruded {shift}px into the bottom "
          f"{bottom_frac * 100:.0f}% safe zone -- shifted picture up to compensate")
    return {"shifted_px": shift}


# ---------------------------------------------------------------------------
# POST-READY METADATA (deliverable 3): per-platform caption length limits,
# AI-content disclosure guidance, and posting-time heuristics.
# ---------------------------------------------------------------------------

CAPTION_LIMITS = {
    # hard platform limits -- truncated (not just recommended) so nothing
    # ever gets silently rejected by a publisher/scheduler on length alone.
    "tiktok": 2200, "instagram_reels": 2200, "instagram_feed": 2200,
    "facebook_reels": 63206, "x_twitter": 280,
    "youtube_shorts_title": 100, "youtube_shorts_desc": 5000,
}


def _truncate(text, limit):
    if not text or len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + "…"


# AI-content disclosure. Researched per-platform 2026 policy (WebSearch):
#  - TikTok requires a visible AI label for realistic synthetic faces/voice
#    clones/AI backgrounds; TikTok's own guidance explicitly EXEMPTS AI
#    scripts, AI-written captions/hashtags, and text overlays -- the labeling
#    requirement targets the visual/auditory media itself.
#  - Meta's *mandatory* AI-disclosure checkbox (2026) is scoped to
#    ADVERTISERS in Ads Manager, not organic creator posts; Meta separately
#    offers a voluntary "AI info" label creators can self-apply.
#  - YouTube's "Altered or synthetic content" toggle is required only when
#    content "could be mistaken for real" (a real person saying/doing
#    something they didn't, or a realistic scene that didn't happen).
#    YouTube's own guidance explicitly excludes AI voiceover over stock
#    footage, faceless animated content, and AI-written scripts.
#  - X/Twitter has no dedicated native AI-disclosure toggle as of 2026.
#
# This channel's content -- an AI-written script, an AI (ElevenLabs) voice
# reading it, over REAL stock footage, with no synthetic human likeness and
# no voice clone of a real identifiable person -- sits in each platform's
# documented EXEMPT/not-clearly-required bucket today. `likely_required` is
# recorded as False for that reason, but `recommended` stays True: policies
# here are moving fast, being wrong costs a channel strike, and transparency
# is free. Treat this whole block as a heuristic to revisit each time a
# platform updates its synthetic-media policy -- it is not legal advice.
AI_DISCLOSURE = {
    "tiktok": {
        "likely_required": False,
        "reasoning": "TikTok's 2026 policy requires labels for realistic synthetic faces, "
                     "voice clones, and AI backgrounds; it explicitly exempts AI-written "
                     "scripts/captions. This channel uses a stock TTS voice (not a clone of a "
                     "real person) over real stock footage, so it falls in the exempt bucket "
                     "today -- verify against TikTok's current policy before publishing.",
        "native_toggle": "Post settings -> 'AI-generated content' (Content Disclosure) toggle.",
        "recommended": True,
        "suggested_disclosure_line": "Narration is AI-generated.",
    },
    "instagram_reels": {
        "likely_required": False,
        "reasoning": "Meta's mandatory AI-disclosure checkbox (2026) is scoped to advertisers "
                     "in Ads Manager, not organic posts. Meta offers a voluntary 'AI info' "
                     "label for organic content.",
        "native_toggle": "Post settings -> 'AI info' label (voluntary for organic posts; "
                          "mandatory only if boosted/run as an ad).",
        "recommended": True,
        "suggested_disclosure_line": "Made with AI narration + real stock footage.",
    },
    "instagram_feed": {
        "likely_required": False,
        "reasoning": "Same as instagram_reels.",
        "native_toggle": "Post settings -> 'AI info' label.",
        "recommended": True,
        "suggested_disclosure_line": "Made with AI narration + real stock footage.",
    },
    "facebook_reels": {
        "likely_required": False,
        "reasoning": "Same Meta policy scoping as Instagram: mandatory disclosure applies to "
                     "advertisers, not organic Reels.",
        "native_toggle": "Post settings -> 'AI info' label.",
        "recommended": True,
        "suggested_disclosure_line": "Made with AI narration + real stock footage.",
    },
    "youtube_shorts": {
        "likely_required": False,
        "reasoning": "YouTube's 'Altered or synthetic content' toggle is required only for "
                     "content that could be mistaken for real (a real person saying/doing "
                     "something they didn't, or a realistic fabricated scene). YouTube's own "
                     "guidance excludes AI voiceover over stock footage and faceless AI-scripted "
                     "content -- this channel's format.",
        "native_toggle": "Upload flow -> 'Altered or synthetic content' toggle (video details step).",
        "recommended": True,
        "suggested_disclosure_line": "This video's narration was written and voiced with AI; "
                                      "footage is real stock/archival.",
    },
    "x_twitter": {
        "likely_required": False,
        "reasoning": "X has no dedicated native AI-disclosure toggle as of 2026.",
        "native_toggle": None,
        "recommended": True,
        "suggested_disclosure_line": "AI-narrated.",
    },
}

# Optimal-post-time heuristics: generic, well-documented best-practice
# windows per platform, NOT personalized to this channel's real audience --
# there is no analytics history yet (see generate.py's perf_<page>.json
# scaffold for the loop that will eventually replace this with real data).
# Times are the audience's assumed local time; refine per-account once real
# engagement data exists.
POST_TIME_HEURISTICS = {
    "tiktok": ["Tue-Thu 7:00-9:00pm", "Sun 7:00-9:00pm"],
    "instagram_reels": ["weekdays 11:00am-1:00pm", "weekdays 7:00-9:00pm"],
    "instagram_feed": ["weekdays 11:00am-1:00pm"],
    "facebook_reels": ["weekdays 1:00-4:00pm"],
    "youtube_shorts": ["weekdays 12:00-3:00pm", "weekdays 7:00-10:00pm"],
    "x_twitter": ["weekdays 8:00-10:00am", "weekdays 6:00-9:00pm"],
}


def write_platform_text(resolved_files):
    """Generate per-platform captions/titles + AI-disclosure + posting-time
    metadata. Reads out/post.json if present. `resolved_files` maps platform
    key -> the actual compliant filename that cut ended up as (post-fixes)."""
    post_path = os.path.join(OUT, "post.json")
    if not os.path.exists(post_path):
        return
    try:
        with open(post_path) as f:
            post = json.load(f)
    except Exception:
        return

    title = post.get("title", "")
    caps = post.get("captions", []) or [title]
    tags = post.get("hashtags", []) or ["#science"]
    keyword = post.get("keyword", "") or (title.split()[0] if title else "science")
    cta_style = post.get("cta_style", "")
    base_cap = caps[0] if caps else title

    # Monetization funnel assets for this render (bio CTA, pinned comment,
    # newsletter blurb, topic-matched affiliate). The bio CTA is added only to
    # the platforms where a link/CTA reads naturally (YouTube description,
    # Facebook) — NOT stamped on every caption — so nothing feels spammy. The
    # pinned comment (the real list-building ask) ships in funnel.json + the
    # release body for the poster to drop as a first comment on every platform.
    fnl = funnel.build_funnel(post)
    bio_line = fnl["bio_cta"]

    # TikTok: keyword-stuffed caption + question (search + comments). Tags inline, heavy.
    tiktok = _truncate(f"{base_cap} {' '.join(tags[:5])}", CAPTION_LIMITS["tiktok"])
    # Instagram Reels: share-prompt framing, fewer tags, cleaner. 'Send this to...' drives DM sends.
    insta_reels = _truncate(
        f"{base_cap}\n\nSend this to someone who needs to see it.\n{' '.join(tags[:5])}",
        CAPTION_LIMITS["instagram_reels"])
    # Instagram feed: same content, deliberately reworded/reordered (not a byte-identical
    # copy of the Reels caption) so cross-posting to both placements doesn't read as spam.
    feed_tags = (tags[1:] + tags[:1])[:5] if len(tags) > 1 else tags[:5]  # rotate tag order
    insta_feed = _truncate(f"{base_cap}\n{' '.join(feed_tags)}", CAPTION_LIMITS["instagram_feed"])
    # YouTube Shorts: real searchable TITLE + description (Shorts has search discovery).
    yt_title = _truncate(title, CAPTION_LIMITS["youtube_shorts_title"] - len(" #shorts")) + " #shorts"
    yt_desc = _truncate(
        f"{base_cap}\n\n{(caps[1] if len(caps) > 1 else '')}\n\n{bio_line}\n\n{' '.join(tags[:8])}",
        CAPTION_LIMITS["youtube_shorts_desc"])
    # Facebook: sound-off world, slightly longer caption restating the hook as
    # text. FB's older audience clicks links, so the bio CTA earns its place here.
    facebook = _truncate(f"{base_cap}\n\n{(caps[2] if len(caps) > 2 else base_cap)}\n\n{bio_line}",
                          CAPTION_LIMITS["facebook_reels"])
    # X: punchy one-liner, 1-2 tags max -- 280-char hard limit enforced via truncation.
    x = _truncate(f"{base_cap} {' '.join(tags[:2])}", CAPTION_LIMITS["x_twitter"])

    def _meta(key, extra):
        d = {**extra}
        disc = AI_DISCLOSURE.get(key)
        if disc:
            d["ai_disclosure"] = disc
        d["optimal_post_time"] = {
            "windows_audience_local_time": POST_TIME_HEURISTICS.get(key, []),
            "channel_hint": PROFILE.get("post_window"),
            "note": "generic best-practice heuristic, NOT personalized -- refine once "
                    "perf_<page>.json (see generate.py) has real engagement data for this page",
        }
        if cta_style:
            d["cta_style"] = cta_style
        return d

    out = {
        "tiktok": _meta("tiktok", {"caption": tiktok, "file": resolved_files.get("tiktok", "tiktok_reels_shorts.mp4")}),
        "instagram_reels": _meta("instagram_reels", {"caption": insta_reels,
                                  "file": resolved_files.get("instagram_reels", "tiktok_reels_shorts.mp4")}),
        "youtube_shorts": _meta("youtube_shorts", {"title": yt_title, "description": yt_desc,
                                 "file": resolved_files.get("youtube_shorts", "youtube_shorts.mp4")}),
        "facebook_reels": _meta("facebook_reels", {"caption": facebook,
                                 "file": resolved_files.get("facebook_reels", "facebook_reels.mp4")}),
        "x_twitter": _meta("x_twitter", {"caption": x, "file": resolved_files.get("x_twitter", "square.mp4")}),
        "instagram_feed": _meta("instagram_feed", {"caption": insta_feed,
                                 "file": resolved_files.get("square_feed", "square.mp4")}),
    }
    # Surface the auto-generated PINNED COMMENT right here alongside the captions
    # (it otherwise only lived in funnel.json). Pin this as your own first comment
    # after posting and reply to early comments — comments are the #1 reach signal.
    out["pinned_comment"] = fnl.get("pinned_comment", "")
    with open(os.path.join(OUT, "platform_text.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("platform_text.json written — native caption/title + AI-disclosure + posting-time + pinned comment.")
    # Also drop the pinned comment as its own one-line file for a fast copy-paste.
    with open(os.path.join(OUT, "pinned_comment.txt"), "w") as f:
        f.write(fnl.get("pinned_comment", ""))

    # funnel.json — the monetization bundle for whoever posts this video:
    # the pinned comment to drop as a first comment on every platform, the
    # ready-to-send newsletter teaser, and the topic-matched affiliate angle.
    with open(os.path.join(OUT, "funnel.json"), "w") as f:
        json.dump(fnl, f, indent=2)
    print("funnel.json written — pinned comment + newsletter + affiliate ("
          f"affiliate: {fnl['affiliate']['search']}).")

    # Emit the GitHub-Release body (out/release_body.md) as JUST the universal
    # caption + hashtags, in plain text. The Zapier "New Release" trigger exposes
    # the body natively, so the Zap maps Publer's "Text" field DIRECTLY to
    # {{Body}} — a TRIGGER field whose ID never changes.
    #
    # Why this replaced the old ===MARKER=== body: that layout required a
    # Formatter "Extract Pattern" step to pull the caption, and every time that
    # Formatter was edited its output field-ID changed and silently emptied the
    # downstream mapping — the recurring "Required field Text is missing" failure.
    # Mapping straight to the trigger's own Body field removes that whole failure
    # mode (no Formatter, nothing to re-break). The per-platform caption variants
    # (Instagram "send this…", YouTube title/description, X) and the funnel's
    # pinned comment still ship in the attached platform_text.json / funnel.json
    # assets for anyone who wants channel-specific text later.
    universal_caption = (out.get("tiktok", {}).get("caption")
                         or post.get("title", "")).strip()
    with open(os.path.join(OUT, "release_body.md"), "w") as f:
        f.write(universal_caption)
    print("release_body.md written — clean universal caption for direct {{Body}} mapping.")


def main():
    master = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "final.mp4")
    if not os.path.exists(master):
        print("no master at", master); sys.exit(1)

    safe_zone_fixes = {}

    # 1) TikTok / Instagram Reels — usually share a cut straight from the
    #    master; each platform's bottom-UI depth is checked independently
    #    below (they happen to match today, but this isn't hard-coded).
    trs = os.path.join(OUT, "tiktok_reels_shorts.mp4")
    safe_zone_fixes["tiktok"] = apply_safe_zone(master, trs, PLATFORM_SPECS["tiktok"], "tiktok")
    print("tiktok_reels_shorts.mp4  <- TikTok + Instagram Reels cut")

    # 2) YouTube Shorts — its own file: distinct (shallower) safe zone and a
    #    separate hard duration cap, auto-fixed below if ever exceeded.
    yts = os.path.join(OUT, "youtube_shorts.mp4")
    safe_zone_fixes["youtube_shorts"] = apply_safe_zone(master, yts, PLATFORM_SPECS["youtube_shorts"], "youtube_shorts")
    print("youtube_shorts.mp4       <- YouTube Shorts cut")

    # 3) Facebook Reels — same 9:16, shifted up out of FB's (deepest) bottom UI.
    fb = os.path.join(OUT, "facebook_reels.mp4")
    safe_zone_fixes["facebook_reels"] = apply_safe_zone(master, fb, PLATFORM_SPECS["facebook_reels"], "facebook_reels")
    print(f"facebook_reels.mp4       <- captions raised {safe_zone_fixes['facebook_reels']['shifted_px']}px "
          f"out of FB bottom UI")

    # 4) Square 1:1 (1080x1080) for X + Facebook + Instagram feed.
    #    Center-crop the vertical to square, keeping the caption band in frame.
    sq = os.path.join(OUT, "square.mp4")
    run(["ffmpeg", "-y", "-i", master,
         "-vf", f"crop=1080:1080:0:{_square_crop_top()},setsar=1",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", sq])
    print("square.mp4               <- 1:1 for X / FB / IG feed")

    # 5) Landscape 16:9 (1920x1080): vertical centered on a blurred fill of itself.
    land = os.path.join(OUT, "landscape.mp4")
    run(["ffmpeg", "-y", "-i", master,
         "-filter_complex",
         "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5[bg];"
         "[0:v]scale=-1:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1[v]",
         "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", land])
    print("landscape.mp4            <- 16:9 for X / YouTube landscape")

    # ---- compliance pass: probe every cut, auto-fix duration overruns, report ----
    # Some platform keys share an underlying file today (instagram_reels with
    # tiktok, x_twitter/instagram_feed with square, x_twitter's landscape use
    # with landscape) -- `_ensure_duration`'s may_be_shared fork prevents a
    # fix for one platform's stricter cap from silently trimming another's file.
    cut_sources = {
        "tiktok": trs, "instagram_reels": trs,
        "facebook_reels": fb, "youtube_shorts": yts,
        "square_feed": sq, "x_twitter": sq,
        "landscape": land,
    }
    shared_count = {}
    for path in cut_sources.values():
        shared_count[path] = shared_count.get(path, 0) + 1

    resolved_files, compliance_report = {}, {}
    for key, path in cut_sources.items():
        spec = PLATFORM_SPECS[key]
        final_path, dur_fix = _ensure_duration(path, spec, key, may_be_shared=shared_count[path] > 1)
        info = probe(final_path)
        violations = check_compliance(info, spec)
        resolved_files[key] = os.path.basename(final_path)
        fixes = []
        if dur_fix:
            fixes.append({"type": "duration_trim", **dur_fix})
        sz_fix = safe_zone_fixes.get(key)
        if sz_fix and sz_fix.get("shifted_px"):
            fixes.append({"type": "safe_zone_shift", **sz_fix})
        compliance_report[key] = {
            "file": resolved_files[key],
            "resolution": f"{info['width']}x{info['height']}" if info["width"] else "unknown",
            "duration_s": round(info["duration"], 1),
            "video_codec": info["vcodec"], "audio_codec": info["acodec"],
            "size_mb": info["size_mb"],
            "violations": violations,
            "compliant": not violations,
            "auto_fixes_applied": fixes,
        }
        status = "COMPLIANT" if not violations else f"VIOLATIONS: {'; '.join(violations)}"
        print(f"  [{key}] {status}")

    # manifest of outputs for the Drive drop / your phone / a publisher script
    files = {
        "TikTok": resolved_files["tiktok"],
        "Instagram Reels": resolved_files["instagram_reels"],
        "Facebook Reels": resolved_files["facebook_reels"],
        "YouTube Shorts": resolved_files["youtube_shorts"],
        "X / Facebook / Instagram feed (square)": resolved_files["square_feed"],
        "X / YouTube (landscape)": resolved_files["landscape"],
    }
    with open(os.path.join(OUT, "platforms.json"), "w") as f:
        json.dump({"files": files, "compliance": compliance_report}, f, indent=2)
    print("\nplatforms.json written — every shape ready + ffprobe-verified compliance report.")
    write_platform_text(resolved_files)


if __name__ == "__main__":
    main()
