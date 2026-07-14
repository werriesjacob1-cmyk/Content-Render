#!/usr/bin/env python3
"""
generate.py — the content brain.
Calls Groq to write ONE fresh science video per run. Rotates 5 viewer-jobs, builds
in completion/save/comment/search optimizations, never repeats recent topics.
Writes manifest.json for the render engine and appends to memory.json (regression record).

Env: GROQ_API_KEY
"""

import os, sys, json, re, time, urllib.request, urllib.error, random, datetime, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.environ.get("PAGE", "science")
SERIES = os.environ.get("SERIES", "").strip()        # e.g. "The Body's Hidden Systems"
SERIES_PART = os.environ.get("SERIES_PART", "").strip()  # e.g. "2"
MEMORY = os.path.join(ROOT, f"memory_{PAGE}.json")
OUT_MANIFEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "manifest.json")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# Google Gemini free tier has a FAR higher daily quota than Groq's free tier
# (~1500 requests/day vs a handful of renders), so when GEMINI_API_KEY is set we
# prefer it for generation — this is what lets many videos batch-render in a day
# without hitting the wall that keeps aborting renders on Groq. Groq stays as an
# automatic fallback. Get a free key at aistudio.google.com (no card) and add it
# as the GEMINI_API_KEY repo secret.
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
# AI Studio keys come in TWO valid shapes: the legacy "AIza..." (~39 chars) and
# the new "AQ.Ab..." auth keys that Google rolled out through 2026 (legacy
# unrestricted "AIza" keys are being rejected from June 2026, so new keys are
# AQ.* by default). Both work against generativelanguage.googleapis.com with the
# x-goog-api-key header we use. Only warn on something that matches NEITHER shape
# (e.g. a "ya29." OAuth access token pasted by mistake), since that really will
# 400. Get keys at https://aistudio.google.com/apikey .
if GEMINI_KEY and not (GEMINI_KEY.startswith("AIza") or GEMINI_KEY.startswith("AQ.")):
    print(f"  [model] WARNING: GEMINI_API_KEY starts with '{GEMINI_KEY[:3]}...', which is "
          f"neither a legacy 'AIza' key nor a new 'AQ.' auth key. If Gemini 400s, get a "
          f"fresh key at https://aistudio.google.com/apikey")
# gemini-1.5-flash was RETIRED (v1beta returns 404 "not found ... not supported
# for generateContent"), so it wasted a fallback slot on every call. Current
# free-tier flash models only.
#
# ORDER MATTERS — 2.5-flash-lite is FIRST on purpose. On the free tier its daily
# request cap (RPD) is ~1000/day vs only ~200 for 2.0-flash and ~250 for
# 2.5-flash. That 4-5x headroom is the single thing that stops us blowing the
# free daily quota after a handful of renders (which is exactly what 429'd runs
# 52/53). It's a touch less capable than 2.0-flash, but the quality gate +
# regeneration catches any weak script, and 2.0/2.5-flash remain as automatic
# higher-capability fallbacks for when lite is rate-limited or refuses.
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"]
# Path A: try strongest available model first; fall back automatically if blocked (403) or rate-limited.
# llama-3.1-70b-versatile was DECOMMISSIONED by Groq (400 "model_decommissioned"),
# so it too wasted a slot; dropped. 3.3-70b (quality) then 3.1-8b-instant (cheap).
MODEL_CHAIN = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
# THIRD free provider (backup to Gemini + Groq). Cerebras' free tier is far more
# generous than Groq's (millions of tokens/day, high RPM) and serves the same
# Llama models on an OpenAI-compatible endpoint, so it's the workhorse fallback
# when Gemini is rate-limited and Groq's tiny daily budget is spent — the exact
# double-outage that shipped degraded videos. Optional: env-gated, no key = skip.
# Free key (no card): https://cloud.cerebras.ai . Add as CEREBRAS_API_KEY.
CEREBRAS_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODELS = ["llama-3.3-70b", "llama3.1-8b"]
BANK_PATH = os.path.join(ROOT, "topic_bank.json")

# ---------------------------------------------------------------------------
# QUALITY RATCHET — pre-publish self-critique scoring (improvement loop, part 1)
# ---------------------------------------------------------------------------
# After a script is built, validated, and punched up, one more Groq call
# scores it against an explicit rubric BEFORE it ever reaches main.py's
# expensive render pipeline (TTS + footage search/judge + ffmpeg encode).
# Below QUALITY_THRESHOLD, the whole video is regenerated from scratch,
# bounded to QUALITY_MAX_REGENERATIONS extra attempts so the unattended daily
# run has a hard time/cost ceiling. If nothing clears the bar, the
# best-scoring attempt ships anyway — this gate must never be able to stop
# the daily run from producing a video.
#
# QUALITY_THRESHOLD started modest on purpose while the channel had no track
# record. RATCHET THIS UP over time (e.g. 7.0 -> 7.5 -> 8.0) once
# perf_<page>.json (see PERF_PATH below) shows higher-scoring scripts actually
# perform better in real engagement data. Raised 7.0 -> 7.5 after "You're
# Always Living in the Past" shipped at overall 7.17 despite payoff:5 and
# blatant 5x repetition of its one reveal — averaging across six criteria let
# a badly broken script hide behind a couple of high scores (rewatch:9).
QUALITY_THRESHOLD = 7.5

# PER-CRITERION FLOORS — the averaging failure above is why these exist. A
# script can have a great hook/surprise/rewatch and still be a bad video if
# it never pays off, doesn't escalate, or opens on a confusing hook — no
# average should be able to paper over that. ANY real score (not a fail-open
# None) below its floor forces a regeneration REGARDLESS of the overall
# average, even if overall clears QUALITY_THRESHOLD. This alone would have
# caught the Sun video: payoff scored 5, floor is 6.
QUALITY_CRITERION_FLOORS = {
    "hook": 6,
    "escalation": 7,
    "payoff": 6,
}
QUALITY_MAX_REGENERATIONS = 2   # extra attempts beyond the first. Keep this SMALL:
                                 # each one re-runs the full generate+validate+punch-up
                                 # pipeline (several Groq calls) inside one daily Action run.
QUALITY_RUBRIC_CRITERIA = ["hook", "surprise", "escalation", "payoff", "rewatch", "clarity"]

# ---------------------------------------------------------------------------
# PERFORMANCE MEMORY — bias future generation using REAL engagement data
# ---------------------------------------------------------------------------
# perf_<page>.json is OPTIONAL and does not exist by default. Paste one in
# yourself once you have real analytics for videos this pipeline has posted.
# Format — a flat object mapping video_id -> engagement metrics:
#
#   {
#     "science_2026-07-11_sharks-vs-trees": {
#       "views": 18400,
#       "watch_through_pct": 0.63,
#       "follows": 41,
#       "shares": 210
#     },
#     "science_2026-07-12_the-void-within": {
#       "views": 2100,
#       "watch_through_pct": 0.31,
#       "follows": 2,
#       "shares": 4
#     }
#   }
#
# Keys are the "video_id" values generate.py writes into manifest.json (and
# main.py copies into out/post.json) on every run — match them up against
# whatever your posting step or analytics dashboard tells you about that
# video. Values:
#   views                total plays
#   watch_through_pct    average fraction of the video watched, 0..1 (63% -> 0.63)
#   follows              follows attributed to this video
#   shares                share count
# Any subset of keys is fine; missing keys count as 0. A missing, empty, or
# malformed perf_<page>.json is completely safe: with no usable data,
# generation is byte-for-byte identical to today's plain random.choice()
# selection (see score_by_key()/main() below) — no regressions, ever.
PERF_PATH = os.path.join(ROOT, f"perf_{PAGE}.json")
PERF_UNSEEN_FLOOR = 0.15   # weight floor given to a fact/job with NO perf data yet,
                           # so unproven options keep getting picked instead of the
                           # pool collapsing onto whichever option happened to score first
EXPLORE_EPSILON = 0.30    # even once perf data exists, this fraction of picks ignore
                           # the weights and choose uniformly at random — explore, don't
                           # just exploit past winners forever

def load_bank():
    try:
        with open(BANK_PATH) as f:
            return json.load(f).get("facts", [])
    except Exception:
        return []
_WORKING_MODEL = None  # cached once we find one that responds

VIEWER_JOBS = [
    ("REFRAME",
     "Flip a SPECIFIC scientific fact the viewer thought they understood. Must center on a real, "
     "verifiable mechanism (how/why something actually works). The payoff rewires their mental model. "
     "End so they think 'I'll never see X the same way.' NOT vague philosophy — a concrete fact."),
    ("SOCIAL_CURRENCY",
     "Built around ONE stunning, TRUE, specific number or comparison (with the actual figure) so striking "
     "the viewer repeats it to sound smart. Must include a real measurable fact, not a feeling."),
    ("EXISTENTIAL_CHILL",
     "Take a REAL, specific scientific fact about reality/the body/time/the universe that happens to be "
     "awe-inducing, and explain the actual science of it. The chill comes from a TRUE mechanism, not from "
     "vague poetry. NO fortune-cookie lines like 'time is a river' — state the real fact and why it's true."),
    ("HOW_TO",
     "A simple, SAFE, surprising science demonstration the viewer can do with common household items, then the science of WHY it works. "
     "STRICT SAFETY: only classic, well-established, proven-safe demos. NO fire, flames, heat, ingestion, swallowing, "
     "chemicals beyond plain kitchen items, electricity, mains power, sharp blades, glass that could shatter, or anything "
     "that could injure a person, child, or pet or damage property. If unsure whether a demo is safe, DO NOT use it. "
     "Good examples: pepper + dish soap surface tension, static-electricity bending water, a teabag 'rocket' is borderline "
     "(involves flame) so AVOID it, salt lifting an ice cube, a balloon stuck by static. The save trigger ('try this') is native."),
    ("MYTH_BUSTER",
     "Take something the viewer has been told their whole life and show it's wrong, with the real science. "
     "Designed to spark comments — people will argue. Plant one line they'll want to reply to."),
]

# ---------------------------------------------------------------------------
# CTA STRATEGY — rotated, content-fit endings (save-worthiness overhaul)
# ---------------------------------------------------------------------------
# The channel used to hard-code the SAME closing command on every single video
# ("Save this so you remember it."). A command doesn't make anyone save a
# video -- saves come from the content actually being worth referencing again,
# plus (sometimes) a natural trigger. So: (1) the CONTENT gets an explicit
# reference-worthy requirement independent of how the video ends (see
# REFERENCE_WORTHY_RE / the validate() check below and the prompt rule in
# build_prompt), and (2) the ENDING is chosen per-video from four distinct
# mechanics instead of one recycled line. Exactly one style per video, picked
# here in main() (weighted by perf_<page>.json once real data exists, same
# scaffold as VIEWER_JOBS/fact selection) and threaded through build_prompt /
# punch_up / score_script so every stage of the pipeline agrees on what
# "sticking the landing" means for THIS video.
CTA_STYLES = ["SAVE_WORTHY", "LOOP", "COMMENT", "SHARE"]

