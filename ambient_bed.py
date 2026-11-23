"""Synthesized ambient music bed: a slow, evolving chord pad that never loops.

Why this exists: the bundled music_*.mp3 beds are ~8 s clips, so a 40 s video repeats the same ~6 s
fragment ~6 times (the user: "not a big fan of the music, I'd probably skip just because of that").
This bed is generated from scratch (numpy only -> no licence question, no network), is exactly as long
as the video, moves through four chords instead of repeating, and is soft by design (lowpassed, no
percussion, no melody) so it can sit under a voiceover.

Pure functions; synth_ambient() writes a stereo 44.1 kHz WAV. Deterministic for a given seed.
"""
import numpy as np

SR = 44100

# Am - F - C - G, voiced low and close so the bed stays out of the voice's way (all < ~500 Hz).
CHORDS = [
    (110.00, 164.81, 220.00, 261.63, 329.63),   # Am
    (87.31, 130.81, 174.61, 220.00, 261.63),    # F
    (130.81, 196.00, 261.63, 329.63, 392.00),   # C
    (98.00, 146.83, 196.00, 246.94, 293.66),    # G
]
CHORD_S = 8.0       # one chord
XFADE_S = 3.0       # overlap between chords


def _voice(freq, n, detunes_cents, vib_hz, vib_cents, seed):
    """One pad note as a few detuned, softly-harmonic partials with a slow vibrato (n samples)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for dc in detunes_cents:
        phase0 = rng.uniform(0, 2 * np.pi)
        vib = vib_cents * np.sin(2 * np.pi * vib_hz * t + rng.uniform(0, 2 * np.pi))
        f = freq * 2 ** ((dc + vib) / 1200.0)
        ph = 2 * np.pi * np.cumsum(f) / SR + phase0
        for h in range(1, 7):                      # soft harmonic stack, 1/h^1.4 roll-off
            out += np.sin(h * ph) / (h ** 1.4)
    return out / len(detunes_cents)


def _chord(freqs, n, side, seed):
    """One chord, n samples; side 0/1 picks a different detune set so L and R decorrelate."""
    dets = ([-9.0, 0.0, 8.0], [-6.0, 3.0, 10.0])[side]
    mix = np.zeros(n)
    for i, f in enumerate(freqs):
        amp = 1.0 if i < 2 else 0.7                 # root + fifth strongest
        mix += amp * _voice(f, n, dets, 0.13 + 0.02 * i, 2.5, seed * 31 + i)
    return mix / len(freqs)


def _gauss_lowpass(x, cutoff_hz):
    """Smooth FFT-domain lowpass (no ringing) on a 1-D signal."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= np.exp(-(f / cutoff_hz) ** 2)
    return np.fft.irfft(X, len(x))


def _highpass(x, cutoff_hz):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 - np.exp(-(f / cutoff_hz) ** 2)
    return np.fft.irfft(X, len(x))


def _reverb(x, seed, tail_s=2.4, wet=0.33):
    """Cheap convolution reverb: an exponentially decaying, lowpassed noise impulse response."""
    rng = np.random.default_rng(seed)
    m = int(tail_s * SR)
    ir = rng.standard_normal(m) * np.exp(-np.arange(m) / (0.75 * SR))
    ir = _gauss_lowpass(ir, 2200.0)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    n = 1 << int(np.ceil(np.log2(len(x) + m)))
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)[:len(x)]
    return (1 - wet) * x + wet * y


def render_pad(duration, seed=7):
    """(left, right) float arrays, `duration` seconds, peak-limited, RMS ~ -22 dBFS."""
    total = int(duration * SR)
    seg = int(CHORD_S * SR)
    xf = int(XFADE_S * SR)
    chans = []
    for side in (0, 1):
        sig = np.zeros(total + seg + xf)
        k, pos = 0, 0
        while pos < total:
            n = seg + xf
            c = _chord(CHORDS[k % len(CHORDS)], n, side, seed + k)
            win = np.ones(n)
            ramp = np.sin(np.linspace(0, np.pi / 2, xf)) ** 2     # equal-power fade in/out
            win[:xf] = ramp
            win[-xf:] = ramp[::-1]
            sig[pos:pos + n] += c * win[:len(sig) - pos][:n]
            pos += seg
            k += 1
        chans.append(sig[:total])
    t = np.arange(total) / SR
    swell = 0.88 + 0.12 * np.sin(2 * np.pi * t / 11.0)              # slow breathing
    out = []
    for i, ch in enumerate(chans):
        ch = _highpass(_gauss_lowpass(ch * swell, 1500.0), 45.0)
        ch = _reverb(ch, seed + 100 + i)
        out.append(ch)
    L, R = out
    fi, fo = int(2.0 * SR), int(2.5 * SR)
    env = np.ones(total)
    env[:fi] = np.linspace(0, 1, fi) ** 2
    env[-fo:] = np.linspace(1, 0, fo) ** 2
    L, R = L * env, R * env
    rms = np.sqrt(np.mean(np.concatenate([L, R]) ** 2)) + 1e-12
    g = (10 ** (-22 / 20)) / rms
    L, R = L * g, R * g
    peak = max(np.max(np.abs(L)), np.max(np.abs(R)))
    lim = 10 ** (-3 / 20)
    if peak > lim:
        L, R = L * lim / peak, R * lim / peak
    return L, R


def synth_ambient(duration, out_wav, seed=7):
    """Write a stereo 16-bit WAV of `duration` seconds and return its path."""
    import soundfile as sf
    L, R = render_pad(max(4.0, float(duration)), seed=seed)
    sf.write(out_wav, np.stack([L, R], axis=1), SR, subtype="PCM_16")
    return out_wav
