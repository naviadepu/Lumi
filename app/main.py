"""Lumi backend.

Run with:  python -m app.main
"""

import asyncio
import base64
import binascii
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.arduino import ArduinoLink, RemoteParser
from app.assistant import Assistant, AssistantUnavailable, Turn
from app import coach
from app.braille import pattern_for, text_to_steps
from app.tts import ElevenLabsTTS, TTSUnavailable
from app.vision import GeminiVision, VisionUnavailable

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"

LETTER_PREFIX = os.getenv("SPEAK_LETTER_PREFIX", "Letter")
NUMBER_PREFIX = os.getenv("SPEAK_NUMBER_PREFIX", "Number")
MAX_SPEAK_CHARS = 200  # /speak is for short prompts; this stops accidental credit burn

tts = ElevenLabsTTS(
    api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
    voice_id=os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
    model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip(),
)

# Letters on the rotating braille wheel (must match WHEEL_LETTERS in braille_wheel.ino or wheel_mega.ino).
WHEEL_LETTERS = "".join(sorted(set(os.getenv("WHEEL_LETTERS", "abceilnp").strip().lower())))
# Wheel-only: lessons only use wheel letters (others are skipped with an explanation).
WHEEL_ONLY = os.getenv("WHEEL_ONLY", "true").strip().lower() in ("1", "true", "yes")
# The wheel shows dot patterns, so a digit is "on the wheel" if its letter is (1 = a, 5 = e, ...).
WHEEL_PATTERNS = {pattern_for(c) for c in WHEEL_LETTERS} - {"000000"}

vision = GeminiVision(
    api_key=os.getenv("GEMINI_API_KEY", "").strip(),
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
    wheel_letters=WHEEL_LETTERS,
)

assistant = Assistant(
    elevenlabs_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
    gemini_key=os.getenv("GEMINI_API_KEY", "").strip(),
    gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
    wheel_letters=WHEEL_LETTERS,
)


# ---- WebSocket clients (browser tabs) ----

clients = set()
main_loop = None


async def broadcast(message):
    for ws in list(clients):
        try:
            await ws.send_json(message)
        except Exception:
            clients.discard(ws)


def broadcast_from_thread(message):
    """Serial and console threads use this to push to the page."""
    if main_loop is not None:
        asyncio.run_coroutine_threadsafe(broadcast(message), main_loop)


remote_parser = RemoteParser()


def handle_line(line, source):
    """A line from the remote or the console, forwarded to the page."""
    messages = remote_parser.parse(line)
    log.info("%s: %s%s", source, line.strip(), "" if messages else " (ignored)")
    for message in messages:
        broadcast_from_thread(message)


ARDUINO_BAUD = int(os.getenv("ARDUINO_BAUD", "9600"))
# Two-board setup: the wheel runs on its own board (wheel_mega.ino on a Mega). Empty = one board.
WHEEL_PORT = os.getenv("ARDUINO_WHEEL_PORT", "").strip()

arduino = ArduinoLink(
    port=os.getenv("ARDUINO_PORT", "").strip(),
    baud=ARDUINO_BAUD,
    on_line=lambda line: handle_line(line, "Arduino"),
    on_status=lambda connected: broadcast_from_thread({"type": "status", "arduino": connected}),
    exclude_ports=(WHEEL_PORT,),  # auto-detect must not grab the wheel board
)

# The wheel board only takes SHOW lines; what it prints back (AT a, NOT ON WHEEL ...) is just logged.
wheel_board = ArduinoLink(
    port=WHEEL_PORT,
    baud=ARDUINO_BAUD,
    on_line=lambda line: log.info("Wheel board: %s", line),
    on_status=lambda connected: log.info("Wheel board %s", "connected" if connected else "disconnected"),
    name="Wheel board",
) if WHEEL_PORT else None


def console_input_loop():
    """Test mode: type remote lines (CELL 1, CHAR 1 a, ...) or DOT 1 / BTN ENTER in this terminal."""
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle_line(line, "Console")


@asynccontextmanager
async def lifespan(app):
    global main_loop
    main_loop = asyncio.get_running_loop()
    arduino.start()
    if wheel_board:
        wheel_board.start()
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=console_input_loop, daemon=True, name="console").start()
        log.info("Test mode: type remote lines here, e.g. CELL 1 then CHAR 1 a (or DOT 1, BTN ENTER)")
    if not vision.enabled:
        log.info("No GEMINI_API_KEY in .env: Snap mode is off")
    if not tts.enabled:
        log.info("No ElevenLabs key/voice in .env: the page will use browser speech")
    yield
    arduino.stop()
    if wheel_board:
        wheel_board.stop()