CTA_ENDING_RULES = {
    "SAVE_WORTHY": (
        "ENDING STYLE FOR THIS VIDEO: RESONANT PAYOFF. End on the single most striking, "
        "mind-expanding line the script has earned -- the fact's biggest implication, or the "
        "detail that quietly reframes how the viewer will see this everyday thing from now on. "
        "State it cleanly and let it land. ABSOLUTELY NO call-to-action or instruction of ANY "
        "kind: never tell the viewer to save, screenshot, remember, look up, keep, or do anything "
        "-- phrases like 'save this', 'worth a screenshot', 'you'll want this again' are BANNED and "
        "read as hollow filler. The last line is a thought that stays with them, not a command. "
        "Best of all is a final line that recasts the hook -- so the thing they thought they "
        "understood at the start now means something bigger."
    ),
    "LOOP": (
        "ENDING STYLE FOR THIS VIDEO: LOOP FOR REWATCH. The final line must be the single most "
        "quotable line of the whole script, and it must loop back to the hook's exact opening image "
        "or phrase so the last frame flows straight back into the first -- a viewer who lets it "
        "replay shouldn't feel a seam. No explicit call-to-action language at all here (no 'save', "
        "no 'share', no 'comment') -- the loop itself is the entire mechanic."
    ),
    "COMMENT": (
        "ENDING STYLE FOR THIS VIDEO: COMMENT BAIT. The final line must pose a genuine binary "
        "question ('Team A or Team B?', 'Would you or no?') or state a claim people will actually "
        "want to argue with ('and that means everything you learned about X is wrong') -- something "
        "a real person would stop and type a reply to, not a rhetorical throwaway. Do not also tell "
        "them to save or share in this line."
    ),
    "SHARE": (
        "ENDING STYLE FOR THIS VIDEO: SHARE TRIGGER. The final line must hand the viewer a concrete, "
        "identity-specific reason to send this to one particular kind of person ('send this to the "
        "friend who still doesn't believe you', 'tag the person who needs to see this') tied "
        "DIRECTLY to the fact just taught -- not a generic 'share this video'. Do not also tell them "
        "to save or comment in this line."
    ),
}

# Rubric wording for score_script()'s "rewatch" criterion -- scored per the
# style actually assigned to this video, not a one-size-fits-all "did it ask
# for a save" question.
CTA_RUBRIC_HINTS = {
    "SAVE_WORTHY": "does the ending land on a striking, resonant final thought or implication "
                    "(ideally recasting the hook), with ZERO command/instruction language "
                    "('save', 'screenshot', 'remember', 'look up' are all disqualifying)?",
    "LOOP": "does the ending loop back cleanly to the hook/opening image so a replay feels seamless, "
            "with no bolted-on CTA language?",
    "COMMENT": "does the ending pose a real binary question or arguable claim a viewer would "
               "actually reply to?",
    "SHARE": "does the ending give a specific, identity-relevant reason to send this to one "
             "particular kind of person, tied to the fact just taught?",
}

# Ending rule handed to punch_up()'s rewrite pass -- same style-specific intent,
# phrased for a line-level rewrite instruction rather than first-draft generation.
CTA_PUNCHUP_RULES = {
    "SAVE_WORTHY": "Final line: a striking, resonant closing thought or implication that ideally "
                   "recasts the hook. NO command/instruction of any kind -- 'save', 'screenshot', "
                   "'remember', 'look up', 'keep this' are all banned. A thought, never an order.",
    "LOOP": "Final line: the most quotable line of the script, looping back to the hook's opening "
            "image/phrase. No CTA language.",
    "COMMENT": "Final line: a genuine binary question or an arguable claim -- something a real "
               "viewer would type a reply to.",
    "SHARE": "Final line: a specific, identity-relevant reason to send this to one particular kind "
             "of person, tied to the fact just taught.",
}

# Banned generic save-command phrasing -- the exact production failure this
# overhaul targets ("Save this so you remember it." on every video). Now that
# SAVE_WORTHY is a pure resonant payoff with NO nudge allowed, the guard is
# broadened to reject ANY save/screenshot-style command ending (user feedback:
# "that number's worth a screenshot" -- why? it isn't). These hollow commands
# fail validation regardless of the assigned CTA style.
GENERIC_SAVE_CMD = re.compile(
    r"\bsave (this|it|that)\b"
    r"|\bscreenshot (this|it|that|that one)\b"
    r"|\bworth a screenshot\b"
    r"|\b(take|grab|get) a screenshot\b"
    r"|\bmake sure (you|to) save\b"
    r"|\bdon'?t forget to (save|screenshot)\b"
    r"|\byou'?ll (want|need) (this|that|it) again\b",
    re.I)

# A "save-worthy" moment is engineered into the CONTENT, not just the ending:
# a concrete number, or a stated comparison/rule-of-thumb pattern. This is a
# heuristic, not a semantic check -- it exists to catch the case where a
# script has literally nothing a viewer could reference again (see
# validate()). Bank-fact videos almost always pass automatically via their
# key_terms; this exists for jobs/scripts without a bank fact behind them.
REFERENCE_WORTHY_RE = re.compile(
    r"\d"                                    # any concrete number
    r"|\bthe (size|weight|length|height|speed) of\b"
    r"|\bequivalent to\b|\bthe same (as|size)\b"
    r"|\byou could\b|\benough to\b|\bfor every\b",
    re.I)

# The specific abstraction failure the Sun video's hook shipped with: a
# "perception vs. reality" construction that only makes sense once the viewer
# already knows the twist ("You're seeing the Sun as it was, not as it is").
# As a FIRST line this reads as confusing, not curious. Deliberately narrow
# (this exact construction) rather than a general vagueness detector, which
# would be too easy to false-positive on legitimately concrete hooks.
ABSTRACT_HOOK_RE = re.compile(
    r"\bas it (was|is),?\s*not as it (is|was)\b"
    r"|\bnot as it (seems|appears)\b"
    r"|\bthings? (aren'?t|are not) what (it|they) (seem|seems|appear|appears)\b"
    r"|\breality isn'?t what it seems\b",
    re.I)


# ---------- TOPIC NOVELTY / DEDUP ----------
# Concepts we never want to repeat regardless of what memory currently holds --
# e.g. the starling-murmuration / flocking / emergence video the user flagged
# as "we have used this idea before". Matched as substrings against a
# candidate's metaphor + title (and injected into the prompt's avoid list).
BANNED_CONCEPTS = [
    "murmuration", "starling", "flock", "flocking", "swarm", "swarming",
    "emergence", "emergent", "hive mind", "school of fish", "self-organiz",
]
RECENT_DOMAIN_WINDOW = 4    # don't reuse the domain of any of the last N videos
TOPIC_SIM_THRESHOLD = 0.62  # difflib ratio between metaphors above this = dupe
TOPIC_TOKEN_OVERLAP = 0.6   # content-word overlap fraction above this = dupe


def _metaphor_too_similar(metaphor, history):
    """True if `metaphor` is a near-duplicate of any recent video's metaphor:
    substring either way, high difflib ratio, or heavy content-word overlap.
    Catches 'bird flock' vs 'starling murmuration' style repeats that an exact
    or substring-only check would miss."""
    import difflib
    c = (metaphor or "").lower().strip()
    if not c:
        return False
    c_tokens = set(re.findall(r"[a-z]{3,}", c))
    for h in history:
        hm = (h.get("metaphor", "") or "").lower().strip()
        if not hm:
            continue
        if hm in c or c in hm:
            return True
        if difflib.SequenceMatcher(None, c, hm).ratio() >= TOPIC_SIM_THRESHOLD:
            return True
        h_tokens = set(re.findall(r"[a-z]{3,}", hm))
        if c_tokens and h_tokens:
            shared = c_tokens & h_tokens
            if shared and len(shared) / min(len(c_tokens), len(h_tokens)) >= TOPIC_TOKEN_OVERLAP:
                return True
    return False


def _hits_banned_concept(*texts):
    blob = " ".join(t or "" for t in texts).lower()
    return any(b in blob for b in BANNED_CONCEPTS)


def load_memory():
    try:
        with open(MEMORY) as f:
            return json.load(f).get("history", [])
    except Exception:
        return []

def save_memory(history, entry):
    history.append(entry)
    history = history[-14:]
    with open(MEMORY, "w") as f:
        json.dump({"history": history}, f, indent=2)

# ---------------------------------------------------------------------------
# PAGE IDENTITY — the thing that turns "a page that posts science facts" (a
# commodity) into a page people FOLLOW and binge. A specific persona + lens +
# tonal range, injected into every script so the channel sounds like a someone,
# not a fact bot. Swappable per page later; this is the science page's identity.
# ---------------------------------------------------------------------------
PAGE_IDENTITY = (
    "CHANNEL IDENTITY — this is who the page IS (bake it into voice and choices, don't state it):\n"
    "You are the narrator of \"Stranger Than It Sounds\": the channel that reveals ordinary reality "
    "is far weirder, bigger, and more unsettling-beautiful than it looks. The vibe is a calm, precise, "
    "quietly eerie documentary narrator — never hype-y, never 'you won't BELIEVE', never an exclamation "
    "salesman. You state astonishing true things plainly and let the strangeness do the work. The "
    "viewer should feel a small chill of awe, like the floor of reality just shifted under them.\n"
    "WHAT MAKES THIS PAGE UNIQUE (lean into it): brutal SPECIFICITY (real names, real numbers, the "
    "actual mechanism — never vague), and finding the UNSETTLING or awe-inducing angle inside a normal "
    "thing. A viewer should think 'I will never see [ordinary thing] the same way again.'\n"
    "EMOTIONAL REGISTER for THIS video (pick the one that fits the fact and commit to it, so the page "
    "has range across videos, not one monotone): AWE (cosmic/scale), UNSETTLING (a quiet dread about "
    "something normal), BEAUTIFUL (something ordinary revealed as gorgeous), or DARKLY FUNNY (absurd "
    "but true). Whichever you pick, keep the calm precise delivery.\n"
)


