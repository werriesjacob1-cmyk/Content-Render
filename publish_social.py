#!/usr/bin/env python3
"""Send an approved render to YouTube Shorts and TikTok -- free official APIs only.

WHY THIS EXISTS. Third-party schedulers (Publer, Zapier) charge for the approvals
the official platform APIs already give away. This talks to those APIs directly.

WHAT IT WILL AND WILL NOT DO

* YouTube: resumable `videos.insert` upload. Privacy defaults to PRIVATE and only
  an explicit, recognised YOUTUBE_PRIVACY value changes that. Google documents
  conflicting behaviour for unverified API projects (one page says uploads are
  not forced private, a help article says they can be locked private with no
  appeal), so the first real upload settles it; private-first means a lock costs
  nothing.
* TikTok: the INBOX/DRAFT flow only. The video lands in the creator's TikTok app
  inbox and a human taps Post. TikTok's Content Sharing Guidelines restrict
  unaudited apps to private viewing for Direct Post and list "a utility tool to
  help upload contents to the account(s) you or your team manages" as not
  acceptable, so this module deliberately never calls Direct Post. Whether the
  inbox flow works for an unaudited app is not stated in TikTok's docs; the
  first real attempt will tell us.

SAFETY CONTRACT

* HARD KILL SWITCH: inert unless AUTO_PUBLISH_ENABLED is exactly the lowercase
  string "true" -- the identical contract publish_publer.py and render.yml use,
  asserted equal in tests so the layers cannot disagree.
* DRY RUN IS THE DEFAULT. Real network calls need --live. A dry run makes ZERO
  network calls, including token refresh.
* A platform you ASK for with missing credentials is a FAILURE, not a quiet skip.
  A silent skip is how a "published" run publishes nothing.
* Failures are isolated per platform and reported; one platform failing never
  stops the other. Exit status is non-zero if any requested platform failed.
* Secrets are never printed. Error text from the network is scrubbed against
  every secret value before it is logged.

Usage:
  python publish_social.py <video.mp4> <post.json> --platforms youtube,tiktok [--live]

Env (all via GitHub secrets):
  AUTO_PUBLISH_ENABLED
  YOUTUBE_CLIENT_ID  YOUTUBE_CLIENT_SECRET  YOUTUBE_REFRESH_TOKEN
  YOUTUBE_PRIVACY    private (default) | unlisted | public
  TIKTOK_CLIENT_KEY  TIKTOK_CLIENT_SECRET   TIKTOK_REFRESH_TOKEN
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
                      "?uploadType=resumable&part=snippet,status")
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"

# TikTok accepts a video as one chunk only up to this size; larger files need the
# multi-chunk protocol, which this module does not implement. Refuse rather than
# send something the API will reject halfway.
TIKTOK_MAX_SINGLE_CHUNK = 64 * 1024 * 1024
YOUTUBE_CATEGORY_SCIENCE_TECH = "28"
YOUTUBE_PRIVACY_VALUES = ("private", "unlisted", "public")
PLATFORMS = ("youtube", "tiktok")

SECRET_ENV = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN",
              "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")


class PublishError(Exception):
    """A platform step failed. The message is already safe to print."""


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def autopublish_enabled():
    """Exact lowercase "true" only -- same contract as publish_publer.py."""
    return os.environ.get("AUTO_PUBLISH_ENABLED", "").strip() == "true"


def _secrets():
    return [v for v in (os.environ.get(k, "").strip() for k in SECRET_ENV) if v]


def scrub(text):
    """Remove every configured secret value (and obvious bearer tokens) from text."""
    out = str(text)
    for s in _secrets():
        out = out.replace(s, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", out)


def _http(method, url, headers=None, body=None, timeout=600):
    """(status, headers, bytes). Raises PublishError with scrubbed detail."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise PublishError(scrub(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}: {detail}"))
    except Exception as e:  # noqa: BLE001 - network failures are reported, not raised raw
        raise PublishError(scrub(f"{type(e).__name__} calling {urllib.parse.urlsplit(url).netloc}: {e}"))


HTTP = _http   # indirection so tests can run the whole flow with zero network


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        raise PublishError("response was not JSON")


# ---------------------------------------------------------------------------
# Pure builders (unit-tested, no network)
# ---------------------------------------------------------------------------

def youtube_privacy(value=None):
    """Only an exact recognised value overrides private; anything else is private."""
    v = (value if value is not None else os.environ.get("YOUTUBE_PRIVACY", "")).strip().lower()
    return v if v in YOUTUBE_PRIVACY_VALUES else "private"


def _clean(text, limit):
    text = re.sub(r"[<>]", "", str(text or "")).strip()
    return text[:limit].rstrip()


