#!/usr/bin/env python3
"""
repackage.py — turn ONE rendered vertical master into platform-ready cuts.
No re-generation, no second render. Pure FFmpeg reshaping of an existing file.

Input : out/final.mp4   (the 1080x1920 master from main.py)
Output (into out/):
  tiktok_reels_shorts.mp4   1080x1920  — TikTok + Instagram Reels + YouTube Shorts (identical master)
  facebook_reels.mp4        1080x1920  — captions sit higher (FB's deeper bottom UI zone)
  square.mp4                1080x1080  — X + Facebook + Instagram feed (square wins these feeds)
  landscape.mp4             1920x1080  — X / YouTube landscape (vertical centered on blurred fill)

Master design rule (enforced in main.py): all captions live inside the universal
safe zone (~900x1400 centered) so every derived cut keeps text on-screen.
"""

import os, sys, subprocess, shutil, json

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(ROOT, "out")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1200:])
        raise RuntimeError("ffmpeg failed: " + " ".join(cmd[:4]))
    return r




def write_platform_text():
    """Generate distinct per-platform text so each post reads as native (avoids originality penalties)
    and exploits each platform's discovery model. Reads out/post.json if present."""
    import json as _json
    post_path = os.path.join(OUT, "post.json")
    if not os.path.exists(post_path):
        return
    try:
        with open(post_path) as f:
            post = _json.load(f)
    except Exception:
        return

    title = post.get("title", "")
    caps = post.get("captions", []) or [title]
    tags = post.get("hashtags", []) or ["#science"]
    keyword = post.get("keyword", "") or (title.split()[0] if title else "science")
    base_cap = caps[0] if caps else title

    # TikTok: keyword-stuffed caption + question (search + comments). Tags inline.
    tiktok = f"{base_cap} {' '.join(tags[:5])}"
    # Instagram Reels: share-prompt framing, fewer tags, cleaner. 'Send this to...' drives DM sends.
    insta = f"{base_cap}\n\nSend this to someone who needs to see it.\n{' '.join(tags[:5])}"
    # YouTube Shorts: real searchable TITLE + description (Shorts has search discovery).
    yt_title = (title if len(title) <= 90 else title[:87] + "...") + " #shorts"
    yt_desc = f"{base_cap}\n\n{(caps[1] if len(caps)>1 else '')}\n\n{' '.join(tags[:8])}"
    # Facebook: sound-off world, slightly longer caption restating the hook as text.
    facebook = f"{base_cap}\n\n{(caps[2] if len(caps)>2 else base_cap)}"
    # X: punchy one-liner, 1-2 tags max.
    x = f"{base_cap} {' '.join(tags[:2])}"

    out = {
        "tiktok": {"caption": tiktok, "file": "tiktok_reels_shorts.mp4"},
        "instagram_reels": {"caption": insta, "file": "tiktok_reels_shorts.mp4"},
        "youtube_shorts": {"title": yt_title, "description": yt_desc, "file": "tiktok_reels_shorts.mp4"},
        "facebook_reels": {"caption": facebook, "file": "facebook_reels.mp4"},
        "x_twitter": {"caption": x, "file": "square.mp4"},
        "instagram_feed": {"caption": insta, "file": "square.mp4"},
    }
    with open(os.path.join(OUT, "platform_text.json"), "w") as f:
        _json.dump(out, f, indent=2)
    print("platform_text.json written — native caption/title per platform.")


def main():
    master = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "final.mp4")
    if not os.path.exists(master):
        print("no master at", master); sys.exit(1)

    # 1) TikTok / Reels / Shorts — the master is already correct; copy under a clear name
    trs = os.path.join(OUT, "tiktok_reels_shorts.mp4")
    shutil.copy(master, trs)
    print("tiktok_reels_shorts.mp4  <- master (no change)")

    # 2) Facebook Reels — same 9:16, but shift the picture DOWN slightly so captions clear
    #    FB's bottom UI eats ~35% vs TikTok ~20%. We pad top / crop bottom by 90px so the
    #    centered captions ride higher in the frame.
    fb = os.path.join(OUT, "facebook_reels.mp4")
    run(["ffmpeg", "-y", "-i", master,
         "-vf", "crop=1080:1830:0:0,pad=1080:1920:0:0:black,setsar=1",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", fb])
    print("facebook_reels.mp4       <- captions raised out of FB bottom UI")

    # 3) Square 1:1 (1080x1080) for X + Facebook + Instagram feed.
    #    Center-crop the vertical to square. Caption sits at ~760/1920 in the master,
    #    which after the centered 420px-tall... we instead scale-pad to keep captions visible:
    #    take full width, center vertically on the caption band.
    sq = os.path.join(OUT, "square.mp4")
    # crop a 1080x1080 window centered on y=540..1620 keeps mid-frame footage + the caption band (~760)
    run(["ffmpeg", "-y", "-i", master,
         "-vf", "crop=1080:1080:0:520,setsar=1",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", sq])
    print("square.mp4               <- 1:1 for X / FB / IG feed")

    # 4) Landscape 16:9 (1920x1080): vertical centered on a blurred fill of itself.
    land = os.path.join(OUT, "landscape.mp4")
    run(["ffmpeg", "-y", "-i", master,
         "-filter_complex",
         "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=20:5[bg];"
         "[0:v]scale=-1:1080[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1[v]",
         "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-c:a", "copy", "-pix_fmt", "yuv420p", land])
    print("landscape.mp4            <- 16:9 for X / YouTube landscape")

    # manifest of outputs for the Drive drop / your phone
    files = {
        "TikTok / Instagram Reels / YouTube Shorts": "tiktok_reels_shorts.mp4",
        "Facebook Reels": "facebook_reels.mp4",
        "X / Facebook / Instagram feed (square)": "square.mp4",
        "X / YouTube (landscape)": "landscape.mp4",
    }
    with open(os.path.join(OUT, "platforms.json"), "w") as f:
        json.dump(files, f, indent=2)
    print("\nplatforms.json written — every shape ready.")
    write_platform_text()


if __name__ == "__main__":
    main()
