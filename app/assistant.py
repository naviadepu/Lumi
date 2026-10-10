"""Ask: say what you want to learn, out loud.

    "How do I write my name in braille?"  ->  "What's your name?"
    "Navi"                                ->  "N, A, V, I. Let's write Navi."

ElevenLabs speech-to-text turns the recording into words; Gemini works out what to
teach, or what to ask next when it needs more (like a name).
Docs: https://elevenlabs.io/docs/api-reference/speech-to-text/convert
"""

import logging
import re

from elevenlabs.client import AsyncElevenLabs
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.vision import thinking_for
from app.wheel import words_for

log = logging.getLogger("assistant")

STT_MODEL = "scribe_v2"
MAX_LESSON_CHARS = 20

def build_prompt(wheel_letters):
    letters = ", ".join(wheel_letters)
    words = ", ".join(words_for(wheel_letters))
    return BASE_PROMPT + f"""
The learner's braille wheel only has these letters: {letters}. If they ask for something with
other letters, still set "learn" to exactly what they asked; the device explains what it skips.
If they ask what they can learn, or want ideas (even "a fruit" or "an animal"), put 2 or 3 words
in "suggestions", chosen ONLY from this list, which the wheel can spell: {words}.
If nothing in the list fits what they asked for, leave "suggestions" empty and set "question" to
"none fit". Otherwise leave "question" empty."""


BASE_PROMPT = f"""You are the voice of a braille learning device for blind adults.
The learner just said something out loud (transcribed below). Decide what to do:
- If it says what to learn ("teach me cat", "how do I write hello", "the letter K",
  "how do I write 2026"), set "learn" to exactly that text: letters, digits and spaces only,
  at most {MAX_LESSON_CHARS} characters. Leave "question" empty.
- If you need one more detail first ("how do I write my name" -> you need their name;
  "my birthday" -> the date), leave "learn" empty and set "question" to one short question,
  for example "What's your name?".
- If they answered your previous question, use the answer as "learn". Spell names the way they
  are most commonly written.
- If it isn't about learning something to write, leave "learn" empty and set "question" to
  "What would you like to learn to write in braille?"
Keep "reply" to one short friendly sentence that is said before the lesson starts, for example
"Let's write your name, Navi." Never ask more than one question at a time."""


class Understanding(BaseModel):
    learn: str = Field(description=f"Text to teach, letters/digits/spaces, max {MAX_LESSON_CHARS} chars, or empty")
    question: str = Field(description="One short follow-up question, or empty")
    reply: str = Field(description="One short sentence said before the lesson, or empty")
    suggestions: list[str] = Field(default_factory=list, description="Words to suggest, from the list, or empty")


class AssistantUnavailable(Exception):
    """No keys, or a call failed."""


class Assistant:
    def __init__(self, elevenlabs_key, gemini_key, gemini_model, wheel_letters="abceilnp"):
        self.prompt = build_prompt(wheel_letters)
        self.wheel_words = words_for(wheel_letters)
        self.stt = AsyncElevenLabs(api_key=elevenlabs_key, timeout=20) if elevenlabs_key else None
        self.gemini = genai.Client(api_key=gemini_key) if gemini_key else None
        self.model = gemini_model

    @property
    def enabled(self):
        return self.stt is not None and self.gemini is not None

    async def transcribe(self, audio, mime_type):
        """Recording -> text, with ElevenLabs Scribe."""
        try:
            result = await self.stt.speech_to_text.convert(
                model_id=STT_MODEL,
                file=("speech", audio, mime_type),
                language_code="en",
                tag_audio_events=False,
            )
        except Exception as e:
            raise AssistantUnavailable(f"ElevenLabs speech-to-text failed: {e}") from e
        return (getattr(result, "text", "") or "").strip()

    async def understand(self, heard, asked=""):
        """What the learner said (+ the question we asked) -> what to teach or ask next."""
        context = f'You previously asked: "{asked}"\n' if asked else ""
        try:
            response = await self.gemini.aio.models.generate_content(
                model=self.model,
                contents=[self.prompt, f'{context}The learner said: "{heard}"'],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Understanding,
                    thinking_config=thinking_for(self.model),
                ),
            )
            result = Understanding.model_validate_json(response.text)
        except Exception as e:
            raise AssistantUnavailable(f"Gemini request failed: {e}") from e

        learn = re.sub(r"[^A-Za-z0-9 ]", "", result.learn).strip()[:MAX_LESSON_CHARS].strip()
        if learn:
            return {"learn": learn, "say": result.reply.strip() or f"Let's write {learn}."}
        wanted_ideas = bool(result.suggestions) or result.question.strip().lower() == "none fit"
        if wanted_ideas:
            # Gemini sometimes suggests words the wheel can't spell ("pear"), so check them here.
            ideas = [w.lower() for w in result.suggestions if w.lower() in self.wheel_words][:3]
            lead_in = "" if ideas else "Your wheel can't spell that yet. "
            ideas = ideas or [w for w in ("pen", "apple", "ball") if w in self.wheel_words]
            if len(ideas) > 1:
                return {"question": f"{lead_in}How about {', '.join(ideas[:-1])} or {ideas[-1]}? Which one?"}
            if ideas:
                return {"question": f"{lead_in}How about {ideas[0]}?"}
        question = result.question.strip() or "What would you like to learn to write in braille?"
        return {"question": question}

    async def listen(self, audio, mime_type, asked=""):
        """Recording -> {"heard", and either "learn" + "say", or "question"}."""
        if not self.enabled:
            raise AssistantUnavailable("Ask needs both ELEVENLABS_API_KEY and GEMINI_API_KEY")
        heard = await self.transcribe(audio, mime_type)
        if not heard:
            return {"heard": ""}
        result = await self.understand(heard, asked)
        log.info("Heard %r (asked %r) -> %s", heard, asked, result)
        return {"heard": heard, **result}
