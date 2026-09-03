#!/usr/bin/env python3
"""Grow topic_bank.json toward ~500 genuinely-WTF facts WITHOUT losing quality.

Hand-typing hundreds of facts injects errors, so this generates them with the LLM
(Gemini-first + grounded, reusing generate.py's provider chain), enforces a strict
"would-someone-actually-stop-scrolling" bar, dedups against the existing bank, and
appends only the survivors. Incremental + idempotent: run it repeatedly (as LLM
quota allows) and it accumulates toward the target over days, checkpointing the
bank after every batch.

Usage:
  python expand_bank.py [--target 500] [--batch 25]
Env: same keys as generate.py (GEMINI_API_KEY etc). GEMINI_GENERATION=1 = Gemini-first.
"""
import difflib
import json
import os
import re
import sys

import generate as G  # reuse call_groq (provider chain + keys)

BANK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_bank.json")
REQUIRED = {"id", "domain", "fact", "angle", "key_terms", "whatif", "wow", "queries"}

# Pure magnitude/scale/counting patterns — the boring "big number" facts the bank
# must NOT accumulate (mirrors the generation rubric's magnitude rejection).
BANNED = re.compile(
    r"\b(how many|how much|times (bigger|smaller|larger|heavier|more|faster)|"
    r"combinations|permutations|factorial|more .{0,20}than (stars|atoms|grains|sand|"
    r"people|cells))\b", re.I)


# The bank had drifted toward generic "What if we could harness this to build
# technology?" prompts. Those application fantasies are not curiosity gaps
# about the science itself; they steer generation away from the verified fact
# and toward invented claims. New entries must ask a question ABOUT the existing
# phenomenon, not propose a product/research agenda.
GENERIC_APPLICATION_WHATIF_RE = re.compile(
    r"^\s*what if we could\b.{0,220}\b(harness|create|develop|use|apply|replicate|"
    r"improve|build|design|turn|learn from)\b"
    r"|\b(new technolog(?:y|ies)|sustainable (?:energy|future)|resource allocation|"
    r"urban planning|transportation systems?)\b",
    re.I)

# Broad overview language that looks like a science topic but is not itself a
# surprising claim. It is rejected only when the entry also lacks a concrete
# specificity signal, so a genuinely specific fact is not punished for using
# one of these words incidentally.
VAGUE_FACT_RE = re.compile(
    r"\b(complex ecosystems?|delicate balance|crucial role|critical role|"
    r"significant (?:impact|effects?|role)|important ecosystem services?|"
    r"vast array|fascinating stories?|valuable insights?|unique ability|"
    r"some of the most diverse and complex)\b",
    re.I)

SPECIFICITY_RE = re.compile(
    r"\d|\b(because|due to|through|when|causes?|contains?|produces?|converts?|"
    r"absorbs?|reflects?|expands?|contracts?|rotates?|orbits?|releases?|forms?|"
    r"detects?|generates?|breaks down|freezes?|boils?|moves?|travels?)\b"
    r"|\b[A-Z][a-z]{2,}\b",
    re.I)


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _domain_counts(facts):
    """Counts by FAMILY (see generate.DOMAIN_FAMILIES), not raw domain string.
    Without this, "thin domain" detection below chases split-domain strings
    (astronomy/mycology/botany/marine/oceanography) that are really part of
    an already-well-stocked family (space/fungi/plants/ocean) under a
    different name -- actively perpetuating the exact fragmentation the
    render-selection dedup logic was built to avoid, by asking the LLM for
    MORE facts in a domain that already has plenty, just spelled differently."""
    c = {}
    for f in facts:
        fam = G._domain_family(f.get("domain", "?"))
        c[fam] = c.get(fam, 0) + 1
    return c


def _too_similar(fact_text, existing_norms, thresh=0.62):
    """True if this fact is near-duplicate of one already in the bank (fuzzy)."""
    fn = _norm(fact_text)
    if not fn:
        return True
    for en in existing_norms:
        if difflib.SequenceMatcher(None, fn, en).ratio() > thresh:
            return True
    return False


def _extract_json_array(raw):
    """Pull the first [...] JSON array out of a model reply (tolerant of prose)."""
    if not raw:
        raise ValueError("empty reply")
    a, b = raw.find("["), raw.rfind("]")
    if a == -1 or b == -1 or b <= a:
        raise ValueError("no JSON array in reply")
    return raw[a:b + 1]


def _clean_id(raw_id, fact):
    fid = re.sub(r"[^a-z0-9_]", "", str(raw_id or "").lower().replace(" ", "_").replace("-", "_"))
    if not fid:  # fall back to a slug of the fact
        fid = "_".join(_norm(fact).split()[:4])
    return fid.strip("_")[:48]


