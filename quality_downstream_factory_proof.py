#!/usr/bin/env python3
"""Real zero-provider downstream factory proof.

This integration harness deliberately starts *after* Writer certification with a
known-good sealed manifest. It produces actual scene MP4s and exercises the real
Content Render downstream primitives that do not require network/provider calls:

- pre-search visual-intent/continuity bible;
- actual FFmpeg scene media with audio;
- ``main.build_body_concat``;
- ``main.build_ass`` karaoke-caption generation;
- real ASS caption burn;
- ``main._ensure_music_bed`` (committed bed / procedural fallback);
- narration/music sidechain mix + the shared measured master;
- actual ``out/final.mp4``;
- ``quality_audio_qa`` against that encoded MP4;
- measured scene timeline via ``quality_science_render``;
- final per-scene asset lineage;
- deterministic holistic-QA repair target;
- bounded scene replacement + reassembly + local re-QA, proving unaffected
  scene files remain byte-identical.

It makes ZERO HTTP/provider calls. The synthetic visual sources are intentional:
this proves the manufacturing/control path independently of stock/API availability.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import urllib.request
import sys
from typing import Any

import final_video_qa as FQ
import main as legacy
import quality_asset_lineage as QAL
import delivery_contract as DC
import delivery_master as DM
import quality_audio_qa as AQA
import quality_postrender_review as PQR
import quality_repair_controller as RC
import quality_science_render as QSR
import quality_visual_bible as QVB
import quality_evidence as QE


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-1800:]}")


def _manifest() -> dict[str, Any]:
    # 40 spoken words / ~16 seconds => ~150 WPM, inside local audio-QA pacing
    # diagnostics. Claims are deliberately mundane fixture truths, not production
    # science assertions.
    lines = [
        "This test opens with one literal subject and a clear visual promise now.",
        "The next scene demonstrates a process while keeping that same subject easy to follow.",
        "A comparison then changes the framing without replacing the subject with unrelated footage.",
        "The payoff returns to concrete proof and closes the visual story cleanly for viewers.",
    ]
    queries = ["fixture subject wide", "fixture subject process", "fixture subject comparison", "fixture subject proof"]
    scenes = []
    for idx, (vo, q) in enumerate(zip(lines, queries), 1):
        scenes.append({
            "id": idx,
            "_v2_role": "hook" if idx == 1 else ("payoff" if idx == 4 else "beat"),
            "voiceover": vo,
            "search_query": q,
            "source_claim_ids": [f"c{idx}"],
            "motion": "zoom_in",
            "duration": 4.0,
            "on_screen_text": "",
        })
    return {
        "title": "Downstream Factory Proof",
        "hook": lines[0],
        "payoff": lines[-1],
        "hook_source_claim_ids": ["c1"],
        "payoff_source_claim_ids": ["c4"],
        "scenes": scenes,
        "script": " ".join(lines),
        "captions": ["Factory proof"],
        "hashtags": ["#science"],
        "keyword": "factory proof",
        "vibe": "awe",
        "treatment": "HIDDEN_MECHANISM",
        "_semantic_verified": True,
        "_v2_spoken_scene_count": 4,
    }


def _make_scene(path: Path, idx: int, duration: float, variant: int = 0) -> None:
    # testsrc2 gives motion, so the proof is not a collection of static images.
    # Hue rotation makes the replacement demonstrably different while retaining
    # identical duration/audio structure.
    hue = (idx * 43 + variant * 71) % 360
    freq = 170 + idx * 38
    draw = f"drawbox=x=20+mod(t*90\\,300):y=90+{idx*45}:w=120:h=120:color=white@0.55:t=fill"
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=540x960:rate=30:duration={duration:.3f}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={duration:.3f}",
        "-vf", f"hue=h={hue},{draw},format=yuv420p",
        "-af", "volume=0.16",
        "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "29",
        "-c:a", "aac", "-b:a", "96k", str(path),
    ])


def _make_captioned(body: Path, ass: Path, dest: Path, duration: float) -> None:
    fade_dur = 0.45
    fade_start = max(0.0, duration - fade_dur)
    run([
        "ffmpeg", "-y", "-i", str(body),
        "-vf", f"ass='{ass}':fontsdir='{legacy.FONTS_DIR}',fade=t=out:st={fade_start:.3f}:d={fade_dur:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        # Delivery args even on the caption intermediate: both proofs master
        # FROM this file, so a 96 kbit/s intermediate made them master a harsher
        # signal than production, whose intermediate uses the ffmpeg default.
        *DC.delivery_audio_encode_args(), str(dest),
    ])


def _mix_final(captioned: Path, dest: Path, duration: float,
               work_dir: Path | None = None) -> dict[str, Any]:
    """Mix -> SHARED measured master -> mux. Identical sequence to production.

    The mix and the master are separate steps on purpose. Mastering has to
    MEASURE its own intermediate result to be accurate (loudnorm's single-pass
    error on realistic material is ~2.4 dB), and a measurement cannot happen
    inside one filter graph. Splitting also means the delivered audio here and
    in main.py comes from the same function rather than two filter strings that
    merely look alike.
    """
    legacy._apply_vibe("awe")
    # Mastering scratch must NOT live inside dest's directory. `out/` is what the
    # workflow uploads as evidence, and the measured master writes four
    # uncompressed WAVs per assembly -- 12.3 MB of stage intermediates that
    # nobody reads, since every measurement they carry is already in the master
    # report this function returns.
    #
    # This shipped in the mastering rewrite and went unnoticed: it silently added
    # ~12 MB to every factory-proof artifact, which is a real share of the day
    # the account hit 100% of its Actions storage. Production never had the bug
    # -- main.py masters into WORK, which is already separate from OUT.
    work = Path(work_dir) if work_dir is not None else Path(
        tempfile.mkdtemp(prefix="delivery_master_"))
    work = work / f"master_{Path(dest).stem}"
    work.mkdir(parents=True, exist_ok=True)
    tag = Path(dest).stem
    mixed = work / f"mixed_{tag}.wav"

    bed = legacy._ensure_music_bed(duration)
    if bed and Path(bed).is_file():
        # Mirror production's voice-keyed duck. Audio only: no mastering here.
        run([
            "ffmpeg", "-y", "-i", str(captioned), "-stream_loop", "-1", "-i", str(bed),
            "-filter_complex",
            f"[1:a]{legacy._vibe_music_filter()}[m_raw];"
            "[m_raw][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=25:release=400:makeup=1[m];"
            "[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map", "[a]", "-ar", str(DC.DELIVERY_SAMPLE_RATE), "-shortest", str(mixed),
        ])
        music_info = {"music_bed": str(bed), "sidechain_duck": True}
    else:
        run(["ffmpeg", "-y", "-i", str(captioned), "-vn",
             "-ar", str(DC.DELIVERY_SAMPLE_RATE), str(mixed)])
        music_info = {"music_bed": "", "sidechain_duck": False}

    mastered = work / f"mastered_{tag}.wav"
    master = DM.master_audio(mixed, mastered, work)
    run([
        "ffmpeg", "-y", "-i", str(captioned), "-i", str(mastered),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        *DC.delivery_audio_encode_args(), "-shortest", str(dest),
    ])
    return {**music_info, "master": master}


def _repair_verdict() -> FQ.FinalQAVerdict:
    return FQ.FinalQAVerdict(
        overall_score=7.2,
        hook_visual=9.0,
        narration_visual_match=6.0,
        scientific_visual_integrity=9.0,
        visual_variety=8.0,
        pacing=8.0,
        caption_legibility=9.0,
        continuity=8.0,
        payoff_visual=9.0,
        ai_artifact_control=10.0,
        critical_failures=(),
        violations=(FQ.QAViolation(
            "narration_visual_match", "major", 2,
            "proof fixture: middle visual intentionally selected for bounded replacement",
        ),),
        summary="Synthetic proof verdict with one bounded middle defect.",
        must_fix=("replace only the affected middle scene",),
        provider="fixture",
        model="deterministic-zero-provider",
    )


def proof(out_root: str) -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    root = Path(out_root).resolve()
    if root.exists():
        shutil.rmtree(root)
    work = root / "work"
    out = root / "out"
    repaired_dir = root / "repaired_scenes"
    work.mkdir(parents=True)
    out.mkdir(parents=True)

    manifest = _manifest()
    manifest_path = root / "manifest.json"
    QE.write_json(manifest_path, manifest)
    visual_bible = QVB.write_visual_bible(manifest, out / "visual_bible.json")

    # MEASURE the zero-network claim instead of asserting it. These counters used
    # to be hardcoded literals, so the proof's headline safety property was true
    # only by inspection -- a future import could quietly add an HTTP call and
    # every check would still report 0. Every outbound socket/urllib path used by
    # this codebase is counted, and any call trips the counter AND fails the run.
    net_calls: list[str] = []
    _real_urlopen = urllib.request.urlopen
    _real_socket_connect = socket.socket.connect
    _real_create_connection = socket.create_connection

    def _blocked_urlopen(*a, **k):
        net_calls.append(f"urlopen({str(a[0])[:80]})")
        raise AssertionError("factory proof attempted an HTTP call")

    def _blocked_connect(self, address, *a, **k):
        net_calls.append(f"socket.connect({address})")
        raise AssertionError("factory proof attempted a network connection")

    def _blocked_create_connection(address, *a, **k):
        net_calls.append(f"create_connection({address})")
        raise AssertionError("factory proof attempted a network connection")

    urllib.request.urlopen = _blocked_urlopen
    socket.socket.connect = _blocked_connect
    socket.create_connection = _blocked_create_connection

    old_work, old_out = legacy.WORK, legacy.OUT
    legacy.WORK, legacy.OUT = str(work), str(out)
    try:
        legacy.WORD_TIMINGS[:] = []
        scene_files: list[str] = []
        segments = []
        lineage_entries: list[QAL.AssetLineageEntry] = []
        for idx, scene in enumerate(manifest["scenes"], 1):
            p = work / f"s{idx}.mp4"
            _make_scene(p, idx, 4.0)
            scene_files.append(str(p))
            segments.append((str(p), 4.0))
            contract = QAL.bible_scene(visual_bible, str(scene["id"]))
            lineage_entries.append(QAL.AssetLineageEntry(
                scene_id=str(scene["id"]), scene_index=idx,
                visual_intent=str(contract.get("intent") or "demonstrate"),
                subject_id=str(contract.get("subject_id") or "fixture"),
                subject=str(contract.get("subject") or "fixture subject"),
                renderer_kind="deterministic_fixture_video",
                output_file=str(p), duration_s=4.0,
                selected_asset_ids=(f"fixture-{idx}",),
                source_family=str(contract.get("preferred_source_family") or "deterministic_fixture"),
                source_claim_ids=tuple(scene["source_claim_ids"]),
                continuity_with=tuple(contract.get("continuity_with") or ()),
                attributable=True,
                notes="zero-provider moving fixture; real FFmpeg output",
            ))
        lineage = QAL.write_lineage(lineage_entries, out / "final_asset_lineage.json")

        def _finish_assembly(files, dest) -> dict[str, Any]:
            """Concat -> captions -> music bed -> shared master, for ANY scene set.

            Both the first assembly and every repaired re-assembly must go
            through this identical finishing path. They used to diverge: the
            repair re-assembled with a bare build_body_concat -- no captions,
            no music bed, no mastering -- and was then judged by the SAME audio
            QA gate that requires normalized -14 LUFS. That asymmetry is why
            the repaired artifact could never pass re-QA, and in production it
            would mean a targeted repair either always fails the gate or ships
            an unmastered, caption-less video.

            Parity is structural rather than promised: there is one call site
            for _mix_final, so a repaired artifact cannot be mastered by a
            different sequence than the original without deleting this function.
            """
            files = [str(f) for f in files]
            dest = Path(dest)
            tag = dest.stem
            body_path = work / f"body_{tag}.mp4"
            legacy.build_body_concat(files, str(body_path))
            durs = [float(legacy.ffprobe_dur(p)) for p in files]
            ass_path = work / f"captions_{tag}.ass"
            legacy.build_ass(manifest["scenes"], segments, durs, str(ass_path), headline="")
            cap_path = work / f"captioned_{tag}.mp4"
            dur = float(legacy.ffprobe_dur(str(body_path)))
            _make_captioned(body_path, ass_path, cap_path, dur)
            result = dict(_mix_final(cap_path, dest, dur, work_dir=work))
            # Surfaced so callers can record duration/caption evidence without
            # reaching back into this function's locals.
            # str, not Path: this dict is written straight into the JSON proof
            # report, and Path is not JSON serializable.
            result["duration_s"] = dur
            result["ass_path"] = str(ass_path)
            return result

        final = out / "final.mp4"
        mix = _finish_assembly(scene_files, final)
        body_duration = float(mix["duration_s"])
        ass = Path(mix["ass_path"])
        if not final.is_file() or final.stat().st_size < 10000:
            raise RuntimeError("real downstream final.mp4 was not produced")

        timeline = QSR._write_scene_timeline(manifest)
        audio = AQA.review(str(final), str(manifest_path))
        QE.write_json(out / "audio_qa_report.json", audio)
        if audio.get("mechanical_pass") is not True:
            raise RuntimeError("real downstream final audio failed QA: " + "; ".join(audio.get("mechanical_reasons") or []))

        packet = FQ.SamplePacket(
            video_path=str(final), duration_s=body_duration,
            timestamps_s=tuple(round((i + 0.5) * body_duration / 9, 3) for i in range(9)),
            frame_paths=tuple(str(work / f"proof_frame_{i}.jpg") for i in range(9)),
            sheet_paths=tuple(str(work / f"proof_sheet_{i}.jpg") for i in range(3)),
        )
        repair_plan = PQR.build_repair_targets(_repair_verdict(), packet, timeline["scenes"])
        QE.write_json(out / "targeted_repair_plan.json", repair_plan)
        targets = repair_plan.get("targets") or []
        if len(targets) != 1 or not targets[0].get("affected_scene_ids"):
            raise RuntimeError("holistic QA did not map defect to concrete scene target")
        target_ids = [str(x) for x in targets[0]["affected_scene_ids"]]

        scene_map = {str(i): work / f"s{i}.mp4" for i in range(1, 5)}
        replacements: dict[str, Path] = {}
        for sid in target_ids:
            repl = root / f"replacement_{sid}.mp4"
            _make_scene(repl, int(sid), 4.0, variant=1)
            replacements[sid] = repl

        repaired_video = out / "repaired.mp4"
        repair_evidence = RC.execute_replacements(
            plan=repair_plan,
            scene_files=scene_map,
            replacements=replacements,
            output_scene_dir=repaired_dir,
            output_video=repaired_video,
            # Same finishing path as the first assembly -- see _finish_assembly.
            assemble=_finish_assembly,
            manifest_path=manifest_path,
        )
        RC.write_evidence(repair_evidence, out / "repair_execution.json")
        if repair_evidence.get("re_qa", {}).get("audio_mechanical_pass") is not True:
            raise RuntimeError("repaired assembly failed local audio re-QA")

        # Provenance has to follow the repair. final_asset_lineage.json names the
        # ORIGINAL scene files; the repaired artifact contains different ones, so
        # shipping the repaired video against that record would attribute it to
        # assets it no longer holds. Rebuild lineage against the files the repair
        # actually assembled, with the swap named rather than implied.
        assembled = repair_evidence["repaired_scene_files"]
        repaired_lineage = QAL.write_repaired_lineage(
            lineage,
            {sid: assembled[sid] for sid in target_ids},
            out / "repaired_asset_lineage.json",
            repaired_video=repaired_video,
            base_video=final,
        )
        for label, payload in (("final", lineage), ("repaired", repaired_lineage)):
            phantom = QAL.phantom_assets(payload)
            if phantom:
                raise RuntimeError(
                    f"{label} lineage attributes scene(s) {list(phantom)} to files "
                    "that do not exist"
                )

        result = {
            "schema": "content-render-downstream-factory-proof-v1",
            # measured, not asserted -- see the interception above
            "provider_calls_made": len(net_calls),
            "network_calls_made": len(net_calls),
            "network_calls_detail": net_calls,
            "manifest_scene_count": len(manifest["scenes"]),
            "actual_final_mp4": str(final),
            "actual_final_bytes": final.stat().st_size,
            "actual_final_duration_s": float(legacy.ffprobe_dur(str(final))),
            "visual_bible_scene_count": len(visual_bible["scenes"]),
            "asset_lineage_scene_count": lineage["scene_count"],
            "all_rendered_scenes_attributable": lineage["all_rendered_scenes_attributable"],
            "scene_timeline_count": timeline["scene_count"],
            "audio_mechanical_pass": True,
            "music": mix,
            "captions_ass_present": ass.is_file() and ass.stat().st_size > 100,
            "repair_target_scene_ids": target_ids,
            "repair_unaffected_scenes_preserved": all(
                x["unchanged"] for x in repair_evidence["unaffected_scene_preservation"].values()
            ),
            "repair_re_qa_audio_pass": repair_evidence["re_qa"]["audio_mechanical_pass"],
            "repaired_mp4": str(repaired_video),
            "repaired_bytes": repaired_video.stat().st_size,
            "repaired_lineage_scene_count": repaired_lineage["scene_count"],
            "repaired_lineage_replaced_scene_ids": repaired_lineage["repaired_scene_ids"],
            "repaired_lineage_all_attributable": repaired_lineage["all_rendered_scenes_attributable"],
            "lineage_phantom_assets": 0,
        }
        QE.write_json(root / "proof_report.json", result, sort_keys=True)
        return result
    finally:
        legacy.WORK, legacy.OUT = old_work, old_out
        urllib.request.urlopen = _real_urlopen
        socket.socket.connect = _real_socket_connect
        socket.create_connection = _real_create_connection


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/downstream_factory_proof")
    args = ap.parse_args(argv)
    try:
        result = proof(args.out)
    except Exception as exc:
        print(f"DOWNSTREAM FACTORY PROOF FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(QE.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
