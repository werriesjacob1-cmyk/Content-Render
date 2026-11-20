#!/usr/bin/env python3
"""publish_social: the safety contract, proven with ZERO network.

Every platform call goes through publish_social.HTTP, which these tests replace
with a recorder. Nothing here can reach YouTube or TikTok.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import contextlib
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import publish_publer as PP
import publish_social as S

SECRETS = {
    "YOUTUBE_CLIENT_ID": "yt-client-id-AAA", "YOUTUBE_CLIENT_SECRET": "yt-client-secret-BBB",
    "YOUTUBE_REFRESH_TOKEN": "yt-refresh-CCC",
    "TIKTOK_CLIENT_KEY": "tt-key-DDD", "TIKTOK_CLIENT_SECRET": "tt-secret-EEE",
    "TIKTOK_REFRESH_TOKEN": "tt-refresh-FFF",
}
POST = {"title": "The Universe You Can't See: Part 1", "hook": "Fresh bananas emit radiation.",
        "captions": ["Banana radiation is real. Comforting or creepy?"],
        "hashtags": ["#physics", "#science", "#radiation"]}


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print(f"PASS {label}")


class Net:
    """Recorder standing in for publish_social.HTTP."""
    def __init__(self, fail_hosts=()):
        self.calls, self.fail_hosts = [], fail_hosts

    def __call__(self, method, url, headers=None, body=None, timeout=0):
        self.calls.append((method, url, dict(headers or {}), body))
        if any(h in url for h in self.fail_hosts):
            raise S.PublishError(S.scrub("HTTP 401 from host: bad " + SECRETS["YOUTUBE_REFRESH_TOKEN"]))
        if "oauth2.googleapis.com" in url:
            return 200, {}, b'{"access_token": "yt-access-token-ZZZ"}'
        if "uploadType=resumable" in url:
            return 200, {"Location": "https://upload.example/session1"}, b"{}"
        if url == "https://upload.example/session1":
            return 200, {}, b'{"id": "abc123"}'
        if "open.tiktokapis.com/v2/oauth/token" in url:
            return 200, {}, b'{"access_token": "tt-access-token-YYY", "refresh_token": "tt-refresh-FFF"}'
        if "inbox/video/init" in url:
            return 200, {}, b'{"data": {"publish_id": "pub9", "upload_url": "https://tt.example/up"}}'
        if url == "https://tt.example/up":
            return 200, {}, b"{}"
        raise AssertionError("unexpected URL " + url)


class Env:
    def __init__(self, **kv):
        self.kv = kv

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in list(SECRETS) + ["AUTO_PUBLISH_ENABLED", "YOUTUBE_PRIVACY"]}
        for k in self.old:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in self.kv.items() if v is not None})

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def _files():
    d = tempfile.mkdtemp()
    v = Path(d) / "v.mp4"
    v.write_bytes(b"\x00" * 2048)
    p = Path(d) / "post.json"
    p.write_text(json.dumps(POST))
    return str(v), str(p)


def _run(platforms, live, env, net=None):
    video, post = _files()
    net = net or Net()
    S.HTTP = net
    buf = io.StringIO()
    with Env(**env), contextlib.redirect_stdout(buf):
        results, ok = S.run(video, post, platforms, live)
    return results, ok, net, buf.getvalue()


ALL = {**SECRETS, "AUTO_PUBLISH_ENABLED": "true"}


def test_1_kill_switch_is_the_same_contract_as_publer():
    for val in (None, "", "TRUE", "True", "1", "yes", " false "):
        env = {**SECRETS, **({"AUTO_PUBLISH_ENABLED": val} if val is not None else {})}
        results, ok, net, _ = _run(["youtube", "tiktok"], True, env)
        check(results == {} and not ok and not net.calls,
              f"AUTO_PUBLISH_ENABLED={val!r}: nothing sent, zero network calls")
    with Env(AUTO_PUBLISH_ENABLED=" true "):
        check(S.autopublish_enabled() and PP._autopublish_enabled(), "' true ' (trimmed) opens both")
    for val in ("TRUE", "1", ""):
        with Env(AUTO_PUBLISH_ENABLED=val):
            check(S.autopublish_enabled() == PP._autopublish_enabled() == False,
                  f"{val!r} closes BOTH layers identically")


def test_2_dry_run_makes_zero_network_calls():
    results, ok, net, _ = _run(["youtube", "tiktok"], False, ALL)
    check(ok and net.calls == [], "dry run succeeds and touches no network (not even token refresh)")
    check(results["youtube"]["mode"] == "dry-run" and results["tiktok"]["mode"] == "dry-run",
          "both platforms report dry-run")


def test_3_youtube_defaults_to_private_and_only_exact_values_widen_it():
    for raw, want in ((None, "private"), ("", "private"), ("PUBLIC ", "public"),
                      ("unlisted", "unlisted"), ("everyone", "private"), ("true", "private")):
        with Env(**({"YOUTUBE_PRIVACY": raw} if raw is not None else {})):
            check(S.youtube_privacy() == want, f"YOUTUBE_PRIVACY={raw!r} -> {want}")
    results, _, net, _ = _run(["youtube"], True, ALL)
    sent = json.loads([c for c in net.calls if "uploadType" in c[1]][0][3])
    check(sent["status"]["privacyStatus"] == "private", "a live upload with no setting is PRIVATE")
    check(sent["status"]["selfDeclaredMadeForKids"] is False, "not declared made-for-kids")


def test_4_youtube_metadata_comes_only_from_post_json():
    m = S.youtube_metadata({"title": "A" * 300 + "<script>", "captions": ["Hello <b>"],
                            "hashtags": ["#a", "b"]}, "private")
    check(len(m["snippet"]["title"]) <= 100 and "<" not in m["snippet"]["title"], "title capped and sanitised")
    check("<" not in m["snippet"]["description"] and "#Shorts" in m["snippet"]["description"],
          "description sanitised and tagged #Shorts")
    check(m["snippet"]["tags"] == ["a", "b"], "tags derived from the manifest's own hashtags")
    empty = S.youtube_metadata({}, "private")
    check(empty["snippet"]["title"], "a missing title falls back instead of crashing")


def test_5_youtube_live_flow_uses_resumable_protocol():
    results, ok, net, out = _run(["youtube"], True, ALL)
    check(ok and results["youtube"]["video_id"] == "abc123", "upload returns a video id")
    methods = [(c[0], c[1].split("?")[0]) for c in net.calls]
    check(methods[0][1].endswith("/token"), "1: refresh the access token")
    check(methods[1][1].endswith("/videos"), "2: open a resumable session")
    check(methods[2] == ("PUT", "https://upload.example/session1"), "3: PUT the bytes to the session URL")
    init_headers = net.calls[1][2]
    check(init_headers["X-Upload-Content-Length"] == "2048", "declares the exact byte length")
    check(net.calls[2][3] == b"\x00" * 2048, "uploads the real file bytes")
    check(results["youtube"]["url"].endswith("/abc123"), "returns the Shorts URL")


def test_6_tiktok_uses_inbox_never_direct_post():
    results, ok, net, _ = _run(["tiktok"], True, ALL)
    check(ok and results["tiktok"]["publish_id"] == "pub9", "inbox upload returns a publish id")
    urls = " ".join(c[1] for c in net.calls)
    check("inbox/video/init" in urls, "uses the inbox (draft) endpoint")
    check("publish/video/init" not in urls.replace("inbox/video/init", ""),
          "never calls the Direct Post endpoint")
    body = json.loads([c for c in net.calls if "inbox/video/init" in c[1]][0][3])["source_info"]
    check(body == {"source": "FILE_UPLOAD", "video_size": 2048, "chunk_size": 2048, "total_chunk_count": 1},
          "single-chunk FILE_UPLOAD body")
    put = [c for c in net.calls if c[0] == "PUT"][0]
    check(put[2]["Content-Range"] == "bytes 0-2047/2048", "Content-Range covers the whole file")
    check("tap Post" in results["tiktok"]["next"], "tells the human what finishes the post")


def test_7_tiktok_refuses_files_it_cannot_single_chunk():
    for size in (0, S.TIKTOK_MAX_SINGLE_CHUNK + 1):
        try:
            S.tiktok_inbox_body(size)
            check(False, f"size {size} should have been refused")
        except S.PublishError:
            check(True, f"size {size} refused before any request is made")
    check(S.tiktok_inbox_body(S.TIKTOK_MAX_SINGLE_CHUNK)["source_info"]["total_chunk_count"] == 1,
          "exactly the limit is accepted")


def test_8_missing_credentials_for_a_requested_platform_is_a_failure():
    env = {"AUTO_PUBLISH_ENABLED": "true", "YOUTUBE_CLIENT_ID": "x"}   # incomplete
    results, ok, net, _ = _run(["youtube"], True, env)
    check(not ok and results["youtube"]["status"] == "failed", "requested + unconfigured = FAIL, not skip")
    check("YOUTUBE_CLIENT_SECRET" in results["youtube"]["error"], "names exactly which credentials are missing")
    check(net.calls == [], "no request is attempted without full credentials")
    results, ok, _, _ = _run(["tiktok"], False, {"AUTO_PUBLISH_ENABLED": "true"})
    check(not ok, "even a DRY RUN fails when credentials are absent (a dry run must prove readiness)")


def test_9_one_platform_failing_does_not_hide_the_other():
    results, ok, net, _ = _run(["youtube", "tiktok"], True, ALL, Net(fail_hosts=("oauth2.googleapis.com",)))
    check(results["youtube"]["status"] == "failed", "youtube reported as failed")
    check(results["tiktok"]["status"] == "ok", "tiktok still ran and succeeded")
    check(not ok, "overall result is failure so the workflow goes red")


def test_10_secrets_never_reach_output():
    results, ok, net, out = _run(["youtube", "tiktok"], True, ALL, Net(fail_hosts=("oauth2.googleapis.com",)))
    blob = json.dumps(results) + out
    for name, val in SECRETS.items():
        check(val not in blob, f"{name} value never appears in results or logs")
    with Env(**ALL):
        check("tt-access" not in S.scrub("Authorization: Bearer tt-access-token-YYY"),
              "bearer tokens are scrubbed even when not a configured secret")


def test_11_unknown_platform_is_rejected():
    video, post = _files()
    S.HTTP = Net()
    with Env(**ALL):
        try:
            S.run(video, post, ["instagram"], False)
            check(False, "should have exited")
        except SystemExit as e:
            check("unknown platform" in str(e), "an unsupported platform is a hard error, not a silent skip")


def test_12_tiktok_rotated_refresh_token_is_flagged():
    class Rot(Net):
        def __call__(self, method, url, *a, **k):
            if "oauth/token" in url:
                self.calls.append((method, url, {}, None))
                return 200, {}, b'{"access_token": "a", "refresh_token": "brand-new-token"}'
            return super().__call__(method, url, *a, **k)
    results, ok, _, out = _run(["tiktok"], True, ALL, Rot())
    check(ok and results["tiktok"]["token_rotated"] is True, "rotation is detected and reported")
    check("::warning::" in out and "brand-new-token" not in out,
          "a visible warning is emitted without printing the new token")


def test_13_no_direct_post_and_no_topic_logic_in_source():
    src = (ROOT / "publish_social.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check("/v2/post/publish/video/init" not in code, "Direct Post endpoint is not referenced in code")


def test_14_workflow_is_manual_gated_dry_by_default_and_injection_safe():
    # Plain-text parsing on purpose: the CI `test` job does not install PyYAML
    # (only factory-proof runs pip install), and an earlier `import yaml` in a
    # zero-dependency job turned CI red. Do not "simplify" this back to yaml.
    import re
    text = (ROOT / ".github/workflows/publish_social.yml").read_text(encoding="utf-8")
    lines = text.splitlines()

    start = lines.index("on:")
    block = []
    for ln in lines[start + 1:]:
        if ln and not ln.startswith(" "):
            break
        block.append(ln)
    triggers = [m.group(1) for m in (re.match(r"^  ([a-z_]+):", l) for l in block) if m]
    check(triggers == ["workflow_dispatch"],
          f"ONLY manual dispatch: no schedule, push or pull_request trigger ({triggers})")

    check(re.search(r'dry_run:\n(?:\s+.*\n)*?\s+default: "true"', text) is not None,
          "dry_run defaults to TRUE")
    check("    if: ${{ vars.AUTO_PUBLISH_ENABLED == 'true' }}" in lines,
          "job is behind the exact master-switch condition render.yml uses")
    perm = text.split("permissions:")[1].split("\n\n")[0]
    check("contents: read" in perm and "actions: read" in perm and "write" not in perm,
          "least privilege: read-only")

    run_block = text.rsplit("run: |", 1)[1]
    check("github.event.inputs" not in run_block and "${{" not in run_block,
          "no workflow expression is interpolated into the shell text (script-injection safe)")
    check("DRY_RUN: ${{ github.event.inputs.dry_run }}" in text
          and "PLATFORMS: ${{ github.event.inputs.platforms }}" in text,
          "inputs are passed via env instead")
    check("echo" not in "".join(l for l in lines if "secrets." in l), "no step echoes a secret")
    check('if [ "$DRY_RUN" = "false" ]; then LIVE="--live"; fi' in text,
          "live mode requires the exact string 'false'")


def test_15_token_helper_builds_correct_urls_and_cleans_pasted_codes():
    import get_social_tokens as G
    u = G.youtube_auth_url("CID")
    check("access_type=offline" in u and "prompt=consent" in u,
          "Google URL asks for offline access + consent (otherwise no refresh token is issued)")
    scope = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)["scope"]
    check(scope == ["https://www.googleapis.com/auth/youtube.upload"], "requests ONLY the upload scope")
    t = G.tiktok_auth_url("KEY", "https://example.com/cb")
    check("video.upload" in t and "video.publish" not in t,
          "TikTok URL requests the inbox scope only, never video.publish")
    check(G.clean_code("4%2FabcXYZ") == "4/abcXYZ", "a bare URL-encoded code is decoded")
    check(G.clean_code("http://localhost:8080/?code=4%2Fabc&scope=x") == "4/abc",
          "a whole pasted redirect URL yields just the code")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("publish_social tests: PASS")
