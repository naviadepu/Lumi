// Braille Reader front end. Plain JavaScript, no build step.
//
// Three modes share one screen (elements with data-show="..." only appear in those modes):
//   Learn: "Type the letter A." The user presses dots (remote or keyboard) and Enter.
//          Wrong -> we say which buttons to press. Right -> next letter.
//   Read:  show and speak each character of the text, one at a time.
//   Type:  free typing with the remote, like braille_interface.html: live cell,
//          preview of what Enter will type, capital/number badges, typed text.

const $ = (id) => document.getElementById(id);

const inputScreen = $("input-screen");
const readerScreen = $("reader-screen");
const textForm = $("text-form");
const textInput = $("text-input");
const formError = $("form-error");
const charEl = $("char");
const cellEl = $("cell");
const positionEl = $("position");
const feedbackEl = $("feedback");
const typedTextEl = $("typed-text");
const statusEl = $("arduino-status");
const targetDots = [...cellEl.querySelectorAll(".dot")];
const inputDots = [...document.querySelectorAll(".dot-button")];

let mode = "learn";    // "learn", "read" or "type"
let steps = [];        // [{char, spoken, pattern, is_number_sign, space_before}]
let index = 0;
let entered = [false, false, false, false, false, false]; // dots 1-6 the user pressed
let elevenLabsEnabled = true;

// Type mode state (the remote keeps its own copy and reports it in "mode" messages).
let typedText = "";
let capitalNext = false;
let numberMode = false;

// Buttons are named by position on the remote, not by dot number.
const ROW = { 1: "top", 2: "middle", 3: "bottom", 4: "top", 5: "middle", 6: "bottom" };
const COLUMN = { 1: "left", 2: "left", 3: "left", 4: "right", 5: "right", 6: "right" };
const capitalize = (s) => s[0].toUpperCase() + s.slice(1);
const dotName = (n) => capitalize(`${ROW[n]} ${COLUMN[n]}`);

// Keyboard stand-ins for the remote: 1-6, or the standard braille keys F D S / J K L.
const DOT_KEYS = { 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, f: 1, d: 2, s: 3, j: 4, k: 5, l: 6 };

// Patterns are "101010" strings (dots 1-6). The remote sends bitmasks (bit 0 = dot 1).
const patternFromMask = (mask) => [0, 1, 2, 3, 4, 5].map((i) => (mask >> i) & 1).join("");
const enteredPattern = () => entered.map((on) => (on ? "1" : "0")).join("");
const enteredMask = () => entered.reduce((mask, on, i) => mask | (on ? 1 << i : 0), 0);

// ---------------------------------------------------------------- speech

const audioCache = new Map(); // spoken text -> Promise<blob URL or null>
let playToken = 0;            // bumps on every new say(), cancelling the old one
let currentAudio = null;
let finishCurrent = null;     // resolves whatever is playing right now

// Fetch ElevenLabs audio once per text; repeats come from this cache instantly.
function getAudioUrl(text) {
  if (!elevenLabsEnabled) return Promise.resolve(null);
  if (!audioCache.has(text)) {
    const promise = fetch("/speak?text=" + encodeURIComponent(text))
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => (blob ? URL.createObjectURL(blob) : null))
      .catch(() => null);
    audioCache.set(text, promise);
    promise.then((url) => { if (!url) audioCache.delete(text); }); // retry next time
  }
  return audioCache.get(text);
}

function stopSpeech() {
  if (currentAudio) currentAudio.pause();
  currentAudio = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (finishCurrent) finishCurrent();
  finishCurrent = null;
}

function playAudio(url) {
  return new Promise((resolve) => {
    const audio = new Audio(url);
    currentAudio = audio;
    finishCurrent = () => resolve(true);
    audio.onended = () => resolve(true);
    audio.onerror = () => resolve(false);
    audio.play().catch(() => resolve(false));
  });
}

