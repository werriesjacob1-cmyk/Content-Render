# Background music credits

All background music beds shipped in this repo are CC0 1.0 Universal (Public
Domain Dedication) — https://creativecommons.org/publicdomain/zero/1.0/ — no
attribution is legally required, but source credits are kept here for
traceability and in case any file ever needs to be re-verified or swapped.

Files were downloaded from Freesound.org (a Creative Commons audio archive)
using each sound's "hq" preview stream, filtered explicitly to
`license:"Creative Commons 0"`, and the CC0 dedication link
(`creativecommons.org/publicdomain/zero/1.0/`) was confirmed present on each
sound's own page before download. Every file was then loudness-normalized to
a consistent ~-18dB mean (via `ffmpeg volumedetect` + a compensating `volume`
filter) so the per-profile `music_vol` multipliers in `profiles.py` behave
predictably regardless of the original source's mastering loudness, and
re-encoded to 128kbps MP3.

| Repo file | Source track | Source URL | License | Used by profile(s) |
|---|---|---|---|---|
| `music_science.mp3` / `music_history.mp3` | "Piano Ambiance 4 (120bpm) [CC0] — Ambient Piano Loop 37" by Erokia | https://freesound.org/people/Erokia/sounds/387588/ | CC0 1.0 | `science`, `history_pov` (calm/reflective mood fits both) |
| `music_mystery.mp3` | "Dark Ambient Loop" by goulven | https://freesound.org/people/goulven/sounds/371277/ | CC0 1.0 | `dark_mystery` |
| `music_ai.mp3` | "Free Uplifting Music" by Seth_Makes_Sounds (trimmed to first 45s) | https://freesound.org/people/Seth_Makes_Sounds/sounds/670819/ | CC0 1.0 | `ai_life` |

`music_science.mp3` and `music_history.mp3` are byte-identical copies of the
same source track — reused rather than sourcing a fourth track, since its
calm/ambient character fits both profiles' post windows (reflective evening
learning; contemplative morning storytelling).

## Why CC0 specifically

CC0 is a public-domain dedication, not merely a permissive license — there is
no attribution requirement, no share-alike obligation, and no risk of a
licensor rescinding permission later. That makes it the safest option for
music baked directly into videos that get redistributed across TikTok/IG/
YouTube, where per-video attribution isn't practical. No copyrighted or
ambiguously-licensed audio (Kevin MacLeod/incompetech-style CC-BY tracks,
YouTube Audio Library "free" tracks, Pixabay's non-CC0 house license, etc.)
was used or considered a substitute — if a confidently-CC0 track wasn't
found for a slot, that slot would have been left silent rather than shipping
questionable audio.

## Mix levels

Background music is mixed under narration via `amix` in `main.py`, at
`PROFILE["music_vol"]` (a linear multiplier, not dB) defined per profile in
`profiles.py`:

| Profile | `music_vol` | ≈ dB under the (already-normalized) music track |
|---|---|---|
| `science` | 0.10 | -20.0 dB |
| `history_pov` | 0.12 | -18.4 dB |
| `dark_mystery` | 0.11 | -19.2 dB |
| `ai_life` | 0.10 | -20.0 dB |

All four sit inside the requested -18 to -22 dB band, keeping the bed
audibly present but clearly subordinate to the narration.
