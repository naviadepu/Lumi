import asyncio
from types import SimpleNamespace

import pytest

from app.assistant import Assistant, AssistantUnavailable


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


def test_needs_both_keys():
    with pytest.raises(AssistantUnavailable):
        run(Assistant("", "", "m").listen(b"audio", "audio/webm"))


def test_asks_a_follow_up_question():
    a, calls = make("How do I write my name in braille?", '{"learn": "", "question": "What is your name?", "reply": ""}')
    assert run(a.listen(b"audio", "audio/webm")) == {"heard": "How do I write my name in braille?", "question": "What is your name?"}
    assert calls["stt"]["model_id"] == "scribe_v2"


def test_answer_becomes_the_lesson_and_question_is_passed_on():
    a, calls = make("Na'vi", '{"learn": "Navi", "question": "", "reply": "Let\'s write your name, Navi."}')
    result = run(a.listen(b"audio", "audio/webm", asked="What is your name?"))
    assert result == {"heard": "Na'vi", "learn": "Navi", "say": "Let's write your name, Navi."}
    assert "What is your name?" in calls["gemini"]["contents"][1]


def test_lesson_text_is_cleaned_and_capped():
    a, _ = make("teach me", '{"learn": "Hello, world!!! and much more text", "question": "", "reply": ""}')
    result = run(a.listen(b"audio", "audio/webm"))
    assert result["learn"] == "Hello world and much"
    assert result["say"] == "Let's write Hello world and much."


def test_silence_is_heard_as_nothing():
    a, _ = make("", "{}")
    assert run(a.listen(b"audio", "audio/webm")) == {"heard": ""}


def test_suggestions_are_checked_against_the_wheel():
    a, _ = make("teach me a fruit", '{"learn": "", "question": "", "reply": "", "suggestions": ["apple", "pear", "banana"]}')
    assert run(a.listen(b"audio", "audio/webm"))["question"] == "How about apple or banana? Which one?"


def test_no_valid_suggestion_falls_back_with_the_lead_in():
    a, _ = make("an animal", '{"learn": "", "question": "none fit", "reply": "", "suggestions": ["cat", "dog"]}')
    assert run(a.listen(b"audio", "audio/webm"))["question"] == "Your wheel can't spell that yet. How about pen, apple or ball? Which one?"
