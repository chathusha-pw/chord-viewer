# Chord Viewer

Chords-over-lyrics song sheets for phone/tablet, with per-semitone transposition.
Songs are stored as [ChordPro](https://www.chordpro.org/) text, where each chord is
anchored to the syllable it belongs to (`[D]සයුරේ [A]ජීවිත`), so alignment holds
in any font and at any screen width.

## Importing Word docs

```powershell
pip install -r requirements.txt
python import_docs.py inbox\            # every .docx in a folder
python import_docs.py Song.docx --force # overwrite an existing .cho
python import_docs.py --reindex         # after hand-editing .cho files
```

The importer measures the text with the same fonts Word used (HarfBuzz shaping)
to work out which syllable each space-aligned chord sits over. Existing `.cho`
files are never overwritten without `--force`, so hand fixes are safe.
Always skim the result: section labels and medley song names are detected
heuristically from bracketed lines like `[Verse 1 – Song Name]` and
`[Break --- Transition to Song Name]`.

## Song file conventions

```
{title: Cartoon Medley}

{x_song: Pissu Poosa}        # starts a song inside a medley
{key: Eb}                    # optional; otherwise guessed from the chords
{start_of_verse: Verse 1}
[Eb]සූට් බූට් දිග කලිසම්,
{end_of_verse}
{comment: Break}
[G] [A] [D]                  # chords-only line
```

## Running

```powershell
python -m http.server 8000 --directory web
```

Open <http://localhost:8000>. `web/tests.html` runs the chord/transpose tests.
The `web/` folder is a static site: host it on GitHub Pages (or any static host)
to use it on phones. It works offline after the first visit, and "keep screen on"
needs HTTPS.
