# MONETIZATION.md — how this channel makes money

Short version: **views are not the product; an owned email audience is.** The
pipeline is being built so that, the day you start posting, every video quietly
funnels the right viewers onto a list you own and can monetize repeatedly —
instead of renting an audience from an algorithm that pays pennies and can zero
you overnight.

This is implemented in code (`funnel.py`, wired into `repackage.py`), so every
render already produces the funnel assets. Nothing here posts anything or stores
a credential.

---

## The funnel

```
   VIDEO           BIO LINK          OWNED EMAIL LIST         MONEY
  (rented    ->   (the bridge)  ->  (the actual asset)  ->  (repeatable, stacks)
   traffic)        one tap          you own it, forever      3 ways below
```

1. **Video** — the free, top-of-funnel reach engine (what we've been perfecting).
   Its only *business* job is to make a curious viewer tap the profile.
2. **Bio link** — a free link-in-bio page (Beacons / Stan.store / Linktree) whose
   single most prominent button is "join the list." One tap from the profile.
3. **Owned email list** — the asset. It can't be de-ranked, it survives a strike
   or a platform dying, and at industry benchmarks a niche list is worth on the
   order of **$0.50–$2 per subscriber per month** once monetized.
4. **Money — three stacking sources:**
   - **Affiliate** (turn on *now*, $0 to start): every video's topic has an
     obvious honest product — a great book on the subject. `funnel.py` maps each
     `topic_bank.json` domain to one (see `AFFILIATE_BY_DOMAIN`) and emits a
     ready newsletter teaser per render. Amazon Associates is free and instant.
   - **Platform payout** (turns on automatically at scale): TikTok Creator
     Rewards (needs **10k followers + 100k views/30d**, video **>1 min**) and
     YouTube Shorts revenue share via YPP (**1k subs + 10M Shorts views/90d**).
     Real but a *consequence* of the audience, not the strategy.
   - **Sponsorship** (the real faceless-channel income): a few thousand engaged
     subscribers in a clean niche (science) sells newsletter classified slots and
     brand deals on the videos. Only reachable because the list exists.

**Why not just chase the platform creator funds?** Because they pay roughly
$0.02–$0.05 per 1,000 views AND gate you behind thresholds you don't have yet.
A single affiliate sale or one newsletter sponsor slot out-earns tens of
thousands of fund-eligible views. The list is where the leverage is.

---

## What every render already produces for this (in `out/`)

| File | What it gives the poster |
|---|---|
| `funnel.json` | `pinned_comment` (post as the first comment, pinned, on every platform — the main list ask), `newsletter` (ready-to-send email teaser + affiliate), `affiliate` (topic-matched book + search phrase), `bio_cta` |
| `platform_text.json` | per-platform captions — the soft bio CTA is added **only** to YouTube's description and Facebook (where a link reads naturally); TikTok/IG/X captions stay clean so nothing feels spammy |
| `release_body.md` | carries `===PINNED_COMMENT_START===…` so a Zap/Buffer step can post it as a first comment automatically |

The CTA is **never shouted inside the video** (that was the formulaic "save this
so you don't forget" ending you disliked). It lives in captions, the pinned
comment, and the newsletter — outside the content itself.

---

## One-time setup (all free tiers) — do this before you start posting

1. **Email list** — create a free account on **Beehiiv** or **Kit (ConvertKit)**
   or **Substack**. Name it something concrete and benefit-led (the default in
   code is *"Stranger Than Fiction"*). Grab the subscribe-page URL.
2. **Link-in-bio** — create a free **Beacons** or **Stan.store** page. Top
   button: "Get the weekly strange-but-true science email" → your subscribe URL.
   Second button: your best affiliate link. Put this bio page's URL in each
   platform's profile.
3. **Amazon Associates** — sign up (free). Turn the `affiliate.search` phrase
   from each `funnel.json` into a tagged link when you send the newsletter.
4. **Tell the pipeline your links** — set three **repo variables** (GitHub →
   Settings → Secrets and variables → Actions → **Variables**, not Secrets, since
   they're not sensitive):
   - `BIO_LINK` = your link-in-bio URL
   - `CHANNEL_HANDLE` = your @handle
   - `LIST_NAME` = your newsletter's name
   Until you set them, `funnel.py` uses readable placeholders so the metadata is
   still valid — the pipeline never breaks waiting on these.

That's the whole funnel. After this, every render's `funnel.json` is
copy-paste-ready and (via `release_body.md`) Zapier can even post the pinned
comment for you.

---

## Staged plan (so effort matches the stage)

- **Stage 0 — now (pre-posting):** funnel is built and dormant. Keep perfecting
  video quality (the loop). Set up the 4 free accounts above whenever convenient.
- **Stage 1 — first posts → ~1k followers:** affiliate + newsletter live from day
  one. Income is small but real and compounding; the goal is *list growth*, not
  revenue yet. Watch which topics convert (the newsletter's click data is your
  first real signal — better than view counts).
- **Stage 2 — ~1k–10k:** platform payouts start turning on (YouTube YPP first).
  Newsletter is big enough to matter; keep affiliate honest and topic-matched.
- **Stage 3 — 10k+:** TikTok Creator Rewards eligible; newsletter can sell
  sponsor slots and the videos can take brand deals. This is where faceless
  channels actually earn.

The single number to watch is **email subscribers**, not followers or views —
it's the one you own and the one that turns into money.

---

## Honest caveats

- These programs' thresholds and rates change; verify TikTok Creator Rewards /
  YPP terms when you cross each bar. The affiliate + list path does not depend on
  any platform's fund and is the resilient core.
- Affiliate income needs *volume of engaged clicks*, which needs the list, which
  needs consistently good videos. So the funnel doesn't replace the quality work
  — it's what turns that quality into money instead of just view counts.
