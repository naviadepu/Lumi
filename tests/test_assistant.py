import asyncio
from types import SimpleNamespace

import pytest

from app.assistant import Assistant, AssistantUnavailable, Turn


def make(heard, reply_json):
    """An Assistant whose ElevenLabs hears `heard` and whose Gemini answers `reply_json`."""
    calls = {}

    async def convert(**kwargs):
        calls["stt"] = kwargs
        return SimpleNamespace(text=heard)

    async def generate_content(**kwargs):
        calls["gemini"] = kwargs
        return SimpleNamespace(text=reply_json)

    a = Assistant("", "", "test-model")
    a.stt = SimpleNamespace(speech_to_text=SimpleNamespace(convert=convert))
    a.gemini = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    return a, calls


def run(coro):
    return asyncio.run(coro)


def said(*texts):
    """said("hi", "Hello!", "teach me cat") -> alternating user / assistant turns."""
    return [Turn(role="user" if i % 2 == 0 else "assistant", text=t) for i, t in enumerate(texts)]


def test_needs_both_keys():
    with pytest.raises(AssistantUnavailable):
        run(Assistant("", "", "m").transcribe(b"audio", "audio/webm"))
    with pytest.raises(AssistantUnavailable):
        run(Assistant("", "", "m").chat(said("hi")))


def test_transcribes_with_scribe():
    a, calls = make("What is braille?", "{}")
    assert run(a.transcribe(b"audio", "audio/webm")) == "What is braille?"
    assert calls["stt"]["model_id"] == "scribe_v2"


def test_replies_to_anything_and_keeps_talking():
    a, calls = make("", '{"reply": "Braille is reading by touch, with raised dots.", "learn": "", "done": false}')
    result = run(a.chat(said("What is braille?")))
    assert result == {"say": "Braille is reading by touch, with raised dots.", "done": False}
    assert "Lumi" in calls["gemini"]["config"].system_instruction


def test_whole_conversation_is_sent_with_roles():
    a, calls = make("", '{"reply": "Let\'s write your name, Navi.", "learn": "Navi", "done": false}')
    result = run(a.chat(said("How do I write my name?", "What's your name?", "Na'vi")))
    assert result == {"say": "Let's write your name, Navi.", "learn": "Navi", "done": False}
    contents = calls["gemini"]["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].text == "What's your name?"


def test_conversation_starts_with_the_learner():
    a, calls = make("", '{"reply": "Hi!", "learn": "", "done": false}')
    run(a.chat([Turn(role="assistant", text="Hello"), *said("hi")]))
    assert calls["gemini"]["contents"][0].role == "user"


def test_goodbye_ends_the_conversation():
    a, _ = make("", '{"reply": "Bye for now, Navi!", "learn": "", "done": true}')
    assert run(a.chat(said("that's all, thanks")))["done"] is True


def test_lesson_text_is_cleaned_and_capped():
    a, _ = make("", '{"reply": "", "learn": "Hello, world!!! and much more text", "done": false}')
    result = run(a.chat(said("teach me")))
    assert result["learn"] == "Hello world and much"
    assert result["say"] == "Let's write Hello world and much."


def test_suggestions_are_checked_against_the_wheel():
    a, _ = make("", '{"reply": "Fruit is a fun one.", "learn": "", "suggestions": ["apple", "pear", "banana"], "done": false}')
    assert run(a.chat(said("teach me a fruit")))["say"] == "Fruit is a fun one. How about apple or banana? Which one?"


def test_no_valid_suggestion_falls_back_with_the_lead_in():
    a, _ = make("", '{"reply": "", "learn": "", "suggestions": ["cat", "dog"], "done": false}')
    assert run(a.chat(said("an animal")))["say"] == "That one isn't on your wheel yet. How about pen, apple or ball? Which one?"
