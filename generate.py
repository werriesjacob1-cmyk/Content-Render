#!/usr/bin/env python3
"""
generate.py — the content brain.
Calls Groq to write ONE fresh science video per run. Rotates 5 viewer-jobs, builds
in completion/save/comment/search optimizations, never repeats recent topics.
Writes manifest.json for the render engine and appends to memory.json (regression record).

Env: GROQ_API_KEY
"""

import os, sys, json, re, time, urllib.request, urllib.error, random

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

def build_prompt(job_name, job_desc, avoid, fact=None):
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
        fact_block = (f"\n\n=== THE VERIFIED FACT FOR THIS VIDEO (this is TRUE — build the whole script around it) ===\n"
                      f"\"{fact['fact']}\"\n"
                      f"Angle: {fact['angle']}.\n"
                      f"ABSOLUTE RULES FOR ACCURACY:\n"
                      f"- Center the ENTIRE script on this one fact. Do NOT introduce other topics.\n"
                      f"- Do NOT invent any statistic, number, or 'fact' that is not in the verified fact above. If you are unsure of a number, do not state one.\n"
                      f"- Never state two different numbers for the same thing. Accuracy over drama.\n"
                      f"- For the footage search_query fields, prefer these proven matches: "
                      f"{[q for q in fact.get('queries', []) if not UNSTOCKABLE_Q.search(q)]}.\n")
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

AVOID these recent topics entirely: {avoid}{series_block}

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
- Every line ends with proper punctuation (. ? or !) — these are spoken sentences,
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

def main():
    if not GROQ_KEY:
        print("ERROR: GROQ_API_KEY not set"); sys.exit(1)

    history = load_memory()
    avoid = ", ".join(h.get("metaphor", "") for h in history) or "none yet"

    # Path C: pick a verified fact from the bank not used recently
    bank = load_bank()
    used_ids = {h.get("fact_id") for h in history if h.get("fact_id")}
    available = [f for f in bank if f["id"] not in used_ids] or bank
    chosen_fact = random.choice(available) if available else None
    if chosen_fact:
        print(f"  [bank] fact: {chosen_fact['id']}")
    last_job = history[-1].get("viewer_job") if history else None
    jobs = [j for j in VIEWER_JOBS if j[0] != last_job] or VIEWER_JOBS
    job_name, job_desc = random.choice(jobs)
    print(f"[generate] job={job_name} avoiding={avoid[:80]}")

    manifest = None
    near_miss = None  # a parsed script that only failed soft checks — better than murmuration fallback
    for attempt in range(5):
        try:
            if attempt > 0:
                time.sleep(8 * attempt)  # escalating cushion — a flat 8s wasn't enough to outlast a 429
            raw = call_groq(build_prompt(job_name, job_desc, avoid, fact=chosen_fact))
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
        print("ERROR: could not generate a valid manifest"); sys.exit(1)

    manifest = punch_up(manifest, chosen_fact)

    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    save_memory(history, {"metaphor": manifest.get("metaphor", manifest["title"]),
                          "viewer_job": job_name, "title": manifest["title"],
                          "fact_id": chosen_fact["id"] if chosen_fact else None})
    print(f"[generate] wrote {manifest['title']!r} ({job_name}) -> {OUT_MANIFEST}")

if __name__ == "__main__":
    main()
