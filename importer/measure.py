"""Approximate Word's horizontal text layout using the installed fonts' metrics.

Chord sheets align chords with spaces in proportional fonts, so the only way to
recover which syllable a chord sits over is to measure what the author saw.
Falls back to rough per-character estimates when a font is not installed.
"""
from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

from .docx_reader import Line, RunStyle

try:
    from fontTools.ttLib import TTCollection, TTFont
except ImportError:
    TTFont = None

try:
    import uharfbuzz as hb
except ImportError:
    hb = None

SINHALA_FALLBACK_FONT = "Nirmala UI"
LATIN_FALLBACK_FONT = "Arial"
TAB_STOP_PT = 36.0
FONT_ALIASES = {"helvetica": "arial", "helvetica neue": "arial", "times": "times new roman"}
CACHE_PATH = Path(__file__).with_name(".font_index.json")


def is_complex_script(char: str) -> bool:
    code = ord(char)
    return 0x0D80 <= code <= 0x0DFF or 0x0B80 <= code <= 0x0BFF or code in (0x200C, 0x200D)


def _font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts", Path("/Library/Fonts")]
    return [d for d in dirs if d.is_dir()]


def _font_files() -> list[Path]:
    suffixes = {".ttf", ".otf", ".ttc"}
    return sorted(p for d in _font_dirs() for p in d.rglob("*") if p.suffix.lower() in suffixes)


def _family_names(font) -> tuple[set[str], bool]:
    name = font["name"]
    families = {
        str(rec.toUnicode()).strip().lower()
        for rec in name.names
        if rec.nameID in (1, 16, 4)
    }
    subfamily = {str(rec.toUnicode()).strip().lower() for rec in name.names if rec.nameID in (2, 17)}
    return families, bool(subfamily & {"regular", "normal", "book", "roman"})


def _build_index(files: list[Path]) -> dict[str, list]:
    index: dict[str, list] = {}
    for path in files:
        try:
            if path.suffix.lower() == ".ttc":
                fonts = list(enumerate(TTCollection(str(path), lazy=True).fonts))
            else:
                fonts = [(0, TTFont(str(path), lazy=True))]
            for number, font in fonts:
                families, regular = _family_names(font)
                for family in families:
                    if regular or family not in index:
                        index[family] = [str(path), number]
        except Exception:
            continue
    return index


def load_font_index() -> dict[str, list]:
    files = _font_files()
    signature = [len(files), sum(p.stat().st_size for p in files)]
    if CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("signature") == signature:
            return cached["index"]
    index = _build_index(files)
    CACHE_PATH.write_text(json.dumps({"signature": signature, "index": index}), encoding="utf-8")
    return index


class _FontMetrics:
    def __init__(self, path: str, number: int):
        font = TTFont(path, fontNumber=number, lazy=True)
        self.units_per_em = font["head"].unitsPerEm
        self.cmap = font.getBestCmap() or {}
        self.hmtx = font["hmtx"]
        self.hb_font = None
        if hb is not None:
            face = hb.Face(hb.Blob.from_file_path(path), number)
            self.hb_font = hb.Font(face)

    def covers(self, text: str) -> bool:
        return all(ord(c) in self.cmap or c in "‌‍" for c in text)

    def advance_em(self, char: str) -> float | None:
        glyph = self.cmap.get(ord(char))
        if glyph is None:
            return None
        return self.hmtx[glyph][0] / self.units_per_em

    def shaped_offsets_em(self, text: str) -> list[float]:
        """Left edge of each character (em) after shaping; characters in one cluster share it."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf)
        cluster_x: dict[int, float] = {}
        x = 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            cluster_x.setdefault(info.cluster, x)
            x += pos.x_advance
        offsets, current = [], 0.0
        for i in range(len(text)):
            current = cluster_x.get(i, current)
            offsets.append(current / self.units_per_em)
        offsets.append(x / self.units_per_em)
        return offsets


def _estimate_em(char: str) -> float:
    category = unicodedata.category(char)
    if char == " ":
        return 0.28
    if category in ("Mn", "Me", "Cf"):
        return 0.0
    if category == "Mc":
        return 0.35
    if is_complex_script(char):
        return 0.7
    if char.isupper():
        return 0.65
    if char.isalnum():
        return 0.52
    return 0.3


class TextMeasurer:
    def __init__(self, use_fonts: bool = True):
        self.index = load_font_index() if (use_fonts and TTFont is not None) else {}
        self._metrics: dict[str, _FontMetrics | None] = {}
        self.missing_fonts: set[str] = set()

    def _font(self, family: str | None) -> _FontMetrics | None:
        if not family:
            return None
        key = FONT_ALIASES.get(family.lower(), family.lower())
        if key not in self._metrics:
            entry = self.index.get(key)
            self._metrics[key] = _FontMetrics(*entry) if entry else None
            if entry is None and self.index:
                self.missing_fonts.add(family)
        return self._metrics[key]

    def _pick_font(self, text: str, style: RunStyle, complex_run: bool) -> _FontMetrics | None:
        if complex_run:
            candidates = (style.cs_font, SINHALA_FALLBACK_FONT)
        else:
            candidates = (style.ascii_font, LATIN_FALLBACK_FONT)
        for family in candidates:
            font = self._font(family)
            if font is not None and font.covers(text):
                return font
        return None

    def _run_offsets_em(self, text: str, style: RunStyle, complex_run: bool) -> list[float]:
        font = self._pick_font(text, style, complex_run)
        if font is not None and font.hb_font is not None:
            return font.shaped_offsets_em(text)
        offsets, x = [], 0.0
        for char in text:
            offsets.append(x)
            advance = font.advance_em(char) if font is not None else None
            x += advance if advance is not None else _estimate_em(char)
        offsets.append(x)
        return offsets

    def positions(self, line: Line) -> list[float]:
        """x position (pt) of the left edge of every character, plus the line end."""
        x = line.indent_pt
        xs: list[float] = []
        for span in line.spans:
            for run, complex_run in _script_runs(span.text):
                if run == "\t":
                    xs.append(x)
                    x = (x // TAB_STOP_PT + 1) * TAB_STOP_PT
                    continue
                style = span.style
                size = (style.cs_size_pt if complex_run else None) or style.size_pt or 11.0
                offsets = self._run_offsets_em(run, style, complex_run)
                xs += [x + o * size for o in offsets[:-1]]
                x += offsets[-1] * size
        xs.append(x)
        return xs


def _script_runs(text: str) -> list[tuple[str, bool]]:
    """Split into tabs and runs of one script; whitespace joins the run it follows."""
    runs: list[tuple[str, bool]] = []
    for char in text:
        if char == "\t":
            runs.append(("\t", False))
            continue
        complex_char = is_complex_script(char)
        if runs and runs[-1][0] != "\t" and (char.isspace() or runs[-1][1] == complex_char):
            runs[-1] = (runs[-1][0] + char, runs[-1][1])
        else:
            runs.append((char, complex_char))
    return runs
