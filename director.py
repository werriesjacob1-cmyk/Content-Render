"""The "director" layer: pure, zero-network decisions made between the script and
the footage/mix stages. main.py does the I/O; everything decidable lives here so it
can be unit-tested without ffmpeg, a network or an LLM.

  * shot list   -- 2-3 literal, filmable shots per narrated line, each with a reason
                   (behind DIRECTOR_SHOTLIST, default OFF until the user has watched a
                   render made with it);
  * mood        -- a per-scene grade nudge (hook / build / turn / payoff);
  * punch-in    -- a subtle zoom bump on the scene's key word;
  * sound plan  -- a quiet ffmpeg-generated bed: room tone, a soft riser into the
                   payoff, a low impact on the reveal. Cut whooshes stay OFF.
"""
from __future__ import annotations

import json
import re

# ---------------------------------------------------------------- shot list
MAX_SHOTS_PER_SCENE = 3
MIN_SHOTS_PER_SCENE = 2
# Words that name an idea, not something a camera can point at. A shot built on one
# of these is where "random stock" comes from, so it is rejected before any search.
_ABSTRACT = re.compile(
    r"\b(concept|idea|ideas|system|systems|network|networks|process|processes|theory|"
    r"mystery|secret|power|energy|time|future|past|evolution|intelligence|knowledge|"
    r"information|connection|connections|complexity|infinity|reality|life|nature|"
    r"science|universe|magic|beauty|wonder)\b", re.I)


def shot_is_filmable(query):
    """A shot query must be 2-5 plain words naming something a camera can film."""
    words = re.findall(r"[A-Za-z]+", query or "")
    if not (2 <= len(words) <= 5):
        return False
    return not _ABSTRACT.search(query or "")


def build_shotlist_prompt(scenes):
    """The single LLM prompt that asks for a shot list for every scene."""
    lines = "\n".join(f"{i}. {s.get('voiceover', '').strip()}" for i, s in enumerate(scenes, 1))
    return (
        "You are the director of a vertical science short. For EACH numbered narration line, "
        f"list {MIN_SHOTS_PER_SCENE}-{MAX_SHOTS_PER_SCENE} LITERAL shots a stock-footage search can find: a "
        "concrete thing a camera can film (an animal, object, place, process, microscope view), "
        "2-5 plain words, subject first. Never an idea, never a metaphor. Give a one-line reason "
        "tying each shot to what is being said.\n"
        'Reply with JSON only: {"scenes":[{"n":1,"shots":[{"query":"honey fungus mushrooms",'
        '"reason":"shows the organism being named"}]}]}\n\nNARRATION:\n' + lines
    )


