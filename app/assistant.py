"""Ask: talk with Lumi, out loud, like talking to a person.

    "Hi, what is braille?"                ->  "It's a way to read by touch, with raised dots. ..."
    "How do I write my name in braille?"  ->  "I'd love to help. What's your name?"
    "Navi"                                ->  "Let's write your name, Navi."  (lesson starts)

ElevenLabs speech-to-text turns each recording into words; Gemini replies to the whole
conversation so far, and starts a lesson when the learner wants one.
Docs: https://elevenlabs.io/docs/api-reference/speech-to-text/convert
"""

import logging
import re
from typing import Literal

from elevenlabs.client import AsyncElevenLabs
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.vision import thinking_for
from app.wheel import words_for

log = logging.getLogger("assistant")

STT_MODEL = "scribe_v2"
MAX_LESSON_CHARS = 20
MAX_TURNS = 30  # older turns are dropped so the request stays small

def build_prompt(wheel_letters):
    letters = ", ".join(wheel_letters)
    words = ", ".join(words_for(wheel_letters))
    return BASE_PROMPT + f"""
The learner's braille wheel only has these letters: {letters}. If they ask to learn something with
other letters, still set "learn" to exactly what they asked; the device explains what it skips.
If they ask what they can learn, or want ideas (even "a fruit" or "an animal"), put 2 or 3 words
in "suggestions", chosen ONLY from this list, which the wheel can spell: {words}.
Don't name the suggested words in "reply"; the device reads them out after it ("How about ...?").
If nothing in the list fits, still fill "suggestions" with any words from the list."""


BASE_PROMPT = f"""You are Lumi, the voice of a braille learning device for blind and low-vision adults.
You are having a spoken conversation: the learner talks to you out loud (transcribed below),
and everything you put in "reply" is read aloud by text-to-speech. They can't see a screen.

Who you are: a warm, patient, curious companion who happens to teach braille. Kind and
encouraging, never judging, lecturing or correcting the learner. Speak like a person, not a menu.

Reply to whatever they say, the way a thoughtful assistant would: answer questions (about braille,
blindness, the device, or anything else), chat back, share a small useful fact, cheer them on,
and ask a follow-up when it helps. Remember what was said earlier in the conversation.
If the transcript looks garbled, kindly say you didn't quite catch it and ask them to say it again.

Keep every reply short enough to listen to: one to three short sentences, under 50 words.
Plain spoken words only: no lists, markdown, emojis, URLs or symbols. One question at a time.

About the device, if they ask: the remote has six buttons laid out like a braille cell,
1, 2, 3 down the left side and 4, 5, 6 down the right. A wheel under their finger shows the
raised letter. They press Enter to talk to you. They can also hold an object up to the camera
and you'll teach them its name.

Lessons:
- When they want to learn to write something ("teach me cat", "how do I write hello",
  "the letter K", "how do I write 2026"), set "learn" to exactly that text: letters, digits and
  spaces only, at most {MAX_LESSON_CHARS} characters. Then "reply" is one short sentence said
  before the lesson starts, for example "Let's write your name, Navi."
- If you need one more detail first ("how do I write my name" -> you need their name;
  "my birthday" -> the date), leave "learn" empty and ask for it in "reply".
- Spell names the way they are most commonly written.
- Otherwise leave "learn" empty. Don't push a lesson on them; just talk.

Set "done" to true only when they are finished talking: they say goodbye, thanks that's all,
stop, or similar. Then "reply" is a short, warm goodbye."""


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class Reply(BaseModel):
    reply: str = Field(description="What Lumi says out loud, under 50 words")
    learn: str = Field(description=f"Text to teach, letters/digits/spaces, max {MAX_LESSON_CHARS} chars, or empty")
    suggestions: list[str] = Field(default_factory=list, description="Words to suggest, from the list, or empty")
    done: bool = Field(default=False, description="True when the learner is finished talking")


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
        if not self.enabled:
            raise AssistantUnavailable("Ask needs both ELEVENLABS_API_KEY and GEMINI_API_KEY")
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

    async def chat(self, turns):
        """The conversation so far (ending with what the learner just said) -> Lumi's answer:
        {"say", "done"}, plus "learn" when a lesson should start."""
        if not self.enabled:
            raise AssistantUnavailable("Ask needs both ELEVENLABS_API_KEY and GEMINI_API_KEY")
        turns = turns[-MAX_TURNS:]
        while turns and turns[0].role != "user":  # Gemini wants the user to speak first
            turns = turns[1:]
        contents = [
            types.Content(role="user" if t.role == "user" else "model", parts=[types.Part(text=t.text)])
            for t in turns
        ]
        try:
            response = await self.gemini.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self.prompt,
                    response_mime_type="application/json",
                    response_schema=Reply,
                    thinking_config=thinking_for(self.model),
                ),
            )
            result = Reply.model_validate_json(response.text)
        except Exception as e:
            raise AssistantUnavailable(f"Gemini request failed: {e}") from e

        reply = result.reply.strip()
        learn = re.sub(r"[^A-Za-z0-9 ]", "", result.learn).strip()[:MAX_LESSON_CHARS].strip()
        if learn:
            return {"say": reply or f"Let's write {learn}.", "learn": learn, "done": False}
        if result.suggestions:
            reply = f"{reply} {self.suggest(result.suggestions)}".strip()
        log.info("Said %r -> %r", turns[-1].text if turns else "", reply)
        return {"say": reply or "I'm here. What would you like to talk about?", "done": result.done}

    def suggest(self, words):
        """Gemini sometimes suggests words the wheel can't spell ("pear"), so check them here."""
        ideas = [w.lower() for w in words if w.lower() in self.wheel_words][:3]
        lead_in = "" if ideas else "That one isn't on your wheel yet. "
        ideas = ideas or [w for w in ("pen", "apple", "ball") if w in self.wheel_words]
        if len(ideas) > 1:
            return f"{lead_in}How about {', '.join(ideas[:-1])} or {ideas[-1]}? Which one?"
        if ideas:
            return f"{lead_in}How about {ideas[0]}?"
        return ""
