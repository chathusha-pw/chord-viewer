function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function segment(chord, text) {
  const seg = el("span", "seg");
  seg.append(el("span", "c", chord ?? ""), el("span", "l", text));
  return seg;
}

/**
 * Each chord is stacked on top of the syllable it belongs to, so alignment
 * survives any font, screen width or line wrap. Words are kept unbreakable
 * and lines wrap only at spaces.
 */
function renderLyrics(line, formatChord) {
  const node = el("div", "line");
  if (!line.hasChords) node.classList.add("no-chords");

  if (line.segments.every((s) => !s.text.trim())) {
    node.classList.add("chords-only");
    for (const s of line.segments) if (s.chord) node.append(el("span", "c", formatChord(s.chord)));
    return node;
  }

  let word = null;
  const closeWord = () => {
    word = null;
  };
  const addToWord = (chord, text) => {
    if (!word) {
      word = el("span", "w");
      node.append(word);
    }
    word.append(segment(chord && formatChord(chord), text));
  };

  for (const s of line.segments) {
    const parts = s.text.split(/(\s+)/).filter((p) => p !== "");
    if (!parts.length) {
      addToWord(s.chord, "");
      continue;
    }
    parts.forEach((part, i) => {
      const chord = i === 0 ? s.chord : null;
      if (/^\s+$/.test(part)) {
        if (chord) addToWord(chord, "");
        closeWord();
        node.append(" ");
      } else {
        addToWord(chord, part);
      }
    });
  }
  return node;
}

export function renderSection(section, formatChord) {
  const node = el("section", "section");
  if (section.type) node.dataset.type = section.type;
  if (section.label) node.append(el("h3", "section-label", section.label));
  for (const line of section.lines) {
    if (line.kind === "blank") node.append(el("div", "blank"));
    else if (line.kind === "comment") node.append(el("div", "comment", line.text));
    else node.append(renderLyrics(line, formatChord));
  }
  return node;
}

export { el };
