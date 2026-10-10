"""ElevenLabs text-to-speech with an in-memory + on-disk cache.

Uses the official ElevenLabs Python SDK (same call as the JS SDK's
elevenlabs.textToSpeech.convert). Docs:
https://elevenlabs.io/docs/api-reference/text-to-speech/convert
"""

import hashlib
import logging
from pathlib import Path

from elevenlabs.client import AsyncElevenLabs

log = logging.getLogger("tts")

OUTPUT_FORMAT = "mp3_44100_128"
CACHE_DIR = Path(__file__).resolve().parent.parent / "audio_cache"


class TTSUnavailable(Exception):
    """No API key, or ElevenLabs failed. The page falls back to browser speech."""


class ElevenLabsTTS:
    def __init__(self, api_key, voice_id, model_id):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.memory_cache = {}
        self.client = AsyncElevenLabs(api_key=api_key, timeout=15) if api_key else None

    @property
    def enabled(self):
        return bool(self.api_key and self.voice_id)

    def _cache_path(self, text):
        # Key includes voice and model so changing either doesn't replay old audio.
        key = f"{self.voice_id}|{self.model_id}|{text}".encode()
        return CACHE_DIR / (hashlib.sha256(key).hexdigest()[:24] + ".mp3")

    async def speak(self, text):
        """Return MP3 bytes for text, from cache when possible."""
        if not self.enabled:
            raise TTSUnavailable("ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID not set")

        if text in self.memory_cache:
            return self.memory_cache[text]

        path = self._cache_path(text)
        if path.exists():
            audio = path.read_bytes()
            self.memory_cache[text] = audio
            return audio

        log.info("ElevenLabs request: %r", text)
        try:
            chunks = self.client.text_to_speech.convert(
                self.voice_id,
                text=text,
                model_id=self.model_id,
                output_format=OUTPUT_FORMAT,
            )
            audio = b"".join([chunk async for chunk in chunks])
        except Exception as e:  # bad key, no credits, network down, ...
            # SDK errors carry status_code/body; network errors just have a message.
            detail = getattr(e, "body", None) or e
            raise TTSUnavailable(f"ElevenLabs request failed ({getattr(e, 'status_code', 'network')}): {detail}") from e
        if not audio:
            raise TTSUnavailable("ElevenLabs returned no audio")

        self.memory_cache[text] = audio
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            path.write_bytes(audio)
        except OSError as e:
            log.warning("Could not write audio cache file: %s", e)
        return audio
