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
# Path A: try strongest available model first; fall back automatically if blocked (403) or rate-limited.
MODEL_CHAIN = ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "llama-3.1-8b-instant"]
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
# QUALITY_THRESHOLD starts modest ON PURPOSE: the channel has no track record
# yet, and setting it too high just burns Groq calls regenerating scripts
# that are already fine. RATCHET THIS UP over time (e.g. 7.0 -> 7.5 -> 8.0)
# once perf_<page>.json (see PERF_PATH below) shows higher-scoring scripts
# actually perform better in real engagement data.
QUALITY_THRESHOLD = 7.0
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

def build_prompt(job_name, job_desc, avoid, fact=None, avoid_openers=None):
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
                      f"- Center the ENTIRE script on this one fact. Do NOT introduce other topics.\n"
                      f"- Do NOT invent any statistic, number, or 'fact' that is not in the verified fact, "
                      f"key terms, or wow detail above. If you are unsure of a number, do not state one.\n"
                      f"- Never state two different numbers for the same thing. Accuracy over drama.\n"
                      f"{key_terms_block}{whatif_block}{wow_block}"
                      f"- Include at least ONE absurd-but-precise felt comparison that turns a number "
                      f"into something physically picturable (e.g. not '400 million years' alone but "
                      f"'before Saturn even had rings', or 'you could watch human civilization rise and "
                      f"fall 80,000 times over'). Keep it precise — no vague hand-waving.\n"
                      f"- For the footage search_query fields, prefer these proven matches: "
                      f"{[q for q in fact.get('queries', []) if not UNSTOCKABLE_Q.search(q)]}.\n")
    opener_block = ""
    if avoid_openers:
        opener_block = (
            f"\n\nHOOK VARIETY: your last several videos' hooks all opened the same way "
            f"({avoid_openers}). Start THIS hook with a different sentence structure or "
            f"opening word — not just a synonym swap of the same structure.")
    return f"""You write scripts for a faceless science TikTok channel engineered to go viral and gain followers.{fact_block}

THIS VIDEO'S JOB: {job_name}. {job_desc}

PROVEN RULES (every one is backed by 2026 TikTok performance data — follow them all):

HOOK (first 2 seconds decide 70% of retention):
- First spoken line = 8-14 words. A contrarian claim or direct call-out that opens a curiosity gap. NOT a description.
- Address the viewer directly ("you"/"your"). Self-relevant beats abstract.

STORY ENGINE (the #1 ranking signal is completion — earn every second):
- 8-12 SHORT scenes. Each scene's voiceover is ONE punchy sentence (fast pacing = +34% retention).
- Total narration MUST be 110-150 words (~45-55 seconds spoken). Write the FULL script. Too short = rejected.
- ESCALATION LADDER (critical): every scene must reveal something NO other scene has said yet.
  State the core reveal — the specific number or comparison from the verified fact — in EXACTLY
  ONE scene, once, as the payoff moment. Every other scene explores a DIFFERENT angle (the setup
  question, the mechanism/why it's true, a second consequence, what it means for YOU) and must
  NOT reference that same number or comparison again, even reworded. A script that circles back to
  the same reveal twice reads as padded and repetitive, not escalating — each scene is a NEW fact
  about the topic, not a rephrasing of the last one: what -> how -> why it's stranger than it
  sounds -> what it means for YOU.
- MIDPOINT TWIST: around scene 5-7, plant a pattern interrupt that reopens curiosity, e.g.
  "But that's not even the strange part." / "And here's where it stops making sense." Then pay it off.
- MAKE IT FELT, not just stated: convert numbers into physical comparisons a viewer can picture
  (not "400 million years" alone — "before Saturn had rings", "you could watch every human
  civilization rise and fall 80,000 times"). One vivid comparison beats three adjectives.
- The ending must LAND: the single most quotable line of the video, then loop back to the hook's
  image so the replay feels seamless. Do NOT trail off, restate the premise, or stack two CTAs.

SEARCH DISCOVERY (now as important as hashtags):
- Pick ONE core keyword phrase (what someone would type to find this).
- Put it in the hook, in at least 2 on_screen_text labels, and in the first caption.

SHARES (THE #1 weighted signal — 10x a like). Engineer the video to be SENT to a friend:
- The fact must be "send-worthy": so surprising or identity-relevant the viewer thinks "I have to show ___ this."
- Include one line that hands the viewer a reason to share ("tag someone who won't believe this", or a fact they'll want to prove to a friend).

SAVES (5x a like — make every video save-worthy):
- The final spoken line delivers a payoff AND invites a save ("Save this so you remember it.").
- Loop the last line back to the hook so it replays cleanly (rewatch = top distribution signal).

COMMENTS (binary questions outperform — easiest to answer, drive depth):
- Plant ONE line that provokes a reply: either a BINARY question ("Team A or Team B?", "Did you know this — yes or no?") OR a claim people will argue with ("no way", "that's not true").
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

def _call_model(model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"}
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {GROQ_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "content-render/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]

def call_groq(prompt):
    global _WORKING_MODEL
    # if we already found a working model, use it
    if _WORKING_MODEL:
        return _call_model(_WORKING_MODEL, prompt)
    # otherwise walk the chain, caching the first that works
    last_err = None
    for model in MODEL_CHAIN:
        try:
            out = _call_model(model, prompt)
            _WORKING_MODEL = model
            print(f"  [model] using {model}")
            return out
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):   # not available to this account — try next
                print(f"  [model] {model} unavailable ({e.code}), trying next")
                last_err = e; continue
            raise   # 429/500 etc — let the retry loop handle it
    raise last_err if last_err else RuntimeError("no model available")

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


def punch_up(m, fact):
    """Second-pass rewrite of the voiceovers only. Structure rules in the main
    prompt get a script that follows the letter of the format but still writes
    flat lines (e.g. following the midpoint twist with 'the difference is
    almost negligible' — an anti-climax — or stacking two CTAs). A focused
    critique-and-rewrite pass fixes delivery; validate() re-guards the result
    and we keep the original whenever the rewrite doesn't survive it."""
    fact_line = fact["fact"] if fact else "the fact stated in the script"
    key_terms = fact.get("key_terms", []) if fact else []
    key_terms_rule = ""
    if key_terms:
        key_terms_rule = (
            f"- MUST preserve every one of these exact terms verbatim, spelled exactly as given, "
            f"somewhere across the rewritten lines: {key_terms}. Do not paraphrase them away or "
            f"swap a real name/number for a vaguer description — if the original said "
            f"'potassium-40', the rewrite must still say 'potassium-40', not 'a radioactive isotope'.\n")
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
- Exactly ONE call-to-action, in the FINAL line only (save OR share OR comment — never two).
- Final line must also close the loop back to the opening image.
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
        ids = [i for i in ids if isinstance(i, int)]
        if len(ids) >= 2:
            return (f"information-gain check flagged {len(ids)} redundant scenes {ids} "
                    f"(no new information beyond an earlier scene) — cut or replace them")
        return None
    except Exception as e:  # noqa: BLE001 - must fail open, never blocks a run
        print(f"  info-gain check failed open ({e}), passing")
        return None

def validate(m, job_name, fact=None):
    for k in ["title", "hook", "script", "scenes", "captions", "hashtags"]:
        if k not in m:
            return f"missing {k}"
    if not isinstance(m["scenes"], list) or not (6 <= len(m["scenes"]) <= 14):
        return f"scene count {len(m.get('scenes', []))} out of range"

    # clean top-level text
    m["title"] = _clean(m["title"])[:90]
    m["hook"] = _clean(m["hook"])
    if not (4 <= len(m["hook"].split()) <= 16):
        return f"hook length {len(m['hook'].split())} words out of range"

    # scenes: clean and validate
    for i, s in enumerate(m["scenes"], 1):
        for k in ("voiceover", "on_screen_text", "search_query"):
            if not s.get(k):
                return f"scene {i} missing {k}"
            s[k] = _clean(s[k])
        s["on_screen_text"] = " ".join(s["on_screen_text"].split()[:4])  # cap label to 4 words
        if len(s["voiceover"].split()) > 28:
            return f"scene {i} voiceover too long"
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

    # script length sanity (≈45-60s spoken = ~100-170 words)
    wc = len(_clean(m["script"]).split())
    if not (70 <= wc <= 240):
        return f"script word count {wc} out of range"
    m["script"] = _clean(m["script"])

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
    # 0.70, not 0.60 — at 0.60 this fired on legitimate scripts (parallel sentence
    # structure reads as similarity), and every false rejection pushed a run toward
    # the much worse near-miss fallback. Catch real restatements only.
    import difflib
    vos = [s["voiceover"].lower() for s in m["scenes"]]
    for i in range(len(vos)):
        for j in range(i + 1, len(vos)):
            ratio = difflib.SequenceMatcher(None, vos[i], vos[j]).ratio()
            if ratio > 0.70:
                return f"scenes {i+1} and {j+1} too similar (repetition)"
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
    import collections
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

def score_script(m, fact=None):
    """Self-critique pass: one Groq call scores the finished, punched-up
    script against an explicit rubric so a weak script can be caught and
    regenerated before it ever reaches main.py's render pipeline. See
    QUALITY_THRESHOLD / QUALITY_MAX_REGENERATIONS above for how the result
    is used.

    MUST fail OPEN — this pipeline runs unattended once a day. Any Groq
    error, timeout, or unparseable/out-of-range response returns None, and
    the caller treats None as "ship this attempt," never as "reject it." A
    scoring hiccup must never brick the autonomous run.
    """
    try:
        fact_line = fact["fact"] if fact else "(no verified fact; general topic)"
        whatif = fact.get("whatif", "") if fact else ""
        scenes_text = "\n".join(f"{s['id']}. {s['voiceover']}" for s in m.get("scenes", []))
        prompt = f"""You are a brutally honest short-form video editor scoring a finished script BEFORE it is rendered and posted. Be strict — most scripts should NOT score 9 or 10.

TITLE: {m.get('title', '')}
HOOK (first spoken line): {m.get('hook', '')}
VERIFIED FACT THIS VIDEO IS BUILT ON: {fact_line}
CENTRAL QUESTION (if any): {whatif or '(none)'}

FULL SCENE-BY-SCENE SCRIPT:
{scenes_text}

Score each criterion 0-10 (integers, be strict):
- hook: does the first line open a REAL curiosity gap (a specific question the viewer NEEDS answered), not just a description or a mild tease?
- surprise: would most adults genuinely react "wait, WHAT?" — not "yeah I knew that" or "sure, I guess"?
- escalation: does EVERY scene reveal something new, with zero scenes just restating an earlier scene in different words?
- payoff: does the central question get answered with a real, concrete, specific detail (not a shrug or a vague gesture)?
- rewatch: does the ending loop back cleanly to the hook/opening image and invite a save or share, so a replay feels seamless?
- clarity: could a 12-year-old follow every sentence on one listen, with no confusing jumps?

Return ONLY valid JSON, exactly:
{{"hook": 0, "surprise": 0, "escalation": 0, "payoff": 0, "rewatch": 0, "clarity": 0}}"""
        raw = call_groq(prompt)
        data = json.loads(raw)
        scores = {}
        for k in QUALITY_RUBRIC_CRITERIA:
            v = data.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return None
            scores[k] = max(0.0, min(10.0, float(v)))
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


def generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers=None):
    """Run the full generate -> validate -> info-gain -> punch-up pipeline
    once and return a finished manifest, or None if nothing usable came out
    of it. Called once per quality-ratchet attempt (see
    QUALITY_MAX_REGENERATIONS in main()) — every call is an independent
    round of Groq attempts with its own near-miss fallback, so a
    low-quality-score regeneration gets a genuinely fresh script, not a
    retry of the exact same one."""
    manifest = None
    near_miss = None  # a parsed script that only failed soft checks — better than murmuration fallback
    for attempt in range(5):
        try:
            if attempt > 0:
                time.sleep(8 * attempt)  # escalating cushion — a flat 8s wasn't enough to outlast a 429
            raw = call_groq(build_prompt(job_name, job_desc, avoid, fact=chosen_fact, avoid_openers=avoid_openers))
            m = json.loads(raw)
            err = validate(m, job_name, fact=chosen_fact)
            if err:
                print(f"  attempt {attempt+1} invalid: {err}")
                # keep it as a backup if it at least has the core pieces
                if all(k in m for k in ("title", "hook", "script", "scenes", "captions")) and near_miss is None:
                    near_miss = m
                continue
            mt = m.get("metaphor", "").lower()
            if any(mt and mt in h.get("metaphor", "").lower() for h in history):
                print(f"  attempt {attempt+1} repeats topic, retrying"); continue
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
        manifest = nm

    if not manifest:
        return None

    return punch_up(manifest, chosen_fact)