// Fallback so the app never goes silent: the browser's built-in voice.
function browserSay(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.9;
    utterance.onend = utterance.onerror = () => resolve();
    finishCurrent = resolve;
    speechSynthesis.speak(utterance);
  });
}

// Speak a list of phrases in order, e.g. ["Space", "Letter B"].
async function say(parts) {
  const token = ++playToken;
  stopSpeech();
  for (const text of parts) {
    const url = await getAudioUrl(text);
    if (token !== playToken) return;
    const played = url ? await playAudio(url) : false;
    if (token !== playToken) return;
    if (!played) await browserSay(text);
    if (token !== playToken) return;
  }
}

// ---------------------------------------------------------------- display

// "101010" -> [1, 3, 5]
const raisedDots = (pattern) => [...pattern].flatMap((bit, i) => (bit === "1" ? [i + 1] : []));

function describeDots(pattern) {
  const raised = raisedDots(pattern);
  return raised.length ? "Braille dots " + raised.join(", ") : "Braille: no raised dots";
}

function render() {
  const step = steps[index];
  charEl.textContent = step.char;
  charEl.classList.remove("small");
  charEl.setAttribute("aria-label", step.spoken);
  for (const dot of targetDots) {
    dot.classList.toggle("raised", step.pattern[dot.dataset.dot - 1] === "1");
  }
  cellEl.setAttribute("aria-label", describeDots(step.pattern));
  positionEl.textContent = `${index + 1} of ${steps.length}`;
  sendToArduino(step);
}

function renderInput() {
  for (const dot of inputDots) {
    const on = entered[dot.dataset.dot - 1];
    dot.classList.toggle("raised", on);
    dot.setAttribute("aria-pressed", String(on));
  }
  if (mode === "type") renderType();
}

function sendToArduino(step) {
  fetch("/api/show", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ char: step.char, pattern: step.pattern }),
  }).catch(() => {});
}

// ---------------------------------------------------------------- dot input (Learn + Type)

function clearInput() {
  entered = entered.map(() => false);
  renderInput();
}

// Keyboard, on-screen click, or "DOT n" test line: the page holds the cell.
function toggleDot(n) {
  if (mode === "read") return;
  entered[n - 1] = !entered[n - 1];
  feedbackEl.textContent = "";
  renderInput();
  say([entered[n - 1] ? dotName(n) : `${dotName(n)} off`]);
}

// braille_remote.ino holds the cell itself and reports the whole bitmask.
function setCellFromRemote(mask, quiet) {
  if (mode === "read") return;
  const before = entered;
  entered = [0, 1, 2, 3, 4, 5].map((i) => Boolean(mask & (1 << i)));
  const changed = [0, 1, 2, 3, 4, 5].filter((i) => before[i] !== entered[i]);
  renderInput();
  // One dot added or removed by the user: say which. (Clearing after Enter is "quiet".)
  if (!quiet && changed.length === 1) {
    const n = changed[0] + 1;
    feedbackEl.textContent = "";
    say([entered[n - 1] ? dotName(n) : `${dotName(n)} off`]);
  }
}

// ---------------------------------------------------------------- learn mode

// "the letter A", "the number 5", "the number sign"
function nameOf(step) {
  if (step.is_number_sign) return "the number sign";
  if (/[0-9]/.test(step.char)) return `the number ${step.char}`;
  return `the letter ${step.char.toUpperCase()}`;
}

const promptFor = (step) => `Type ${nameOf(step)}.`;

// Spoken: "Top, left. Bottom, left. Middle, right." Left column first, top to bottom.
function buttonsToPress(pattern) {
  return raisedDots(pattern).map((n) => `${capitalize(ROW[n])}, ${COLUMN[n]}.`).join(" ");
}

