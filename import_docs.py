"""Import chord-sheet .docx files into ChordPro (.cho) songs for the web viewer.

Usage:
    python import_docs.py inbox/                 # every .docx in a folder
    python import_docs.py Song.docx --force      # overwrite an existing .cho
    python import_docs.py --reindex              # rebuild songs/index.json after hand edits
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from importer.convert import Converter
from importer.docx_reader import read_lines
from importer.measure import TextMeasurer

SONGS_DIR = Path(__file__).parent / "web" / "songs"
DIRECTIVE_RE = re.compile(r"^\{(\w+)\s*:\s*(.*?)\s*\}\s*$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return slug or "song"


def title_from_filename(path: Path) -> str:
    return re.sub(r"[_\s]+", " ", path.stem).strip()


def collect_inputs(inputs: list[Path]) -> list[Path]:
    files = []
    for item in inputs:
        if item.is_dir():
            files += sorted(item.rglob("*.docx"))
        else:
            files.append(item)
    return [f for f in files if not f.name.startswith("~$")]


def import_file(path: Path, converter: Converter, out_dir: Path, force: bool) -> None:
    if path.suffix.lower() != ".docx":
        print(f"SKIP  {path.name}: only .docx is supported (open it in Word and Save As .docx)")
        return
    target = out_dir / f"{slugify(path.stem)}.cho"
    if target.exists() and not force:
        print(f"SKIP  {path.name}: {target.name} already exists (use --force to overwrite)")
        return
    chordpro, report = converter.convert(read_lines(path), title_from_filename(path), path.name)
    target.write_text(chordpro, encoding="utf-8")
    songs = f", {len(report.songs)} songs: {', '.join(report.songs)}" if len(report.songs) > 1 else ""
    print(f"OK    {path.name} -> {target.name} ({report.chord_count} chords, "
          f"{report.lyric_lines} lyric lines{songs})")
    for warning in report.warnings:
        print(f"      warning: {warning}")


def read_song_meta(path: Path) -> dict:
    meta = {"file": path.name, "title": path.stem, "artist": "", "songs": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DIRECTIVE_RE.match(line.strip())
        if not match:
            continue
        name, value = match.group(1).lower(), match.group(2)
        if name in ("title", "t"):
            meta["title"] = value
        elif name in ("artist", "a"):
            meta["artist"] = value
        elif name == "x_song":
            meta["songs"].append(value)
    return meta


def write_index(out_dir: Path) -> None:
    songs = sorted((read_song_meta(p) for p in out_dir.glob("*.cho")), key=lambda m: m["title"].lower())
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps(songs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Index: {len(songs)} songs -> {index_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", type=Path, help=".docx files or folders")
    parser.add_argument("--out", type=Path, default=SONGS_DIR, help="output folder for .cho files")
    parser.add_argument("--force", action="store_true", help="overwrite existing .cho files")
    parser.add_argument("--reindex", action="store_true", help="only rebuild index.json")
    parser.add_argument("--no-fonts", action="store_true", help="estimate widths instead of reading fonts")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.reindex:
        if not args.inputs:
            parser.error("give at least one .docx file or folder (or --reindex)")
        measurer = TextMeasurer(use_fonts=not args.no_fonts)
        converter = Converter(measurer)
        for path in collect_inputs(args.inputs):
            import_file(path, converter, args.out, args.force)
        if measurer.missing_fonts:
            print(f"Fonts not installed (widths approximated): {', '.join(sorted(measurer.missing_fonts))}")
    write_index(args.out)


if __name__ == "__main__":
    main()
