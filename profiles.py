#!/usr/bin/env python3
"""
profiles.py — per-page configuration. One config = one mechanically distinct channel.
The same engine reads a profile and produces a different fingerprint (voice, captions,
pacing, grade, music, posting window, hashtags). Adding a page = adding a profile here.

Select with env PAGE (default "science").
"""

PROFILES = {
    "science": {
        "name": "Science, Stranger Than It Sounds",
        "eleven_voice": "JBFqnCBsd6RMkjVDRZzb",   # George — warm British
        "voice_settings": {"stability": 0.40, "similarity_boost": 0.80, "style": 0.30, "use_speaker_boost": True},
        "edge_voice": "en-US-GuyNeural",
        # captions
        "cap_font": "DejaVu Sans",
        "cap_size": 120,
        "cap_y": 760,                 # eye level
        "cap_primary": "&H00FFFFFF",  # white
        "cap_outline": 4,
        # look
        "grade": "eq=contrast=1.08:saturation=1.12:brightness=-0.02,curves=preset=medium_contrast",
        "zoom_speed": 0.0006,         # slow cinematic
        "motion_graphics": True,      # animated number card when a scene has a stat
        # audio
        "music": "music_science.mp3",
        "music_vol": 0.10,
        # posting
        "post_window": "evening (7-10pm) — reflective, lean-back learning",
        "hashtags_base": ["#science", "#learnontiktok", "#stem"],
        "scene_pace": "fast",         # 3-4s scenes
    },
    "history_pov": {
        "name": "A Day In Their Life (history POV)",
        "eleven_voice": "onwK4e9ZLuTAKqWW03F9",   # Daniel — deep authoritative (swap to any you prefer)
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.45, "use_speaker_boost": True},
        "edge_voice": "en-US-ChristopherNeural",
        "cap_font": "DejaVu Serif",
        "cap_size": 104,
        "cap_y": 1480,                # lower third
        "cap_primary": "&H00F0F0E8",  # warm off-white
        "cap_outline": 3,
        "grade": "eq=contrast=1.05:saturation=0.92:brightness=-0.01,curves=preset=vintage",
        "zoom_speed": 0.0004,         # slower, contemplative
        "music": "music_history.mp3",
        "music_vol": 0.12,
        "post_window": "morning (7-9am) — commute storytelling",
        "hashtags_base": ["#history", "#historytok", "#ancienthistory"],
        "scene_pace": "slow",         # longer holds
    },
    "dark_mystery": {
        "name": "Unsolved (dark history & mysteries)",
        "eleven_voice": "JBFqnCBsd6RMkjVDRZzb",   # placeholder; pick a low ominous voice in ElevenLabs
        "voice_settings": {"stability": 0.50, "similarity_boost": 0.85, "style": 0.55, "use_speaker_boost": True},
        "edge_voice": "en-US-EricNeural",
        "cap_font": "DejaVu Sans",
        "cap_size": 112,
        "cap_y": 300,                 # top-positioned bold
        "cap_primary": "&H00FFFFFF",
        "cap_outline": 5,
        "grade": "eq=contrast=1.14:saturation=0.80:brightness=-0.05,curves=preset=darker",
        "zoom_speed": 0.0005,
        "music": "music_mystery.mp3",
        "music_vol": 0.14,
        "post_window": "night (9pm-12am) — eerie, high-attention scroll",
        "hashtags_base": ["#unsolved", "#mystery", "#history"],
        "scene_pace": "medium",
    },
    "ai_life": {
        "name": "AI For Real Life",
        "eleven_voice": "onwK4e9ZLuTAKqWW03F9",   # placeholder; pick a bright American voice
        "voice_settings": {"stability": 0.35, "similarity_boost": 0.80, "style": 0.25, "use_speaker_boost": True},
        "edge_voice": "en-US-BrianNeural",
        "cap_font": "DejaVu Sans",
        "cap_size": 124,
        "cap_y": 820,
        "cap_primary": "&H0000F0FF",  # bright accent (yellow-ish) — boxed feel via outline
        "cap_outline": 6,
        "grade": "eq=contrast=1.10:saturation=1.18:brightness=0.01,curves=preset=lighter",
        "zoom_speed": 0.0007,         # punchy
        "music": "music_ai.mp3",
        "music_vol": 0.10,
        "post_window": "midday (11am-1pm) + evening — utility/productivity windows",
        "hashtags_base": ["#ai", "#aitools", "#productivity"],
        "scene_pace": "fast",
    },
}


def get_profile(name=None):
    import os
    name = name or os.environ.get("PAGE", "science")
    return PROFILES.get(name, PROFILES["science"]), name