function checkAnswer(answer = enteredPattern()) {
  const step = steps[index];
  clearInput();

  if (answer !== step.pattern) {
    feedbackEl.textContent = "Incorrect. Press: " + raisedDots(step.pattern).map(dotName).join(", ");
    say([`Incorrect. ${buttonsToPress(step.pattern)}`]);
    return;
  }

  const finished = index === steps.length - 1;
  index = finished ? 0 : index + 1;
  render();
  feedbackEl.textContent = "Good job!";
  const intro = finished ? "Good job! You did every letter. Starting over." : "Good job!";
  say([`${intro} Next is: ${nameOf(steps[index])}`]);
  prefetchLearn();
}

// Warm the audio cache so feedback plays without a pause.
function prefetchLearn() {
  const step = steps[index];
  const upcoming = steps[index + 1];
  getAudioUrl(promptFor(step));
  getAudioUrl(`Incorrect. ${buttonsToPress(step.pattern)}`);
  if (upcoming) getAudioUrl(`Good job! Next is: ${nameOf(upcoming)}`);
}

// ---------------------------------------------------------------- type mode

// Same table as braille_remote.ino, so the preview matches what the remote types.
const CAPITAL_SIGN_MASK = 32; // dot 6
const NUMBER_SIGN_MASK = 60;  // dots 3-4-5-6
const LETTER_MASKS = [1, 3, 9, 25, 17, 11, 27, 19, 10, 26, 5, 7, 13, 29, 21, 15, 31, 23, 14, 30, 37, 39, 58, 45, 61, 53];
const CHAR_FOR_MASK = { 0: " ", 2: ",", 6: ";", 18: ":", 50: ".", 22: "!", 38: "?", 4: "'", 36: "-" };
LETTER_MASKS.forEach((mask, i) => { CHAR_FOR_MASK[mask] = "abcdefghijklmnopqrstuvwxyz"[i]; });

const PUNCTUATION_NAMES = {
  ",": "comma", ";": "semicolon", ":": "colon", ".": "period",
  "!": "exclamation mark", "?": "question mark", "'": "apostrophe", "-": "dash",
};

// What Enter would produce for this cell: {kind: "char" | "capital" | "number" | "none", char}
function decodeCell(mask) {
  if (mask === CAPITAL_SIGN_MASK) return { kind: "capital" };
  if (mask === NUMBER_SIGN_MASK) return { kind: "number" };
  let char = CHAR_FOR_MASK[mask];
  if (char === undefined) return { kind: "none" };
  const aToJ = "abcdefghij".indexOf(char);
  if (numberMode && aToJ >= 0) return { kind: "char", char: String((aToJ + 1) % 10) };
  if (capitalNext) char = char.toUpperCase();
  return { kind: "char", char };
}

function spokenName(char) {
  if (char === " ") return "Space";
  if (/[0-9]/.test(char)) return `Number ${char}`;
  if (/[A-Z]/.test(char)) return `Capital ${char}`;
  if (/[a-z]/.test(char)) return `Letter ${char.toUpperCase()}`;
  return PUNCTUATION_NAMES[char] || char;
}

function renderType() {
  const result = decodeCell(enteredMask());
  const preview =
    result.kind === "capital" ? "Capital sign" :
    result.kind === "number" ? "Number sign" :
    result.kind === "none" ? "No match" :
    result.char === " " ? "Space" : result.char;
  charEl.textContent = preview;
  charEl.classList.toggle("small", preview.length > 1);
  charEl.setAttribute("aria-label", "Enter will type: " + preview);
  $("capital-badge").classList.toggle("on", capitalNext);
  $("number-badge").classList.toggle("on", numberMode);
  typedTextEl.textContent = typedText;
}

// Show and speak a committed cell. The remote decodes it itself; the keyboard uses decodeCell.
function showTypeCommit(result, mask) {
  if (result.kind === "char") {
    typedText += result.char;
    feedbackEl.textContent = "";
    say([spokenName(result.char)]);
  } else if (result.kind === "capital") {
    say(["Capital sign"]);
  } else if (result.kind === "number") {
    say(["Number sign"]);
  } else {
    feedbackEl.textContent = "No braille character for " + raisedDots(patternFromMask(mask)).map(dotName).join(", ");
    say(["No match"]);
  }
  renderType();
}

