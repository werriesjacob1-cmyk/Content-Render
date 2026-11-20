# Free posting to YouTube Shorts + TikTok — one-time setup

Everything below is free. Nothing posts until you (1) add the secrets, (2) set the
`AUTO_PUBLISH_ENABLED` variable to `true`, and (3) click **Run workflow** on
`publish-social`. It defaults to a **dry run** and uploads YouTube as **private**.

What was verified against the platforms' own docs (Nov 2026) and what was NOT:

| | Verified | NOT verified — the first real run tells us |
|---|---|---|
| YouTube | free, 100 uploads/day default, vertical ≤3 min = a Short | whether an unverified API project's uploads get locked private (Google's pages contradict each other); the audit process |
| TikTok | Direct Post is private-only for unaudited apps, and "a tool to post to accounts you manage" is listed as not acceptable, so this uses the **inbox/draft** flow | whether the inbox flow works for an unaudited app; whether refresh tokens rotate |

## A. YouTube (do this first)

1. Go to <https://console.cloud.google.com/>, create a project (any name).
2. **APIs & Services → Library →** search **YouTube Data API v3 → Enable**.
3. **APIs & Services → OAuth consent screen:** User type **External**, fill the
   required name/email, add **your own Google account as a Test user**.
4. **Credentials → Create credentials → OAuth client ID → Application type:
   Desktop app.** Copy the client ID and client secret.
5. On your own computer: `python get_social_tokens.py youtube`. Follow the prompts.
   It prints a refresh token.
6. GitHub → repo → Settings → Secrets and variables → Actions → **Secrets**, add:
   `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

**Watch out:** a consent screen left in *Testing* status may expire the refresh
token after about 7 days (from experience; Google's pages I could read do not
confirm it). If uploads start failing with an auth error after a week, switch the
consent screen to **In production** and redo step 5. A warning screen about an
unverified app is expected for your own account.

## B. TikTok (drafts only)

1. <https://developers.tiktok.com/> → register, **Manage apps → Create app**.
2. Add the **Content Posting API** product and the scope **`video.upload`**
   (NOT `video.publish` — we do not use Direct Post).
3. Register a redirect URI you control (TikTok's web flow wants HTTPS).
4. Copy the client key and client secret.
5. On your own computer: `python get_social_tokens.py tiktok`.
6. Add secrets: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.

TikTok may require the app to pass review before the Content Posting API works at
all, even for drafts, and the docs do not say. If so, the dry run will pass but the
live run will fail with a clear message; that failure is information, not a bug.

## C. Using it

1. A render finishes (private artifact). Watch it. Decide it is good.
2. Actions → **publish-social → Run workflow.** Enter that render's run id.
3. Leave **dry_run = true** the first time: it builds the exact requests and checks
   your credentials without sending anything.
4. Re-run with **dry_run = false**. YouTube lands **private** — open YouTube Studio
   and make it public yourself the first few times. TikTok lands in your app inbox;
   tap the notification and press Post.

To let YouTube publish directly as public, set the repo **Variable**
`YOUTUBE_PRIVACY` to `public` (or `unlisted`). Do that only after a private upload
has worked and you trust the pipeline's output.

## D. What can go wrong, in plain words

- `missing credentials: ...` — a secret is not set. Requested platforms with no
  credentials fail on purpose rather than skipping quietly.
- `HTTP 401/403` from Google/TikTok — the token expired or the app is not approved.
- The workflow does not start at all — `AUTO_PUBLISH_ENABLED` is not exactly `true`.
- **Tokens never appear in logs**; they are scrubbed from all error output.