def parse_shotlist(text, n_scenes):
    """{scene_index(0-based): [{"query","reason"}, ...]} from the model's reply.
    Unfilmable or duplicate shots are dropped; a scene left with no shot is simply
    absent, so the caller keeps that scene's existing search_query. Never raises."""
    try:
        m = re.search(r"\{.*\}", text or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for item in (data.get("scenes") or []):
        try:
            i = int(item.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= i < n_scenes):
            continue
        seen, shots = set(), []
        for sh in (item.get("shots") or []):
            q = re.sub(r"\s+", " ", str((sh or {}).get("query", ""))).strip()
            if q.lower() in seen or not shot_is_filmable(q):
                continue
            seen.add(q.lower())
            shots.append({"query": q, "reason": str((sh or {}).get("reason", "")).strip()[:140]})
        if shots:
            out[i] = shots[:MAX_SHOTS_PER_SCENE]
    return out


def apply_shotlist(scenes, shotlist):
    """Attach shots to scenes. The FIRST shot becomes the scene's search_query (so the
    existing relevance judge, fal and still fallbacks all gate it exactly as before);
    the rest are kept on scene["shots"] for the extra-clip search. Returns the count
    of scenes changed."""
    n = 0
    for i, shots in shotlist.items():
        if 0 <= i < len(scenes) and shots:
            scenes[i]["shots"] = shots
            scenes[i]["search_query"] = shots[0]["query"]
            n += 1
    return n


def shot_queries(scene):
    """Extra-clip search queries for a scene: its directed shots after the first."""
    return [s["query"] for s in (scene.get("shots") or [])[1:] if s.get("query")]


# --------------------------------------------------------------------- mood
MOODS = ("hook", "build", "turn", "payoff")

# ffmpeg filter fragments appended AFTER the profile grade. Deliberately mild: the
# profile grade is already heavy (saturation 1.3), so a mood is a nudge, not a look.
_MOOD_FILTER = {
    "hook": ",eq=contrast=1.05:saturation=1.05",
    "build": "",
    "turn": ",colorbalance=bs=0.04:rs=-0.03",
    "payoff": ",colorbalance=rs=0.05:bs=-0.04,eq=contrast=1.03",
}


def scene_mood(idx, n_scenes, voiceover=""):
    """hook = first scene; payoff = last; turn = a scene that asks a question (the
    re-hook beats); build = everything else. idx is 0-based."""
    if idx <= 0:
        return "hook"
    if idx >= n_scenes - 1:
        return "payoff"
    return "turn" if "?" in (voiceover or "") else "build"


def mood_filter(mood):
    return _MOOD_FILTER.get(mood, "")


# ----------------------------------------------------------------- punch-in
PUNCH_AMOUNT = 0.05      # peak extra zoom (5%)
PUNCH_HALF_S = 0.30      # ramp up and back down around the key word


def keyword_time(scene_words, keyword_tokens):
    """Scene-local start (s) of the first word that is one of the video's keyword
    tokens, or None. scene_words: [(word, start_s, end_s)] already relative to the
    scene start."""
    kt = {t.upper() for t in (keyword_tokens or [])}
    for w, st, _ in scene_words:
        if re.sub(r"[^A-Za-z0-9]", "", w).upper() in kt:
            return float(st)
    return None


def punch_in_filter(t0, w=1080, h=1920, amount=PUNCH_AMOUNT, half=PUNCH_HALF_S):
    """ffmpeg fragment (leading comma) that bumps the zoom by `amount` around t0 and
    returns to 1.0, as a triangle: z(t) = amount * max(0, 1 - |t - t0| / half).
    Commas inside the expressions are escaped for -filter_complex."""
    if t0 is None or t0 < 0:
        return ""
    z = f"{amount}*max(0\\,1-abs(n/30-{t0:.3f})/{half})"
    # crop's default centring uses the size it was CONFIGURED with, not the per-frame
    # scaled size (measured: the zoom drifted toward the bottom-right), so the centre
    # offset is computed from the same z(n) expression.
    return (f",scale=w='trunc({w}*(1+{z})/2)*2':h='trunc({h}*(1+{z})/2)*2':eval=frame,"
            f"crop={w}:{h}:x='trunc({w}*{z}/2)':y='trunc({h}*{z}/2)'")


# ------------------------------------------------------------- sound design
ROOM_VOL = 0.04          # room tone gain (very low pink noise, lowpassed)
RISER_VOL = 0.20
IMPACT_VOL = 0.90
RISER_S = 1.4


def sound_plan(total_dur, payoff_start):
    """Events for the quiet bed: [(kind, start_s, length_s)].
      room   -- the whole video;
      riser  -- a soft swell that ENDS at the payoff scene's first word;
      impact -- one low thud ON that moment (the reveal).
    payoff_start None or too early -> room tone only."""
    total = float(total_dur)
    ev = [("room", 0.0, total)]
    if payoff_start is not None and payoff_start > RISER_S + 0.5 and payoff_start < total - 0.3:
        ev.append(("riser", round(payoff_start - RISER_S, 3), RISER_S))
        ev.append(("impact", round(payoff_start, 3), 0.9))
    return ev
