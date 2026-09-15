# Example presentation

Placeholder decks for trying out the tools. The PDFs are flat-colour pages
with a label (regenerate with `uv run python make_pdfs.py` from this
directory); `config.toml` uses every slide option: titles, page numbers,
progress bars, countdowns, a wall-clock `until` slide, a portrait page and a
pause-only slide.

```bash
uv run presentslides example
uv run webslides /tmp/webslides-out example
uv run videoslides example
```
