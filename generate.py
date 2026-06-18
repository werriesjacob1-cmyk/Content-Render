#!/usr/bin/env python3
"""
generate.py — the content brain.
Calls Groq to write ONE fresh science video per run. Rotates 5 viewer-jobs, builds
in completion/save/comment/search optimizations, never repeats recent topics.
Writes manifest.json for the render engine and appends to memory.json (regression record).

Env: GROQ_API_KEY
"""

import os, sys, json, re, urllib.request, urllib.error, random

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.environ.get("PAGE", "science")
MEMORY = os.path.join(ROOT, f"memory_{PAGE}.json")
OUT_MANIFEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "manifest.json")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "llama-3.1-8b-instant"   # widely-available model; swap to 70b if your account supports it

VIEWER_JOBS = [
    ("REFRAME",
     "Flip something the viewer thought they understood. The payoff rewires their mental model. "
     "End so they think 'I'll never see X the same way.'"),
    ("SOCIAL_CURRENCY",
     "Built around ONE stunning number or comparison so striking the viewer repeats it to sound smart. "
     "The fact itself is the share trigger."),
    ("EXISTENTIAL_CHILL",
     "Leave an eerie awe/dread feeling about reality, the body, time, or the universe. "
     "End on an unresolved, haunting note that lingers."),
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

def build_prompt(job_name, job_desc, avoid):
    return f"""You write scripts for a faceless science TikTok channel engineered to go viral and gain followers.

THIS VIDEO'S JOB: {job_name}. {job_desc}

PROVEN RULES (every one is backed by 2026 TikTok performance data — follow them all):

HOOK (first 2 seconds decide 70% of retention):
- First spoken line = 8-14 words. A contrarian claim or direct call-out that opens a curiosity gap. NOT a description.
- Address the viewer directly ("you"/"your"). Self-relevant beats abstract.

COMPLETION (the #1 ranking signal):
- 8-12 SHORT scenes. Each scene's voiceover is ONE punchy sentence (fast pacing = +34% retention).
- Total narration 110-150 words (~45-55 seconds spoken).
- Build ONE open loop in the first 5 seconds; resolve it ONLY at the end.

SEARCH DISCOVERY (now as important as hashtags):
- Pick ONE core keyword phrase (what someone would type to find this). 
- Put it in the hook, in at least 2 on_screen_text labels, and in the first caption.

SAVES (we are weakest here — make every video save-worthy):
- The final spoken line must deliver a payoff AND explicitly invite a save (e.g. "Save this before you forget it.")
- ALSO loop the last line back to the hook's idea so it replays cleanly (rewatch = #1 distribution signal).

COMMENTS:
- Plant ONE line people will argue with or react to ("no way", "that's not true", "wait what").

CONTENT:
- ONE surprising, TRUE science fact/idea. Counterintuitive. Connects to the viewer's body/life/world.
- Visually deliverable with real stock footage (nature, space, ocean, animals, cities, body, weather, hands, household).
- No "imagine", no "did you know", no filler.

AVOID these recent topics entirely: {avoid}

For each scene give: one-sentence voiceover, a 2-4 word on_screen_text label (punchy, include the keyword where natural),
and a 2-5 word LITERAL stock-footage search query.

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
  "hashtags": ["#science", "#...", "..."],
  "render": {{"voice": "en-US-GuyNeural", "rate": "-5%", "resolution": "1080x1920"}}
}}"""

def call_groq(prompt):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
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

# basic safety net for HOW_TO output
UNSAFE = re.compile(r"\b(fire|flame|burn|burning|lit|light a|matches?|lighter|candle|stove|boil|boiling|"
                    r"microwave|oven|heat|hot water|electric|outlet|socket|battery acid|bleach|ammonia|"
                    r"swallow|drink|eat|ingest|knife|blade|razor|shatter|explode|explosion)\b", re.I)

def _clean(t):
    # strip code fences / markdown / stray quotes the model sometimes adds
    t = str(t).strip().strip("`").strip()
    return re.sub(r"\s+", " ", t)

def validate(m, job_name):
    for k in ["title", "hook", "script", "scenes", "captions", "hashtags"]:
        if k not in m:
            return f"missing {k}"
    if not isinstance(m["scenes"], list) or not (5 <= len(m["scenes"]) <= 14):
        return f"scene count {len(m.get('scenes', []))} out of range"

    # clean top-level text
    m["title"] = _clean(m["title"])[:90]
    m["hook"] = _clean(m["hook"])
    if not (5 <= len(m["hook"].split()) <= 16):
        return f"hook length {len(m['hook'].split())} words out of range"

    # scenes: clean, validate, dedup search queries so footage doesn't repeat
    seen_q = set()
    for i, s in enumerate(m["scenes"], 1):
        for k in ("voiceover", "on_screen_text", "search_query"):
            if not s.get(k):
                return f"scene {i} missing {k}"
            s[k] = _clean(s[k])
        s["on_screen_text"] = " ".join(s["on_screen_text"].split()[:4])  # cap label to 4 words
        if len(s["voiceover"].split()) > 28:
            return f"scene {i} voiceover too long"
        q = s["search_query"].lower()
        if q in seen_q:
            s["search_query"] = s["search_query"] + " cinematic"  # nudge variety
        seen_q.add(q)
        # numeric, sane duration
        try:
            s["duration"] = max(2, min(8, int(float(s.get("duration", 4)))))
        except Exception:
            s["duration"] = 4
        if s.get("motion") not in ("zoom_in", "zoom_out", "pan", "static"):
            s["motion"] = random.choice(["zoom_in", "zoom_out", "pan", "static"])

    # script length sanity (≈45-60s spoken = ~100-170 words)
    wc = len(_clean(m["script"]).split())
    if not (80 <= wc <= 200):
        return f"script word count {wc} out of range"
    m["script"] = _clean(m["script"])

    # captions / hashtags hygiene
    m["captions"] = [_clean(c) for c in m["captions"] if _clean(c)][:3] or [m["title"]]
    tags = []
    for h in m["hashtags"]:
        h = _clean(h).replace(" ", "")
        if not h.startswith("#"):
            h = "#" + h
        if h.lower() not in [t.lower() for t in tags]:
            tags.append(h)
    if "#science" not in [t.lower() for t in tags]:
        tags.insert(0, "#science")
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
    last_job = history[-1].get("viewer_job") if history else None
    jobs = [j for j in VIEWER_JOBS if j[0] != last_job] or VIEWER_JOBS
    job_name, job_desc = random.choice(jobs)
    print(f"[generate] job={job_name} avoiding={avoid[:80]}")

    manifest = None
    for attempt in range(4):
        try:
            raw = call_groq(build_prompt(job_name, job_desc, avoid))
            m = json.loads(raw)
            err = validate(m, job_name)
            if err:
                print(f"  attempt {attempt+1} invalid: {err}"); continue
            mt = m.get("metaphor", "").lower()
            if any(mt and mt in h.get("metaphor", "").lower() for h in history):
                print(f"  attempt {attempt+1} repeats topic, retrying"); continue
            manifest = m; break
        except Exception as e:
            print(f"  attempt {attempt+1} error: {e}")

    if not manifest:
        print("ERROR: could not generate a valid manifest"); sys.exit(1)

    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    save_memory(history, {"metaphor": manifest.get("metaphor", manifest["title"]),
                          "viewer_job": job_name, "title": manifest["title"]})
    print(f"[generate] wrote {manifest['title']!r} ({job_name}) -> {OUT_MANIFEST}")

if __name__ == "__main__":
    main()
