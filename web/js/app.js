import { parseChordPro, chordsIn } from "./chordpro.js";
import {
  guessKey, keyName, normalizeOffset, parseKey, semitonesBetween,
  transposeChord, transposeKey, TONIC_CHOICES,
} from "./chords.js";
import { renderSection, el } from "./render.js";

const $ = (id) => document.getElementById(id);
const app = $("app");

const store = {
  get(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : JSON.parse(value);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: settings just won't persist */
    }
  },
};

let songIndex = null;
let current = null;

async function loadIndex() {
  if (!songIndex) {
    const response = await fetch("songs/index.json", { cache: "no-cache" });
    songIndex = await response.json();
  }
  return songIndex;
}

// ---------- Library ----------

async function showLibrary() {
  current = null;
  document.title = "Chord Viewer";
  $("page-title").textContent = "Songs";
  for (const id of ["back", "font-down", "font-up", "awake", "transpose-bar"]) $(id).hidden = true;
  releaseWakeLock();

  app.replaceChildren($("library-template").content.cloneNode(true));
  const list = $("song-list");
  const search = $("search");
  const songs = await loadIndex();

  const draw = () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren();
    for (const song of songs) {
      const haystack = [song.title, song.artist, ...song.songs].join(" ").toLowerCase();
      if (q && !haystack.includes(q)) continue;
      const item = el("li");
      const link = el("a", "song-link");
      link.href = `#/song/${encodeURIComponent(song.file)}`;
      link.append(el("span", "song-title", song.title));
      const sub = song.songs.length > 1 ? `Medley · ${song.songs.join(" · ")}` : song.artist;
      if (sub) link.append(el("span", "song-sub", sub));
      item.append(link);
      list.append(item);
    }
    if (!list.children.length) list.append(el("li", "empty", "No songs found"));
  };
  search.addEventListener("input", draw);
  draw();
}

// ---------- Song view ----------

function settingsKey(file) {
  return `cv:transpose:${file}`;
}

function saveOffsets() {
  store.set(settingsKey(current.file), { global: current.global, parts: current.parts });
}

function partOffset(i) {
  return normalizeOffset(current.global + current.parts[i]);
}

function formatter(i) {
  const offset = partOffset(i);
  const target = transposeKey(current.keys[i], offset);
  return (chord) => transposeChord(chord, offset, target);
}

function signed(n) {
  return n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "0";
}

async function showSong(file) {
  const response = await fetch(`songs/${file}`, { cache: "no-cache" });
  if (!response.ok) {
    app.replaceChildren(el("p", "empty", `Could not load ${file}`));
    return;
  }
  const song = parseChordPro(await response.text());
  const keys = song.songs.map((p) => parseKey(p.key) ?? guessKey(chordsIn(p)));
  const saved = store.get(settingsKey(file), null);
  const parts = song.songs.map((_, i) => saved?.parts?.[i] ?? 0);
  current = { file, song, keys, global: saved?.global ?? 0, parts };

  document.title = song.title || "Chord Viewer";
  $("page-title").textContent = song.title || file;
  for (const id of ["back", "font-down", "font-up", "awake", "transpose-bar"]) $(id).hidden = false;
  $("unify").hidden = song.songs.length < 2;
  $("global-label").textContent = song.songs.length > 1 ? "Medley" : "Transpose";
  drawSong();
  window.scrollTo(0, 0);
  if (store.get("cv:awake", false)) requestWakeLock();
}

function drawSong() {
  const { song, keys } = current;
  const medley = song.songs.length > 1;
  const container = el("div", "sheet");

  song.songs.forEach((part, i) => {
    const partNode = el("article", "part");
    const offset = partOffset(i);
    const target = transposeKey(keys[i], offset);
    const head = el("header", "part-head");
    if (medley) head.append(el("h2", "part-name", part.name ?? "Intro"));
    if (keys[i]) {
      const keyLabel = el("span", "key-chip");
      keyLabel.textContent = offset === 0
        ? `Key ${keyName(keys[i])}`
        : `Key ${keyName(target)} (${keyName(keys[i])} ${signed(offset)})`;
      head.append(keyLabel);
    }
    if (medley && keys[i]) {
      const stepper = el("div", "stepper small");
      const down = el("button", null, "−");
      const up = el("button", null, "+");
      down.setAttribute("aria-label", `${part.name}: down a semitone`);
      up.setAttribute("aria-label", `${part.name}: up a semitone`);
      down.onclick = () => shiftPart(i, -1);
      up.onclick = () => shiftPart(i, 1);
      stepper.append(down, el("output", null, signed(current.parts[i])), up);
      head.append(stepper);
    }
    partNode.append(head);
    const format = formatter(i);
    for (const section of part.sections) partNode.append(renderSection(section, format));
    container.append(partNode);
  });

  app.replaceChildren(container);
  $("global-value").textContent = signed(current.global);
  drawUnify();
}