def accept_fact(f, have_ids, have_norms):
    """Strict gate: schema-complete, novel, WTF-not-magnitude. Returns cleaned
    fact dict or None. Pure/testable (no network)."""
    if not isinstance(f, dict) or not REQUIRED <= set(f):
        return None
    if not isinstance(f.get("key_terms"), list) or not isinstance(f.get("queries"), list):
        return None
    if not f["key_terms"] or not f["queries"]:
        return None
    fact = str(f.get("fact", "")).strip()
    if len(fact) < 20:
        return None
    if BANNED.search(fact + " " + str(f.get("wow", ""))):
        return None
    whatif = str(f.get("whatif", "")).strip()
    wow = str(f.get("wow", "")).strip()
    if GENERIC_APPLICATION_WHATIF_RE.search(whatif):
        return None
    if VAGUE_FACT_RE.search(fact) and not SPECIFICITY_RE.search(fact):
        return None
    if VAGUE_FACT_RE.search(wow) and not SPECIFICITY_RE.search(wow):
        return None
    fid = _clean_id(f.get("id"), fact)
    if not fid or fid in have_ids:
        return None
    if _too_similar(fact, have_norms):
        return None
    # canonicalize to the domain FAMILY's name (e.g. "astronomy" -> "space") so
    # newly-added facts heal the existing split-domain fragmentation instead of
    # adding another instance of it -- see _domain_counts above.
    raw_domain = str(f.get("domain", "misc")).lower().split()[0]
    return {"id": fid, "domain": G._domain_family(raw_domain),
            "fact": fact, "angle": str(f.get("angle", ""))[:60],
            "key_terms": [str(k) for k in f["key_terms"]][:5],
            "whatif": whatif, "wow": wow,
            "queries": [str(q) for q in f["queries"]][:4]}


def _prompt(existing_titles, thin_domains, n):
    ex = "; ".join(existing_titles[-140:])  # cap tokens; recent titles for dedup
    return f"""You expand a viral science-shorts idea bank. Give me EXACTLY {n} NEW facts, each a genuine "WAIT, WHAT?!" — the kind that makes someone stop mid-scroll and say "no way that's real."

HARD BAR — reject your own weak ideas before writing:
- WTF / delightful / shocking-but-TRUE and verifiable. Reaction must be "that can't be real" then "...it IS".
- It must REFRAME reality, expose a hidden mechanism, or be wildly counterintuitive. NOT trivia, NOT a dictionary definition.
- BANNED: pure size/scale/counting ("how many", "N times bigger", "more X than Y", combinations, factorials). Magnitude alone is boring and will be rejected.
- Concrete and FILMABLE with ordinary stock footage (give plain visual search queries — no jargon in the queries).
- Everyday words a 12-year-old understands. Never a term you'd have to look up.
- The FACT must itself be a specific surprising claim/mechanism, NOT a broad overview like "forests are complex ecosystems" or "X plays a crucial role".
- The WHATIF must open curiosity about what the phenomenon ALREADY does/is/means. BANNED: "What if we could harness/use/develop/apply this to make technology", sustainability pitches, invention ideas, or research agendas. Those leave the science and invite fabrication.
- The WOW must be a second independently checkable detail, not "this is incredible/complex/important".
- DOMAIN must describe the literal scientific subject, not an application or neighboring field. Use a stable family label where possible (animals, biology, body, chemistry, earth, fungi, history, language, light, materials, math, nature, neurology, ocean, physics, plants, psychology, senses, space).
- Spread across domains; PREFER these thin ones: {", ".join(thin_domains)}.

Do NOT repeat any of these existing facts: {ex}

Return ONLY a JSON array. Each item EXACTLY these keys:
{{"id":"snake_case_id","domain":"one_word_domain","fact":"the wow claim, 1-2 sentences","angle":"short tag","key_terms":["real","words","the script says"],"whatif":"a 'What if...' that opens the curiosity gap, 1-2 sentences","wow":"an escalation detail that makes it even wilder","queries":["filmable search 1","filmable search 2","filmable search 3"]}}"""


def main():
    args = sys.argv[1:]

    def opt(name, default):
        return args[args.index(name) + 1] if name in args else default

    target = int(opt("--target", "500"))
    batch = int(opt("--batch", "25"))
    add_cap = int(opt("--add", "0"))  # max facts to add THIS run (0 = up to target).
    #                                   Keeps a nightly run's LLM spend bounded so
    #                                   the bank climbs to the target over days, not
    #                                   in one expensive blast.
    data = json.load(open(BANK))
    facts = data["facts"]
    have_ids = {f["id"] for f in facts}
    have_norms = [_norm(f["fact"]) for f in facts]
    titles = [f["fact"][:70] for f in facts]
    added = 0
    while len(facts) < target and (add_cap <= 0 or added < add_cap):
        thin = sorted((d for d, c in _domain_counts(facts).items() if c < 6),
                      key=lambda d: _domain_counts(facts)[d]) or \
               ["math", "chemistry", "senses", "light", "fungi", "geology", "history", "weather"]
        need = min(batch, target - len(facts))
        if add_cap > 0:
            need = min(need, add_cap - added)
        try:
            raw = G.call_groq(_prompt(titles, thin, need))
            arr = json.loads(_extract_json_array(raw))
        except Exception as e:  # noqa: BLE001
            print(f"[expand] batch failed ({type(e).__name__}: {str(e)[:120]}) — stopping")
            break
        got = 0
        for f in (arr if isinstance(arr, list) else []):
            ok = accept_fact(f, have_ids, have_norms)
            if ok:
                facts.append(ok)
                have_ids.add(ok["id"])
                have_norms.append(_norm(ok["fact"]))
                titles.append(ok["fact"][:70])
                got += 1
        added += got
        json.dump(data, open(BANK, "w"), indent=2, ensure_ascii=False)  # checkpoint
        print(f"[expand] +{got} accepted this batch — bank now {len(facts)}")
        if got == 0:
            print("[expand] nothing new cleared the bar (dedup/quality/quota) — stopping")
            break
    print(f"[expand] DONE: +{added} facts, bank at {len(facts)} (target {target})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