app = FastAPI(title="Lumi", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def always_fresh_page(request, call_next):
    """Make browsers re-check the page and its scripts, so a refresh always gets the latest code."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


class StepsRequest(BaseModel):
    text: str = Field(max_length=10_000)


@app.post("/api/steps")
def steps(req: StepsRequest):
    """Text -> list of braille cells to show one at a time, each with a memory hint."""
    steps = text_to_steps(req.text, LETTER_PREFIX, NUMBER_PREFIX)
    for step in steps:
        step["hint"] = coach.hint(step["char"], step["is_number_sign"], WHEEL_LETTERS if WHEEL_ONLY else None)
        step["on_wheel"] = step["pattern"] in WHEEL_PATTERNS
    return {"steps": steps}


class CheckRequest(BaseModel):
    target: str = Field(min_length=1, max_length=40)  # "D", "4" or "the number sign"
    expected: str = Field(pattern=r"^[01]{6}$")
    got: str = Field(pattern=r"^[01]{6}$")


@app.post("/api/check")
def check(req: CheckRequest):
    """Learn mode: is the answer right, and if not, why not?"""
    return coach.check(req.target, req.expected, req.got)


class ShowRequest(BaseModel):
    char: str = Field(min_length=1, max_length=1)
    pattern: str = Field(pattern=r"^[01]{6}$")


@app.post("/api/show")
def show(req: ShowRequest):
    """The page calls this whenever the current character changes."""
    arduino.send_show(req.char, req.pattern)
    if wheel_board:
        wheel_board.send_show(req.char, req.pattern)
    return {"ok": True}


@app.get("/api/status")
def status():
    return {
        "arduino": arduino.connected,
        "wheel_board": wheel_board.connected if wheel_board else None,  # None = one-board setup
        "elevenlabs": tts.enabled,
        "vision": vision.enabled,
        "ask": assistant.enabled,
        "wheel_letters": WHEEL_LETTERS,
        "wheel_only": WHEEL_ONLY,
    }


MAX_RECORDING_BYTES = 5_000_000


@app.post("/api/transcribe")
async def transcribe(request: Request):
    """Ask mode: raw recording in the body (audio/webm from the mic) -> {"heard": "what they said"}."""
    audio = await request.body()
    if not audio or len(audio) > MAX_RECORDING_BYTES:
        raise HTTPException(status_code=400, detail="Expected a short recording")
    mime_type = request.headers.get("content-type", "audio/webm").split(";")[0]
    try:
        return {"heard": await assistant.transcribe(audio, mime_type)}
    except AssistantUnavailable as e:
        log.warning("Ask unavailable: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


class ChatRequest(BaseModel):
    turns: list[Turn] = Field(min_length=1, max_length=60)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Ask mode: the conversation so far -> {"say", "done"} and "learn" when a lesson should start."""
    try:
        return await assistant.chat(req.turns)
    except AssistantUnavailable as e:
        log.warning("Ask unavailable: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


class ClientLog(BaseModel):
    message: str = Field(max_length=1000)


@app.post("/api/log")
def client_log(entry: ClientLog):
    """The page reports problems here (e.g. why the camera didn't open) so they show in this terminal."""
    log.warning("Page: %s", entry.message)
    return {"ok": True}


class SnapRequest(BaseModel):
    image: str = Field(max_length=8_000_000)  # data URL from the webcam: "data:image/jpeg;base64,..."


@app.post("/api/snap")
async def snap(req: SnapRequest):
    """Webcam photo -> {"description": "I see ...", "word": "tylenol"} via Gemini."""
    header, _, data = req.image.partition(",")
    mime_type = header.removeprefix("data:").removesuffix(";base64")
    if mime_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Expected a JPEG, PNG or WebP data URL")
    try:
        image_bytes = base64.b64decode(data, validate=True)
    except binascii.Error:
        raise HTTPException(status_code=400, detail="Image is not valid base64")
    try:
        return await vision.snap(image_bytes, mime_type)
    except VisionUnavailable as e:
        log.warning("Vision unavailable: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/speak")
async def speak(text: str = Query(min_length=1, max_length=MAX_SPEAK_CHARS)):
    """MP3 audio for text, e.g. /speak?text=Letter%20A. 503 means: use browser speech."""
    try:
        audio = await tts.speak(text)
    except TTSUnavailable as e:
        log.warning("TTS unavailable: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "status", "arduino": arduino.connected})
    try:
        while True:
            await ws.receive_text()  # we only push from server; just keep it open
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
