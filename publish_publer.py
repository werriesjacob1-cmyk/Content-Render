#!/usr/bin/env python3
"""Push a finished render to Publer as a DRAFT via the Publer API — a DIRECT
replacement for the flaky "GitHub Release -> Zapier -> Publer" hop (Zapier's free
task cap / OAuth expiry silently stops posts reaching Publer).

DORMANT BY DEFAULT: with no PUBLER_API_KEY set this is a clean no-op (exit 0), so
it is safe in the render workflow and the existing Zapier path is untouched. It
activates only once the Publer secrets are set. Publer's API needs a BUSINESS plan;
the key lives at Publer -> Settings -> Access & Login -> API Keys.

It never fails the workflow: any error is logged and we exit 0, because the video
is already safely published to the GitHub Release regardless.

Env:
  PUBLER_API_KEY       activate; Publer Business plan, Settings -> Access & Login -> API Keys
  PUBLER_WORKSPACE_ID  the workspace to post into (required with the key)
  PUBLER_ACCOUNT_IDS   optional comma-separated social-account ids to target;
                       unset = every connected account in the workspace
  PUBLER_STATE         'draft' (default — you review/publish in Publer) or 'scheduled'
Usage: python publish_publer.py <video.mp4> [caption_file]
API docs: https://publer.com/docs/api-reference/introduction
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("PUBLER_API_BASE", "https://app.publer.com/api/v1").rstrip("/")
KEY = os.environ.get("PUBLER_API_KEY", "").strip()
WS = os.environ.get("PUBLER_WORKSPACE_ID", "").strip()


def _headers(extra=None):
    # Publer uses the unusual "Bearer-API <key>" scheme + a workspace header.
    h = {"Authorization": f"Bearer-API {KEY}", "Publer-Workspace-Id": WS}
    if extra:
        h.update(extra)
    return h


def _req(method, path, data=None, headers=None, timeout=240):
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers or _headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode() or "{}"
    return json.loads(raw)


def _multipart(filefield, filepath):
    boundary = "----publer" + uuid.uuid4().hex
    fname = os.path.basename(filepath)
    ctype = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{filefield}\"; "
            f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    with open(filepath, "rb") as f:
        body = head + f.read() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _poll_job(job_id, tries=80, delay=3):
    """Publer's create/upload calls are async: poll /job_status/{id} to completion."""
    for _ in range(tries):
        try:
            j = _req("GET", f"/job_status/{job_id}")
        except Exception as e:  # noqa: BLE001
            print(f"  [publer] job poll error: {e}")
            return None
        st = str(j.get("status") or (j.get("data") or {}).get("status") or "").lower()
        if st in ("complete", "completed", "success", "done"):
            return j
        if st in ("failed", "error"):
            print(f"  [publer] job failed: {json.dumps(j)[:300]}")
            return None
        time.sleep(delay)
    print("  [publer] job still working after poll budget — check Publer manually")
    return None


def upload_media(path):
    body, ctype = _multipart("file", path)
    r = _req("POST", "/media", data=body, headers=_headers({"Content-Type": ctype}))
    mid = r.get("id") or (r.get("data") or {}).get("id")
    job = r.get("job_id") or (r.get("data") or {}).get("job_id")
    if not mid and job:
        j = _poll_job(job) or {}
        res = j.get("result") or (j.get("data") or {}).get("result") or j.get("data") or {}
        mid = res.get("id") or (res.get("media") or {}).get("id") if isinstance(res, dict) else None
    return mid


def list_accounts():
    """Return [(account_id, provider)] to target — a configured subset if
    PUBLER_ACCOUNT_IDS is set, else every account in the workspace."""
    conf = {x.strip() for x in os.environ.get("PUBLER_ACCOUNT_IDS", "").split(",") if x.strip()}
    r = _req("GET", "/accounts")
    accs = r if isinstance(r, list) else (r.get("accounts") or r.get("data") or [])
    out = []
    for a in accs:
        if not isinstance(a, dict):
            continue
        aid = a.get("id")
        prov = str(a.get("provider") or a.get("type") or a.get("network") or "").lower()
        if not aid or (conf and str(aid) not in conf):
            continue
        out.append((aid, prov or "instagram"))
    return out


def _caption(argv):
    if len(argv) > 2:
        try:
            return open(argv[2]).read().strip()
        except Exception:  # noqa: BLE001
            pass
    for path in ("out/release_body.md", "out/post.json"):
        try:
            if path.endswith(".json"):
                caps = json.load(open(path)).get("captions") or [""]
                return caps[0]
            return open(path).read().strip()
        except Exception:  # noqa: BLE001
            continue
    return ""


def main():
    if not KEY or not WS:
        print("[publer] PUBLER_API_KEY / PUBLER_WORKSPACE_ID not set — skipping direct "
              "push (dormant; the GitHub Release + any Zapier path are unaffected)")
        return 0
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        print("[publer] no video file given/found — nothing to push")
        return 0
    video = sys.argv[1]
    caption = _caption(sys.argv)
    try:
        mid = upload_media(video)
        if not mid:
            print("[publer] media upload returned no id — video still on the Release, skipping")
            return 0
        accounts = list_accounts()
        if not accounts:
            print("[publer] no target accounts resolved — check PUBLER_ACCOUNT_IDS / connections")
            return 0
        state = os.environ.get("PUBLER_STATE", "draft").strip() or "draft"
        posts = [{
            "networks": {prov: {"type": "video", "text": caption,
                                "media": [{"id": mid, "type": "video"}]}},
            "accounts": [{"id": aid}],
        } for aid, prov in accounts]
        body = json.dumps({"bulk": {"state": state, "posts": posts}}).encode()
        r = _req("POST", "/posts/schedule", data=body,
                 headers=_headers({"Content-Type": "application/json"}))
        job = r.get("job_id") or (r.get("data") or {}).get("job_id")
        if job:
            _poll_job(job)
        print(f"[publer] {state} push submitted for {len(accounts)} account(s) — check Publer")
        return 0
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:  # noqa: BLE001
            pass
        print(f"[publer] API HTTP {e.code}: {detail} — video still on the Release, skipping")
        return 0
    except Exception as e:  # noqa: BLE001 — must never fail the render workflow
        print(f"[publer] push failed ({type(e).__name__}: {str(e)[:200]}) — video still on the Release")
        return 0


if __name__ == "__main__":
    sys.exit(main())
