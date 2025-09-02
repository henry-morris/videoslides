from PyPDF2 import PdfReader, PdfWriter
from pathlib import Path

INPUT_PDF = "input.pdf"
OUTPUT_DIR = Path("split_pdf")
OUTPUT_DIR.mkdir(exist_ok=True)

reader = PdfReader(INPUT_PDF)
total_pages = len(reader.pages)

print(f"📄 Splitting '{INPUT_PDF}' into {total_pages} individual PDFs...")

for i, page in enumerate(reader.pages, start=1):
    writer = PdfWriter()
    writer.add_page(page)

    output_path = OUTPUT_DIR / f"{i} 15.pdf"
    with open(output_path, "wb") as f_out:
        writer.write(f_out)

    print(f"💾 Saved {output_path}")

print(f"✅ All done! PDFs saved in '{OUTPUT_DIR.resolve()}'")