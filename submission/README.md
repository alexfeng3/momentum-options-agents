# Hackathon submission assets

| File | What |
|---|---|
| `cover.png` | 1920x1080 cover image |
| `deck.pdf` | 9-slide deck, 16:9 |
| `pitch.mp4` | ~114s narrated pitch video, 1080p, Kokoro-82M TTS |

`src/` holds the generator scripts for reproducibility — none of this was hand-drawn or hand-recorded.

## Regenerating

All scripts need an isolated venv with `pillow`, `reportlab`, `fpdf2` (Python 3.14 is fine for these):

```bash
python3 -m venv .venv && .venv/bin/pip install pillow reportlab fpdf2
.venv/bin/python src/make_cover.py     # -> cover.png
.venv/bin/python src/build_deck.py     # -> deck.pdf
.venv/bin/python src/make_slides.py    # -> slide_01.png .. slide_08.png (video frames)
```

The narration (`src/gen_narration.py`) uses **Kokoro-82M**, a local neural TTS,
instead of macOS's built-in `say` voices — noticeably more natural. It needs
its own venv on **Python 3.12** (Kokoro's dependency chain, notably `torch`
and `misaki`, doesn't yet have wheels for 3.14) and a working `espeak-ng`:

```bash
brew install espeak-ng
python3.12 -m venv .venv312 && .venv312/bin/pip install kokoro soundfile
.venv312/bin/python src/gen_narration.py   # -> beat_01_kokoro.wav .. beat_08_kokoro.wav
```

**Known trap:** `kokoro`'s import (via `misaki.espeak`) resets `phonemizer`'s
espeak-ng library/data path to a broken path baked into the `espeakng_loader`
wheel at build time (a CI-only path that doesn't exist on a real machine —
this is an upstream packaging bug, not a config error). `gen_narration.py`
works around it by importing `kokoro` *first*, then overriding
`EspeakWrapper.set_library()` / `set_data_path()` to point at the Homebrew
install — doing this in the other order gets silently overwritten.

After generating the beat WAVs and slide PNGs, assemble with `ffmpeg`
(loop each slide for its beat's duration + ~0.5s padding, mux the WAV, then
concat all 8 clips) — see the shell commands in this project's session
history, or write your own; it's ~15 lines of `ffmpeg -loop 1 ... | concat`.
