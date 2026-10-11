// Lumi front end. Plain JavaScript, no build step.
//
// Three modes share one screen (elements with data-show="..." only appear in those modes):
//   Learn: "Type the letter A." The user presses dots (remote or keyboard) and Enter.
//          Wrong -> we say which buttons to press. Right -> next letter.
//   Read:  show and speak each character of the text, one at a time.
//   Snap:  hold something up to the webcam; Gemini reads it and Learn mode
//          teaches that word ("I see a pen. Write pen."). Each letter is on the
//          rotating braille wheel to feel first; letters not on it flash on the LEDs.
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
const wheelStatusEl = $("wheel-status");
const cameraScreen = $("camera-screen");
const video = $("camera");
const cameraStatus = $("camera-status");
const cameraPermissionEl = $("camera-permission");
const targetDots = [...cellEl.querySelectorAll(".dot")];
const inputDots = [...document.querySelectorAll(".dot-button")];

let mode = "learn";    // "learn", "read" or "type"
let steps = [];        // [{char, spoken, pattern, is_number_sign, space_before, hint}]
let lessonSteps = [];  // Learn: the original lesson; steps may also hold review copies
let mistakes = {};     // Learn: wrong answers per character this lesson
let index = 0;
let entered = [false, false, false, false, false, false]; // dots 1-6 the user pressed
let elevenLabsEnabled = true;
let visionEnabled = false;
let askEnabled = false;
let wheelOnly = false;       // lessons only use the letters on the wheel
let wheelLetters = "abceilnp";
let lessonWord = "";   // Snap: the word from the photo, e.g. "Tylenol"

// Type mode state (the remote keeps its own copy and reports it in "mode" messages).
let typedText = "";
let capitalNext = false;
let numberMode = false;

// Buttons are named by position on the remote, not by dot number.
const ROW = { 1: "top", 2: "middle", 3: "bottom", 4: "top", 5: "middle", 6: "bottom" };
const COLUMN = { 1: "left", 2: "left", 3: "left", 4: "right", 5: "right", 6: "right" };
const capitalize = (s) => s[0].toUpperCase() + s.slice(1);
// Buttons are called by number and position: "1, top left" (spoken), "1 top left" (shown).
const dotName = (n) => `${n}, ${ROW[n]} ${COLUMN[n]}`;
const dotText = (n) => `${n} ${ROW[n]} ${COLUMN[n]}`;

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
    audio.play().catch((error) => {
      if (error.name === "NotAllowedError") audioBlocked = true;
      resolve(false);
    });
  });
}

// Fallback so the app never goes silent: the browser's built-in voice.
function browserSay(text) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.9;
    utterance.onend = () => resolve();
    utterance.onerror = (e) => {
      if (e.error === "not-allowed") audioBlocked = true;
      resolve();
    };
    finishCurrent = resolve;
    speechSynthesis.speak(utterance);
  });
}

// Browsers block sound until someone touches the page (start.sh turns that off).
// If it was blocked, replay the last thing said on the first key press or click.
let audioBlocked = false;
let lastSpoken = [];
function replayIfBlocked() {
  if (audioBlocked) {
    audioBlocked = false;
    say(lastSpoken);
  }
}
document.addEventListener("pointerdown", replayIfBlocked);
document.addEventListener("keydown", replayIfBlocked);

// /speak takes up to 200 characters, so longer replies are spoken a sentence at a time.
const MAX_SPEAK_CHARS = 200;
function speakable(text) {
  if (text.length <= MAX_SPEAK_CHARS) return [text];
  const sentences = text.match(/[^.!?]+[.!?]*\s*/g) || [text];
  return sentences.flatMap((sentence) => {
    const pieces = [];
    for (let rest = sentence.trim(); rest; ) {
      const space = rest.lastIndexOf(" ", MAX_SPEAK_CHARS);
      const cut = rest.length <= MAX_SPEAK_CHARS ? rest.length : space > 0 ? space : MAX_SPEAK_CHARS;
      pieces.push(rest.slice(0, cut).trim());
      rest = rest.slice(cut).trim();
    }
    return pieces;
  }).filter(Boolean);
}

