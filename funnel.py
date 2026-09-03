#!/usr/bin/env python3
"""
funnel.py — the monetization funnel, as code.

The channel's job is not "get views." Views are rented traffic on someone
else's platform; an algorithm change or a strike can zero them overnight, and
the platform creator-payout programs (TikTok Creator Rewards, YouTube Shorts
revenue share) pay pennies per thousand views AND gate you behind large
follower/watch-time thresholds you don't have yet. So chasing payout programs
first is the low-EV path.

The high-EV faceless-channel funnel — the one this file encodes — is:

    VIDEO  ->  BIO LINK  ->  OWNED EMAIL LIST  ->  money
   (rented)   (bridge)      (the actual asset)    (repeatable)

Every video's real call to action is "there's more where this came from, and
I'll send it to you" — moving an anonymous viewer onto an email list you own.
An email list can't be de-ranked, is worth ~$1/subscriber/month at industry
benchmarks once monetized, and is monetized THREE ways that stack:

  1. AFFILIATE  — each video's topic has an obvious, honest product (usually a
     great book on the subject). Amazon Associates is free to join; the link
     lives in the newsletter and the bio, never shouted in the video. See
     AFFILIATE_BY_DOMAIN below.
  2. PLATFORM PAYOUT — TikTok Creator Rewards (needs 10k followers + 100k
     views/30d, video >1 min) and YouTube Shorts revenue share (YPP: 1k subs +
     10M Shorts views/90d) turn on automatically once the audience is big
     enough. Free money at scale, but a CONSEQUENCE of the list-building, not
     the strategy.
  3. SPONSORSHIP — the real faceless-channel income. A newsletter with a few
     thousand engaged subscribers in a clean niche (science) sells classified
     ad slots; brand deals on the videos themselves follow. Only reachable
     because steps above build a real, owned, niche audience.

This module produces, per render, the concrete funnel assets a
publisher/scheduler needs: a soft bio CTA line (varied, never the banned
"save this so you don't forget" formula), a pinned-comment that does the
list-building ask, a newsletter blurb, and the topic-matched affiliate angle.
It writes out/funnel.json and feeds repackage.py's per-platform captions.

Nothing here posts anything or stores a credential. The two placeholders you
fill once (your bio-link URL and @handle) come from env so they never live in
the repo:  BIO_LINK  and  CHANNEL_HANDLE.
"""

import os
import random

# The two things you set once, in the environment (GitHub Actions secret/var,
# or your shell), not in the repo. Sensible placeholders so a dry run still
# produces readable assets before you've created the accounts.
BIO_LINK = os.environ.get("BIO_LINK", "").strip() or "the link in my bio"
CHANNEL_HANDLE = os.environ.get("CHANNEL_HANDLE", "").strip() or "@stranger.science"
# TRUE only once a real bio link is configured. Until then the captions must NOT
# promise a newsletter / "weekly in your inbox" / a bio link that doesn't exist —
# an empty promise a viewer taps and finds nothing is worse than no CTA. When
# unset we fall back to FOLLOW-only CTAs (a follow is always real), and the
# newsletter/link language switches on automatically the moment BIO_LINK is set.
HAS_FUNNEL = bool(os.environ.get("BIO_LINK", "").strip())
# The owned asset's name — what the viewer is subscribing TO. Keep it concrete
# and benefit-led, not "my newsletter."
LIST_NAME = os.environ.get("LIST_NAME", "").strip() or "Stranger Than Fiction"