// Keyboard / on-screen Enter in Type mode. Mirrors the sketch's commit().
function typeEnter() {
  const mask = enteredMask();
  const result = decodeCell(mask);
  if (result.kind === "capital") capitalNext = true;
  if (result.kind === "number") numberMode = true;
  if (result.kind === "char") {
    if (!/[0-9]/.test(result.char)) numberMode = false; // space or any non a-j ends numbers
    capitalNext = false;
  }
  entered = entered.map(() => false);
  renderInput();
  showTypeCommit(result, mask);
}

function backspace() {
  if (!typedText) return say(["Nothing to delete"]);
  const removed = typedText.slice(-1);
  typedText = typedText.slice(0, -1);
  renderType();
  say([`Deleted ${spokenName(removed)}`]);
}

function clearTyped() {
  typedText = "";
  renderType();
  say(["Cleared"]);
}

// ---------------------------------------------------------------- navigation

function goTo(newIndex, crossedSpace) {
  index = newIndex;
  render();
  if (mode === "learn") {
    clearInput();
    feedbackEl.textContent = "";
    say([promptFor(steps[index])]);
    prefetchLearn();
  } else {
    say(crossedSpace ? ["Space", steps[index].spoken] : [steps[index].spoken]);
    const upcoming = steps[index + 1];
    if (upcoming) getAudioUrl(upcoming.spoken);
  }
}

function next() {
  if (mode === "type") return;
  if (index >= steps.length - 1) return say(["End of text"]);
  goTo(index + 1, steps[index + 1].space_before);
}

function prev() {
  if (mode === "type") return;
  if (index <= 0) return say(["Start of text"]);
  goTo(index - 1, steps[index].space_before);
}

function repeat() {
  if (mode === "type") return say([typedText.trim() ? typedText.slice(-150) : "Nothing typed yet"]);
  say([mode === "learn" ? promptFor(steps[index]) : steps[index].spoken]);
}

function enter() {
  if (mode === "learn") checkAnswer();
  else if (mode === "type") typeEnter();
  else next();
}

function readerOpen() {
  return !readerScreen.hidden;
}

function openReader(newMode) {
  mode = newMode;
  readerScreen.dataset.mode = mode;
  for (const el of readerScreen.querySelectorAll("[data-show]")) {
    el.hidden = !el.dataset.show.split(" ").includes(mode);
  }
  feedbackEl.textContent = "";
  inputScreen.hidden = true;
  readerScreen.hidden = false;
  $({ learn: "check-button", read: "next-button", type: "enter-button" }[mode]).focus();
}

async function start(newMode) {
  formError.textContent = "";
  if (newMode === "type") {
    typedText = "";
    capitalNext = numberMode = false; // the remote re-syncs these on its next Enter
    openReader("type");
    clearInput();
    say(["Start typing. Press Enter after each letter."]);
    return;
  }

  let data;
  try {
    const r = await fetch("/api/steps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: textInput.value }),
    });
    if (!r.ok) throw new Error();
    data = await r.json();
  } catch {
    formError.textContent = "Could not reach the server. Is it running?";
    return;
  }
  // Learn mode skips punctuation: there is nothing to type for it.
  const usable = newMode === "learn" ? data.steps.filter((s) => s.pattern !== "000000") : data.steps;
  if (!usable.length) {
    formError.textContent = newMode === "learn" ? "Type some letters or numbers first." : "Type some text first.";
    textInput.focus();
    return;
  }
  steps = usable;
  openReader(newMode);
  goTo(0, false);
}

function backToInput() {
  playToken++;
  stopSpeech();
  readerScreen.hidden = true;
  inputScreen.hidden = false;
  textInput.focus();
  textInput.select();
}