// Speak a list of phrases in order, e.g. ["Space", "Letter B"].
async function say(parts) {
  parts = parts.flatMap(speakable);
  lastSpoken = parts;
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

// While pressing dots, keep the hint for the current letter visible.
function resetFeedback() {
  feedbackEl.textContent = mode === "learn" ? hintText(steps[index]) : "";
}

// Keyboard, on-screen click, or "DOT n" test line: the page holds the cell.
function toggleDot(n) {
  if (mode === "read") return;
  entered[n - 1] = !entered[n - 1];
  resetFeedback();
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
    resetFeedback();
    say([entered[n - 1] ? dotName(n) : `${dotName(n)} off`]);
  }
}

// ---------------------------------------------------------------- learn mode
//
// The coach (app/coach.py) explains *why* an answer is wrong: mirror image,
// one row off, a missing or extra dot. Letters you miss come back for review,
// and the lesson ends with a short summary.

// "the letter A", "the number 5", "the number sign"
function nameOf(step) {
  if (step.is_number_sign) return "the number sign";
  if (/[0-9]/.test(step.char)) return `the number ${step.char}`;
  return `the letter ${step.char.toUpperCase()}`;
}

// How the coach refers to the target: "D", "4" or "the number sign"
const targetOf = (step) => (step.is_number_sign ? "the number sign" : step.char.toUpperCase());

// Spoken: "1, top left. 3, bottom left." Left column first, top to bottom.
function buttonsToPress(pattern) {
  return raisedDots(pattern).map((n) => `${dotName(n)}.`).join(" ");
}

// Letters on the wheel are felt first. Others flash on the LEDs and we read the dots out.
function findIt(step) {
  if (step.on_wheel) return "Feel it on the wheel.";
  return `It's not on the wheel. Press ${buttonsToPress(step.pattern)}`;
}

// The structure hint only for wheel letters; for the others we already read out the dots.
const hintFor = (step) => (step.hint && step.on_wheel && !step.review ? step.hint : "");
const hintText = (step) => (hintFor(step) ? "Hint: " + hintFor(step) : "");

// "Next is: the letter P. Feel it on the wheel."  /  "Let's try D again. Feel it on the wheel."
function introFor(step) {
  const first = step.review ? `Let's try ${nameOf(step)} again.` : `Next is: ${nameOf(step)}.`;
  return [first, findIt(step), hintFor(step) && `Hint: ${hintFor(step)}`].filter(Boolean).join(" ");
}

// "Type the letter P. Feel it on the wheel. Hint: P is F plus bottom left."
function promptFor(step) {
  if (step.review) return introFor(step);
  return [`Type ${nameOf(step)}.`, findIt(step), hintFor(step) && `Hint: ${hintFor(step)}`].filter(Boolean).join(" ");
}

async function coachCheck(step, answer) {
  try {
    const r = await fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: targetOf(step), expected: step.pattern, got: answer }),
    });
    if (r.ok) return await r.json();
  } catch {}
  // Server unreachable: plain right/wrong.
  const correct = answer === step.pattern;
  return {
    correct,
    spoken: correct ? "Good job!" : `Good try. ${buttonsToPress(step.pattern)}`,
    text: correct ? "Good job!" : "Good try. Press: " + raisedDots(step.pattern).map(dotText).join(", "),
  };
}

function lessonSummary() {
  const total = lessonSteps.filter((s) => !s.is_number_sign).length;
  const missed = Object.values(mistakes).reduce((a, b) => a + b, 0);
  const things = total === 1 ? "1 character" : `${total} characters`;
  if (!missed) return { spoken: `Lesson complete! ${things}, all on the first try. Wonderful.`, text: `Lesson complete! ${things}, all on the first try.` };
  const [trickiest] = Object.entries(mistakes).sort((a, b) => b[1] - a[1])[0];
  const name = nameOf({ char: trickiest, is_number_sign: trickiest === "#" });
  return {
    spoken: `Lesson complete! You practiced ${things}. Nice work. One to keep practicing: ${name}.`,
    text: `Lesson complete! ${things} practiced · keep practicing: ${name.replace(/^the /, "")}`,
  };
}