def main():
    if not GROQ_KEY:
        print("ERROR: GROQ_API_KEY not set"); sys.exit(1)

    history = load_memory()
    avoid = ", ".join(h.get("metaphor", "") for h in history) or "none yet"
    avoid_openers = overused_hook_openers(history)

    # Performance-memory scaffold (improvement loop, part 2): fully optional,
    # fully fail-safe. With no perf_<page>.json (today's reality for every
    # page), fact_scores/job_scores stay {} and selection below falls
    # straight through to the exact same random.choice() calls as before.
    perf = load_perf()
    fact_scores = score_by_key(history, perf, "fact_id") if perf else {}
    job_scores = score_by_key(history, perf, "viewer_job") if perf else {}

    # Path C: pick a verified fact from the bank not used recently
    bank = load_bank()
    used_ids = {h.get("fact_id") for h in history if h.get("fact_id")}
    available = [f for f in bank if f["id"] not in used_ids] or bank
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

    # Quality ratchet (improvement loop, part 1): generate, self-critique,
    # and — if the score is below QUALITY_THRESHOLD — regenerate from
    # scratch, bounded to QUALITY_MAX_REGENERATIONS extra attempts. Keeps
    # the best-scoring attempt across all rounds and ships it even if none
    # cleared the bar, so this can never block the daily run.
    best_manifest, best_overall, best_quality = None, None, None
    for regen_i in range(QUALITY_MAX_REGENERATIONS + 1):
        candidate = generate_candidate(job_name, job_desc, avoid, chosen_fact, history, avoid_openers)
        if candidate is None:
            print(f"  [quality] attempt {regen_i+1}: generation produced nothing usable")
            continue
        quality = score_script(candidate, chosen_fact)
        if quality is None:
            # fail OPEN: scoring itself broke, not the script. Ship this
            # attempt immediately rather than burn remaining regen budget.
            print(f"  [quality] attempt {regen_i+1}: scoring failed open — shipping this attempt")
            best_manifest, best_quality, best_overall = candidate, None, None
            break
        overall = quality["overall"]
        print(f"  [quality] attempt {regen_i+1}: overall {overall}/10 {quality}")
        if best_overall is None or overall > best_overall:
            best_manifest, best_overall, best_quality = candidate, overall, quality
        if overall >= QUALITY_THRESHOLD:
            print(f"  [quality] cleared threshold ({overall} >= {QUALITY_THRESHOLD}) — shipping")
            break
    else:
        if best_manifest is not None:
            print(f"  [quality] no attempt cleared {QUALITY_THRESHOLD} — shipping best-scoring "
                  f"attempt (overall {best_overall})")

    manifest = best_manifest
    if not manifest:
        print("ERROR: could not generate a valid manifest"); sys.exit(1)

    # Stable video id for the performance-memory loop: PAGE + date + a title
    # slug. Written into the manifest so main.py can carry it through to
    # out/post.json, and into memory_<page>.json so a later perf_<page>.json
    # can be matched back to this run (see PERF_PATH doc above).
    video_id = f"{PAGE}_{datetime.date.today().isoformat()}_{_slugify(manifest.get('title', ''))}"
    manifest["video_id"] = video_id

    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    save_memory(history, {
        "video_id": video_id,
        "metaphor": manifest.get("metaphor", manifest["title"]),
        "viewer_job": job_name,
        "title": manifest["title"],
        "fact_id": chosen_fact["id"] if chosen_fact else None,
        "hook": manifest.get("hook", ""),
        "structure": {
            "scene_count": len(manifest.get("scenes", [])),
            "used_whatif": bool(chosen_fact and chosen_fact.get("whatif")),
        },
        "quality": best_quality,
    })
    print(f"[generate] wrote {manifest['title']!r} ({job_name}) -> {OUT_MANIFEST} [video_id={video_id}]")

if __name__ == "__main__":
    main()
