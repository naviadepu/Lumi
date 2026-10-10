"""Braille Reader backend.

Run with:  python -m app.main
"""

import asyncio
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.arduino import ArduinoLink, RemoteParser
from app.braille import text_to_steps
from app.tts import ElevenLabsTTS, TTSUnavailable

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


arduino = ArduinoLink(
    port=os.getenv("ARDUINO_PORT", "").strip(),
    baud=int(os.getenv("ARDUINO_BAUD", "9600")),
    on_line=lambda line: handle_line(line, "Arduino"),
    on_status=lambda connected: broadcast_from_thread({"type": "status", "arduino": connected}),
)


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
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=console_input_loop, daemon=True, name="console").start()
        log.info("Test mode: type remote lines here, e.g. CELL 1 then CHAR 1 a (or DOT 1, BTN ENTER)")
    if not tts.enabled:
        log.info("No ElevenLabs key/voice in .env: the page will use browser speech")
    yield
    arduino.stop()


app = FastAPI(title="Braille Reader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


class StepsRequest(BaseModel):
    text: str = Field(max_length=10_000)


@app.post("/api/steps")
def steps(req: StepsRequest):
    """Text -> list of braille cells to show one at a time."""
    return {"steps": text_to_steps(req.text, LETTER_PREFIX, NUMBER_PREFIX)}


class ShowRequest(BaseModel):
    char: str = Field(min_length=1, max_length=1)
    pattern: str = Field(pattern=r"^[01]{6}$")


@app.post("/api/show")
def show(req: ShowRequest):
    """The page calls this whenever the current character changes."""
    arduino.send_show(req.char, req.pattern)
    return {"ok": True}


@app.get("/api/status")
def status():
    return {"arduino": arduino.connected, "elevenlabs": tts.enabled}


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