def build_prompt(job_name, job_desc, avoid, fact=None, avoid_openers=None, cta_style="SAVE_WORTHY",
                 dossier=None):
    series_block = ""
    if SERIES:
        part = SERIES_PART or "1"
        series_block = (f"\n\nSERIES MODE: This is PART {part} of an ongoing series titled \"{SERIES}\". "
                        f"Open by referencing it's part {part} of the series (e.g. 'Part {part}: ...'). "
                        f"Cover ONE distinct sub-topic that fits the series theme but does NOT repeat earlier parts. "
                        f"End by teasing the NEXT part to make viewers follow so they don't miss it "
                        f"(e.g. 'Follow so you don't miss part {int(part)+1}.'). "
                        f"Put the series name + part number in the first on_screen_text and first caption.")
    fact_block = ""
    if fact:
        key_terms = fact.get("key_terms", [])
        whatif = fact.get("whatif", "")
        wow = fact.get("wow", "")
        key_terms_block = ""
        if key_terms:
            key_terms_block = (
                f"- MANDATORY KEY TERMS: the script MUST explicitly SAY at least 2 of these exact "
                f"specifics somewhere in the voiceover — the real proper noun(s) and/or the real "
                f"number(s), not a vague paraphrase: {key_terms}. A script that says 'a naturally "
                f"occurring isotope' instead of 'potassium-40' is a FAILED script. Name the thing. "
                f"State the number.\n")
        whatif_block = ""
        if whatif:
            whatif_block = (
                f"- THE CENTRAL QUESTION (curiosity gap): pose this as a genuine question EARLY "
                f"(in the hook or one of the first 3-4 scenes), in your own words, based on: "
                f"\"{whatif}\"\n"
                f"  Then ANSWER it for real as the MIDPOINT TWIST payoff (around scene 5-7) — the "
                f"actual answer with the real numbers/names, not a tease or a shrug. The viewer must "
                f"walk away knowing exactly what would really happen.\n")
        wow_block = ""
        if wow:
            wow_block = (
                f"- ESCALATION FUEL: after the midpoint payoff, use this verified supporting detail "
                f"as a further escalation rung (a 'but here's the even wilder part') instead of "
                f"inventing a new stat: \"{wow}\"\n")
        fact_block = (f"\n\n=== THE VERIFIED FACT FOR THIS VIDEO (this is TRUE — build the whole script around it) ===\n"
                      f"\"{fact['fact']}\"\n"
                      f"Angle: {fact['angle']}.\n"
                      f"ABSOLUTE RULES FOR ACCURACY:\n"
                      f"- Stay entirely on THIS topic — but tell its FULL, rich story (draw on the RESEARCH "
                      f"section below): don't drift to unrelated topics, don't stay shallow.\n"
                      f"- Do NOT FABRICATE. Every number/name must come from the verified fact, key terms, "
                      f"wow detail above, OR the RESEARCH section below. If unsure of a number, describe the "
                      f"mechanism instead of inventing one.\n"
                      f"- Never state two different numbers for the same thing. Accuracy over drama.\n"
                      f"{key_terms_block}{whatif_block}{wow_block}"
                      f"- Include at least ONE absurd-but-precise felt comparison that turns a number "
                      f"into something physically picturable (e.g. not '400 million years' alone but "
                      f"'before Saturn even had rings', or 'you could watch human civilization rise and "
                      f"fall 80,000 times over'). Keep it precise — no vague hand-waving.\n"
                      f"- For the footage search_query fields, prefer these proven matches: "
                      f"{[q for q in fact.get('queries', []) if not UNSTOCKABLE_Q.search(q)]}.\n")
    dossier_block = ""
    if dossier:
        bullets = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(dossier))
        dossier_block = (
            f"\n\n=== RESEARCH: {len(dossier)} DISTINCT TRUE FACETS OF THIS TOPIC (this is your raw material) ===\n"
            f"{bullets}\n"
            f"HOW TO USE THIS RESEARCH (this is the difference between an interesting video and a boring one):\n"
            f"- Each scene must be built on a DIFFERENT item above. Walk the viewer through the topic like a "
            f"curious scientist revealing one new surprise at a time — never restate a point already made.\n"
            f"- The hook, the midpoint twist, and the final payoff must each use a DIFFERENT facet. If two "
            f"scenes would make the same point, DELETE one and pull a fresh facet from the list.\n"
            f"- Pick the 6-8 MOST surprising, most 'wait-WHAT' facets and order them so each raises a new "
            f"question the next one answers (curiosity chain). Skip the boring/obvious ones.\n"
            f"- Keep the specific detail (the number, the name, the mechanism) in the spoken line — that "
            f"specificity is what makes it feel like real knowledge, not filler.")
    opener_block = ""
    if avoid_openers:
        opener_block = (
            f"\n\nHOOK VARIETY: your last several videos' hooks all opened the same way "
            f"({avoid_openers}). Start THIS hook with a different sentence structure or "
            f"opening word — not just a synonym swap of the same structure.")
    return f"""You write scripts for "Stranger Than It Sounds", a faceless science page built to make people FOLLOW and binge — not just watch one video.

{PAGE_IDENTITY}{fact_block}{dossier_block}

THIS VIDEO'S JOB: {job_name}. {job_desc}

ADDICTIVE CRAFT (what separates a bingeable page from the 10,000 identical AI fact pages):
- STRUCTURE IT AS A TINY MYSTERY, not a list: open a real question the brain CANNOT ignore, build
  tension, then reveal. Each scene should make the viewer need the next one. A list of facts is
  boring even when every fact is true; a reveal with tension is not.
- QUESTION HOOK the mind auto-answers: the strongest hooks are a concrete question the viewer starts
  answering in their head ("How much of you isn't technically human?", "What's the oldest thing you'll
  touch today?") — or a flat claim so specific it demands the 'how is that possible?' The brain can't
  scroll past an open loop.
- LEAVE THE PAGE, NOT JUST THE VIDEO, OPEN: the final line should quietly imply there is a whole world
  of this strangeness (this is one of many) — a resonant thought that makes them want the NEXT one.
  NOT a command ('follow me', 'save this') — the pull comes from the feeling that reality is full of
  these and this page finds them.
- SPECIFICITY IS THE BRAND: wherever a competitor would be vague, name the exact thing. The proof is
  the point.

PROVEN RULES (every one is backed by 2026 TikTok performance data — follow them all):

HOOK (first 2 seconds decide 70% of retention):
- First spoken line = 8-14 words. A contrarian claim or direct call-out that opens a curiosity gap. NOT a description.
- Address the viewer directly ("you"/"your"). Self-relevant beats abstract.
- CONCRETE, NOT ABSTRACT (critical): the hook must be something a viewer instantly PICTURES, self-
  contained with no setup needed — not a mood, not a musing about perception vs. reality, not a
  sentence that only makes sense once you already know the twist.
  GOOD: "Your body is mostly empty space." (a concrete, physical, immediately graspable claim)
  GOOD: "Sharks are older than trees." (a specific, checkable, instantly pictured comparison)
  BAD: "You're seeing the Sun as it was, not as it is." (abstract — the viewer can't picture
  anything from this alone; it only lands after the explanation, so it reads as confusing, not
  intriguing, as the FIRST line of the video)
  BAD: "Reality isn't what it seems." (vague fortune-cookie phrasing, not a real claim)
  If your hook needs the rest of the script to make sense, rewrite it — name the concrete thing
  (a body part, an animal, an object, a number) up front.

STORY ENGINE (the #1 ranking signal is completion — earn every second):
- 8-10 SHORT scenes. Each scene's voiceover is ONE punchy sentence (fast pacing = +34% retention).
- Total narration MUST be 90-120 words (~30-40 seconds spoken). Write the FULL script. Too short = rejected.
  A tight 30-40s video beats a padded 60s one: competitors win on completion, so cut every non-essential line.
- PER-SCENE LENGTH: 6-16 words is the sweet spot. NEVER exceed 22 words in a single scene — a long
  run-on scene wedged between short punchy ones is jarring and reads as choppy, not varied. Vary
  scene length a little for rhythm, but no scene should be dramatically longer than its neighbors.
- BREATHING ROOM: this is spoken narration, not a wall of text — each scene is its own sentence with
  a natural beat before the next one starts. The video should feel PACED, not like it never stops
  talking. If you can't say a scene's line out loud in one comfortable breath, it's too long or too
  packed with clauses — split the idea or cut it.
- ESCALATION LADDER (critical, ZERO exceptions): the core reveal — the specific number or comparison
  from the verified fact — may appear in EXACTLY ONE scene, ONE time, as the payoff moment. This is
  a hard rule, not a suggestion: if you catch yourself writing that same number, comparison, or its
  paraphrase in a second scene, DELETE that scene's line entirely and write a genuinely different
  fact or angle instead. Every other scene must teach something the payoff scene did NOT — the setup
  question, the mechanism/why it's true, a second independent consequence, what it means for YOU —
  never a rephrasing of the reveal in new words. A script that circles back to the same reveal even
  twice is an automatic FAIL: each scene is a NEW fact about the topic, not an echo of the last one:
  what -> how -> why it's stranger than it sounds -> what it means for YOU.
- MIDPOINT TWIST: around scene 5-7, plant a pattern interrupt that reopens curiosity, e.g.
  "But that's not even the strange part." / "And here's where it stops making sense." CRITICAL:
  the line right AFTER the interrupt must deliver a GENUINELY NEW fact the viewer has not heard
  yet in this video — a second, escalated surprise. It must NOT restate, rephrase, or circle back
  to the hook or anything already said (the #1 failure: "that's not even the strange part" followed
  by a reworded version of the opening — that makes the promise land on nothing and feels
  repetitive). If you don't have a real second surprise to reveal, do NOT use the interrupt at all.
  Pay it off ONCE and never return to it.
- MAKE IT FELT, not just stated: convert numbers into physical comparisons a viewer can picture
  (not "400 million years" alone — "before Saturn had rings", "you could watch every human
  civilization rise and fall 80,000 times"). One vivid comparison beats three adjectives.
- The ending must LAND on this video's assigned ending style (see ENDING section below). Do NOT
  trail off, restate the premise, or stack two different endings together.

SEARCH DISCOVERY (now as important as hashtags):
- Pick ONE core keyword phrase (what someone would type to find this).
- Put it in the hook, in at least 2 on_screen_text labels, and in the first caption.

SHARES (THE #1 weighted signal — 10x a like). Engineer the video to be SENT to a friend:
- The fact must be "send-worthy": so surprising or identity-relevant the viewer thinks "I have to show ___ this."
- Somewhere in the script (not necessarily the ending), include a beat that hands the viewer a
  reason to share it with someone specific.

SAVES (5x a like) — THIS COMES FROM THE CONTENT, NOT A COMMAND:
- Telling someone to save a video does not make them save it. A save happens because the video
  contains something genuinely worth referencing again. So: somewhere in the script, land at least
  ONE concrete "screenshot-this" moment — a specific number, a counterintuitive rule of thumb, or a
  vivid comparison the viewer would actually want to remember or reuse later (prove someone wrong
  with it, cite it, look it up again). This is mandatory REGARDLESS of this video's ending style
  below. Do not just assert the fact is surprising — make the actual detail specific enough that a
  person could repeat it verbatim.

{CTA_ENDING_RULES.get(cta_style, CTA_ENDING_RULES["SAVE_WORTHY"])}

COMMENTS (binary questions outperform — easiest to answer, drive depth):
- Independent of the ending style above, plant ONE line somewhere in the script that provokes a
  reply: either a BINARY question ("Team A or Team B?", "Did you know this — yes or no?") OR a claim
  people will argue with ("no way", "that's not true"). (If this video's ending style is COMMENT,
  the ending line itself can serve as this beat — don't force a second one.)
- Put a binary/question version in the FIRST caption too (comments often come from the caption).

CONTENT (CRITICAL):
- The video MUST teach ONE concrete, TRUE, verifiable science fact or mechanism — a real number, a real process, a real cause.
- The fact must be GENUINELY SURPRISING — something most adults do NOT know. Aim for "wait, WHAT?" not "yeah I knew that."
- BANNED TOPICS (too obvious/overdone): static electricity, the water cycle, why the sky is blue, photosynthesis basics, "we only use 10% of our brain", basic volcano/rainbow facts.
- BANNED STYLE: vague philosophy, mysticism, fortune-cookie lines, metaphors-as-substance, motivational fluff.
- Prefer the strange and specific: deep-sea biology, quantum weirdness made real, the body's hidden systems, cosmic scale, time dilation, animal superpowers, numbers that sound fake but are true.
- If a 12-year-old couldn't learn a NEW fact from it, it's wrong. Substance + surprise over mood.
- Visually deliverable with real stock footage (nature, space, ocean, animals, cities, body, weather, hands, household).
- No "imagine", no "did you know", no filler.

AVOID these recent topics entirely: {avoid}{series_block}{opener_block}

FOOTAGE QUERIES (the #1 visual-quality lever — a wrong clip breaks trust instantly):
- Each scene needs a 2-5 word stock-footage search query describing something a videographer
  ACTUALLY FILMS: a concrete subject + action or setting (animals, nature, weather, oceans, space,
  cities, machines, food, hands doing things, people reacting).
- BANNED query words: anatomy, anatomical, organ, cell/cells, microscope, microscopic, diagram,
  xray, x-ray, molecular, atom, quantum, abstract, concept, system. Free stock libraries have
  almost nothing real for these — searches degrade into random flesh/lab/texture close-ups.
- If the concept is invisible (acid, time, gravity, DNA, speed of nerves), pick a VISUAL METAPHOR
  a library does have: "bubbling green liquid" for acid, "hourglass sand falling" for time,
  "lightning storm slow motion" for nerve signals, "dominoes falling chain" for reactions.
- Every scene's query must be VISUALLY DISTINCT from every other scene's (different subject or
  setting) — a video that shows the same three shots on loop reads as spam.

For each scene give: one-sentence voiceover, a 2-4 word on_screen_text label (punchy, include the keyword where natural),
and the search query as specified above.

Return ONLY valid JSON, no markdown, exactly:
{{
  "title": "...",
  "viewer_job": "{job_name}",
  "keyword": "the core search phrase",
  "metaphor": "3-5 word topic tag",
  "hook": "first spoken line, 8-14 words",
  "script": "full narration as one string",
  "scenes": [
    {{"id": 1, "duration": 4, "voiceover": "one sentence", "on_screen_text": "2-4 words", "search_query": "2-5 words", "motion": "zoom_in"}}
  ],
  "captions": ["caption with keyword + a question (drives comments)", "caption 2", "caption 3"],
  "hashtags": ["#science", "#space", "#facts"],  // 4-6 REAL one-word tags people search. No underscores, no sentences, no made-up phrases.
  "render": {{"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"}}
}}"""

