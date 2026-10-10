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

def build_prompt(wheel_letters):
    """The braille wheel only has some letters, so ask for a word that fits it when one honestly does."""
    letters = ", ".join(wheel_letters)
    return f"""You help a blind adult learn braille using the things in their life.
The camera watches all the time, so first decide: is someone holding up or showing a distinct
object to the camera? Set "found" to false if the photo only shows a person, a face, hands with
nothing in them, a room, or a blur. If found is false, leave description and word empty.
Otherwise pick ONE short word for that object to learn in braille.
The braille wheel can only show these letters: {letters}.
1. If a plain, common name for the object is spelled only with those letters, use it.
   For example a pill bottle -> "pill", a pencil -> "pencil", an apple -> "apple", a pen -> "pen".
2. Otherwise use the plain name of the object anyway, for example "mug" or "keys".
Never make up a word that doesn't fit the object just to match the letters.
The word must be letters a-z only, at most {MAX_WORD_LETTERS} letters.
Also write a short, friendly description, under 12 words, starting with "I see",
for example "I see a pen." Never identify a person from their face."""


class SnapResult(BaseModel):
    found: bool = Field(description="True only if a distinct object is being shown to the camera")
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
    def __init__(self, api_key, model, wheel_letters="abceilnp"):
        self.model = model
        self.prompt = build_prompt(wheel_letters)
        self.client = genai.Client(api_key=api_key) if api_key else None

    @property
    def enabled(self):
        return self.client is not None

    async def snap(self, image_bytes, mime_type):
        """Photo -> {"found": True, "description": "I see a pen.", "word": "pen"} or {"found": False}"""
        if not self.enabled:
            raise VisionUnavailable("GEMINI_API_KEY not set")
        # One retry: a flaky call shouldn't end the demo with "I couldn't read that".
        for attempt in (1, 2):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), self.prompt],
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
        if not result.found or not word:
            return {"found": False}
        log.info("Snap: %s -> %s", result.description, word)
        return {"found": True, "description": result.description.strip(), "word": word}
