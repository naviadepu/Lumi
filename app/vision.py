"""Snap it, learn it: Gemini looks at a webcam photo and picks a word to learn.

Hold up a medicine bottle, a name badge or a spice jar; Gemini reads the label
and we turn the word into a braille lesson. Labeling your own things is one of
the first everyday uses of braille for someone who has lost their sight.

Docs: https://ai.google.dev/gemini-api/docs/image-understanding
"""

import logging
import re

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

log = logging.getLogger("vision")

MAX_WORD_LETTERS = 10

PROMPT = f"""You help a blind adult learn braille by labeling things in their life.
Look at the photo and pick ONE word to learn in braille:
- If there is printed text (a brand, a product name, a name on a badge, a sign), use the
  most important word of it, for example "Tylenol", "Cinnamon" or "Maya".
- If there is no readable text, use the plain name of the main object, for example "mug" or "keys".
- The word must be letters a-z only, at most {MAX_WORD_LETTERS} letters.
Also write a short, friendly description of what you see, under 12 words, that starts with
"I see", for example "I see a bottle of Tylenol." Never identify a person from their face;
only read printed text."""


class SnapResult(BaseModel):
    description: str = Field(description='Under 12 words, starting with "I see"')
    word: str = Field(description=f"One word, letters a-z only, at most {MAX_WORD_LETTERS} letters")


def thinking_for(model):
    """Snap needs a fast answer, not deep reasoning: thinking on made Flash take ~38 s.
    Flash-Lite takes a thinking level; Flash takes a thinking budget."""
    if "lite" in model:
        return types.ThinkingConfig(thinking_level="minimal")
    return types.ThinkingConfig(thinking_budget=0)


class VisionUnavailable(Exception):
    """No Gemini key, or the call failed."""


class GeminiVision:
    def __init__(self, api_key, model):
        self.model = model
        self.client = genai.Client(api_key=api_key) if api_key else None

    @property
    def enabled(self):
        return self.client is not None

    async def snap(self, image_bytes, mime_type):
        """Photo -> {"description": "I see ...", "word": "tylenol"}"""
        if not self.enabled:
            raise VisionUnavailable("GEMINI_API_KEY not set")
        # One retry: a flaky call shouldn't end the demo with "I couldn't read that".
        for attempt in (1, 2):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=SnapResult,
                        thinking_config=thinking_for(self.model),
                    ),
                )
                result = SnapResult.model_validate_json(response.text)
                break
            except Exception as e:  # bad key, quota, network, unparseable reply
                if attempt == 2:
                    raise VisionUnavailable(f"Gemini request failed: {e}") from e
                log.warning("Gemini call failed, retrying: %s", str(e)[:120])

        # Trust but verify: keep it to a short a-z word the lesson can teach.
        word = re.sub(r"[^a-z]", "", result.word.lower())[:MAX_WORD_LETTERS]
        if not word:
            raise VisionUnavailable(f"Gemini returned no usable word: {result.word!r}")
        log.info("Snap: %s -> %s", result.description, word)
        return {"description": result.description.strip(), "word": word}