def _call_openai_compat(url, key, model, prompt):
    """One call to any OpenAI-compatible chat endpoint (Groq, Cerebras, ...).
    Both serve Llama models with the same request/response shape, so the only
    per-provider difference is the base URL and bearer key."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"}
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "content-render/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


def _call_model(model, prompt):
    return _call_openai_compat("https://api.groq.com/openai/v1/chat/completions",
                               GROQ_KEY, model, prompt)


def _call_cerebras(model, prompt):
    return _call_openai_compat("https://api.cerebras.ai/v1/chat/completions",
                               CEREBRAS_KEY, model, prompt)

def _extract_json(text):
    """Return the bare JSON object from a model reply. Gemini (without forced
    JSON mode) may wrap the JSON in ```json fences or add a line of prose; the
    callers json.loads() the result, so strip fences and, if needed, slice from
    the first '{' to the last '}'."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j != -1 and j > i:
            t = t[i:j + 1]
    return t


GEMINI_RPM_MAX_WAIT = 20   # seconds; a 429 asking to wait longer than this is a
                           # DAILY-quota exhaustion, not a per-minute burst —
                           # don't stall the render, fall through to the next model.


def _gemini_retry_delay(err):
    """Pull the retryDelay Gemini attaches to a 429 (e.g. '"retryDelay": "6s"').
    Returns the seconds as a float, or None if absent/unparseable. A small delay
    means we merely hit the free-tier per-minute (RPM) cap and a short sleep lets
    the very next call succeed; a large one means the daily quota is gone."""
    try:
        body = err.read().decode("utf-8", "replace")
        m = re.search(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)s"?', body)
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def _call_gemini(model, prompt):
    """Google Gemini generateContent. Same contract as _call_model: returns the
    model's text (a JSON string). Raises HTTPError on failure so the provider
    chain can fall through. NOTE: no responseMimeType — an earlier version set
    responseMimeType='application/json' and Gemini returned HTTP 400 on every
    call; a plain generateContent works on every model, and _extract_json handles
    any markdown fences the reply might carry.

    RPM SELF-HEAL: one render fires ~25-40 LLM calls in a burst, which trips the
    free tier's per-minute cap (~15 RPM) even with a full daily quota. On a 429
    whose retryDelay is short, sleep it out and retry the SAME model ONCE — that
    turns a fall-through-to-Groq into a Gemini success and keeps generation on the
    high-quota provider. A long retryDelay (daily quota gone) is re-raised so the
    chain falls through immediately instead of stalling."""
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": GEMINI_KEY,
                 "User-Agent": "content-render/1.0"})
    for _attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
            return _extract_json(data["candidates"][0]["content"]["parts"][0]["text"])
        except urllib.error.HTTPError as e:
            if e.code == 429 and _attempt == 0:
                delay = _gemini_retry_delay(e)
                if delay is not None and 0 < delay <= GEMINI_RPM_MAX_WAIT:
                    print(f"  [model] gemini:{model} hit RPM cap — waiting {delay:.0f}s and retrying once")
                    time.sleep(delay + 0.5)
                    continue
            raise


_CONSEC_EXHAUSTIONS = 0   # times the WHOLE provider chain 429'd back-to-back
_CIRCUIT_OPEN = False     # once open, calls fail fast instead of hammering dead quota


def call_groq(prompt):
    """Call the LLM for a JSON response. Prefers Gemini (much higher free quota)
    when GEMINI_API_KEY is set, then falls back to Groq automatically. Name kept
    as call_groq so every existing call site is unchanged.

    CIRCUIT BREAKER: if every provider rate-limits 3 calls in a row, the circuit
    opens and further calls fail instantly for the rest of this run. Without it,
    an exhausted-quota render burned ~4 minutes retrying doomed calls (5 attempts
    x escalating sleeps x every pipeline stage) AND wasted whatever little quota
    remained. Fail-fast = the render aborts in seconds and stops hammering the
    limit. When the LLM is healthy the circuit never opens (behaviour identical)."""
    global _WORKING_MODEL, _CONSEC_EXHAUSTIONS, _CIRCUIT_OPEN
    if _CIRCUIT_OPEN:
        raise RuntimeError("LLM circuit open — provider(s) rate-limited this run; failing fast")
    # Order = free-quota headroom: Gemini (2.5-flash-lite ~1000 RPD) → Cerebras
    # (very generous free tier) → Groq (tiny daily budget, last resort).
    chain = ([("gemini", m) for m in GEMINI_MODELS] if GEMINI_KEY else []) + \
            ([("cerebras", m) for m in CEREBRAS_MODELS] if CEREBRAS_KEY else []) + \
            ([("groq", m) for m in MODEL_CHAIN] if GROQ_KEY else [])
    # try the cached working provider first (also re-walks the chain if it now
    # fails, fixing the old bug where a cached model that started 429ing raised
    # without ever falling back to the other provider).
    if _WORKING_MODEL and _WORKING_MODEL in chain:
        chain = [_WORKING_MODEL] + [c for c in chain if c != _WORKING_MODEL]
    last_err = None
    for prov, model in chain:
        try:
            if prov == "gemini":
                out = _call_gemini(model, prompt)
            elif prov == "cerebras":
                out = _call_cerebras(model, prompt)
            else:
                out = _call_model(model, prompt)
            if _WORKING_MODEL != (prov, model):
                print(f"  [model] using {prov}:{model}")
            _WORKING_MODEL = (prov, model)
            _CONSEC_EXHAUSTIONS = 0   # a success closes/keeps-closed the circuit
            return out
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404, 429):
                # 400 = bad request for THIS model/provider (commonly an invalid
                # or wrong-type API key, e.g. an OAuth token pasted where a
                # Gemini AIza key belongs, or a param a given model rejects);
                # 403/404 = unavailable; 429 = rate-limited. All are
                # model/provider-specific, so fall through to the next entry
                # instead of aborting the whole run. If EVERY provider fails the
                # chain still ends by raising last_err below. Log the server's
                # error body (truncated) — without it a silently-failing Gemini
                # looks identical to a healthy one that just chose Groq, which is
                # exactly how a bad key hid for a whole run.
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
                print(f"  [model] {prov}:{model} failed HTTP {e.code} — falling through"
                      + (f" :: {detail}" if detail else ""))
                last_err = e; continue
            raise   # 5xx etc — let the outer retry loop handle it
        except Exception as e:  # noqa: BLE001 - network/parse hiccup, try next provider
            # e.g. Gemini returned 200 but the reply was truncated/safety-blocked
            # so ["candidates"][0]... KeyError'd. Log it so this failure mode is
            # visible instead of silently dropping to the next provider.
            print(f"  [model] {prov}:{model} failed ({type(e).__name__}: {str(e)[:160]}) — falling through")
            last_err = e; continue
    # every provider failed this call
    _CONSEC_EXHAUSTIONS += 1
    if _CONSEC_EXHAUSTIONS >= 3 and not _CIRCUIT_OPEN:
        _CIRCUIT_OPEN = True
        print("  [model] circuit OPEN — all LLM providers rate-limited 3x in a row; "
              "failing fast for the rest of this run (add GEMINI_API_KEY for a much larger free quota)")
    raise last_err if last_err else RuntimeError("no LLM provider available")

# basic safety net for HOW_TO output
UNSAFE = re.compile(r"\b(fire|flame|burn|burning|lit|light a|matches?|lighter|candle|stove|boil|boiling|"
                    r"microwave|oven|heat|hot water|electric|outlet|socket|battery acid|bleach|ammonia|"
                    r"swallow|drink|eat|ingest|knife|blade|razor|shatter|explode|explosion)\b", re.I)

# terms free stock libraries can't actually satisfy — searches for them degrade
# into random flesh/lab/texture close-ups (see the belly-button incident)
UNSTOCKABLE_Q = re.compile(r"\b(anatom\w*|organ|cells?|microscop\w*|diagram|x-?ray|molecul\w*|"
                           r"atoms?|quantum|abstract|concept\w*|system)\b", re.I)

# visually-rich neutral B-roll for query dedup / repair — always available on stock sites
VARIETY_QUERIES = ["ocean waves aerial", "night sky timelapse", "city street timelapse",
                   "lightning storm clouds", "forest sunlight drone", "hourglass sand falling",
                   "hands typing closeup", "waterfall slow motion", "desert dunes aerial",
                   "northern lights sky", "rain window closeup", "eagle flying mountains"]


def punch_up(m, fact, cta_style="SAVE_WORTHY"):
    """Second-pass rewrite of the voiceovers only. Structure rules in the main
    prompt get a script that follows the letter of the format but still writes
    flat lines (e.g. following the midpoint twist with 'the difference is
    almost negligible' — an anti-climax — or stacking two different endings).
    A focused critique-and-rewrite pass fixes delivery; validate() re-guards
    the result and we keep the original whenever the rewrite doesn't survive
    it. cta_style pins the final-line rule to the ending style chosen for
    this video (see CTA_PUNCHUP_RULES) instead of a fixed save-command."""
    fact_line = fact["fact"] if fact else "the fact stated in the script"
    key_terms = fact.get("key_terms", []) if fact else []
    key_terms_rule = ""
    if key_terms:
        key_terms_rule = (
            f"- MUST preserve every one of these exact terms verbatim, spelled exactly as given, "
            f"somewhere across the rewritten lines: {key_terms}. Do not paraphrase them away or "
            f"swap a real name/number for a vaguer description — if the original said "
            f"'potassium-40', the rewrite must still say 'potassium-40', not 'a radioactive isotope'.\n")
    ending_rule = CTA_PUNCHUP_RULES.get(cta_style, CTA_PUNCHUP_RULES["SAVE_WORTHY"])
    scenes_json = json.dumps([{"id": s["id"], "voiceover": s["voiceover"]} for s in m["scenes"]])
    prompt = f"""You are a short-form script doctor. Rewrite ONLY the voiceover lines below for maximum retention.

THE VERIFIED FACT (do not alter it, do not add new numbers): "{fact_line}"

RULES:
- Same number of scenes, same ids, same order, same underlying meaning per scene.
- Each line stays ONE punchy spoken sentence, 6-18 words, natural to read aloud.
- ESCALATE: every line must feel like a step deeper than the last. No line may deflate
  ("it's tiny", "almost negligible", "basically nothing") right after a tension-raiser.
  If a smallness caveat is needed, fuse it INTO an impressive frame ("so small only an
  atomic clock can see it — but it never stops").
- The line right after any "that's not the strange part"-style interrupt must deliver the
  single most surprising concrete detail of the whole script.
- {ending_rule}
- Only the FINAL line may carry any ending/CTA language at all — every other line stays pure
  content, no stray "save"/"share"/"comment" language anywhere else.
- Keep any real numbers exactly as they are. Add NO new facts or numbers.
{key_terms_rule}- Every line ends with proper punctuation (. ? or !) — these are spoken sentences,
  and the TTS engine uses end punctuation to pace pauses between scenes.

Scenes: {scenes_json}

Return ONLY valid JSON, exactly: {{"scenes": [{{"id": 1, "voiceover": "..."}}]}}"""
    try:
        raw = call_groq(prompt)
        new_scenes = {}
        for s in json.loads(raw)["scenes"]:
            if not s.get("voiceover"):
                continue
            line = _clean(s["voiceover"])
            if line and line[-1] not in ".?!":  # model drops terminal punctuation
                line += "."                     # under real-world load; don't rely on the prompt alone
            new_scenes[s["id"]] = line
    except Exception as e:  # noqa: BLE001 - punch-up is best-effort
        print(f"  punch-up failed ({e}), keeping original")
        return m
    if set(new_scenes) != {s["id"] for s in m["scenes"]}:
        print("  punch-up returned mismatched scenes, keeping original")
        return m
    import copy
    trial = copy.deepcopy(m)
    for s in trial["scenes"]:
        s["voiceover"] = new_scenes[s["id"]]
    trial["script"] = " ".join(s["voiceover"] for s in trial["scenes"])
    if key_terms:
        orig_text = " ".join(s["voiceover"] for s in m["scenes"])
        new_text = " ".join(s["voiceover"] for s in trial["scenes"])
        dropped = [kt for kt in key_terms
                   if _key_term_present(kt, orig_text) and not _key_term_present(kt, new_text)]
        if dropped:
            print(f"  punch-up dropped key term(s) {dropped}, keeping original")
            return m
    err = validate(trial, m.get("viewer_job", ""), fact=fact)
    if err:
        print(f"  punch-up rejected by validation ({err}), keeping original")
        return m
    print("  punch-up applied")
    return trial

def _clean(t):
    # strip code fences / markdown / stray quotes the model sometimes adds
    t = str(t).strip().strip("`").strip()
    return re.sub(r"\s+", " ", t)

