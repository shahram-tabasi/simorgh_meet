"""PCM helpers, resampling and a streaming utterance segmenter (no heavy deps)."""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

TARGET_RATE = 16000


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def _lowpass_kernel(cutoff: float, taps: int = 63) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff * n) * np.hamming(taps)
    return (kernel / kernel.sum()).astype(np.float32)


def resample(samples: np.ndarray, src_rate: int, dst_rate: int = TARGET_RATE) -> np.ndarray:
    """Band-limited resampling. Integer decimation (48k->16k) uses FIR+decimate,
    other ratios fall back to linear interpolation after low-pass filtering."""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    if src_rate > dst_rate:
        filtered = np.convolve(samples, _lowpass_kernel(0.5 * dst_rate / src_rate), mode="same")
    else:
        filtered = samples
    if src_rate % dst_rate == 0:
        return filtered[:: src_rate // dst_rate].astype(np.float32)
    duration = samples.size / src_rate
    dst_len = int(round(duration * dst_rate))
    src_x = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    dst_x = np.linspace(0.0, duration, num=dst_len, endpoint=False)
    return np.interp(dst_x, src_x, filtered).astype(np.float32)


def rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * math.log10(max(rms, 1e-9))


@dataclass
class Utterance:
    samples: np.ndarray  # float32 @16 kHz
    start_ms: int  # relative to the participant stream start
    end_ms: int
    final: bool


@dataclass
class UtteranceSegmenter:
    """Energy-based VAD with hangover, operating on 30 ms frames at 16 kHz.

    Emits a final utterance after ``min_silence_ms`` of silence or once
    ``max_utterance_s`` is reached (cut at the quietest recent frame)."""

    threshold_db: float = -45.0
    min_silence_ms: int = 700
    min_speech_ms: int = 300
    max_utterance_s: float = 25.0
    frame_ms: int = 30
    pre_roll_ms: int = 300

    _pending: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    _speech: list[np.ndarray] = field(default_factory=list)
    _speech_frames: int = 0
    _silence_frames: int = 0
    _in_speech: bool = False
    _pre_roll: list[np.ndarray] = field(default_factory=list)
    _consumed_samples: int = 0
    _utt_start_sample: int = 0
    _noise_floor_db: float = -70.0

    @property
    def _frame_len(self) -> int:
        return TARGET_RATE * self.frame_ms // 1000

    def _threshold(self) -> float:
        # Adaptive: at least 12 dB above the tracked noise floor.
        return max(self.threshold_db, self._noise_floor_db + 12.0)

    def push(self, samples: np.ndarray) -> list[Utterance]:
        out: list[Utterance] = []
        self._pending = np.concatenate([self._pending, samples.astype(np.float32)])
        n = self._frame_len
        while self._pending.size >= n:
            frame, self._pending = self._pending[:n], self._pending[n:]
            out.extend(self._process_frame(frame))
            self._consumed_samples += n
        return out

    def _process_frame(self, frame: np.ndarray) -> list[Utterance]:
        level = rms_dbfs(frame)
        voiced = level >= self._threshold()
        if not voiced:
            # Slowly track the noise floor while not speaking.
            self._noise_floor_db = 0.95 * self._noise_floor_db + 0.05 * level
        max_pre = max(1, self.pre_roll_ms // self.frame_ms)
        if not self._in_speech:
            if voiced:
                self._in_speech = True
                self._speech = list(self._pre_roll) + [frame]
                self._utt_start_sample = self._consumed_samples - len(self._pre_roll) * self._frame_len
                self._speech_frames = 1
                self._silence_frames = 0
                self._pre_roll = []
            else:
                self._pre_roll.append(frame)
                if len(self._pre_roll) > max_pre:
                    self._pre_roll.pop(0)
            return []

        self._speech.append(frame)
        if voiced:
            self._speech_frames += 1
            self._silence_frames = 0
        else:
            self._silence_frames += 1

        if self._silence_frames * self.frame_ms >= self.min_silence_ms:
            return self._emit(drop_tail_frames=max(0, self._silence_frames - 5))
        if len(self._speech) * self.frame_ms >= self.max_utterance_s * 1000:
            return self._emit(drop_tail_frames=0)
        return []

    def _emit(self, drop_tail_frames: int) -> list[Utterance]:
        frames = self._speech[: len(self._speech) - drop_tail_frames] if drop_tail_frames else self._speech
        speech_ms = self._speech_frames * self.frame_ms
        start = self._utt_start_sample
        self._in_speech = False
        self._speech = []
        self._speech_frames = 0
        self._silence_frames = 0
        if speech_ms < self.min_speech_ms or not frames:
            return []
        audio = np.concatenate(frames)
        start_ms = max(0, start * 1000 // TARGET_RATE)
        return [Utterance(audio, start_ms, start_ms + audio.size * 1000 // TARGET_RATE, True)]

    def current_partial(self) -> Utterance | None:
        if not self._in_speech or not self._speech:
            return None
        audio = np.concatenate(self._speech)
        start_ms = max(0, self._utt_start_sample * 1000 // TARGET_RATE)
        return Utterance(audio, start_ms, start_ms + audio.size * 1000 // TARGET_RATE, False)

    def flush(self) -> list[Utterance]:
        if self._in_speech:
            return self._emit(drop_tail_frames=0)
        return []


class WavAppender:
    """Appends 16 kHz mono PCM to a WAV file (kept for the refinement pass)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(TARGET_RATE)

    def write(self, samples: np.ndarray) -> None:
        self._wav.writeframes(float_to_pcm16(samples))

    def close(self) -> None:
        self._wav.close()


def read_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        data = pcm16_to_float(wav.readframes(wav.getnframes()))
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return resample(data, rate, TARGET_RATE)