async function checkAnswer(answer = enteredPattern()) {
  const step = steps[index];
  clearInput();
  const result = await coachCheck(step, answer);

  if (!result.correct) {
    const key = step.is_number_sign ? "#" : step.char.toLowerCase();
    mistakes[key] = (mistakes[key] || 0) + 1;
    step.missed = true;
    feedbackEl.textContent = result.text;
    say([result.spoken]);
    sendToArduino(step); // wheel stays on the right letter; off-wheel letters flash on the LEDs again
    return;
  }

  // Missed letters come back for review a couple of letters later.
  if (step.missed && !step.review && /^[a-z]$/i.test(step.char)) {
    steps.splice(Math.min(index + 3, steps.length), 0, { ...step, review: true, missed: false });
  }

  if (index === steps.length - 1 && lessonWord) {
    // Snap lesson done: celebrate, then straight back to the camera for the next thing.
    const summary = lessonSummary();
    feedbackEl.textContent = summary.text;
    const word = lessonWord;
    lessonWord = "";
    openCamera({ speak: false, waitForNewObject: true });
    cameraStatus.textContent = `You wrote ${word} in braille! Hold up something new.`;
    say([`You just wrote ${word} in braille! ${summary.spoken}`, "Hold up something new, or press Enter to ask for a word."]);
    return;
  }

  if (index === steps.length - 1) {
    const summary = lessonSummary();
    steps = lessonSteps.map((s) => ({ ...s, missed: false }));
    mistakes = {};
    index = 0;
    render();
    feedbackEl.textContent = summary.text;
    say([`${summary.spoken} Starting over. ${introFor(steps[0])}`]);
  } else {
    index += 1;
    render();
    feedbackEl.textContent = ["Good job!", hintText(steps[index])].filter(Boolean).join(" ");
    say([`Good job! ${introFor(steps[index])}`]);
  }
  prefetchLearn();
}

