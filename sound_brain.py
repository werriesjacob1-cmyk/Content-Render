#!/usr/bin/env python3
"""Sound Brain v1 — restrained scene-aware sound design for Content Render.

This module is intentionally NOT wired into production. It provides:
- a typed sound-event contract;
- deterministic restraint rules so narration stays dominant;
- an ElevenLabs SFX adapter with a hard credit ceiling;
- a deterministic FFmpeg mix-plan builder for later integration.

Current ElevenLabs Sound Effects contract verified 2026-09-03:
POST https://api.elevenlabs.io/v1/sound-generation
model eleven_text_to_sound_v2
specified duration 0.5..30s, documented cost 40 credits/second.

The governing rule is subtle support, not trailer noise.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import argparse
import json
import math
import os
import subprocess
import urllib.error
import urllib.request

ELEVEN_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"
ELEVEN_SFX_MODEL = "eleven_text_to_sound_v2"
CREDITS_PER_SECOND = 40
VERIFIED_ON = "2026-09-03"


class SoundKind(str, Enum):
    AMBIENCE = "ambience"
    FOLEY = "foley"
    MECHANISM = "mechanism"
    TRANSITION = "transition"
    IMPACT = "impact"


DEFAULT_GAIN_DB = {
    SoundKind.AMBIENCE: -24.0,
    SoundKind.FOLEY: -20.0,
    SoundKind.MECHANISM: -19.0,
    SoundKind.TRANSITION: -21.0,
    SoundKind.IMPACT: -18.0,
}


@dataclass(frozen=True)
class SoundEvent:
    event_id: str
    kind: SoundKind
    start_s: float
    duration_s: float
    prompt: str
    scene_id: str = ""
    gain_db: float | None = None
    loop: bool = False

    def effective_gain_db(self) -> float:
        return DEFAULT_GAIN_DB[self.kind] if self.gain_db is None else float(self.gain_db)

    def validate(self, video_duration_s: float | None = None) -> list[str]:
        errors: list[str] = []
        if not self.event_id.strip(): errors.append("event_id required")
        if not self.prompt.strip(): errors.append("prompt required")
        if len(self.prompt) > 450: errors.append("prompt must be <=450 chars")
        if not math.isfinite(float(self.start_s)) or self.start_s < 0: errors.append("start_s must be finite and >=0")
        if not math.isfinite(float(self.duration_s)) or not (0.5 <= self.duration_s <= 30): errors.append("duration_s must be 0.5..30")
        gain = self.effective_gain_db()
        if not math.isfinite(gain) or gain > -12.0 or gain < -40.0:
            errors.append("gain_db must stay between -40 and -12 dB so narration remains dominant")
        if video_duration_s is not None and self.start_s + self.duration_s > float(video_duration_s) + 0.01:
            errors.append("event extends beyond video duration")
        if self.loop and self.kind not in {SoundKind.AMBIENCE}:
            errors.append("looping is reserved for ambience")
        return errors


@dataclass(frozen=True)
class SoundPlan:
    video_duration_s: float
    events: tuple[SoundEvent, ...]

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not math.isfinite(float(self.video_duration_s)) or self.video_duration_s <= 0:
            errors.append("video_duration_s must be finite and >0")
            return errors
        seen=set()
        for e in self.events:
            if e.event_id in seen: errors.append(f"duplicate event_id: {e.event_id}")
            seen.add(e.event_id)
            errors.extend(f"{e.event_id}: {x}" for x in e.validate(self.video_duration_s))
        max_events=max(2, math.ceil(self.video_duration_s / 60.0 * 5))
        if len(self.events) > max_events:
            errors.append(f"too many sound events: {len(self.events)} > restraint cap {max_events}")
        total=sum(e.duration_s for e in self.events)
        if total > self.video_duration_s * 0.35 + 0.01:
            errors.append("sound-effect coverage exceeds 35% of video duration")
        if sum(e.kind == SoundKind.IMPACT for e in self.events) > 1:
            errors.append("more than one impact is not allowed")
        return errors

    def estimated_credits(self) -> int:
        errors=self.validate()
        if errors: raise ValueError("; ".join(errors))
        return sum(math.ceil(e.duration_s * CREDITS_PER_SECOND) for e in self.events)


def build_sfx_prompt(event: SoundEvent) -> str:
    errors=event.validate()
    if errors: raise ValueError("; ".join(errors))
    restraint=(
        "subtle documentary ambience, no music, no voice, no cinematic braam"
        if event.kind == SoundKind.AMBIENCE else
        "clean realistic foley, no music, no voice, no exaggerated trailer effect"
    )
    if event.kind == SoundKind.MECHANISM:
        restraint="subtle explanatory mechanism sound, realistic and restrained, no music, no voice, no sci-fi exaggeration"
    elif event.kind == SoundKind.TRANSITION:
        restraint="very subtle short transition texture, no music, no voice, no dramatic whoosh"
    elif event.kind == SoundKind.IMPACT:
        restraint="single restrained impact accent, no music, no voice, no trailer braam, no explosion unless literally requested"
    return f"{event.prompt.strip()}. {restraint}."[:450]


def enforce_credit_budget(plan: SoundPlan, max_credits: int) -> int:
    if not isinstance(max_credits, int) or max_credits < 0:
        raise ValueError("max_credits must be a non-negative integer")
    estimate=plan.estimated_credits()
    if estimate > max_credits:
        raise ValueError(f"estimated SFX cost {estimate} credits exceeds hard ceiling {max_credits}")
    return estimate


def generate_eleven_sfx(event: SoundEvent, dest: str, api_key: str) -> dict:
    prompt=build_sfx_prompt(event)
    body={
        "text": prompt,
        "loop": bool(event.loop),
        "duration_seconds": float(event.duration_s),
        "prompt_influence": 0.7,
        "model_id": ELEVEN_SFX_MODEL,
    }
    url=ELEVEN_SFX_URL + "?output_format=mp3_44100_128"
    req=urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"xi-api-key":api_key,"Content-Type":"application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            data=r.read()
    except urllib.error.HTTPError as exc:
        detail=""
        try: detail=exc.read().decode("utf-8","replace")[:500]
        except Exception: pass
        raise RuntimeError(f"ElevenLabs SFX HTTP {exc.code}: {detail}") from exc
    if len(data)<256: raise RuntimeError("ElevenLabs SFX returned implausibly small audio")
    with open(dest,"wb") as f: f.write(data)
    return {
        "event_id":event.event_id,
        "provider":"elevenlabs",
        "model":ELEVEN_SFX_MODEL,
        "duration_s":event.duration_s,
        "estimated_credits":math.ceil(event.duration_s*CREDITS_PER_SECOND),
        "prompt":prompt,
        "file":os.path.basename(dest),
    }


def mix_filtergraph(plan: SoundPlan) -> str:
    """Build a deterministic FFmpeg filtergraph; input 0 narration, 1..N SFX."""
    errors=plan.validate()
    if errors: raise ValueError("; ".join(errors))
    parts=["[0:a]volume=1.0[narr]"]
    labels=[]
    for idx,e in enumerate(plan.events,1):
        delay=int(round(e.start_s*1000))
        gain=e.effective_gain_db()
        fade=min(0.12,max(0.03,e.duration_s/8))
        out=f"s{idx}"
        parts.append(
            f"[{idx}:a]atrim=0:{e.duration_s:.3f},asetpts=PTS-STARTPTS,"
            f"volume={gain:.1f}dB,afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={max(0,e.duration_s-fade):.3f}:d={fade:.3f},"
            f"adelay={delay}|{delay}[{out}]"
        )
        labels.append(f"[{out}]")
    inputs="[narr]"+"".join(labels)
    parts.append(f"{inputs}amix=inputs={1+len(labels)}:duration=first:normalize=0,alimiter=limit=0.95[out]")
    return ";".join(parts)


def plan_from_json(path: str) -> SoundPlan:
    with open(path,encoding="utf-8") as f: raw=json.load(f)
    events=[]
    for row in raw.get("events",[]):
        events.append(SoundEvent(
            event_id=str(row["event_id"]),kind=SoundKind(str(row["kind"])),
            start_s=float(row["start_s"]),duration_s=float(row["duration_s"]),
            prompt=str(row["prompt"]),scene_id=str(row.get("scene_id",'')),
            gain_db=(None if row.get("gain_db") is None else float(row["gain_db"])),
            loop=bool(row.get("loop",False)),
        ))
    return SoundPlan(float(raw["video_duration_s"]),tuple(events))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan",required=True)
    ap.add_argument("--max-credits",type=int,required=True)
    ap.add_argument("--out-dir",default="sound_brain")
    ap.add_argument("--plan-only",action="store_true")
    args=ap.parse_args()
    plan=plan_from_json(args.plan)
    credits=enforce_credit_budget(plan,args.max_credits)
    os.makedirs(args.out_dir,exist_ok=True)
    report={"verified_on":VERIFIED_ON,"estimated_credits":credits,"event_count":len(plan.events),"events":[],"plan_only":bool(args.plan_only)}
    with open(os.path.join(args.out_dir,"mix_filtergraph.txt"),"w") as f: f.write(mix_filtergraph(plan)+"\n")
    if args.plan_only:
        with open(os.path.join(args.out_dir,"report.json"),"w") as f: json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2)); print("PLAN ONLY: zero SFX calls made."); return
    key=os.getenv("ELEVENLABS_API_KEY","")
    if not key: raise SystemExit("ELEVENLABS_API_KEY required for SFX generation")
    for e in plan.events:
        dest=os.path.join(args.out_dir,f"{e.event_id}.mp3")
        report["events"].append(generate_eleven_sfx(e,dest,key))
    with open(os.path.join(args.out_dir,"report.json"),"w") as f: json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
