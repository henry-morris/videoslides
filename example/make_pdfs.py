"""Regenerate the example PDFs: flat-colour pages with a label, nothing more.

Run from this directory:  uv run python make_pdfs.py
"""
import fitz  # PyMuPDF

DECKS = {
    "intro.pdf": [(0.10, 0.35, 0.65), (0.15, 0.45, 0.75), (0.20, 0.55, 0.85)],
    "main.pdf": [
        (0.55, 0.15, 0.15), (0.65, 0.25, 0.15), (0.75, 0.35, 0.15), (0.85, 0.45, 0.15),
        (0.60, 0.20, 0.40), (0.50, 0.30, 0.50), (0.40, 0.40, 0.60), (0.30, 0.50, 0.70),
        (0.20, 0.60, 0.60), (0.30, 0.70, 0.50), (0.40, 0.80, 0.40), (0.50, 0.70, 0.30),
    ],
    "break.pdf": [(0.20, 0.20, 0.20)],
    "qa.pdf": [(0.95, 0.85, 0.20)],
    "tall.pdf": [(0.30, 0.60, 0.30)],  # portrait, to show letterboxing
}

for name, colours in DECKS.items():
    doc = fitz.open()
    for i, colour in enumerate(colours, 1):
        width, height = (600, 800) if name == "tall.pdf" else (960, 540)
        page = doc.new_page(width=width, height=height)
        page.draw_rect(page.rect, color=colour, fill=colour)
        page.insert_text((60, 200), f"{name[:-4]} p{i}", fontsize=90, color=(1, 1, 1))
        page.insert_text((60, 300), "The quick brown fox jumps over the lazy dog",
                         fontsize=28, color=(1, 1, 1))
    doc.save(name)
    print(f"wrote {name} ({len(colours)} pages)")
