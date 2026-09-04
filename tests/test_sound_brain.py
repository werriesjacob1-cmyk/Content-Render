#!/usr/bin/env python3
"""Zero-network regressions for Sound Brain v1."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sound_brain as S


def check(cond, label):
    if not cond: raise AssertionError(label)
    print(f"PASS {label}")


def plan():
    return S.SoundPlan(30.0,(
        S.SoundEvent("amb1",S.SoundKind.AMBIENCE,0.0,3.0,"quiet underwater reef ambience",scene_id="1"),
        S.SoundEvent("mech1",S.SoundKind.MECHANISM,12.0,2.0,"brief cavitation snap and bubble collapse",scene_id="3"),
    ))


def test_restraint_and_budget():
    p=plan()
    check(not p.validate(),"restrained two-event plan validates")
    check(p.estimated_credits()==200,"3s + 2s explicit SFX cost = 200 credits")
    check(S.enforce_credit_budget(p,200)==200,"exact credit ceiling accepted")
    try:
        S.enforce_credit_budget(p,199); raise AssertionError("budget should fail")
    except ValueError as e:
        check("exceeds hard ceiling" in str(e),"one-credit-under ceiling rejected")
    noisy=S.SoundPlan(30.0,tuple(
        S.SoundEvent(f"x{i}",S.SoundKind.TRANSITION,i*2,1,"transition") for i in range(3)
    ))
    check(any("too many" in x for x in noisy.validate()),"short video cannot accumulate transition spam")
    impacts=S.SoundPlan(30.0,(
        S.SoundEvent("i1",S.SoundKind.IMPACT,2,1,"impact"),
        S.SoundEvent("i2",S.SoundKind.IMPACT,8,1,"impact"),
    ))
    check(any("impact" in x for x in impacts.validate()),"multiple cinematic impacts rejected")


def test_narration_dominance_and_prompting():
    e=S.SoundEvent("e",S.SoundKind.MECHANISM,1,1.5,"small electrical crack")
    check(e.effective_gain_db()<=-18,"default SFX gain remains well below narration")
    prompt=S.build_sfx_prompt(e)
    check("no music" in prompt and "no voice" in prompt,"SFX prompt excludes competing music/voice")
    check("no sci-fi exaggeration" in prompt,"mechanism sound explicitly resists theatrical exaggeration")
    too_loud=S.SoundEvent("loud",S.SoundKind.FOLEY,1,1,"tap",gain_db=-6)
    check(any("narration" in x for x in too_loud.validate()),"SFX cannot be mixed near narration level")


def test_mix_graph():
    graph=S.mix_filtergraph(plan())
    check("[0:a]volume=1.0[narr]" in graph,"narration is preserved at full level")
    check("adelay=12000|12000" in graph,"event timing is deterministic")
    check("volume=-24.0dB" in graph and "volume=-19.0dB" in graph,"per-kind restrained gains enter mix")
    check("amix=inputs=3:duration=first:normalize=0" in graph,"mix follows narration duration")
    check("alimiter=limit=0.95" in graph,"final mix gets peak protection")


def test_provider_contract_without_network():
    captured={}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def read(self): return b"ID3"+b"0"*300
    old=S.urllib.request.urlopen
    def fake(req,timeout=90):
        captured["url"]=req.full_url
        captured["headers"]={k.lower():v for k,v in req.header_items()}
        captured["body"]=json.loads(req.data.decode("utf-8"))
        return FakeResponse()
    S.urllib.request.urlopen=fake
    try:
        with tempfile.TemporaryDirectory() as td:
            dest=os.path.join(td,"sfx.mp3")
            meta=S.generate_eleven_sfx(plan().events[1],dest,"key")
            check(os.path.getsize(dest)>256,"generated SFX bytes are persisted")
    finally:
        S.urllib.request.urlopen=old
    check(captured["url"].startswith("https://api.elevenlabs.io/v1/sound-generation"),"current ElevenLabs SFX endpoint used")
    check(captured["body"]["model_id"]=="eleven_text_to_sound_v2","current SFX model used")
    check(captured["body"]["duration_seconds"]==2.0,"explicit duration controls cost")
    check(abs(captured["body"]["prompt_influence"]-0.7)<0.001,"literal prompt adherence preferred")
    check(meta["estimated_credits"]==80,"provider metadata preserves credit estimate")


def test_json_plan_loader():
    raw={"video_duration_s":20,"events":[{"event_id":"a","kind":"foley","start_s":2,"duration_s":1,"prompt":"small shell tap"}]}
    with tempfile.TemporaryDirectory() as td:
        p=os.path.join(td,"plan.json")
        with open(p,"w") as f: json.dump(raw,f)
        loaded=S.plan_from_json(p)
    check(loaded.events[0].kind==S.SoundKind.FOLEY,"JSON sound plan maps to typed event")
    check(not loaded.validate(),"loaded sound plan validates")


if __name__=="__main__":
    test_restraint_and_budget(); test_narration_dominance_and_prompting(); test_mix_graph(); test_provider_contract_without_network(); test_json_plan_loader()
    print("sound_brain tests: PASS")
