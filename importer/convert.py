"""Convert chords-over-lyrics lines into ChordPro, detecting medley songs and sections."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .docx_reader import Line, Span
from .measure import TextMeasurer, is_complex_script

CHORD_RE = re.compile(
    r"^[A-G][#b♯♭]?(?:maj|min|m|M|dim|aug|sus|add|no|[+°ø\-#b♯♭]|\d)*"
    r"(?:\([^)\s]*\))?(?:/[A-G][#b♯♭]?)?$"
)
NON_CHORD_TOKEN_RE = re.compile(r"^(?:\|+:?|:?\|+|[x×]\d+|\d+[x×]|-+|/+|%|N\.?C\.?|\.+)$", re.I)
BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
TIMESTAMP_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
DASH_RE = re.compile(r"\s*(?:[-–—]{1,}|:)\s+|\s+[-–—]{1,}\s*")
TRANSITION_RE = re.compile(r"transition\s+to\s+(.+)", re.I)
SECTION_WORDS = (
    "pre-chorus", "prechorus", "chorus", "verse", "bridge", "interlude", "intro", "outro",
    "break", "solo", "instrumental", "refrain", "hook", "coda", "tag", "transition", "ending",
)
SECTION_WORD_RE = re.compile(
    r"^(?:" + "|".join(re.escape(w) for w in SECTION_WORDS) + r")\b\s*\d*\s*", re.I
)
TRAILING_SECTION_WORD_RE = re.compile(
    r"\s+(?:" + "|".join(re.escape(w) for w in SECTION_WORDS) + r")\s*\d*$", re.I
)
SAME_SONG_RATIO = 0.75


def normalize_chord(token: str) -> str:
    return token.replace("♯", "#").replace("♭", "b")


def is_chord(token: str) -> bool:
    return bool(CHORD_RE.match(token.strip("()")))


def chord_tokens(text: str) -> list[tuple[int, str]] | None:
    """(column, chord) pairs if every token on the line is a chord or rhythm mark."""
    tokens = [(m.start(), m.group()) for m in re.finditer(r"\S+", text)]
    if not tokens:
        return None
    chords = []
    for column, token in tokens:
        if is_chord(token):
            chords.append((column, normalize_chord(token)))
        elif not NON_CHORD_TOKEN_RE.match(token):
            return None
    return chords or None


def has_complex_script(text: str) -> bool:
    return any(is_complex_script(c) for c in text)


def grapheme_boundaries(text: str) -> list[int]:
    """Indices where a chord may be inserted without splitting a character cluster."""
    boundaries = [0]
    for i in range(1, len(text)):
        char, prev = text[i], text[i - 1]
        if unicodedata.category(char) in ("Mn", "Mc", "Me") or char in "‌‍":
            continue
        if prev in "‌‍":
            continue
        boundaries.append(i)
    boundaries.append(len(text))
    return boundaries


def slice_line(line: Line, start: int, end: int | None = None) -> Line:
    out = Line(indent_pt=line.indent_pt)
    pos = 0
    for span in line.spans:
        span_start, span_end = pos, pos + len(span.text)
        pos = span_end
        lo = max(start, span_start)
        hi = span_end if end is None else min(end, span_end)
        if lo < hi:
            out.spans.append(Span(span.text[lo - span_start:hi - span_start], span.style))
    return out


@dataclass
class Label:
    section: str | None
    song: str | None
    extra: str = ""


def parse_label(content: str) -> Label | None:
    content = content.strip().strip("-–— ")
    if not content or TIMESTAMP_RE.match(content):
        return None
    transition = TRANSITION_RE.search(content)
    if transition:
        before = content[:transition.start()].strip(" -–—")
        section = before if before else "Transition"
        return Label(section=section, song=transition.group(1).strip(" -–—") or None)

    pieces = [p.strip() for p in DASH_RE.split(content) if p.strip()]
    standalone = [p for p in pieces if (m := SECTION_WORD_RE.match(p)) and m.end() == len(p)]
    section = standalone[0] if standalone else None
    song = None
    for piece in pieces:
        if piece in standalone:
            continue
        keyword = SECTION_WORD_RE.match(piece)
        if keyword:
            section = section or keyword.group().strip()
            piece = piece[keyword.end():].strip()
        trailing = TRAILING_SECTION_WORD_RE.search(piece)
        if trailing:
            section = section or trailing.group().strip()
            piece = piece[:trailing.start()].strip()
        if piece and song is None:
            song = piece
    if section is None and song is None:
        return None
    return Label(section=section, song=song)


def section_type(name: str | None) -> str:
    if not name:
        return "verse"
    word = name.split()[0].lower().replace("-", "_")
    if word in ("prechorus", "pre_chorus"):
        return "prechorus"
    return re.sub(r"[^a-z_]", "", word) or "verse"


@dataclass
class Report:
    warnings: list[str] = field(default_factory=list)
    songs: list[str] = field(default_factory=list)
    chord_count: int = 0
    lyric_lines: int = 0


class ChordProWriter:
    def __init__(self, title: str, source: str):
        self.out: list[str] = [f"{{title: {title}}}", f"{{x_source: {source}}}"]
        self.song: str | None = None
        self.songs: list[str] = []
        self.open_section: str | None = None
        self.body: list[tuple[str | None, str]] = []

    def start_song(self, name: str) -> None:
        self.close_section()
        self.song = name
        self.songs.append(name)
        self.body.append((name, ""))

    def start_section(self, name: str) -> None:
        self.close_section()
        kind = section_type(name)
        self.body.append((None, f"{{start_of_{kind}: {name}}}"))
        self.open_section = kind

    def close_section(self) -> None:
        self._trim_blank()
        start = self.body[-1][1] if self.body else ""
        if self.open_section and start.startswith(f"{{start_of_{self.open_section}:"):
            label = start.split(":", 1)[1].rstrip("}").strip()
            self.body[-1] = (None, f"{{comment: {label}}}")
            self.body.append((None, ""))
            self.open_section = None
        if self.open_section:
            self.body.append((None, f"{{end_of_{self.open_section}}}"))
            self.body.append((None, ""))
            self.open_section = None

    def line(self, text: str) -> None:
        last = self.body[-1][1] if self.body else ""
        if text == "" and (last == "" or last.startswith("{start_of_")):
            return
        self.body.append((None, text))

    def _trim_blank(self) -> None:
        while self.body and self.body[-1] == (None, ""):
            self.body.pop()

    def render(self) -> str:
        self.close_section()
        medley = len(self.songs) > 1
        lines = list(self.out)
        for song, text in self.body:
            if song is not None:
                if medley:
                    lines += ["", f"{{x_song: {song}}}"]
                continue
            lines.append(text)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines) + "\n"


class Converter:
    def __init__(self, measurer: TextMeasurer):
        self.measurer = measurer

    def split_lines(self, lines: list[Line]) -> list[Line]:
        """Split out bracketed labels and chords glued onto the start of a lyric line."""
        result: list[Line] = []
        for line in lines:
            text = line.text
            if not BRACKET_RE.search(text):
                result.extend(self._split_glued_chords(line))
                continue
            pos = 0
            for match in BRACKET_RE.finditer(text):
                if has_complex_script(match.group(1)):
                    continue
                before = text[pos:match.start()]
                if before.strip(" -–—"):
                    result.extend(self._split_glued_chords(slice_line(line, pos, match.start())))
                result.append(slice_line(line, match.start(), match.end()))
                pos = match.end()
            rest = text[pos:]
            if rest.strip(" -–—"):
                result.extend(self._split_glued_chords(slice_line(line, pos)))
        return result

    def _split_glued_chords(self, line: Line) -> list[Line]:
        text = line.text
        first_complex = next((i for i, c in enumerate(text) if is_complex_script(c)), None)
        if not first_complex:
            return [line]
        prefix = text[:first_complex]
        if chord_tokens(prefix) is None:
            return [line]
        lyric = slice_line(line, first_complex)
        chord_line = slice_line(line, 0, first_complex)
        return [chord_line, lyric]

    def convert(self, lines: list[Line], title: str, source: str) -> tuple[str, Report]:
        report = Report()
        writer = ChordProWriter(title, source)
        lines = self.split_lines(lines)
        current_song: str | None = None
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text
            stripped = text.strip()

            bracket = BRACKET_RE.fullmatch(stripped)
            if bracket and not has_complex_script(bracket.group(1)):
                label = parse_label(bracket.group(1))
                if label is not None:
                    if label.song and not self._same_song(label.song, current_song):
                        current_song = label.song
                        writer.start_song(label.song)
                    writer.start_section(label.section or label.song or "Section")
                i += 1
                continue
            if bracket:
                writer.line(f"{{comment: {bracket.group(1).strip()}}}")
                i += 1
                continue

            if not stripped:
                writer.line("")
                i += 1
                continue

            chords = chord_tokens(text)
            if chords is not None:
                report.chord_count += len(chords)
                next_line = lines[i + 1] if i + 1 < len(lines) else None
                if next_line is not None and self._is_lyric(next_line):
                    writer.line(self.merge(line, chords, next_line, report, i))
                    report.lyric_lines += 1
                    i += 2
                else:
                    writer.line(" ".join(f"[{c}]" for _, c in chords))
                    i += 1
                continue

            if self._looks_like_mixed_chords(text):
                report.warnings.append(f"line {i + 1}: chords mixed with words, kept as lyrics: {stripped!r}")
            writer.line(" ".join(stripped.split()))
            report.lyric_lines += 1
            i += 1

        report.songs = writer.songs
        return writer.render(), report

    def _same_song(self, name: str, current: str | None) -> bool:
        if current is None:
            return False
        a, b = name.lower(), current.lower()
        return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= SAME_SONG_RATIO

    def _is_lyric(self, line: Line) -> bool:
        stripped = line.text.strip()
        if not stripped or chord_tokens(stripped) is not None:
            return False
        return not (BRACKET_RE.fullmatch(stripped) and not has_complex_script(stripped))

    def _looks_like_mixed_chords(self, text: str) -> bool:
        tokens = text.split()
        chords = sum(is_chord(t) for t in tokens)
        return len(tokens) >= 2 and chords / len(tokens) >= 0.5

    def merge(self, chord_line: Line, chords: list[tuple[int, str]], lyric: Line,
              report: Report, index: int) -> str:
        chord_x = self.measurer.positions(chord_line)
        lyric_x = self.measurer.positions(lyric)
        text = lyric.text
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        boundaries = [
            b for b in grapheme_boundaries(text)
            if start <= b <= end and (b == end or not text[b].isspace())
        ]
        word_starts = {b for b in boundaries if b == start or (b > 0 and text[b - 1].isspace())}
        cluster_width = max(lyric_x[end] - lyric_x[start], 1.0) / max(len(boundaries) - 1, 1)
        end_x = lyric_x[end]

        inserts: dict[int, list[str]] = {}
        overflow: list[str] = []
        for column, chord in chords:
            x = chord_x[column]
            if x > end_x + cluster_width:
                overflow.append(chord)
                continue

            def distance(b: int) -> float:
                bias = 0.35 * cluster_width if b in word_starts else 0.0
                return abs(lyric_x[b] - x) - bias

            best = min(boundaries, key=distance)
            inserts.setdefault(best, []).append(chord)

        pieces = []
        for pos in range(start, end + 1):
            for chord in inserts.get(pos, []):
                pieces.append(f"[{chord}]")
            if pos < end:
                pieces.append(text[pos])
        merged = re.sub(r"\s+", " ", "".join(pieces))
        if overflow:
            merged += " " + " ".join(f"[{c}]" for c in overflow)
        return merged
