"""Read a .docx into visual lines of styled text spans.

Word line breaks (<w:br/>) inside a paragraph start a new visual line, which is
how most chord sheets stack a chord line on top of its lyric line.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

DEFAULT_SIZE_PT = 11.0


@dataclass
class RunStyle:
    ascii_font: str | None = None
    cs_font: str | None = None
    size_pt: float | None = None
    cs_size_pt: float | None = None

    def merged(self, override: RunStyle) -> RunStyle:
        return RunStyle(
            override.ascii_font or self.ascii_font,
            override.cs_font or self.cs_font,
            override.size_pt or self.size_pt,
            override.cs_size_pt or self.cs_size_pt,
        )


@dataclass
class Span:
    text: str
    style: RunStyle


@dataclass
class Line:
    spans: list[Span] = field(default_factory=list)
    indent_pt: float = 0.0

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


class _Styles:
    def __init__(self, styles_xml: bytes | None, theme_xml: bytes | None):
        self.theme_fonts = _read_theme_fonts(theme_xml)
        self.defaults = RunStyle(size_pt=DEFAULT_SIZE_PT)
        self.by_id: dict[str, tuple[str | None, RunStyle]] = {}
        if styles_xml is None:
            return
        root = ET.fromstring(styles_xml)
        rpr = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        if rpr is not None:
            self.defaults = self.defaults.merged(self.parse_rpr(rpr))
        for style in root.iter(f"{W}style"):
            style_id = style.get(f"{W}styleId")
            based_on = style.find(f"{W}basedOn")
            rpr = style.find(f"{W}rPr")
            self.by_id[style_id] = (
                based_on.get(f"{W}val") if based_on is not None else None,
                self.parse_rpr(rpr) if rpr is not None else RunStyle(),
            )

    def resolve(self, style_id: str | None, depth: int = 0) -> RunStyle:
        if not style_id or style_id not in self.by_id or depth > 20:
            return RunStyle()
        parent, own = self.by_id[style_id]
        return self.resolve(parent, depth + 1).merged(own)

    def parse_rpr(self, rpr: ET.Element) -> RunStyle:
        style = RunStyle()
        fonts = rpr.find(f"{W}rFonts")
        if fonts is not None:
            style.ascii_font = (
                fonts.get(f"{W}ascii")
                or fonts.get(f"{W}hAnsi")
                or self._theme(fonts.get(f"{W}asciiTheme") or fonts.get(f"{W}hAnsiTheme"))
            )
            style.cs_font = fonts.get(f"{W}cs") or self._theme(fonts.get(f"{W}cstheme"))
        size = rpr.find(f"{W}sz")
        if size is not None:
            style.size_pt = int(size.get(f"{W}val")) / 2
        cs_size = rpr.find(f"{W}szCs")
        if cs_size is not None:
            style.cs_size_pt = int(cs_size.get(f"{W}val")) / 2
        return style

    def _theme(self, name: str | None) -> str | None:
        if not name:
            return None
        return self.theme_fonts.get(name)


def _read_theme_fonts(theme_xml: bytes | None) -> dict[str, str]:
    if theme_xml is None:
        return {}
    root = ET.fromstring(theme_xml)
    fonts = {}
    for kind in ("major", "minor"):
        font = root.find(f".//{A}{kind}Font")
        if font is None:
            continue
        latin = font.find(f"{A}latin")
        cs = font.find(f"{A}cs")
        if latin is not None and latin.get("typeface"):
            fonts[f"{kind}HAnsi"] = fonts[f"{kind}Ascii"] = latin.get("typeface")
        if cs is not None and cs.get("typeface"):
            fonts[f"{kind}Bidi"] = cs.get("typeface")
    return fonts


def _twips_to_pt(value: str | None) -> float:
    return int(value) / 20 if value else 0.0


def _paragraph_indents(p: ET.Element) -> tuple[float, float]:
    ind = p.find(f"{W}pPr/{W}ind")
    if ind is None:
        return 0.0, 0.0
    left = _twips_to_pt(ind.get(f"{W}left") or ind.get(f"{W}start"))
    first = _twips_to_pt(ind.get(f"{W}firstLine")) - _twips_to_pt(ind.get(f"{W}hanging"))
    return left, first


def read_lines(path: Path) -> list[Line]:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        document = ET.fromstring(z.read("word/document.xml"))
        styles = _Styles(
            z.read("word/styles.xml") if "word/styles.xml" in names else None,
            z.read("word/theme/theme1.xml") if "word/theme/theme1.xml" in names else None,
        )

    body = document.find(f"{W}body")
    lines: list[Line] = []
    for p in body.iter(f"{W}p"):
        p_style_el = p.find(f"{W}pPr/{W}pStyle")
        p_style = styles.defaults.merged(
            styles.resolve(p_style_el.get(f"{W}val") if p_style_el is not None else None)
        )
        left, first = _paragraph_indents(p)
        current = Line(indent_pt=left + first)
        lines.append(current)
        for run in p.iter(f"{W}r"):
            rpr = run.find(f"{W}rPr")
            style = p_style
            if rpr is not None:
                r_style_el = rpr.find(f"{W}rStyle")
                if r_style_el is not None:
                    style = style.merged(styles.resolve(r_style_el.get(f"{W}val")))
                style = style.merged(styles.parse_rpr(rpr))
            for child in run:
                tag = child.tag
                if tag == f"{W}t":
                    current.spans.append(Span(child.text or "", style))
                elif tag == f"{W}tab":
                    current.spans.append(Span("\t", style))
                elif tag in (f"{W}br", f"{W}cr"):
                    current = Line(indent_pt=left)
                    lines.append(current)
                elif tag == f"{W}noBreakHyphen":
                    current.spans.append(Span("-", style))
    return lines