// ---------------------------------------------------------------- input

textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  start(e.submitter?.dataset.mode || "learn");
});

textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    start("learn");
  }
});

$("prev-button").addEventListener("click", prev);
$("next-button").addEventListener("click", next);
$("check-button").addEventListener("click", () => checkAnswer());
$("enter-button").addEventListener("click", typeEnter);
$("backspace-button").addEventListener("click", backspace);
$("clear-button").addEventListener("click", clearTyped);
$("repeat-button").addEventListener("click", repeat);
$("back-button").addEventListener("click", backToInput);
for (const dot of inputDots) {
  dot.addEventListener("click", () => toggleDot(Number(dot.dataset.dot)));
}

const SHORTCUTS = {
  ArrowRight: next,
  ArrowLeft: prev,
  r: repeat,
  R: repeat,
  Escape: backToInput,
};

document.addEventListener("keydown", (e) => {
  if (!readerOpen() || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
  const onButton = e.target.closest?.("button");
  let action = SHORTCUTS[e.key];

  if (mode === "read") {
    if (e.key === " ") action = next; // Space is always "next"
  } else {
    const dot = DOT_KEYS[e.key.toLowerCase()];
    if (dot) action = () => toggleDot(dot);
    // Enter/Space commit the cell, unless a button has focus (then it's pressed as normal).
    if ((e.key === "Enter" || e.key === " ") && !onButton) action = enter;
    if (mode === "type" && e.key === "Backspace") action = backspace;
  }

  if (!action) return;
  e.preventDefault();
  action();
});

// Firefox clicks a focused button on Space keyup; in Read mode Space means "next" only.
document.addEventListener("keyup", (e) => {
  if (readerOpen() && mode === "read" && e.key === " ") e.preventDefault();
});

// ---------------------------------------------------------------- server link

function setArduinoStatus(connected) {
  statusEl.textContent = connected ? "Arduino: connected" : "Arduino: not connected";
  // A freshly plugged-in board is blank, so send it the current character.
  if (connected && readerOpen() && mode !== "type") sendToArduino(steps[index]);
}

// A cell committed on braille_remote.ino (Enter pressed on the remote).
function remoteCommit(msg) {
  if (mode === "learn") {
    checkAnswer(patternFromMask(msg.mask));
  } else if (mode === "type") {
    const result =
      msg.char !== null ? { kind: "char", char: msg.char } :
      msg.mask === CAPITAL_SIGN_MASK ? { kind: "capital" } :
      msg.mask === NUMBER_SIGN_MASK ? { kind: "number" } : { kind: "none" };
    showTypeCommit(result, msg.mask);
  } else {
    next();
  }
}

// Remote buttons arrive here and do exactly what the keyboard does.
const BUTTONS = { next, prev, repeat, enter };

function handleRemote(msg) {
  if (msg.type === "mode") {
    capitalNext = msg.capital;
    numberMode = msg.number;
    if (readerOpen() && mode === "type") renderType();
    return;
  }
  if (!readerOpen()) {
    // Judges can start the lesson straight from the remote's Enter button.
    if (msg.type === "commit" || (msg.type === "button" && msg.action === "enter")) start("learn");
    return;
  }
  if (msg.type === "dot") toggleDot(msg.dot);
  if (msg.type === "cell") setCellFromRemote(msg.mask, msg.quiet);
  if (msg.type === "commit") remoteCommit(msg);
  if (msg.type === "button" && BUTTONS[msg.action]) BUTTONS[msg.action]();
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "status") setArduinoStatus(msg.arduino);
    else handleRemote(msg);
  };
  ws.onclose = () => {
    setArduinoStatus(false);
    setTimeout(connectWebSocket, 2000);
  };
}

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => { elevenLabsEnabled = s.elevenlabs; })
  .catch(() => {});

connectWebSocket();
textInput.focus();
