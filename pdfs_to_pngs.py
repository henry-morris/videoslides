from pdf2image import convert_from_path
from PIL import Image
from pathlib import Path

PDF_DIR = Path("pdfs")
OUTPUT_DIR = Path("pngs")
OUTPUT_DIR.mkdir(exist_ok=True)
TARGET_WIDTH, TARGET_HEIGHT = 1920, 1080

print("🧩 Starting PDF → PNG conversion with custom naming...")

for pdf_path in sorted(PDF_DIR.glob("*.pdf")):
    print(f"\n📄 Processing '{pdf_path.name}'...")

    try:
        order_str, duration_str = pdf_path.stem.split()
        order = int(order_str)
        duration = int(duration_str)
    except ValueError:
        raise RuntimeError(f"❌ Invalid filename format: '{pdf_path.name}'. Expected 'order duration.pdf'")

    pages = convert_from_path(pdf_path, fmt="png", thread_count=4)
    print(f"✅ Rendered {len(pages)} page(s)")

    for i, img in enumerate(pages, start=1):
        print(f"🔧 Processing page {i}/{len(pages)}...")
        img = img.convert("RGB")
        w, h = img.size

        scale = min(TARGET_WIDTH / w, TARGET_HEIGHT / h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)

        background = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), "black")
        left = (TARGET_WIDTH - new_size[0]) // 2
        top = (TARGET_HEIGHT - new_size[1]) // 2
        background.paste(img, (left, top))

        output_filename = f"{order} {i} {duration}.png"
        output_path = OUTPUT_DIR / output_filename
        background.save(output_path, "PNG")
        print(f"💾 Saved: {output_filename}")

print(f"\n🎬 All done! Slides saved in '{OUTPUT_DIR.resolve()}'")