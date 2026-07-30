from __future__ import annotations

from dataclasses import dataclass

from kajovodagmar.realtime.protocol import FRAME_MILLISECONDS


@dataclass(frozen=True, slots=True)
class VoiceActivity:
    started: bool = False
    ended: bool = False
    level: float = 0.0


class VoiceActivityDetector:
    """Server-authoritative PCM endpoint detector with bounded hysteresis."""

    def __init__(
        self,
        *,
        threshold: int = 600,
        start_frames: int = 3,
        endpoint_silence_ms: int = 900,
    ) -> None:
        if threshold <= 0 or start_frames <= 0 or endpoint_silence_ms < FRAME_MILLISECONDS:
            raise ValueError("Konfigurace VAD musí používat kladné bezpečné limity.")
        self.threshold = threshold
        self.start_frames = start_frames
        self.endpoint_silence_ms = endpoint_silence_ms
        self.active = False
        self._voiced_frames = 0
        self._silence_ms = 0

    def reset(self) -> None:
        self.active = False
        self._voiced_frames = 0
        self._silence_ms = 0

    def process(self, pcm16: bytes) -> VoiceActivity:
        level = self._rms(pcm16)
        voiced = level >= self.threshold
        started = False
        ended = False
        if not self.active:
            self._voiced_frames = self._voiced_frames + 1 if voiced else 0
            if self._voiced_frames >= self.start_frames:
                self.active = True
                self._silence_ms = 0
                started = True
        elif voiced:
            self._silence_ms = 0
        else:
            self._silence_ms += FRAME_MILLISECONDS
            if self._silence_ms >= self.endpoint_silence_ms:
                self.active = False
                self._voiced_frames = 0
                self._silence_ms = 0
                ended = True
        return VoiceActivity(started=started, ended=ended, level=level)

    @staticmethod
    def _rms(pcm16: bytes) -> float:
        if not pcm16 or len(pcm16) % 2:
            return 0.0
        total = 0
        samples = len(pcm16) // 2
        for offset in range(0, len(pcm16), 2):
            sample = int.from_bytes(pcm16[offset : offset + 2], "little", signed=True)
            total += sample * sample
        return (total / samples) ** 0.5
