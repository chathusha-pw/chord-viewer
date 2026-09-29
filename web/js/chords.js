const LETTERS = ["C", "D", "E", "F", "G", "A", "B"];
const LETTER_PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const MAJOR_KEY_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const MINOR_KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];
// Scale degree (letter steps above the tonic) used to spell each interval,
// e.g. interval 3 is spelled as a flat third, interval 6 as a sharp fourth.
const INTERVAL_DEGREE = [0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6];
const AWKWARD = new Set(["E#", "B#", "Cb", "Fb"]);

const CHORD_RE = /^([A-G])([#b♯♭]?)(.*?)(?:\/([A-G])([#b♯♭]?))?$/;

const mod12 = (n) => ((n % 12) + 12) % 12;

function accidentalValue(acc) {
  if (acc === "#" || acc === "♯") return 1;
  if (acc === "b" || acc === "♭") return -1;
  return 0;
}

export function notePc(name) {
  return mod12(LETTER_PC[name[0]] + accidentalValue(name.slice(1)));
}

export function parseChord(text) {
  const m = CHORD_RE.exec(text.trim());
  if (!m) return null;
  return {
    root: mod12(LETTER_PC[m[1]] + accidentalValue(m[2])),
    quality: m[3],
    bass: m[4] ? mod12(LETTER_PC[m[4]] + accidentalValue(m[5])) : null,
  };
}

export function isMinorQuality(quality) {
  return /^(m(?!aj)|min|-)/.test(quality);
}

/** A key is { tonic: pitch class, minor: bool }. */
export function parseKey(text) {
  if (!text) return null;
  const chord = parseChord(text.replace(/\s*(major|maj)$/i, "").replace(/\s*minor$/i, "m"));
  if (!chord) return null;
  return { tonic: chord.root, minor: isMinorQuality(chord.quality) };
}

export function keyName(key) {
  if (!key) return "?";
  return key.minor ? `${MINOR_KEY_NAMES[key.tonic]}m` : MAJOR_KEY_NAMES[key.tonic];
}

export function transposeKey(key, semitones) {
  return key ? { tonic: mod12(key.tonic + semitones), minor: key.minor } : null;
}

function prefersFlats(key) {
  const name = keyName(key);
  return name.includes("b") || name === "F" || name === "Dm" || name === "Gm" || name === "Cm" || name === "Fm";
}

/** Name a pitch class the way it is usually written in the given key. */
export function spellNote(pc, key) {
  if (!key) return FLAT_NAMES[pc];
  const tonicName = key.minor ? MINOR_KEY_NAMES[key.tonic] : MAJOR_KEY_NAMES[key.tonic];
  const tonicLetter = LETTERS.indexOf(tonicName[0]);
  const interval = mod12(pc - key.tonic);
  const letter = LETTERS[(tonicLetter + INTERVAL_DEGREE[interval]) % 7];
  let diff = mod12(pc - LETTER_PC[letter]);
  if (diff > 6) diff -= 12;
  const name = letter + (diff === 1 ? "#" : diff === -1 ? "b" : diff === 0 ? "" : "?");
  if (name.includes("?") || AWKWARD.has(name)) {
    return (prefersFlats(key) ? FLAT_NAMES : SHARP_NAMES)[pc];
  }
  return name;
}

/** Transpose a chord symbol; unparseable text (N.C., x2, ...) is returned unchanged. */
export function transposeChord(text, semitones, targetKey) {
  const chord = parseChord(text);
  if (!chord) return text;
  const root = spellNote(mod12(chord.root + semitones), targetKey);
  const bass = chord.bass === null ? "" : `/${spellNote(mod12(chord.bass + semitones), targetKey)}`;
  return root + chord.quality + bass;
}

const MAJOR_TRIADS = [[0, "maj"], [2, "min"], [4, "min"], [5, "maj"], [7, "maj"], [9, "min"], [11, "dim"]];
const MINOR_TRIADS = [[0, "min"], [2, "dim"], [3, "maj"], [5, "min"], [7, "min"], [7, "maj"], [8, "maj"], [10, "maj"]];

function triadKind(quality) {
  if (/^(dim|°|m7b5|ø)/.test(quality)) return "dim";
  return isMinorQuality(quality) ? "min" : "maj";
}

/** Guess the key from the chords used, weighting the first and last chord. */
export function guessKey(chordTexts) {
  const chords = chordTexts.map(parseChord).filter(Boolean);
  if (!chords.length) return null;
  const first = chords[0];
  const last = chords[chords.length - 1];
  let best = null;
  for (let tonic = 0; tonic < 12; tonic++) {
    for (const minor of [false, true]) {
      const triads = minor ? MINOR_TRIADS : MAJOR_TRIADS;
      const tonicKind = minor ? "min" : "maj";
      let score = 0;
      for (const c of chords) {
        const kind = triadKind(c.quality);
        if (triads.some(([step, k]) => mod12(tonic + step) === c.root && k === kind)) score += 1;
      }
      for (const c of [first, last]) {
        if (c.root === tonic && triadKind(c.quality) === tonicKind) score += 2;
      }
      if (!best || score > best.score) best = { score, key: { tonic, minor } };
    }
  }
  return best.key;
}

/** Semitones from one key to another, in the range -5..+6 (fewest steps). */
export function semitonesBetween(fromKey, toTonic) {
  let diff = mod12(toTonic - fromKey.tonic);
  if (diff > 6) diff -= 12;
  return diff;
}

export function normalizeOffset(n) {
  let v = mod12(n);
  if (v > 6) v -= 12;
  return v;
}

export const TONIC_CHOICES = MAJOR_KEY_NAMES.map((name, pc) => ({ pc, name }));