# ---------------------------------------------------------------------------
# AFFILIATE_BY_DOMAIN — for each topic domain in topic_bank.json, the honest,
# obviously-relevant product to point at. Books, because (a) they never feel
# scammy on a science page, (b) Amazon Associates is free and instant, (c) a
# curious viewer who just learned one strange fact is in the exact mindset to
# buy the book that has a hundred more. `search` is a stable Amazon search
# phrase (resilient to any single title going out of print); turn it into your
# tagged affiliate link once, in the newsletter/bio — NOT shouted in the video.
# ---------------------------------------------------------------------------
AFFILIATE_BY_DOMAIN = {
    "space":     {"kind": "book", "search": "Astrophysics for People in a Hurry",
                  "angle": "the book that makes the whole universe feel this close"},
    "body":      {"kind": "book", "search": "Gulp Adventures on the Alimentary Canal Mary Roach",
                  "angle": "the book that makes your own body this strange"},
    "ocean":     {"kind": "book", "search": "The Brilliant Abyss deep ocean",
                  "angle": "the book on everything still hiding in the deep"},
    "animals":   {"kind": "book", "search": "An Immense World Ed Yong animal senses",
                  "angle": "the book on the senses animals have and we don't"},
    "physics":   {"kind": "book", "search": "Seven Brief Lessons on Physics Rovelli",
                  "angle": "the book that explains reality in an afternoon"},
    "earth":     {"kind": "book", "search": "The Story of the Earth Robert Hazen",
                  "angle": "the book on how the planet actually got made"},
    "light":     {"kind": "book", "search": "Catching the Light Arthur Zajonc",
                  "angle": "the book on what light really is"},
    "materials": {"kind": "book", "search": "Stuff Matters Mark Miodownik",
                  "angle": "the book on the hidden science of ordinary stuff"},
    # ADDED 2026-08-03 (system-wide sweep): these families cover ~2/3 of the bank
    # (biology, psychology, chemistry, neurology, plants, math, history, senses,
    # matter, fungi, nature, deep_time) but had no mapping, so every video from
    # them silently fell to the generic AFFILIATE_DEFAULT in the newsletter's
    # monetization pitch -- the one place this file is actually supposed to make
    # money. Real, well-known, topic-matched books for each.
    "biology":   {"kind": "book", "search": "The Vital Question Nick Lane",
                  "angle": "the book on how life itself got started"},
    "psychology":{"kind": "book", "search": "Thinking Fast and Slow Kahneman",
                  "angle": "the book on why your own mind fools you"},
    "chemistry": {"kind": "book", "search": "The Disappearing Spoon Sam Kean",
                  "angle": "the book with a wild story behind every element"},
    "neurology": {"kind": "book", "search": "The Brain That Changes Itself Norman Doidge",
                  "angle": "the book on how strange the brain really is"},
    "plants":    {"kind": "book", "search": "The Hidden Life of Trees Peter Wohlleben",
                  "angle": "the book on what plants are secretly doing"},
    "math":      {"kind": "book", "search": "How Not to Be Wrong Jordan Ellenberg",
                  "angle": "the book that makes math feel like a superpower"},
    "history":   {"kind": "book", "search": "Sapiens Yuval Noah Harari",
                  "angle": "the book on the whole strange story of us"},
    "senses":    {"kind": "book", "search": "An Immense World Ed Yong",
                  "angle": "the book on senses you didn't know existed"},
    "matter":    {"kind": "book", "search": "The Elegant Universe Brian Greene",
                  "angle": "the book on what everything is actually made of"},
    "fungi":     {"kind": "book", "search": "Entangled Life Merlin Sheldrake",
                  "angle": "the book that will make you see fungi everywhere"},
    "nature":    {"kind": "book", "search": "The Sixth Extinction Elizabeth Kolbert",
                  "angle": "the book on the wildest parts of the natural world"},
    "deep_time": {"kind": "book", "search": "Timefulness Marcia Bjornerud",
                  "angle": "the book that will wreck your sense of time"},
    # ADDED 2026-09-03: "language"/"linguistics" is a real bank domain family
    # (generate.DOMAIN_FAMILIES) with no book mapped -- caught by the affiliate
    # coverage test after "ecology"/"zoology"/"microbiology"/"marine_biology"/
    # "materials_science"/"mathematics"/"meteorology"/"neuroscience" were folded
    # into existing families above instead of needing their own entries.
    "language":  {"kind": "book", "search": "The Language Instinct Steven Pinker",
                  "angle": "the book on why language itself is stranger than you think"},
}
# Fallback for any domain not mapped above.
AFFILIATE_DEFAULT = {"kind": "book", "search": "What If Randall Munroe",
                     "angle": "the book full of answers to questions like this one"}


# ---------------------------------------------------------------------------
# Bio CTA lines — the soft nudge toward the owned list. Rotated so the channel
# never reads like a copy-paste. DELIBERATELY not the banned "save this so you
# don't forget" formula, and never begging — each one offers MORE of the thing
# the viewer already showed they want. Only some platforms get one (see
# repackage wiring); it is never stamped identically across every channel.
# ---------------------------------------------------------------------------
BIO_CTA_LINES = [
    "If this rewired something for you, I send one like it every week — {link}.",
    "One strange, true thing like this in your inbox weekly: {link}.",
    "I collect the ones that sound fake but aren't. Free, weekly — {link}.",
    "There are a hundred more of these. The best ones go out weekly — {link}.",
    "Follow {handle} for more, or get the weekly one at {link}.",
]

