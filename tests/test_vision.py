import asyncio
from types import SimpleNamespace

import pytest

from app.vision import GeminiVision, VisionUnavailable


def fake_gemini(reply_json=None, error=None):
    """A GeminiVision whose client returns reply_json (or raises error)."""
    async def generate_content(**kwargs):
        if error:
            raise error
        return SimpleNamespace(text=reply_json)

    vision = GeminiVision(api_key="", model="test-model")
    vision.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    return vision


def run(coro):
    return asyncio.run(coro)


def test_no_key_means_disabled():
    vision = GeminiVision(api_key="", model="m")
    assert not vision.enabled
    with pytest.raises(VisionUnavailable):
        run(vision.snap(b"img", "image/jpeg"))


def test_word_is_cleaned_to_short_lowercase_letters():
    v = fake_gemini('{"found": true, "description": "I see a bottle of Tylenol.", "word": "Tylenol®"}')
    assert run(v.snap(b"img", "image/jpeg")) == {"found": True, "description": "I see a bottle of Tylenol.", "word": "tylenol"}

    v = fake_gemini('{"found": true, "description": "I see a sign.", "word": "Supercalifragilistic"}')
    assert run(v.snap(b"img", "image/jpeg"))["word"] == "supercalif"


def test_nothing_shown_is_not_found():
    v = fake_gemini('{"found": false, "description": "", "word": ""}')
    assert run(v.snap(b"img", "image/jpeg")) == {"found": False}
    # found, but no usable letters: also nothing to teach
    v = fake_gemini('{"found": true, "description": "I see a 7.", "word": "7"}')
    assert run(v.snap(b"img", "image/jpeg")) == {"found": False}


def test_unusable_reply_is_unavailable():
    with pytest.raises(VisionUnavailable):
        run(fake_gemini("not json").snap(b"img", "image/jpeg"))
    with pytest.raises(VisionUnavailable):
        run(fake_gemini(error=RuntimeError("quota")).snap(b"img", "image/jpeg"))


def test_retries_once_after_a_failure():
    calls = []

    async def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("403 PERMISSION_DENIED")
        return SimpleNamespace(text='{"found": true, "description": "I see a mug.", "word": "mug"}')

    vision = GeminiVision(api_key="", model="m")
    vision.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=flaky)))
    assert run(vision.snap(b"img", "image/jpeg"))["word"] == "mug"
    assert len(calls) == 2