def _key_term_present(term, text):
    """Is a dossier key_term actually named in text? Case-insensitive substring
    match for proper nouns/phrases ("potassium-40", "Mariana Trench"). For terms
    that lead with a number ("0.1 microsieverts", "5,000 times a second") also
    match on the bare digit sequence, comma-insensitive, so rounding/formatting
    differences ("5000" vs "5,000" vs "roughly 5000") don't cause a false
    negative — the actual proper-noun substring match stays the primary path so
    a stray shared number elsewhere in the script can't cause a false positive."""
    term = term.strip()
    if not term:
        return False
    if term.lower() in text.lower():
        return True
    if term[0].isdigit():
        digits = re.findall(r"\d[\d,\.]*", term)
        norm_text = text.replace(",", "")
        for d in digits:
            d_norm = d.rstrip(".").replace(",", "")
            if d_norm and d_norm in norm_text:
                return True
    return False

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1000, "million": 1000000, "billion": 1000000000,
}


def _salient_number_phrases(text):
    """Find 'number + unit' phrases (e.g. 'eight minutes', '8 minutes',
    'eight-minute delay') and normalize them so a word-number and a digit,
    or a hyphenated adjective form and a plain phrase, all collapse to the
    SAME token ('8 minute'). This is what catches "the same reveal re-said
    in different words" — the Sun video said "eight minutes ago", "an
    eight-minute delay", and "eight minutes and twenty seconds" across four
    different scenes; three different sentences, the same core number every
    time. Restricted to number+unit pairs (not bare digits) so two scenes
    that legitimately cite two DIFFERENT numbers (100 miles vs. 15 seconds)
    never collide."""
    def numval(tok):
        if tok.isdigit():
            return int(tok)
        return _NUM_WORDS.get(tok)

    tokens = re.findall(r"[a-z]+(?:-[a-z]+)*|\d[\d,\.]*", text.lower())
    phrases = set()
    for i, tok in enumerate(tokens):
        if "-" in tok:
            parts = tok.split("-")
            v = numval(parts[0])
            if v is not None and len(parts) > 1 and parts[1].isalpha() and len(parts[1]) > 2:
                phrases.add(f"{v} {parts[1].rstrip('s')}")
            continue
        v = numval(tok)
        if v is not None and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt.isalpha() and len(nxt) > 2 and "-" not in nxt:
                phrases.add(f"{v} {nxt.rstrip('s')}")
    return phrases