// Warm the audio cache so the next prompts play without a pause.
function prefetchLearn() {
  const upcoming = steps[index + 1];
  getAudioUrl(promptFor(steps[index]));
  if (upcoming) getAudioUrl(`Good job! ${introFor(upcoming)}`);
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
    feedbackEl.textContent = "Not a letter yet: " + raisedDots(patternFromMask(mask)).map(dotText).join(", ");
    say(["That isn't a letter yet. Try again."]);
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

function goTo(newIndex, crossedSpace, intro = "") {
  index = newIndex;
  render();
  if (mode === "learn") {
    clearInput();
    feedbackEl.textContent = hintText(steps[index]);
    say(intro ? [intro, promptFor(steps[index])] : [promptFor(steps[index])]);
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

async function start(newMode, intro = "") {
  formError.textContent = "";
  lessonWord = "";
  if (newMode === "snap") return openCamera();
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
  let usable = newMode === "learn" ? data.steps.filter((s) => s.pattern !== "000000") : data.steps;
  if (!usable.length) {
    formError.textContent = newMode === "learn" ? "Type some letters or numbers first." : "Type some text first.";
    textInput.focus();
    return false;
  }

  // Wheel-only: keep the letters the wheel has, and say which ones we skip.
  if (newMode === "learn" && wheelOnly) {
    const skipped = [...new Set(usable.filter((s) => !fitsWheel(s)).map((s) => (/[0-9#]/.test(s.char) ? "numbers" : s.char.toUpperCase())))];
    usable = usable.filter(fitsWheel);
    if (!usable.length) {
      nothingOnWheel(Boolean(intro));
      return false;
    }
    if (skipped.length) intro = [intro, skippedNote(skipped)].filter(Boolean).join(" ");
  }
  lessonSteps = usable;
  steps = usable.map((s) => ({ ...s })); // copies: review steps get added to this list
  mistakes = {};
  openReader(newMode);
  goTo(0, false, intro);
  return true;
}

// ---- wheel-only helpers
// Numbers need the number sign, which isn't on the wheel, so they're skipped too.
const fitsWheel = (step) => step.on_wheel && !step.is_number_sign && !/[0-9]/.test(step.char);

const listWords = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);

// "V isn't on your wheel, so we'll skip it."
function skippedNote(skipped) {
  const letters = skipped.filter((x) => x !== "numbers");
  const parts = [];
  if (letters.length === 1) parts.push(`${letters[0]} isn't on your wheel, so we'll skip it.`);
  if (letters.length > 1) parts.push(`${listWords(letters)} aren't on your wheel, so we'll skip them.`);
  if (skipped.includes("numbers")) parts.push("Numbers aren't on your wheel yet, so we'll skip them.");
  return parts.join(" ");
}

// Nothing in the request is on the wheel: say what is, and suggest words that work.
function nothingOnWheel(fromCameraOrVoice) {
  const letters = listWords(wheelLetters.toUpperCase().split(""));
  const message = `None of those letters are on your wheel. Your wheel has ${letters}. Try a pen, an apple, or a ball.`;
  if (fromCameraOrVoice) {
    openCamera({ speak: false, waitForNewObject: true });
    cameraStatus.textContent = message;
  } else {
    formError.textContent = message;
    textInput.focus();
  }
  say([message]);
}

function backToInput() {
  playToken++;
  stopSpeech();
  closeCamera();
  readerScreen.hidden = true;
  inputScreen.hidden = false;
  textInput.focus();
  textInput.select();
}

// ---------------------------------------------------------------- snap (camera + Gemini)

let cameraStream = null;
let snapping = false;

const cameraOpen = () => !cameraScreen.hidden;

// The round status icons at the top: lit when on; the words go to screen readers and the tooltip.
function setIconStatus(icon, on, words) {
  icon.dataset.state = on ? "on" : "off";
  icon.title = words;
  icon.querySelector(".sr-only").textContent = words;
}

// Camera status: "Camera: allowed / blocked / not allowed yet", kept up to date.
let cameraPermission = "unknown";
const CAMERA_STATES = { granted: "Camera: allowed", denied: "Camera: blocked", prompt: "Camera: not allowed yet" };

async function watchCameraPermission() {
  try {
    const status = await navigator.permissions.query({ name: "camera" });
    const show = () => {
      cameraPermission = status.state;
      setIconStatus(cameraPermissionEl, status.state === "granted", CAMERA_STATES[status.state] || "Camera");
    };
    show();
    status.onchange = show;
  } catch {} // some browsers can't report it; the error messages below still explain
}

// Plain-language fix for each way opening the camera can fail.
// Send a line to the server's terminal, so problems on this screen can be diagnosed there.
function reportToServer(message) {
  fetch("/api/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: message.slice(0, 1000) }),
  }).catch(() => {});
}

function cameraErrorMessage(error) {
  switch (error.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "The camera is blocked. In Chrome, click the camera icon at the right end of the address bar and choose Allow, then click Snap again. Still blocked? On your Mac open System Settings > Privacy & Security > Camera, turn on Google Chrome, and restart Chrome.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No camera found. Check a webcam is connected and switched on.";
    case "NotReadableError":
    case "AbortError":
      return "The camera is busy. Quit other apps using it (Zoom, FaceTime, Photo Booth) and click Snap again.";
    default:
      return `Couldn't open the camera (${error.name || error}). Try Chrome at http://127.0.0.1:8000.`;
  }
}

const HOLD_UP =
  "Hold up any object to the camera, and I'll teach you its name in braille. " +
  "Or press Enter and tell me what you'd like to learn.";

async function openCamera({ speak = true, welcome = false, waitForNewObject = false } = {}) {
  if (!visionEnabled) {
    formError.textContent = "Snap needs a Gemini API key in .env (GEMINI_API_KEY).";
    say(["Snap needs a Gemini API key."]);
    return;
  }
  inputScreen.hidden = true;
  readerScreen.hidden = true;
  cameraScreen.hidden = false;
  if (!cameraStream) {
    if (!navigator.mediaDevices?.getUserMedia) {
      reportToServer(`camera unavailable in this browser: ${navigator.userAgent}`);
      showCameraError("This browser can't use the camera here. Open http://127.0.0.1:8000 in Chrome.");
      return;
    }
    if (cameraPermission !== "granted") {
      cameraStatus.textContent = "Snap needs your camera. Click Allow when the browser asks.";
      say(["Snap needs your camera. Please click Allow."]);
    }
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
    } catch (error) {
      reportToServer(`camera failed: ${error.name}: ${error.message} | permission=${cameraPermission} | ${navigator.userAgent}`);
      showCameraError(cameraErrorMessage(error));
      return;
    }
    reportToServer(`camera opened: ${cameraStream.getVideoTracks()[0]?.label} | ${navigator.userAgent}`);
    video.srcObject = cameraStream;
  }
  $("talk-button").focus();
  startWatching({ armed: !waitForNewObject });
  lastReminder = Date.now(); // don't talk over the welcome or the lesson summary
  if (speak) {
    cameraStatus.textContent = "Hold up an object, or press Enter and say what to learn.";
    say([welcome ? `Welcome to Lumi. ${HOLD_UP}` : HOLD_UP]);
  }
}

function showCameraError(message) {
  closeCamera();
  inputScreen.hidden = false;
  formError.textContent = message;
  say(["I couldn't open the camera. The fix is on the screen."]);
  $("snap-button").focus();
}

function closeCamera() {
  stopWatching();
  if (cameraStream) cameraStream.getTracks().forEach((track) => track.stop());
  cameraStream = null;
  video.srcObject = null;
  cameraScreen.hidden = true;
}

// Grab a frame, ask Gemini what it is, and turn the word into a lesson.
// Manual (Enter / button) or automatic (something held steady in view).
async function takePhoto({ auto = false } = {}) {
  if (snapping || !video.videoWidth) return;
  snapping = true;
  cameraStatus.textContent = "Looking...";
  if (!auto) say(["Looking."]);

  const scale = Math.min(1, 1024 / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);

  try {
    const r = await fetch("/api/snap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: canvas.toDataURL("image/jpeg", 0.85) }),
    });
    if (!r.ok) throw new Error();
    const result = await r.json();
    if (talking || !cameraOpen()) return; // they started talking (or left) while we looked
    if (!result.found) {
      cameraStatus.textContent = "Hold up any object and keep it still.";
      nothingSeen(auto);
      return;
    }
    const { description, word } = result;
    const Word = capitalize(word);
    closeCamera();
    textInput.value = Word;
    if (!(await start("learn", `${description} Write ${Word}.`))) return;
    lessonWord = Word;
    feedbackEl.textContent = `From your photo: ${Word}`;
  } catch {
    cameraStatus.textContent = "I couldn't read that. Hold it closer.";
    if (!auto) say(["I couldn't read that. Hold it closer and keep it still."]);
  } finally {
    snapping = false;
  }
}

// Nothing to learn in the picture. Say so when asked; when watching, only remind now and then.
let lastReminder = 0;
function nothingSeen(auto) {
  if (!auto || Date.now() - lastReminder > 20000) {
    lastReminder = Date.now();
    say(["I don't see an object yet. Hold it close to the camera and keep it still."]);
  }
}

// ---- hands-free: look automatically when something is held steady in front of the camera.
// Compares tiny grayscale frames: movement "arms" it, then ~1 s of stillness takes the photo.
const MOTION = 10;       // average pixel change (0-255) that counts as movement
const STILL = 4;         // below this the picture is steady
const STEADY_MS = 900;   // how long it must stay steady
const MIN_GAP_MS = 3000; // at most one look every 3 s (keeps Gemini calls low)

const tiny = document.createElement("canvas");
tiny.width = 48;
tiny.height = 36;
const tinyContext = tiny.getContext("2d", { willReadFrequently: true });
let watchTimer = null;
let previousFrame = null;
let armed = false;
let steadySince = 0;
let lastLook = 0;

function frameChange() {
  tinyContext.drawImage(video, 0, 0, tiny.width, tiny.height);
  const pixels = tinyContext.getImageData(0, 0, tiny.width, tiny.height).data;
  const frame = new Uint8Array(tiny.width * tiny.height);
  let total = 0;
  for (let i = 0; i < frame.length; i++) {
    frame[i] = (pixels[i * 4] + pixels[i * 4 + 1] + pixels[i * 4 + 2]) / 3;
    if (previousFrame) total += Math.abs(frame[i] - previousFrame[i]);
  }
  const hadPrevious = previousFrame !== null;
  previousFrame = frame;
  return hadPrevious ? total / frame.length : 0;
}

function watchTick() {
  if (!cameraOpen() || snapping || !video.videoWidth) return;
  const change = frameChange();
  const now = Date.now();
  if (change > MOTION) {
    armed = true; // something moved: look once it settles
    steadySince = 0;
  } else if (change < STILL) {
    steadySince = steadySince || now;
    if (armed && now - steadySince >= STEADY_MS && now - lastLook >= MIN_GAP_MS) {
      armed = false; // after looking, wait for new movement before looking again
      lastLook = now;
      takePhoto({ auto: true });
    }
  } else {
    steadySince = 0;
  }
}

// armed: look as soon as the picture is steady (on first open the object may already be there).
// After a lesson, wait for movement so the same object doesn't start the same lesson again.
function startWatching({ armed: armNow }) {
  stopWatching();
  previousFrame = null;
  armed = armNow;
  steadySince = 0;
  watchTimer = setInterval(watchTick, 200);
}

function stopWatching() {
  clearInterval(watchTimer);
  watchTimer = null;
}

// ---------------------------------------------------------------- ask (voice)
//
// Press Enter (remote or keyboard), hear a beep, and talk to Lumi like a person:
// "What is braille?" -> an answer -> "How do I write my name?" -> "What's your name?" -> lesson.
// After each reply it listens again, until they go quiet or say goodbye.
// ElevenLabs turns speech into text; Gemini replies to the whole conversation.

const MIN_SPEECH_LEVEL = 0.01; // mic loudness (RMS) that always counts as talking...
const NOISE_MULTIPLE = 3;      // ...or this many times the room's background noise, if louder
const NOISE_SAMPLE_MS = 250;   // background noise is measured right after the beep
const END_SILENCE_MS = 1200; // stop recording after this much quiet once they've spoken
const NO_SPEECH_MS = 6000;   // give up if nothing is said for this long
const MAX_RECORD_MS = 10000;
const MAX_TURNS = 20;        // back-and-forths in one conversation

let micStream = null;
let talking = false;   // in a conversation: automatic looks are ignored
let listening = false;
let stopRecording = false;

// A short tone: high = "I'm listening", low = "got it".
function beep(frequency, ms) {
  return new Promise((resolve) => {
    try {
      const context = new AudioContext();
      const tone = context.createOscillator();
      const volume = context.createGain();
      tone.frequency.value = frequency;
      volume.gain.value = 0.15;
      tone.connect(volume).connect(context.destination);
      tone.start();
      setTimeout(() => { tone.stop(); context.close(); resolve(); }, ms);
    } catch {
      resolve();
    }
  });
}

// Record until they stop talking. Resolves to an audio Blob, or null if nothing was said.
async function record() {
  micStream = micStream || (await navigator.mediaDevices.getUserMedia({ audio: true }));
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  context.createMediaStreamSource(micStream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
  const recorder = new MediaRecorder(micStream, type ? { mimeType: type } : {});
  const chunks = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);

  await beep(880, 120);
  listening = true;
  cameraScreen.classList.add("listening");
  stopRecording = false;
  cameraStatus.textContent = "Listening...";
  recorder.start(100);

  return new Promise((resolve) => {
    const startedAt = Date.now();
    let spoke = false;
    let lastSound = startedAt;
    let loudest = 0;
    let quietest = Infinity;
    let speechLevel = MIN_SPEECH_LEVEL;
    const timer = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      const level = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
      const now = Date.now();
      loudest = Math.max(loudest, level);
      if (now - startedAt < NOISE_SAMPLE_MS) {
        quietest = Math.min(quietest, level);
        speechLevel = Math.max(MIN_SPEECH_LEVEL, quietest * NOISE_MULTIPLE);
      }
      if (level > speechLevel) {
        spoke = true;
        lastSound = now;
      }
      const finished =
        stopRecording ||
        (spoke && now - lastSound > END_SILENCE_MS) ||
        (!spoke && now - startedAt > NO_SPEECH_MS) ||
        now - startedAt > MAX_RECORD_MS;
      if (!finished) return;
      clearInterval(timer);
      recorder.onstop = () => {
        context.close();
        cameraScreen.classList.remove("listening");
        if (!spoke) reportToServer(`no speech heard; loudest mic level ${loudest.toFixed(4)} (threshold ${speechLevel.toFixed(4)})`);
        listening = false;
        beep(440, 100);
        resolve(spoke || stopRecording ? new Blob(chunks, { type: recorder.mimeType }) : null);
      };
      recorder.stop();
    }, 50);
  });
}

function resumeScanning() {
  if (cameraOpen()) {
    cameraStatus.textContent = "Hold up an object, or press Enter and say what to learn.";
    startWatching({ armed: false });
  }
}

// A conversation: listen, reply, listen again, until they go quiet, say goodbye or ask for a lesson.
let lumiSpeaking = false;
async function talk() {
  if (listening) {
    stopRecording = true; // Enter again = "I'm done talking"
    return;
  }
  if (lumiSpeaking) {
    playToken++; // Enter while Lumi talks = cut in and listen
    stopSpeech();
    return;
  }
  if (talking) return;
  if (!askEnabled) {
    say(["Talking needs the ElevenLabs and Gemini keys."]);
    return;
  }
  stopWatching();
  playToken++;
  stopSpeech();
  talking = true;
  try {
    await conversation();
  } finally {
    talking = false;
  }
}

async function postJson(url, body, headers = { "Content-Type": "application/json" }) {
  const r = await fetch(url, { method: "POST", headers, body });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function conversation() {
  const turns = []; // [{role: "user" | "assistant", text}]
  for (let turn = 0; turn < MAX_TURNS; turn++) {
    let audio;
    try {
      audio = await record();
    } catch (error) {
      reportToServer(`microphone failed: ${error.name}: ${error.message}`);
      cameraStatus.textContent = "Couldn't use the microphone. Allow it in Chrome and in Mac System Settings > Privacy & Security > Microphone.";
      say(["I couldn't use the microphone."]);
      return resumeScanning();
    }
    if (!cameraOpen()) return; // they left the screen while it was listening
    if (!audio) {
      // Quiet after a chat just means they're done; quiet at the start may be a mic problem.
      say([turns.length ? "I'm here whenever you want to talk. Just press Enter." : "I didn't hear anything. Press Enter to try again."]);
      return resumeScanning();
    }

    cameraStatus.textContent = "Thinking...";
    let heard, result;
    try {
      ({ heard } = await postJson("/api/transcribe", audio, { "Content-Type": audio.type || "audio/webm" }));
      if (heard) {
        turns.push({ role: "user", text: heard.slice(0, 1000) });
        result = await postJson("/api/chat", JSON.stringify({ turns: turns.slice(-40) }));
      }
    } catch (error) {
      reportToServer(`talk failed: ${error.message}`);
      say(["Sorry, something went wrong on my side. Press Enter to try again."]);
      return resumeScanning();
    }
    if (!cameraOpen()) return;
    if (!heard) {
      await say(["Sorry, I didn't catch that. Could you say it again?"]);
      if (!cameraOpen()) return;
      continue;
    }

    turns.push({ role: "assistant", text: result.say });
    if (result.learn) return startSpokenLesson(result.learn, result.say);

    cameraStatus.textContent = `You said: "${heard}". Lumi: ${result.say}`;
    lumiSpeaking = true;
    try {
      await say([result.say]);
    } finally {
      lumiSpeaking = false;
    }
    if (!cameraOpen()) return; // they left the screen meanwhile
    if (result.done) return resumeScanning();
  }
  say(["That was a lovely chat. Press Enter any time to talk again."]);
  resumeScanning();
}

// "Let's write your name, Navi. N, A, V, I." then the lesson.
async function startSpokenLesson(text, intro) {
  const letters = text.replace(/\s+/g, "");
  const spelled = letters.length <= 12 ? ` ${letters.toUpperCase().split("").join(", ")}.` : "";
  closeCamera();
  textInput.value = text;
  if (!(await start("learn", `${intro}${spelled}`))) return;
  lessonWord = text;
  feedbackEl.textContent = `You asked for: ${text}`;
}

$("talk-button").addEventListener("click", talk);
$("shutter-button").addEventListener("click", () => takePhoto());
$("camera-back-button").addEventListener("click", backToInput);

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
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
  if (cameraOpen()) {
    const onButton = e.target.closest?.("button");
    if ((e.key === "Enter" || e.key === " ") && !onButton) { e.preventDefault(); talk(); }
    if (e.key === "Escape") { e.preventDefault(); backToInput(); }
    return;
  }
  if (!readerOpen()) return;
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
  setIconStatus(statusEl, connected, connected ? "Remote: connected" : "Remote: not connected");
  // A freshly plugged-in board is blank, so send it the current character.
  if (connected && readerOpen() && mode !== "type") sendToArduino(steps[index]);
}

// Two-board setup only: the Mega wheel's own icon. null = one board, so the icon stays hidden.
function setWheelStatus(connected) {
  wheelStatusEl.hidden = connected === null || connected === undefined;
  setIconStatus(wheelStatusEl, connected === true, connected ? "Wheel: connected" : "Wheel: not connected");
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
  const isEnter = msg.type === "commit" || (msg.type === "button" && msg.action === "enter");
  if (cameraOpen()) {
    if (isEnter) talk(); // the remote's Enter = "I want to say what to learn"
    return;
  }
  if (!readerOpen()) {
    // Judges can start straight from the remote: Snap if the camera is set up, else Learn.
    if (isEnter) start(visionEnabled ? "snap" : "learn");
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
    if (msg.type === "status") {
      if ("arduino" in msg) setArduinoStatus(msg.arduino);
      if ("wheel" in msg) setWheelStatus(msg.wheel);
    } else handleRemote(msg);
  };
  ws.onclose = () => {
    setArduinoStatus(false);
    if (!wheelStatusEl.hidden) setWheelStatus(false);
    setTimeout(connectWebSocket, 2000);
  };
}

fetch("/api/status")
  .then((r) => r.json())
  .then((s) => {
    elevenLabsEnabled = s.elevenlabs;
    visionEnabled = s.vision;
    askEnabled = s.ask;
    wheelOnly = s.wheel_only;
    wheelLetters = s.wheel_letters || wheelLetters;
    // Hands-free: go straight to the camera. (Escape shows the text screen for sighted helpers.)
    if (visionEnabled && !readerOpen()) openCamera({ welcome: true });
    else if (!readerOpen()) inputScreen.hidden = false;
  })
  .catch(() => { inputScreen.hidden = false; });

// ---------------------------------------------------------------- high contrast
// Plain black and white for low vision. Follows the system setting unless switched here.
const contrastButton = $("contrast-toggle");

function setContrast(high, remember) {
  document.documentElement.dataset.contrast = high ? "high" : "normal";
  contrastButton.setAttribute("aria-pressed", String(high));
  if (remember) {
    try { localStorage.setItem("lumi-contrast", high ? "high" : "normal"); } catch {}
  }
}

let savedContrast = null;
try { savedContrast = localStorage.getItem("lumi-contrast"); } catch {}
setContrast(savedContrast ? savedContrast === "high" : matchMedia("(prefers-contrast: more)").matches, false);
contrastButton.addEventListener("click", () => {
  const high = document.documentElement.dataset.contrast !== "high";
  setContrast(high, true);
  say([high ? "High contrast on." : "High contrast off."]);
});

watchCameraPermission();
connectWebSocket();
textInput.focus();