def youtube_metadata(post, privacy):
    """The videos.insert body, from the manifest's own post.json. Nothing invented."""
    title = _clean(post.get("title") or post.get("hook") or "Science short", 100)
    captions = [c for c in (post.get("captions") or []) if isinstance(c, str) and c.strip()]
    tags = [h.lstrip("#") for h in (post.get("hashtags") or []) if isinstance(h, str) and h.strip()]
    tagline = " ".join(f"#{t}" for t in tags)
    desc = "\n\n".join(p for p in (captions[0] if captions else "", tagline, "#Shorts") if p)
    return {
        "snippet": {
            "title": title,
            "description": _clean(desc, 4900),
            "tags": tags[:15],
            "categoryId": YOUTUBE_CATEGORY_SCIENCE_TECH,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


def tiktok_inbox_body(video_size):
    """Single-chunk FILE_UPLOAD init body for the inbox (draft) endpoint."""
    if video_size <= 0:
        raise PublishError("video is empty")
    if video_size > TIKTOK_MAX_SINGLE_CHUNK:
        raise PublishError(f"video is {video_size} bytes; single-chunk TikTok upload "
                           f"is limited to {TIKTOK_MAX_SINGLE_CHUNK}")
    return {"source_info": {"source": "FILE_UPLOAD", "video_size": video_size,
                            "chunk_size": video_size, "total_chunk_count": 1}}


def _need(names):
    missing = [n for n in names if not os.environ.get(n, "").strip()]
    if missing:
        raise PublishError("missing credentials: " + ", ".join(missing))
    return {n: os.environ[n].strip() for n in names}


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------

def publish_youtube(video_path, post, live):
    creds = _need(("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))
    privacy = youtube_privacy()
    meta = youtube_metadata(post, privacy)
    size = os.path.getsize(video_path)
    if not live:
        return {"mode": "dry-run", "privacy": privacy, "title": meta["snippet"]["title"],
                "bytes": size}

    form = urllib.parse.urlencode({
        "client_id": creds["YOUTUBE_CLIENT_ID"], "client_secret": creds["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": creds["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token",
    }).encode()
    _, _, raw = HTTP("POST", YOUTUBE_TOKEN_URL,
                     {"Content-Type": "application/x-www-form-urlencoded"}, form, 60)
    token = _json(raw).get("access_token")
    if not token:
        raise PublishError("token refresh returned no access_token")

    _, hdrs, _ = HTTP("POST", YOUTUBE_UPLOAD_URL, {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    }, json.dumps(meta).encode("utf-8"), 60)
    location = next((v for k, v in hdrs.items() if k.lower() == "location"), "")
    if not location:
        raise PublishError("resumable session returned no Location header")

    with open(video_path, "rb") as fh:
        data = fh.read()
    _, _, raw = HTTP("PUT", location, {"Content-Type": "video/mp4",
                                       "Content-Length": str(size)}, data, 900)
    vid = _json(raw).get("id")
    if not vid:
        raise PublishError("upload finished but no video id came back")
    return {"mode": "live", "video_id": vid, "privacy": privacy,
            "url": f"https://www.youtube.com/shorts/{vid}"}


def publish_tiktok(video_path, post, live):
    creds = _need(("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"))
    size = os.path.getsize(video_path)
    body = tiktok_inbox_body(size)
    if not live:
        return {"mode": "dry-run", "flow": "inbox/draft (user taps Post in the app)", "bytes": size}

    form = urllib.parse.urlencode({
        "client_key": creds["TIKTOK_CLIENT_KEY"], "client_secret": creds["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": creds["TIKTOK_REFRESH_TOKEN"],
    }).encode()
    _, _, raw = HTTP("POST", TIKTOK_TOKEN_URL, {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"}, form, 60)
    tok = _json(raw)
    access = tok.get("access_token")
    if not access:
        raise PublishError("TikTok token refresh returned no access_token")
    rotated = bool(tok.get("refresh_token")) and tok["refresh_token"] != creds["TIKTOK_REFRESH_TOKEN"]
    if rotated:
        # We cannot write a GitHub secret from here. If TikTok rotates refresh tokens
        # the stored one will eventually go stale; say so loudly instead of hiding it.
        print("::warning::TikTok returned a NEW refresh token; the stored "
              "TIKTOK_REFRESH_TOKEN secret will need updating if the old one stops working")

    _, _, raw = HTTP("POST", TIKTOK_INBOX_INIT_URL, {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json; charset=UTF-8"}, json.dumps(body).encode(), 60)
    data = (_json(raw).get("data") or {})
    upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
    if not upload_url or not publish_id:
        raise PublishError("TikTok init returned no upload_url/publish_id")

    with open(video_path, "rb") as fh:
        blob = fh.read()
    HTTP("PUT", upload_url, {"Content-Type": "video/mp4", "Content-Length": str(size),
                             "Content-Range": f"bytes 0-{size - 1}/{size}"}, blob, 900)
    return {"mode": "live", "publish_id": publish_id, "token_rotated": rotated,
            "next": "open the TikTok app inbox notification and tap Post"}


RUNNERS = {"youtube": publish_youtube, "tiktok": publish_tiktok}


def run(video_path, post_path, platforms, live):
    """Returns (results, ok). results maps platform -> dict(status, ...)."""
    if not autopublish_enabled():
        print("PUBLISHING DISABLED -- AUTO_PUBLISH_ENABLED is not exactly 'true'; nothing sent.")
        return {}, False
    unknown = [p for p in platforms if p not in RUNNERS]
    if unknown:
        raise SystemExit(f"unknown platform(s): {', '.join(unknown)}; choose from {', '.join(PLATFORMS)}")
    with open(post_path, "r", encoding="utf-8") as fh:
        post = json.load(fh)
    results, ok = {}, True
    for name in platforms:
        try:
            results[name] = {"status": "ok", **RUNNERS[name](video_path, post, live)}
        except PublishError as e:
            ok = False
            results[name] = {"status": "failed", "error": scrub(e)}
        except Exception as e:  # noqa: BLE001 - never let one platform hide another's result
            ok = False
            results[name] = {"status": "failed", "error": scrub(f"{type(e).__name__}: {e}")}
    return results, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video")
    ap.add_argument("post_json")
    ap.add_argument("--platforms", default="youtube")
    ap.add_argument("--live", action="store_true", help="really upload (default is a dry run)")
    a = ap.parse_args(argv)
    platforms = [p.strip().lower() for p in a.platforms.split(",") if p.strip()]
    if not os.path.isfile(a.video):
        raise SystemExit(f"video not found: {a.video}")
    results, ok = run(a.video, a.post_json, platforms, a.live)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if (ok and results) else 1


if __name__ == "__main__":
    sys.exit(main())