def _salient_proper_nouns(text):
    """Multi-word capitalized phrases only ("Mariana Trench", "Turritopsis
    Dohrnii") — deliberately excludes single capitalized words so a video's
    own recurring subject noun ("Sun", "Earth") legitimately appearing in
    most scenes never trips this check; only a specific multi-word proper
    noun repeated as the crux of several scenes counts."""
    return {m.group(0).lower()
            for m in re.finditer(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+\b", text)}


def check_information_gain(m):
    """One extra Groq call, run only after structural validate() has already
    passed: hand the model the numbered voiceover list and ask which scenes (if
    any) add NO new information beyond an earlier scene. This catches semantic
    redundancy — the same idea said in different words — that the structural
    pairwise-similarity and fact-restatement checks in validate() can miss
    because they only compare surface phrasing.

    MUST fail-open: this is a nice-to-have quality gate, not a correctness gate,
    and it must never be able to brick generation. Any network error, timeout,
    malformed JSON, or unexpected shape from the model is treated as a pass.
    """
    try:
        scenes = m.get("scenes", [])
        if len(scenes) < 2:
            return None
        numbered = "\n".join(f"{s['id']}. {s['voiceover']}" for s in scenes)
        prompt = (
            "Here is the numbered voiceover script of a short video, in scene order:\n\n"
            f"{numbered}\n\n"
            "A scene 'adds no new information' only if everything it says was already "
            "conveyed — even in different words — by an EARLIER scene in this list. Scene "
            "1 never counts (there is no earlier scene). A scene that reveals a new number, "
            "a new mechanism, a new consequence, or a new comparison is NOT redundant even "
            "if it's on the same topic.\n\n"
            'Return ONLY valid JSON, exactly: {"no_new_info_scene_ids": [2, 5]} '
            "-- an empty array if every scene adds something new. No explanation, JSON only."
        )
        raw = call_groq(prompt)
        data = json.loads(raw)
        ids = data.get("no_new_info_scene_ids", [])
        if not isinstance(ids, list):
            return None
        # Robust coercion: accept ints and numeric strings ("2") alike so a
        # model that answers under JSON mode but still writes id numbers as
        # strings doesn't silently make this whole check inert (the exact
        # class of bug fixed in score_script's _coerce_score — see the
        # comment there). Bools are rejected explicitly since JSON true/false
        # would otherwise smuggle in as 1/0 under a bare isinstance(int) check.
        clean_ids = []
        for i in ids:
            if isinstance(i, bool):
                continue
            if isinstance(i, int):
                clean_ids.append(i)
            elif isinstance(i, str) and i.strip().lstrip("-").isdigit():
                clean_ids.append(int(i.strip()))
        ids = clean_ids
        # HARDER GATE: was ">= 2" (two or more redundant scenes needed to
        # reject). One redundant scene is already a scene that earns its
        # runtime for free — reject on the first one flagged, same as any
        # other structural validation failure.
        if len(ids) >= 1:
            print(f"  [info-gain] flagged {len(ids)} redundant scene(s) {ids} "
                  f"— no new information beyond an earlier scene")
            return (f"information-gain check flagged {len(ids)} redundant scene(s) {ids} "
                    f"(no new information beyond an earlier scene) — cut or replace them")
        return None
    except Exception as e:  # noqa: BLE001 - must fail open, never blocks a run
        print(f"  info-gain check failed open ({e}), passing")
        return None

def validate(m, job_name, fact=None):
    for k in ["title", "hook", "script", "scenes", "captions", "hashtags"]:
        if k not in m:
            return f"missing {k}"
    # Scene-count ceiling tightened 14 -> 11 -> 10 (target is 8-10, see
    # build_prompt): the Sun video ran 12 scenes at 166 words and read as
    # "does not stop talking" -- fewer, better-paced scenes beat cramming in
    # more reveals, and a tight ~30-40s video wins on completion.
    if not isinstance(m["scenes"], list) or not (6 <= len(m["scenes"]) <= 10):
        return f"scene count {len(m.get('scenes', []))} out of range"

    # clean top-level text
    m["title"] = _clean(m["title"])[:90]
    m["hook"] = _clean(m["hook"])
    if not (4 <= len(m["hook"].split()) <= 16):
        return f"hook length {len(m['hook'].split())} words out of range"
    # Concrete-hook guard: catches the exact abstraction failure the Sun video
    # shipped with ("You're seeing the Sun as it was, not as it is" -- reads
    # as confusing, not intriguing, as a viewer's very first line because it
    # only makes sense once you already know the twist). Narrow phrase match
    # by design -- it targets this specific "as it was/is, not as it is/was"
    # perception-vs-reality construction, not hooks in general, so it can't
    # false-positive on a normal concrete hook.
    if ABSTRACT_HOOK_RE.search(m["hook"]):
        return (f"hook '{m['hook']}' is too abstract/vague — a viewer can't picture anything "
                f"concrete from it alone; open with a self-contained, concrete image or claim "
                f"instead (see the good/bad hook examples in the prompt)")

    # scenes: clean and validate
    for i, s in enumerate(m["scenes"], 1):
        for k in ("voiceover", "on_screen_text", "search_query"):
            if not s.get(k):
                return f"scene {i} missing {k}"
            s[k] = _clean(s[k])
        s["on_screen_text"] = " ".join(s["on_screen_text"].split()[:4])  # cap label to 4 words
        # Hard per-scene cap tightened 28 -> 22 words. The Sun video's scene
        # 11 ran 34 words -- a run-on jammed between 6-9 word scenes is
        # exactly the "choppy / doesn't stop talking" complaint: one scene
        # breathless while its neighbors are punchy reads as uneven, not
        # varied. Prompt targets 6-16 words/scene; 22 is the hard ceiling.
        if len(s["voiceover"].split()) > 22:
            return f"scene {i} voiceover too long ({len(s['voiceover'].split())} words, cap is 22)"
        # stock libraries return junk (flesh closeups, random labs) for these:
        # the belly-button-as-stomach incident came from 'human stomach anatomy'
        if UNSTOCKABLE_Q.search(s["search_query"]):
            return f"scene {i} query '{s['search_query']}' uses un-filmable terms"
        # NOTE: a duplicate search_query used to get force-swapped to an
        # unrelated VARIETY_QUERIES term here. That's how a scene whose
        # voiceover was "humanity fits in a sugar cube" ended up querying
        # "ocean waves aerial" -- pure noise, zero relevance, and the judge
        # in main.py could only rate what it was given. It also solved a
        # problem main.py already handles: fetch_clip's candidate sources
        # exclude every previously-used clip id (_used_video_ids), so two
        # scenes sharing a query get different clips automatically. No
        # swap needed -- leave the query tied to its own scene's content.
        # numeric, sane duration
        try:
            s["duration"] = max(2, min(8, int(float(s.get("duration", 4)))))
        except Exception:
            s["duration"] = 4
        if s.get("motion") not in ("zoom_in", "zoom_out", "pan", "static"):
            s["motion"] = random.choice(["zoom_in", "zoom_out", "pan", "static"])

    # script length sanity: target is 90-120 words (~30-40s spoken, see
    # build_prompt); hard ceiling tightened 240 -> 150 -> 135 -- the Sun video
    # ran 166 words and read as relentless / "does not stop talking", and a
    # tight 30-40s video beats a padded 60s one on completion. Floor kept at
    # 70 so a legitimately tight script isn't penalized for being efficient.
    wc = len(_clean(m["script"]).split())
    if not (70 <= wc <= 135):
        return f"script word count {wc} out of range (target 90-120, hard cap 135)"
    m["script"] = _clean(m["script"])

    # CTA overhaul guard 1: the exact production failure this whole rework
    # targets was every video ending on the same hard-coded command ("Save
    # this so you remember it."). Reject any script that still contains that
    # command or a close paraphrase of it, regardless of which CTA style was
    # assigned — a command is not a substitute for save-worthy content and is
    # banned outright now, not just discouraged.
    full_blob = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
    if GENERIC_SAVE_CMD.search(full_blob):
        return ("script contains the banned generic save-command phrasing "
                "('save this so you...') — the ending must earn a save through "
                "content, not a command; see this video's assigned CTA style")

    # CTA overhaul guard 2: save-worthiness must be engineered into the
    # CONTENT, not just claimed by the ending. Require at least one concrete,
    # specific, reference-worthy detail somewhere in the script (a real
    # number, or a stated comparison/rule-of-thumb) — the kind of thing a
    # viewer could actually repeat or look up again. Bank-fact videos already
    # clear this via mandatory key_terms; this catches jobs/scripts with no
    # bank fact behind them (e.g. HOW_TO, or a MYTH_BUSTER with no fact_id).
    if not REFERENCE_WORTHY_RE.search(full_blob):
        return ("no reference-worthy / 'screenshot-this' detail found anywhere in the "
                "script — include a specific number, rule of thumb, or vivid comparison "
                "a viewer would actually want to remember or reuse")

    # Path B: numeric-contradiction guard — catch fabricated/contradictory numbers (e.g. "7 colors" then "16.5 colors")
    full = (m["script"] + " " + " ".join(c for c in m.get("captions", []))).lower()
    # map each "number + following noun" and each "number + preceding noun"
    pairs = re.findall(r"(\d[\d,\.]*)\s+([a-z]{3,})", full)
    by_noun = {}
    for num, noun in pairs:
        n = num.rstrip(".").replace(",", "")
        by_noun.setdefault(noun, set()).add(n)
    for noun, nums in by_noun.items():
        if len(nums) > 1 and noun not in ("times", "ways", "kinds", "types", "of", "the", "and"):
            return f"contradictory numbers for '{noun}': {sorted(nums)}"
    # reject absurd fractional counts of discrete things (16.5 colors, 3.5 hearts)
    for num, noun in pairs:
        if "." in num and noun in ("colors", "colours", "hearts", "planets", "stars", "people",
                                   "cells", "bones", "legs", "eyes", "moons", "times", "animals"):
            return f"impossible fractional count: {num} {noun}"

    # anti-repetition: reject if scene voiceovers are too similar to each other.
    # Lowered 0.70 -> 0.62 after the Sun video: scenes 8 and 11 ("...you are
    # always seeing the Sun as it was eight minutes ago, never as it is right
    # now" vs. "...you are seeing it as it was eight minutes and twenty
    # seconds in the past, never as it is right now") scored under 0.70 on
    # pure sequence similarity despite being obviously the same line restated.
    # 0.62 still leaves room for legitimate parallel sentence structure (short
    # scenes built the same way but about different facts) — tested against
    # both the bad Sun manifest (must reject) and a known-good non-repetitive
    # manifest (must pass) below.
    #
    # Exception: scene 1 vs. the final scene. The LOOP CTA style (and, before
    # the CTA-style split, the general "loop back to the hook" ending rule)
    # deliberately wants the closing line to echo the hook's exact phrasing so
    # a replay feels seamless — that is the mechanic, not accidental
    # repetition. The anti-restatement check below already carves out this
    # same exception for the verified-fact comparison; mirror it here so a
    # well-executed loop ending can't get rejected for doing exactly what it
    # was asked to do.
    import difflib
    vos = [s["voiceover"].lower() for s in m["scenes"]]
    for i in range(len(vos)):
        for j in range(i + 1, len(vos)):
            if i == 0 and j == len(vos) - 1:
                continue
            ratio = difflib.SequenceMatcher(None, vos[i], vos[j]).ratio()
            if ratio > 0.62:
                return f"scenes {i+1} and {j+1} too similar (repetition)"

    # anti-repetition (salient-token variant): catches "re-says the same
    # thing" even when each restatement uses a DIFFERENT sentence structure,
    # which the pairwise phrasing check above can miss. The Sun video's core
    # reveal ("eight minutes") showed up as the crux of scene 7 ("left the Sun
    # about eight minutes ago"), scene 8 ("...eight minutes ago, never as it
    # is right now"), scene 9 ("an eight-minute delay"), and scene 11
    # ("...eight minutes and twenty seconds...") — four different sentences,
    # one number, said over and over. If the same salient number-phrase (a
    # normalized "8 minute" style token) or the same multi-word proper noun
    # is the crux of 3+ scenes, that is the reveal being re-said instead of
    # the script escalating to something new each time.
    #
    # Excludes the final scene, same rationale as the pairwise exception
    # above: a LOOP-style ending is SUPPOSED to echo the hook/central image.
    token_scenes = collections.defaultdict(list)
    for i, vo in enumerate(vos[:-1] if len(vos) > 1 else vos):
        for tok in _salient_number_phrases(vo) | _salient_proper_nouns(vo):
            token_scenes[tok].append(i + 1)
    repeated_core = {tok: ids for tok, ids in token_scenes.items() if len(ids) >= 3}
    if repeated_core:
        return (f"the same core detail is re-said as the crux of 3+ scenes {repeated_core} — "
                f"state it once as the payoff and make every other scene a genuinely different "
                f"fact or angle, not a reworded repeat")

    # mandatory key-term naming: the real production failure that motivated this
    # (the potassium-40 banana video) was that topic_bank facts used to be bare
    # one-liners, so the model never had a specific isotope name or a real dose
    # figure to reach for and just said "a naturally occurring isotope" instead.
    # Dossiers now carry key_terms (proper nouns / real numbers the script MUST
    # say) plus a whatif hypothetical the script must pose early and pay off.
    key_terms = fact.get("key_terms", []) if fact else []
    if key_terms:
        full_text = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
        named = [kt for kt in key_terms if _key_term_present(kt, full_text)]
        if len(named) < 2:
            return (f"only {len(named)}/{len(key_terms)} mandatory key terms named "
                     f"({named or 'none'}) — the script must explicitly say at least 2 of "
                     f"{key_terms}; a script that says 'a naturally occurring isotope' instead "
                     f"of 'potassium-40' is a failed script")
        whatif = fact.get("whatif", "")
        if whatif:
            q_part, sep, a_part = whatif.partition("?")
            answer_text = a_part if sep else whatif
            early_count = min(4, len(m["scenes"]))
            early_text = m["hook"] + " " + " ".join(s["voiceover"] for s in m["scenes"][:early_count])
            if "?" not in early_text:
                return ("whatif curiosity gap never opened — the hook or one of the first few "
                        "scenes must pose a real question, not just state facts")
            payoff_terms = [kt for kt in key_terms if _key_term_present(kt, answer_text)] or key_terms
            if not any(_key_term_present(kt, full_text) for kt in payoff_terms):
                return (f"whatif payoff never answered — the script must state the real answer "
                        f"using one of {payoff_terms}, not just pose the question and move on")

    # anti-restatement: the pairwise check above only catches near-identical
    # PHRASING between two scenes. It missed a real production failure: scene
    # 1 said "your body is nearly all empty space", scene 3 said "humanity
    # fits in a sugar cube", and scene 6 then restated BOTH combined almost
    # verbatim as one line -- the same reveal delivered three times with
    # different words, which is exactly what the escalation-ladder rule is
    # supposed to prevent. Catch it by checking how many scenes closely
    # mirror the verified fact itself: one scene doing so is the expected
    # payoff moment; two or more means the core reveal got restated instead
    # of the script escalating to something new each time.
    if fact and fact.get("fact") and len(vos) > 1:
        fact_text = fact["fact"].lower()
        # exclude the final scene: the prompt explicitly wants the closing line
        # to loop back to the hook/central image, which legitimately re-touches
        # the fact's vocabulary -- that's a deliberate design choice, not a bug.
        restated = [i + 1 for i, vo in enumerate(vos[:-1])
                    if difflib.SequenceMatcher(None, vo, fact_text).ratio() > 0.40]
        if len(restated) > 1:
            return (f"the verified fact is restated in {len(restated)} scenes {restated} "
                    f"instead of being revealed once and escalated from")
    # reject if the title's key noun appears in nearly every scene (circling one idea)
    # (collections is imported at module level above)
    words = collections.Counter(re.sub(r"[^a-z ]", "", " ".join(vos)).split())
    common = [w for w, c in words.items() if len(w) > 4 and c >= max(4, len(vos) - 1)]
    if common:
        return f"word(s) {common} repeated in nearly every scene (not progressing)"

    # captions / hashtags hygiene
    m["captions"] = [_clean(c) for c in m["captions"] if _clean(c)][:3] or [m["title"]]
    tags = []
    for h in m["hashtags"]:
        h = _clean(h).lstrip("#")
        # reject phrase/sentence tags: drop anything with underscores or that's too long
        if "_" in h or len(h) > 20 or " " in h.strip():
            # try to salvage the first word only
            h = re.sub(r"[_\s].*$", "", h)
        h = re.sub(r"[^A-Za-z0-9]", "", h)  # letters/numbers only
        if not h or len(h) < 2:
            continue
        tag = "#" + h.lower()
        if tag not in tags:
            tags.append(tag)
    # guarantee core tags
    for core in ["#science", "#learnontiktok"]:
        if core not in tags:
            tags.append(core)
    m["hashtags"] = tags[:6]

    if job_name == "HOW_TO":
        blob = m["script"] + " " + " ".join(s["voiceover"] for s in m["scenes"])
        if UNSAFE.search(blob):
            return "HOW_TO tripped safety filter"

    m.setdefault("render", {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"})
    return None

def _coerce_score(v):
    """Pull a 0-10 number out of whatever the model returned for a rubric
    criterion — int, float, "8", "8/10", "8.5 - strong". Returns None only
    when there's genuinely no number to read (or a bool, which JSON true/false
    would otherwise smuggle in as 1/0)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return max(0.0, min(10.0, float(v)))
    if isinstance(v, str):
        mm = re.search(r"-?\d+(?:\.\d+)?", v)
        if mm:
            return max(0.0, min(10.0, float(mm.group())))
    return None


def score_script(m, fact=None, cta_style="SAVE_WORTHY"):
    """Self-critique pass: one Groq call scores the finished, punched-up
    script against an explicit rubric so a weak script can be caught and
    regenerated before it ever reaches main.py's render pipeline. See
    QUALITY_THRESHOLD / QUALITY_MAX_REGENERATIONS above for how the result
    is used. cta_style adjusts the "rewatch" criterion's wording to match
    this video's assigned ending style (CTA_RUBRIC_HINTS) instead of always
    asking whether it "invited a save."

    MUST fail OPEN — this pipeline runs unattended once a day. Any Groq
    error, timeout, or unparseable/out-of-range response returns None, and
    the caller treats None as "ship this attempt," never as "reject it." A
    scoring hiccup must never brick the autonomous run.
    """
    try:
        fact_line = fact["fact"] if fact else "(no verified fact; general topic)"
        whatif = fact.get("whatif", "") if fact else ""
        scenes_text = "\n".join(f"{s['id']}. {s['voiceover']}" for s in m.get("scenes", []))
        rewatch_hint = CTA_RUBRIC_HINTS.get(cta_style, CTA_RUBRIC_HINTS["SAVE_WORTHY"])
        prompt = f"""You are a brutally honest short-form video editor scoring a finished script BEFORE it is rendered and posted. Be strict — most scripts should NOT score 9 or 10.

TITLE: {m.get('title', '')}
HOOK (first spoken line): {m.get('hook', '')}
VERIFIED FACT THIS VIDEO IS BUILT ON: {fact_line}
CENTRAL QUESTION (if any): {whatif or '(none)'}
THIS VIDEO'S ASSIGNED ENDING STYLE: {cta_style}

FULL SCENE-BY-SCENE SCRIPT:
{scenes_text}

Score each criterion 0-10 (integers, be strict):
- hook: does the first line open a REAL curiosity gap (a specific question the viewer NEEDS answered), not just a description or a mild tease?
- surprise: would most adults genuinely react "wait, WHAT?" — not "yeah I knew that" or "sure, I guess"?
- escalation: does EVERY scene reveal something new, with zero scenes just restating an earlier scene in different words?
- payoff: does the central question get answered with a real, concrete, specific detail (not a shrug or a vague gesture)?
- rewatch: {rewatch_hint}
- clarity: could a 12-year-old follow every sentence on one listen, with no confusing jumps?

Return ONLY valid JSON, exactly:
{{"hook": 0, "surprise": 0, "escalation": 0, "payoff": 0, "rewatch": 0, "clarity": 0}}"""
        raw = call_groq(prompt)
        data = json.loads(raw)
        # Robust coercion: the model frequently returns a score as a STRING
        # ("8") or with a suffix ("8/10") even under JSON mode. The old code
        # required a raw int/float for EVERY criterion and returned None (=
        # ship unscored, fail-open) if even one was a string — which made the
        # whole quality ratchet silently inert whenever that happened. Coerce
        # numbers out of strings, tolerate a minority of unparseable/missing
        # criteria, and only truly fail open when we can't read a majority.
        scores, missing = {}, 0
        for k in QUALITY_RUBRIC_CRITERIA:
            sv = _coerce_score(data.get(k))
            if sv is None:
                missing += 1
            else:
                scores[k] = sv
        if len(scores) < 4:  # couldn't read a majority of 6 — genuinely unusable
            return None
        if missing:  # fill the few unreadable ones with the mean of the rest
            mean = sum(scores.values()) / len(scores)
            for k in QUALITY_RUBRIC_CRITERIA:
                scores.setdefault(k, round(mean, 2))
        # Compute overall ourselves from the per-criterion scores rather than
        # trusting the model's own arithmetic — a model that returns six 9s
        # and a self-reported "overall: 3" (or vice versa) can't silently
        # cause a good script to be rejected or a bad one to ship.
        scores["overall"] = round(sum(scores[k] for k in QUALITY_RUBRIC_CRITERIA) / len(QUALITY_RUBRIC_CRITERIA), 2)
        return scores
    except Exception as e:  # noqa: BLE001 - must fail open, never blocks a run
        print(f"  [quality] scoring failed open ({e}), treating as pass")
        return None


def _slugify(text, maxlen=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen] or "video"


def load_perf():
    """Load perf_<page>.json if present (see the format doc near PERF_PATH
    above). Never raises — a missing file, invalid JSON, or non-dict payload
    is treated as "no performance data yet," so callers always degrade
    safely to plain random selection."""
    try:
        with open(PERF_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _perf_score(entry):
    """Collapse one video's raw engagement metrics into a single 0..1-ish
    score used to weight future selection. watch_through_pct is the primary
    quality signal; follows/shares are rarer, higher-value actions scaled up
    relative to views so one viral outlier can't own the whole score."""
    if not isinstance(entry, dict):
        return 0.0
    views = max(0.0, float(entry.get("views", 0) or 0))
    watch = max(0.0, min(1.0, float(entry.get("watch_through_pct", 0) or 0)))
    follows = max(0.0, float(entry.get("follows", 0) or 0))
    shares = max(0.0, float(entry.get("shares", 0) or 0))
    denom = max(views, 1.0)
    follow_rate = min(1.0, (follows / denom) * 20)
    share_rate = min(1.0, (shares / denom) * 10)
    return 0.5 * watch + 0.3 * follow_rate + 0.2 * share_rate


def score_by_key(history, perf, key_field):
    """Mean _perf_score() per distinct value of key_field (e.g. "fact_id" or
    "viewer_job"), over memory history entries whose video_id has a matching
    perf_<page>.json entry. Keys with no perf data are simply absent from
    the result — callers apply PERF_UNSEEN_FLOOR themselves."""
    buckets = {}
    for h in history:
        vid, key = h.get("video_id"), h.get(key_field)
        if not vid or not key or vid not in perf:
            continue
        buckets.setdefault(key, []).append(_perf_score(perf[vid]))
    return {k: sum(v) / len(v) for k, v in buckets.items() if v}


def _weighted_choice(options, weights, epsilon):
    """Explore/exploit selection. epsilon fraction of calls (and any call
    where every weight is <= 0) pick uniformly at random across ALL options
    (explore); otherwise sample proportional to weight (exploit) — so
    better-performing options get picked more often without unseen/losing
    options ever dropping to zero chance."""
    if not options:
        return None
    if random.random() < epsilon or sum(weights) <= 0:
        return random.choice(options)
    total = sum(weights)
    r = random.uniform(0, total)
    upto = 0.0
    for opt, w in zip(options, weights):
        upto += max(0.0, w)
        if upto >= r:
            return opt
    return options[-1]


def _hook_opener(hook):
    words = re.sub(r"[^A-Za-z' ]", "", hook or "").split()
    return " ".join(w.lower() for w in words[:2])


def overused_hook_openers(history, min_count=3):
    """Light freshness guard (improvement loop, part 3): if the last several
    videos' hooks keep starting with the same 2 words, surface that opener
    so build_prompt() can nudge the next hook toward a different structure.
    Advisory only — never blocks generation. With < min_count repeats
    (including on totally fresh history) this returns [] and behavior is
    unchanged."""
    counts = collections.Counter(
        _hook_opener(h.get("hook", "")) for h in history if h.get("hook"))
    return [op for op, c in counts.items() if op and c >= min_count]


def research_dossier(fact):
    """SCIENTIST BRAIN — stage 1 (research before writing).

    The repetition problem is structural: a script locked to ONE verified fact +
    2-3 key terms has only ~4 real points but needs ~8 scenes, so it MUST pad
    with restatements. This stage first enumerates a RICH, DIVERSE set of
    specific, surprising, TRUE details about the same topic, so stage 2 can build
    each scene from a DIFFERENT real point instead of rephrasing the premise.

    Returns a list of concrete fact strings (or [] on failure — the caller then
    generates the old way, so this can never break a render). Best with the
    Gemini free tier (reliable, high quota); degrades under Groq rate limits."""
    if not fact:
        return []
    topic = fact.get("fact") or fact.get("angle") or ""
    if not topic:
        return []
    kt = ", ".join(fact.get("key_terms", []) or [])
    prompt = (
        "You are the researcher behind the most fascinating science videos on the internet "
        "(think Veritasium, Kurzgesagt, Radiolab) — relentlessly curious, obsessed with the "
        "specific and the counterintuitive.\n\n"
        f'TOPIC: "{topic}"\n'
        f"Known specifics you may build on (keep these accurate): {kt}\n\n"
        "List 9 DISTINCT, genuinely surprising, CONCRETE facts about this topic — the kind that "
        "make a smart adult go 'wait, WHAT?'. Deliberately span DIFFERENT KINDS of point so none "
        "overlap: (1) a hard number or almost-unbelievable scale, (2) the hidden mechanism — HOW/WHY "
        "it actually works, (3) an extreme case or record, (4) a counterintuitive twist that "
        "contradicts what people assume, (5) a vivid physical comparison that makes a number "
        "graspable, (6) a real consequence that touches the viewer's own life, (7) a little-known "
        "discovery/historical detail, (8) an open mystery scientists still can't explain, (9) one "
        "more genuinely weird specific.\n"
        "HARD RULES: every item must contain a specific, checkable detail (a real number, name, or "
        "mechanism) — never a vague adjective. Only include things you are confident are TRUE and "
        "well-established; if unsure of a number, describe the mechanism instead of inventing one. "
        "No two items may be the same point reworded. Prefer strange-but-true over obvious.\n"
        'Return ONLY JSON: {"facts": ["...", "...", "...", "...", "...", "...", "...", "...", "..."]}'
    )
    try:
        raw = call_groq(prompt)
        data = json.loads(raw)
        facts = [str(x).strip() for x in (data.get("facts") or []) if str(x).strip()]
        facts = [f for f in facts if len(f) > 12][:10]
        if facts:
            print(f"  [research] scientist-brain dossier: {len(facts)} distinct angles gathered")
        return facts
    except Exception as e:
        print(f"  [research] dossier unavailable ({e}); writing from the base fact only")
        return []


def generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers=None,
                        cta_style="SAVE_WORTHY"):
    """Run the full generate -> validate -> info-gain -> punch-up pipeline
    once and return a finished manifest, or None if nothing usable came out
    of it. Called once per quality-ratchet attempt (see
    QUALITY_MAX_REGENERATIONS in main()) — every call is an independent
    round of Groq attempts with its own near-miss fallback, so a
    low-quality-score regeneration gets a genuinely fresh script, not a
    retry of the exact same one. cta_style pins which of the four rotated
    endings (CTA_ENDING_RULES) this attempt is built and punched up toward."""
    manifest = None
    near_miss = None  # a parsed script that only failed soft checks — better than murmuration fallback
    # SCIENTIST BRAIN — gather diverse specific material ONCE up front, so every
    # attempt writes from a rich research base instead of rephrasing one fact.
    dossier = research_dossier(chosen_fact)
    for attempt in range(5):
        try:
            if attempt > 0:
                time.sleep(8 * attempt)  # escalating cushion — a flat 8s wasn't enough to outlast a 429
            raw = call_groq(build_prompt(job_name, job_desc, avoid, fact=chosen_fact,
                                          avoid_openers=avoid_openers, cta_style=cta_style,
                                          dossier=dossier))
            m = json.loads(raw)
            err = validate(m, job_name, fact=chosen_fact)
            if err:
                print(f"  attempt {attempt+1} invalid: {err}")
                # keep it as a backup if it at least has the core pieces
                if all(k in m for k in ("title", "hook", "script", "scenes", "captions")) and near_miss is None:
                    near_miss = m
                continue
            if _hits_banned_concept(m.get("metaphor", ""), m.get("title", "")):
                print(f"  attempt {attempt+1} hits a banned concept "
                      f"(flocking/emergence/etc), retrying"); continue
            if _metaphor_too_similar(m.get("metaphor", ""), history):
                print(f"  attempt {attempt+1} too similar to a recent topic, retrying"); continue
            ig_err = check_information_gain(m)
            if ig_err:
                print(f"  attempt {attempt+1} invalid: {ig_err}")
                if near_miss is None:
                    near_miss = m
                continue
            manifest = m; break
        except Exception as e:
            print(f"  attempt {attempt+1} error: {e}")

    if not manifest and near_miss is not None:
        # repair the near-miss minimally so it can render, rather than fall back to murmuration
        print("  using best near-miss (repaired)")
        nm = near_miss
        nm.setdefault("render", {"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"})
        nm["hashtags"] = nm.get("hashtags", ["#science"])
        nm["captions"] = nm.get("captions") or [nm.get("title", "Watch this")]
        # ENFORCE PACING on the near-miss too. A script usually lands here
        # precisely BECAUSE the stricter validate() rejected it (too many
        # scenes / a run-on / repetition), and the old repair shipped it
        # uncapped — that's how the 14-scene, choppy "Morning Height" video
        # got out. Trim to <=10 scenes by dropping the most REDUNDANT middle
        # scenes (always keeping the hook and the ending), which cuts the
        # choppy over-cutting AND the restatement in a single pass.
        import difflib as _dl
        _scenes = nm.get("scenes", [])
        MAX_NEARMISS_SCENES = 10
        if len(_scenes) > MAX_NEARMISS_SCENES:
            def _redundancy(i):
                vo = _scenes[i].get("voiceover", "").lower()
                return max((_dl.SequenceMatcher(None, vo, _scenes[j].get("voiceover", "").lower()).ratio()
                            for j in range(len(_scenes)) if j != i), default=0.0)
            middle = sorted(range(1, len(_scenes) - 1), key=_redundancy, reverse=True)
            drop = set(middle[:len(_scenes) - MAX_NEARMISS_SCENES])
            _scenes = [s for i, s in enumerate(_scenes) if i not in drop]
            for _new_id, s in enumerate(_scenes, 1):
                s["id"] = _new_id
            nm["scenes"] = _scenes
            print(f"  near-miss trimmed {len(drop)} most-redundant middle scene(s) "
                  f"-> {len(_scenes)} scenes (pacing/repetition)")
        # fill in queries the model left out or made un-filmable. Duplicate
        # queries are deliberately NOT swapped here (they used to be, via a
        # "seen" set) -- that was the same bug fixed in validate(): main.py's
        # fetch_clip already excludes previously-used clip ids per scene, so
        # two scenes sharing a query get different clips automatically, and
        # swapping to an unrelated pool term (e.g. "night sky timelapse" for
        # an ocean/plankton scene) was actively making footage LESS relevant,
        # not preventing repeated footage.
        pool = (chosen_fact.get("queries", []) if chosen_fact else []) + VARIETY_QUERIES
        for i, s in enumerate(nm.get("scenes", [])):
            s.setdefault("motion", "zoom_in"); s.setdefault("duration", 5)
            s.setdefault("on_screen_text", "")
            if not s.get("search_query") or UNSTOCKABLE_Q.search(s.get("search_query", "")):
                s["search_query"] = pool[i % len(pool)]
        # strip any lingering banned generic save-command phrasing -- even the
        # last-resort near-miss path must not ship the old hard-coded line.
        for s in nm.get("scenes", []):
            vo = s.get("voiceover", "")
            if GENERIC_SAVE_CMD.search(vo):
                s["voiceover"] = GENERIC_SAVE_CMD.sub("", vo).strip(" .") or "Now you know."
        nm["script"] = " ".join(s.get("voiceover", "") for s in nm.get("scenes", []))
        # Log-only info-gain pass on the repaired near-miss: this is the
        # last-resort path that exists specifically so the unattended run can
        # never come up empty, so it is not rejected here even if flagged --
        # but the run log should still show a redundant near-miss was shipped
        # rather than silently hiding it.
        nm_ig_err = check_information_gain(nm)
        if nm_ig_err:
            print(f"  [info-gain] near-miss fallback still redundant ({nm_ig_err}) — "
                  f"shipping anyway (last-resort fallback, never blocks the run)")
        # Mark this as a DEGRADED candidate: it reached the repair path because
        # strict validate() rejected every real attempt (usually because the LLM
        # was rate-limited/exhausted and never produced a clean script). main()
        # uses this together with whether quality scoring was available to decide
        # whether to ship or ABORT — a degraded near-miss that also can't be
        # scored is exactly the junk video we must never publish. Stripped before
        # the manifest is written to disk.
        nm["_degraded"] = True
        manifest = nm

    if not manifest:
        return None

    result = punch_up(manifest, chosen_fact, cta_style=cta_style)
    # Ensure information-gain is checked on the SCRIPT THAT ACTUALLY SHIPS,
    # not just the pre-punch-up draft: punch_up rewrites every voiceover line,
    # so it's the one place after validate() that could reintroduce semantic
    # redundancy the earlier check already cleared. If punch_up's rewrite is
    # now flagged, fall back to the pre-punch-up manifest, which already
    # passed this same check (or was explicitly logged as the last-resort
    # near-miss exception above).
    if result is not manifest:
        post_ig_err = check_information_gain(result)
        if post_ig_err:
            print(f"  post-punch-up info-gain check failed ({post_ig_err}), "
                  f"reverting to pre-punch-up script")
            return manifest
    return result


def main():
    if not GROQ_KEY:
        print("ERROR: GROQ_API_KEY not set"); sys.exit(1)

    history = load_memory()
    # avoid list = recent metaphors PLUS the always-banned concepts, so the
    # model is steered off both recent topics and the flagged flocking/
    # emergence idea from the very first attempt.
    _recent_metaphors = [h.get("metaphor", "") for h in history if h.get("metaphor")]
    avoid = ", ".join(_recent_metaphors + BANNED_CONCEPTS) or "none yet"
    avoid_openers = overused_hook_openers(history)

    # Performance-memory scaffold (improvement loop, part 2): fully optional,
    # fully fail-safe. With no perf_<page>.json (today's reality for every
    # page), fact_scores/job_scores stay {} and selection below falls
    # straight through to the exact same random.choice() calls as before.
    perf = load_perf()
    fact_scores = score_by_key(history, perf, "fact_id") if perf else {}
    job_scores = score_by_key(history, perf, "viewer_job") if perf else {}
    cta_scores = score_by_key(history, perf, "cta_style") if perf else {}

    # Path C: pick a verified fact from the bank not used recently. Dedup is
    # now two-layered: exclude the exact fact_id used before AND exclude the
    # DOMAIN of the last RECENT_DOMAIN_WINDOW videos, so a different exact fact
    # that is still "the same kind of video" (two space facts, two animal
    # facts) doesn't ship back to back. Domain comes from the new memory field
    # with a bank lookup fallback for older entries that predate it. Filters
    # widen gracefully if they would empty the pool.
    bank = load_bank()
    used_ids = {h.get("fact_id") for h in history if h.get("fact_id")}
    _id_to_domain = {f["id"]: f.get("domain") for f in bank}
    recent_domains = set()
    for h in history[-RECENT_DOMAIN_WINDOW:]:
        d = h.get("domain") or _id_to_domain.get(h.get("fact_id"))
        if d:
            recent_domains.add(d)
    fresh = [f for f in bank
             if f["id"] not in used_ids and f.get("domain") not in recent_domains]
    available = fresh or [f for f in bank if f["id"] not in used_ids] or bank
    if recent_domains:
        print(f"  [bank] avoiding recent domains {sorted(recent_domains)} "
              f"({len(fresh)} of {len(bank)} facts fresh)")
    if available and fact_scores:
        weights = [fact_scores.get(f["id"], 0.0) + PERF_UNSEEN_FLOOR for f in available]
        chosen_fact = _weighted_choice(available, weights, EXPLORE_EPSILON)
    else:
        chosen_fact = random.choice(available) if available else None
    if chosen_fact:
        print(f"  [bank] fact: {chosen_fact['id']}")
    last_job = history[-1].get("viewer_job") if history else None
    jobs = [j for j in VIEWER_JOBS if j[0] != last_job] or VIEWER_JOBS
    # HOW_TO asks for a household demo the viewer can try. That is incompatible
    # with a fixed verified fact from the bank: pairing "immortal jellyfish"
    # with HOW_TO once produced a jellyfish script that bolted an unrelated
    # dish-soap experiment onto the final scene. When a bank fact is driving
    # the video, exclude HOW_TO — it only makes sense as a standalone demo job.
    if chosen_fact:
        jobs = [j for j in jobs if j[0] != "HOW_TO"] or jobs
    if job_scores:
        weights = [job_scores.get(j[0], 0.0) + PERF_UNSEEN_FLOOR for j in jobs]
        job_name, job_desc = _weighted_choice(jobs, weights, EXPLORE_EPSILON)
    else:
        job_name, job_desc = random.choice(jobs)
    print(f"[generate] job={job_name} avoiding={avoid[:80]}")

    # CTA style selection (save-worthiness overhaul, part 2): rotate the
    # ending mechanic per video instead of always closing on the same save
    # command. Excludes whatever style the last video used so back-to-back
    # videos don't repeat an ending, same pattern as last_job above. Once
    # perf_<page>.json has real engagement data, weights lean toward
    # styles that actually earn saves/shares/comments/rewatches for THIS
    # page; until then this is a plain rotation (PERF_UNSEEN_FLOOR keeps
    # every style in the running).
    last_cta = history[-1].get("cta_style") if history else None
    cta_options = [c for c in CTA_STYLES if c != last_cta] or CTA_STYLES
    if cta_scores:
        weights = [cta_scores.get(c, 0.0) + PERF_UNSEEN_FLOOR for c in cta_options]
        cta_style = _weighted_choice(cta_options, weights, EXPLORE_EPSILON)
    else:
        cta_style = random.choice(cta_options)
    print(f"[generate] cta_style={cta_style}")

    # Quality ratchet (improvement loop, part 1): generate, self-critique,
    # and — if the score is below QUALITY_THRESHOLD — regenerate from
    # scratch, bounded to QUALITY_MAX_REGENERATIONS extra attempts. Keeps
    # the best-scoring attempt across all rounds and ships it even if none
    # cleared the bar, so this can never block the daily run.
    best_manifest, best_overall, best_quality, best_rank = None, None, None, None
    for regen_i in range(QUALITY_MAX_REGENERATIONS + 1):
        candidate = generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers,
                                        cta_style=cta_style)
        if candidate is None:
            print(f"  [quality] attempt {regen_i+1}: generation produced nothing usable")
            continue
        quality = score_script(candidate, chosen_fact, cta_style=cta_style)
        if quality is None:
            # Scoring itself broke (usually the LLM is rate-limited/exhausted).
            # Fail OPEN only for a CLEAN candidate — one that passed strict
            # validate() — because that script is structurally sound and just
            # couldn't be graded. A DEGRADED near-miss with no score is the
            # worst case: no research, no punch-up, no grading, shipped anyway.
            # That is precisely how quota-exhausted runs 52/53 published thin,
            # repetitive videos. Refuse it — try another attempt, and if every
            # attempt is degraded+unscored, main() aborts the run (no bad video
            # published) instead of polluting the profile.
            if candidate.get("_degraded"):
                print(f"  [quality] attempt {regen_i+1}: degraded near-miss AND scoring "
                      f"unavailable (LLM exhausted) — refusing to ship, trying another attempt")
                continue
            print(f"  [quality] attempt {regen_i+1}: scoring failed open on a clean script — shipping this attempt")
            best_manifest, best_quality, best_overall = candidate, None, None
            break
        overall = quality["overall"]
        # A REAL score (as opposed to the fail-open None above) that breaks a
        # per-criterion floor must trigger regeneration NO MATTER how high the
        # average is -- this is what catches a script like the Sun video
        # (overall 7.17, payoff 5).
        violations = {k: quality[k] for k, floor in QUALITY_CRITERION_FLOORS.items()
                      if quality.get(k, 10) < floor}
        flag = f" — FLOOR VIOLATION {violations} (floors: {QUALITY_CRITERION_FLOORS})" if violations else ""
        print(f"  [quality] attempt {regen_i+1}: overall {overall}/10 {quality}{flag}")
        # Rank best-so-far by (no floor violation, overall) so that, if the
        # regen budget runs out, we ship the best NON-violating attempt we
        # saw rather than whichever had the highest average regardless of a
        # broken payoff/hook/escalation.
        rank = (0 if violations else 1, overall)
        if best_rank is None or rank > best_rank:
            best_manifest, best_overall, best_quality, best_rank = candidate, overall, quality, rank
        if violations:
            print(f"  [quality] attempt {regen_i+1} rejected: per-criterion floor broken "
                  f"regardless of overall {overall} — regenerating")
            continue
        if overall >= QUALITY_THRESHOLD:
            print(f"  [quality] cleared threshold ({overall} >= {QUALITY_THRESHOLD}) with no "
                  f"floor violations — shipping")
            break
    else:
        if best_manifest is not None:
            print(f"  [quality] no attempt cleared {QUALITY_THRESHOLD} with all floors intact — "
                  f"shipping best-scoring attempt (overall {best_overall})")

    manifest = best_manifest
    if not manifest:
        # Reaching here means no attempt produced a clean, shippable script —
        # typically every attempt was a degraded near-miss that also couldn't be
        # quality-scored because the LLM providers were rate-limited/exhausted.
        # Aborting (exit 1) is deliberate: the workflow's generate step turns a
        # non-zero exit into "no render, no release", so a quota-starved run
        # publishes NOTHING rather than a thin, repetitive fallback video. The
        # daily cron simply tries again once the free quotas reset.
        print("ERROR: could not generate a valid manifest — no clean script this run "
              "(likely LLM quota exhausted). Aborting so no degraded video is published.")
        sys.exit(1)

    # Stable video id for the performance-memory loop: PAGE + date + a title
    # slug. Written into the manifest so main.py can carry it through to
    # out/post.json, and into memory_<page>.json so a later perf_<page>.json
    # can be matched back to this run (see PERF_PATH doc above).
    video_id = f"{PAGE}_{datetime.date.today().isoformat()}_{_slugify(manifest.get('title', ''))}"
    manifest["video_id"] = video_id
    # cta_style is engine-assigned (main() above), not model-authored, but it's
    # part of the manifest so main.py can carry it through to out/post.json
    # and so a publisher/scheduler downstream can see which ending shipped.
    manifest["cta_style"] = cta_style
    # Carry the topic domain through to the manifest (and thus out/post.json)
    # so funnel.py can pick the topic-matched affiliate angle per video.
    manifest["domain"] = chosen_fact.get("domain") if chosen_fact else None
    # internal-only gate flag (see generate_candidate / the quality loop) — never
    # belongs in the manifest main.py renders from.
    manifest.pop("_degraded", None)

    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    save_memory(history, {
        "video_id": video_id,
        "metaphor": manifest.get("metaphor", manifest["title"]),
        "viewer_job": job_name,
        "cta_style": cta_style,
        "title": manifest["title"],
        "fact_id": chosen_fact["id"] if chosen_fact else None,
        "domain": chosen_fact.get("domain") if chosen_fact else None,
        "hook": manifest.get("hook", ""),
        "structure": {
            "scene_count": len(manifest.get("scenes", [])),
            "used_whatif": bool(chosen_fact and chosen_fact.get("whatif")),
        },
        "quality": best_quality,
    })
    print(f"[generate] wrote {manifest['title']!r} ({job_name}, cta={cta_style}) -> "
          f"{OUT_MANIFEST} [video_id={video_id}]")

if __name__ == "__main__":
    main()
