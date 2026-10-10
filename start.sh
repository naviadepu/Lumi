#!/bin/sh
# Start Lumi hands-free (macOS): the server, plus Chrome as a full-screen app
# that may use the camera and microphone and play sound without anyone clicking first.
#
#   ./start.sh
#
# Chrome uses its own profile (~/.lumi-chrome) so these settings don't touch
# your normal browser. Quit it with Cmd+Q.

cd "$(dirname "$0")"
URL="http://127.0.0.1:${PORT:-8000}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

open_app() {
  # Wait for the server, then open the page.
  for _ in $(seq 1 60); do
    curl -s "$URL/api/status" >/dev/null && break
    sleep 0.5
  done
  "$CHROME" --user-data-dir="$HOME/.lumi-chrome" --app="$URL" --start-fullscreen \
    --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream \
    --no-first-run --no-default-browser-check >/dev/null 2>&1 &
}

if curl -s "$URL/api/status" >/dev/null; then
  echo "Server already running at $URL; opening the app."
  open_app
else
  open_app &
  # The server stays in the foreground so you can type test lines (CELL 1, CHAR 1 a) here.
  exec .venv/bin/python -m app.main
fi
