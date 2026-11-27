"""Bounded MP3 -> model-readable signal observation, not semantic hearing.

The observation is tied to exact source bytes. It reports measured dynamics
and frequency distribution, never guesses events (birds, trucks, instruments)
or claims that a model received the audio waveform.
"""
import hashlib
import json
import subprocess

import numpy as np


class AudioError(ValueError):
    pass


SAMPLE_RATE = 16000
BIN_SECONDS = 4


def observe_pcm(samples: np.ndarray, source_sha256: str) -> dict:
    if (samples.ndim != 1 or not 0 < len(samples) <= SAMPLE_RATE * 300
        or not np.isfinite(samples).all()):
        raise AudioError("invalid decoded audio")
    bins = []
    width = SAMPLE_RATE * BIN_SECONDS
    for start in range(0, len(samples), width):
        segment = samples[start:start + width].astype(np.float64)
        rms = float(np.sqrt(np.mean(segment * segment)))
        peak = float(np.max(np.abs(segment)))
        # A windowed spectral centroid is a brightness proxy, not an event label.
        windows = []
        for offset in range(0, len(segment) - 1023, 1024):
            spectrum = np.abs(np.fft.rfft(segment[offset:offset + 1024] * np.hanning(1024)))
            total = float(spectrum.sum())
            if total > 1e-9:
                windows.append(float(np.dot(np.fft.rfftfreq(1024, 1 / SAMPLE_RATE), spectrum) / total))
        bins.append({"start_s": round(start / SAMPLE_RATE, 3),
                     "end_s": round(min(start + width, len(samples)) / SAMPLE_RATE, 3),
                     "rms": round(rms, 5), "peak": round(peak, 5),
                     "centroid_hz": round(float(np.median(windows)), 1) if windows else None})
    return {"schema": "thornfield.audio-observation.v1", "source_sha256": source_sha256,
            "decode": "ffmpeg mono f32le 16000Hz", "duration_s": round(len(samples) / SAMPLE_RATE, 3),
            "bin_seconds": BIN_SECONDS, "bins": bins,
            "limits": "Signal measurements only; no semantic event or listened-encounter claim."}


def observe_mp3(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 20 * 1024 * 1024:
        raise AudioError("invalid MP3 bytes")
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-f", "f32le",
             "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError("audio decode unavailable") from exc
    if result.returncode != 0 or not result.stdout or len(result.stdout) > SAMPLE_RATE * 300 * 4:
        raise AudioError("audio decode failed or exceeded five minutes")
    return observe_pcm(np.frombuffer(result.stdout, dtype="<f4"), hashlib.sha256(raw).hexdigest())


def model_text(observation: dict) -> str:
    """A bounded text rendition suitable as an elected listen-in record."""
    if observation.get("schema") != "thornfield.audio-observation.v1":
        raise AudioError("invalid observation")
    lines = [f"Audio source sha256:{observation['source_sha256']}; decoded {observation['duration_s']} s.",
             "Measured 4-second bins (RMS level, peak level, spectral centroid Hz):"]
    for item in observation["bins"]:
        lines.append(f"{item['start_s']}-{item['end_s']} s: RMS {item['rms']}, peak {item['peak']}, centroid {item['centroid_hz']}")
    lines.append("These are signal measurements, not a transcript or proof of hearing. Interpret with the authored score and sleeve; do not infer a sound source from them alone.")
    return "\n".join(lines)


def observation_json(observation: dict) -> bytes:
    return (json.dumps(observation, sort_keys=True, separators=(",", ":")) + "\n").encode()