# Used until a real BIO_LINK exists — these promise ONLY a follow, so nothing
# can ring hollow. No inbox, no newsletter, no "link in my bio".
FOLLOW_CTA_LINES = [
    "If this rewired something for you, there are a hundred more — follow for one a day.",
    "I collect the ones that sound fake but aren't. Follow so you don't miss the next.",
    "There are a hundred more of these. Follow and you'll get one every day.",
    "Follow for more strange-but-true science, one at a time.",
]

# Pinned-comment templates — the single highest-converting free growth lever on
# short-form (a pinned comment gets outsized views and drives the profile tap).
# It asks a light engagement question AND makes the list ask, without touching
# the video itself. Rotated.
PINNED_COMMENT_LINES = [
    "Wildest part to me: {hook_frag}. If you want one of these a week, it's at {link} 👀",
    "Tell me you knew this already (I didn't). More strange-but-true weekly: {link}",
    "{hook_frag} — and that's the part most people never hear. Full list: {link}",
    "Save this for the next time someone says science is boring. Weekly drop: {link}",
]

# Follow-only pinned comments for before a bio link/list exists — engagement
# hook + a real follow ask, nothing external to over-promise.
FOLLOW_PINNED_LINES = [
    "Wildest part to me: {hook_frag}. Follow if you want more like this 👀",
    "Tell me you knew this already (I didn't). Follow for one a day.",
    "{hook_frag} — and that's the part most people never hear. Follow so you don't miss the next.",
    "Save this for the next time someone says science is boring — and follow for more 👀",
]


def _fill(t, **kw):
    return t.format(link=BIO_LINK, handle=CHANNEL_HANDLE, list_name=LIST_NAME, **kw)


def affiliate_for(domain):
    """The honest, topic-matched product angle for this video's domain."""
    a = AFFILIATE_BY_DOMAIN.get((domain or "").lower(), AFFILIATE_DEFAULT)
    return {**a, "domain": domain or "science"}


def bio_cta(seed=None):
    r = random.Random(seed)
    # Newsletter/link CTAs only once a real bio link exists; otherwise follow-only.
    return _fill(r.choice(BIO_CTA_LINES if HAS_FUNNEL else FOLLOW_CTA_LINES))


def pinned_comment(hook="", seed=None):
    r = random.Random(seed)
    # A short fragment of the video's own hook keeps the pinned comment specific
    # to THIS video, not generic. Trim to a clean clause.
    frag = (hook or "").strip().rstrip(".!?")
    if len(frag) > 90:
        frag = frag[:90].rsplit(" ", 1)[0] + "…"
    if not frag:
        frag = "this one genuinely surprised me"
    lines = PINNED_COMMENT_LINES if HAS_FUNNEL else FOLLOW_PINNED_LINES
    return _fill(r.choice(lines), hook_frag=frag)


def newsletter_blurb(title, hook, domain):
    """A ready-to-send email teaser for the owned list: restates the hook and
    points at the topic-matched affiliate product honestly. This is where the
    money actually gets made, so it's generated per video and saved for you."""
    aff = affiliate_for(domain)
    return {
        "subject": (title or "One strange, true thing").strip()[:70],
        "body": (
            f"{(hook or title).strip()}\n\n"
            f"That's today's from {LIST_NAME}. If it made you want the rest of the "
            f"story, {aff['angle']}: search “{aff['search']}”.\n\n"
            f"— more next week."
        ),
        "affiliate": aff,
        "disclosure": "Contains an affiliate link; costs you nothing, supports the channel.",
    }


def build_funnel(post):
    """Assemble the full per-render funnel bundle from out/post.json's fields.
    Pure/deterministic given the same post (seeded on video_id) so a re-run
    produces the same assets."""
    title = post.get("title", "")
    hook = post.get("hook", "") or (post.get("captions", [""]) or [""])[0] or title
    domain = post.get("domain", "") or "science"
    seed = post.get("video_id", title)
    aff = affiliate_for(domain)
    return {
        "strategy": "video -> bio link -> owned email list -> affiliate + payout + sponsorship",
        "bio_link": BIO_LINK,
        "handle": CHANNEL_HANDLE,
        "list_name": LIST_NAME,
        "bio_cta": bio_cta(seed),
        "pinned_comment": pinned_comment(hook, seed),
        "newsletter": newsletter_blurb(title, hook, domain),
        "affiliate": aff,
        "notes": "BIO_LINK/CHANNEL_HANDLE/LIST_NAME come from env; set them once. "
                 "CTAs live in captions/pinned comments/newsletter — never shouted in the video.",
    }