function drawUnify() {
  const select = $("unify");
  const tonics = current.keys
    .map((k, i) => (k ? transposeKey(k, partOffset(i)).tonic : null))
    .filter((t) => t !== null);
  const same = tonics.length && tonics.every((t) => t === tonics[0]) ? tonics[0] : null;
  select.replaceChildren(el("option", null, "All in…"));
  select.firstChild.value = "";
  for (const { pc, name } of TONIC_CHOICES) {
    const option = el("option", null, `All in ${name}`);
    option.value = String(pc);
    if (pc === same) option.selected = true;
    select.append(option);
  }
  if (same === null) select.value = "";
}

function shiftPart(i, delta) {
  current.parts[i] = normalizeOffset(current.parts[i] + delta);
  saveOffsets();
  preserveScroll(drawSong);
}

function shiftGlobal(delta) {
  current.global = normalizeOffset(current.global + delta);
  saveOffsets();
  preserveScroll(drawSong);
}

function unifyTo(tonic) {
  current.global = 0;
  current.parts = current.keys.map((k) => (k ? semitonesBetween(k, tonic) : 0));
  saveOffsets();
  preserveScroll(drawSong);
}

function resetTranspose() {
  current.global = 0;
  current.parts = current.parts.map(() => 0);
  saveOffsets();
  preserveScroll(drawSong);
}

function preserveScroll(fn) {
  const y = window.scrollY;
  fn();
  window.scrollTo(0, y);
}

// ---------- Preferences ----------

function applyFontScale(scale) {
  document.documentElement.style.setProperty("--scale", String(scale));
}

function changeFont(delta) {
  const scale = Math.min(2.2, Math.max(0.7, +(store.get("cv:scale", 1) + delta).toFixed(2)));
  store.set("cv:scale", scale);
  applyFontScale(scale);
}

const THEMES = ["auto", "dark", "light"];

function applyTheme(theme) {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  $("theme").title = `Theme: ${theme}`;
}

let wakeLock = null;

async function requestWakeLock() {
  $("awake").setAttribute("aria-pressed", "true");
  if (!("wakeLock" in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
  } catch {
    wakeLock = null;
  }
}

function releaseWakeLock() {
  wakeLock?.release();
  wakeLock = null;
}

function toggleWakeLock() {
  const on = !store.get("cv:awake", false);
  store.set("cv:awake", on);
  if (on) requestWakeLock();
  else {
    $("awake").setAttribute("aria-pressed", "false");
    releaseWakeLock();
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && current && store.get("cv:awake", false)) requestWakeLock();
});

// ---------- Wiring ----------

$("back").onclick = () => {
  location.hash = "#/";
};
$("font-down").onclick = () => changeFont(-0.1);
$("font-up").onclick = () => changeFont(0.1);
$("awake").onclick = toggleWakeLock;
$("theme").onclick = () => {
  const next = THEMES[(THEMES.indexOf(store.get("cv:theme", "auto")) + 1) % THEMES.length];
  store.set("cv:theme", next);
  applyTheme(next);
};
$("global-down").onclick = () => shiftGlobal(-1);
$("global-up").onclick = () => shiftGlobal(1);
$("reset").onclick = resetTranspose;
$("unify").onchange = (e) => {
  if (e.target.value !== "") unifyTo(Number(e.target.value));
};

function route() {
  const match = /^#\/song\/(.+)$/.exec(location.hash);
  if (match) showSong(decodeURIComponent(match[1]));
  else showLibrary();
}

applyFontScale(store.get("cv:scale", 1));
applyTheme(store.get("cv:theme", "auto"));
window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
