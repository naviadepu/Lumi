#!/bin/sh
# Start Lumi hands-free: the server, plus Chrome as a full-screen app that may use the
# camera and microphone and play sound without anyone clicking first.
#
#   macOS / Linux:        ./start.sh
#   Windows (Git Bash):   ./start.sh      (or: sh start.sh)
#
# Chrome uses its own profile (~/.lumi-chrome) so these settings don't touch your normal
# browser. Quit it with Cmd+Q (Mac) or Alt+F4 (Windows). Stop the server with Ctrl+C.

cd "$(dirname "$0")" || exit 1

# Leave the window open on errors, so the message can be read when it was opened by double-click.
fail() {
  echo
  echo "Lumi didn't start: $1"
  printf "Press Enter to close. "
  read -r _
  exit 1
}

# PORT from the environment, else from .env, else 8000.
if [ -z "$PORT" ] && [ -f .env ]; then
  PORT=$(sed -n 's/^PORT=\([0-9][0-9]*\).*/\1/p' .env | tail -n 1)
fi
URL="http://127.0.0.1:${PORT:-8000}"

# The venv's Python: .venv/Scripts/python.exe on Windows, .venv/bin/python elsewhere.
if [ -x .venv/Scripts/python.exe ]; then
  PYTHON=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  fail "there is no .venv folder with Python in it yet. Set it up once, one line at a time:
    Windows:      py -m venv .venv
                  .venv/Scripts/python.exe -m pip install -r requirements.txt
    macOS/Linux:  python3 -m venv .venv
                  .venv/bin/python -m pip install -r requirements.txt"
fi

# Chrome (or Edge on Windows, which takes the same flags).
CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/c/Program Files/Google/Chrome/Application/chrome.exe" \
  "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
  "${LOCALAPPDATA:+$(cygpath -u "$LOCALAPPDATA" 2>/dev/null)/Google/Chrome/Application/chrome.exe}" \
  "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  "/c/Program Files/Microsoft/Edge/Application/msedge.exe"; do
  if [ -n "$candidate" ] && [ -f "$candidate" ]; then CHROME="$candidate"; break; fi
done
if [ -z "$CHROME" ]; then
  CHROME=$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || command -v chromium-browser)
fi

PROFILE="$HOME/.lumi-chrome"
# Windows programs need a Windows path (C:\Users\...), not Git Bash's /c/Users/...
command -v cygpath >/dev/null 2>&1 && PROFILE=$(cygpath -w "$PROFILE")

open_app() {
  # Wait for the server, then open the page.
  for _ in $(seq 1 60); do
    curl -s "$URL/api/status" >/dev/null && break
    sleep 0.5
  done
  if [ -z "$CHROME" ]; then
    echo "Chrome wasn't found. Open $URL in Chrome yourself."
    return
  fi
  echo "Opening $URL in $(basename "$CHROME")"
  "$CHROME" --user-data-dir="$PROFILE" --app="$URL" --start-fullscreen \
    --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream \
    --no-first-run --no-default-browser-check >/dev/null 2>&1 &
}

if curl -s "$URL/api/status" >/dev/null; then
  echo "Server already running at $URL; opening the app."
  open_app
  exit 0
fi

open_app &
# The server stays in the foreground so you can type test lines (CELL 1, CHAR 1 a) here.
"$PYTHON" -m app.main || fail "the server stopped with an error (see the lines above)."
