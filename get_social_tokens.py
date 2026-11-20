#!/usr/bin/env python3
"""One-time helper: turn a Google / TikTok app into the refresh token the uploader needs.

Run this ON YOUR OWN COMPUTER, once per platform. It needs no extra packages.
It prints the refresh token to your terminal -- paste that into a GitHub secret.
It never writes the token to disk and never sends it anywhere but the platform.

    python get_social_tokens.py youtube
    python get_social_tokens.py tiktok

You are asked for the app's client id/secret (never stored), shown a URL to open,
and then asked to paste back the `code=` value from the address bar after you
approve. Paste-back is used instead of a local web server because TikTok does not
accept http://localhost redirect URIs, and this works the same everywhere.
"""
from __future__ import annotations

import getpass
import json
import sys
import urllib.parse
import urllib.request

YOUTUBE_REDIRECT = "http://localhost:8080"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def youtube_auth_url(client_id, redirect_uri=YOUTUBE_REDIRECT):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": YOUTUBE_SCOPE,
        # offline + consent is what makes Google issue a refresh token at all.
        "access_type": "offline", "prompt": "consent",
    })


def tiktok_auth_url(client_key, redirect_uri, state="content-render"):
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": client_key, "scope": "user.info.basic,video.upload",
        "response_type": "code", "redirect_uri": redirect_uri, "state": state,
    })


def clean_code(pasted):
    """Accept the bare code, or the whole redirect URL, and URL-decode it."""
    pasted = pasted.strip()
    if "code=" in pasted:
        qs = urllib.parse.urlsplit(pasted).query or pasted.split("?", 1)[-1]
        pasted = urllib.parse.parse_qs(qs).get("code", [pasted])[0]
    return urllib.parse.unquote(pasted)


def _post(url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main(argv):
    if len(argv) != 2 or argv[1] not in ("youtube", "tiktok"):
        print(__doc__)
        return 2
    if argv[1] == "youtube":
        cid = input("Google OAuth client ID: ").strip()
        secret = getpass.getpass("Google OAuth client secret (hidden): ").strip()
        print("\nOpen this URL, sign in with the YouTube channel's Google account, approve:\n")
        print(youtube_auth_url(cid))
        print("\nYour browser will then fail to load http://localhost:8080 -- that is expected.")
        code = clean_code(input("Paste that address-bar URL (or just the code= value): "))
        tok = _post("https://oauth2.googleapis.com/token", {
            "code": code, "client_id": cid, "client_secret": secret,
            "redirect_uri": YOUTUBE_REDIRECT, "grant_type": "authorization_code"})
        key = "refresh_token"
    else:
        ck = input("TikTok client key: ").strip()
        secret = getpass.getpass("TikTok client secret (hidden): ").strip()
        redirect = input("The redirect URI registered in your TikTok app: ").strip()
        print("\nOpen this URL, log in, approve:\n")
        print(tiktok_auth_url(ck, redirect))
        code = clean_code(input("\nPaste the redirected URL (or just the code= value): "))
        tok = _post("https://open.tiktokapis.com/v2/oauth/token/", {
            "client_key": ck, "client_secret": secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect})
        key = "refresh_token"
    if not tok.get(key):
        print("\nNo refresh token came back. Response keys:", sorted(tok))
        return 1
    print(f"\n{key.upper()} (paste into the GitHub secret, then clear your terminal):\n{tok[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
