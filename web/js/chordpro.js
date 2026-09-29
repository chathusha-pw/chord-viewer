const SHORT_SECTIONS = { soc: "chorus", sov: "verse", sob: "bridge", eoc: "chorus", eov: "verse", eob: "bridge" };

function newSection(type = null, label = null) {
  return { type, label, lines: [] };
}

function parseLyricLine(text) {
  const segments = [];
  const re = /\[([^\]]*)\]/g;
  let pos = 0;
  let chord = null;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > pos || chord !== null) segments.push({ chord, text: text.slice(pos, m.index) });
    chord = m[1].trim();
    pos = re.lastIndex;
  }
  segments.push({ chord, text: text.slice(pos) });
  const cleaned = segments.filter((s) => s.chord !== null || s.text !== "");
  return { kind: "lyrics", segments: cleaned, hasChords: cleaned.some((s) => s.chord) };
}

/**
 * Parse ChordPro text. A medley is split into songs with the {x_song: name}
 * directive; each song may declare its own {key}.
 */
export function parseChordPro(source) {
  const song = { title: "", artist: "", key: null, songs: [] };
  let part = null;
  let section = null;

  const ensurePart = () => {
    if (!part) {
      part = { name: null, key: null, sections: [] };
      song.songs.push(part);
    }
    return part;
  };
  const ensureSection = () => {
    if (!section) {
      section = newSection();
      ensurePart().sections.push(section);
    }
    return section;
  };

  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (line.startsWith("#")) continue;

    const directive = /^\s*\{\s*([\w-]+)\s*(?::\s*(.*?))?\s*\}\s*$/.exec(line);
    if (directive) {
      const name = directive[1].toLowerCase();
      const value = directive[2] ?? "";
      if (name === "title" || name === "t") song.title = value;
      else if (name === "artist" || name === "a") song.artist = value;
      else if (name === "key") {
        if (part) part.key = value;
        else song.key = value;
      } else if (name === "x_song") {
        part = { name: value, key: null, sections: [] };
        song.songs.push(part);
        section = null;
      } else if (name.startsWith("start_of_") || SHORT_SECTIONS[name] && name.startsWith("so")) {
        const type = SHORT_SECTIONS[name] ?? name.slice("start_of_".length);
        section = newSection(type, value || type[0].toUpperCase() + type.slice(1));
        ensurePart().sections.push(section);
      } else if (name.startsWith("end_of_") || SHORT_SECTIONS[name]) {
        section = null;
      } else if (["comment", "c", "comment_italic", "ci", "highlight"].includes(name)) {
        ensureSection().lines.push({ kind: "comment", text: value });
      }
      continue;
    }

    if (line.trim() === "") {
      if (section && section.lines.length) section.lines.push({ kind: "blank" });
      continue;
    }
    ensureSection().lines.push(parseLyricLine(line.trim()));
  }

  for (const p of song.songs) {
    for (const s of p.sections) {
      while (s.lines.length && s.lines[s.lines.length - 1].kind === "blank") s.lines.pop();
    }
    p.sections = p.sections.filter((s) => s.lines.length || s.label);
    if (!p.key && song.songs.length === 1) p.key = song.key;
  }
  return song;
}

export function chordsIn(part) {
  const chords = [];
  for (const s of part.sections) {
    for (const l of s.lines) {
      if (l.kind === "lyrics") for (const seg of l.segments) if (seg.chord) chords.push(seg.chord);
    }
  }
  return chords;
}
