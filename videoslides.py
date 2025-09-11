#!/usr/bin/env python3

from PyPDF2 import PdfReader, PdfWriter
from pdf2image import convert_from_path
from PIL import Image
from pathlib import Path
import re
import argparse
import os
import tomllib
from moviepy import ImageClip, concatenate_videoclips


def parse_page_range(pages_str, total_pages):
    """Parse page range string into list of page numbers."""
    if pages_str.lower() == "all":
        return list(range(1, total_pages + 1))

    pages = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))

    return sorted(set(pages))


def pdfs_to_pngs(config, target_width=1920, target_height=1080):
    """Convert PDF files to PNG images based on config."""
    output_path = Path(config["settings"].get("output_cache", "output_cache/"))
    output_path.mkdir(exist_ok=True)

    pdf_threads = config["settings"].get("pdf_threads", 4)
    background_color = config["settings"].get("background_color", "black")

    print("🧩 Starting PDF → PNG conversion from config...")

    for order, slide in enumerate(config["slides"], start=1):
        filename = slide["filename"]
        duration = slide.get("duration", 15)
        pages_spec = slide.get("pages", "all")

        pdf_file = Path(filename)
        if not pdf_file.exists():
            print(f"⚠️ Skipping '{filename}' - file not found")
            continue

        print(f"\n📄 Processing '{filename}' (order={order}, duration={duration}s, pages={pages_spec})...")

        pages = convert_from_path(pdf_file, fmt="png", thread_count=pdf_threads)
        total_pages = len(pages)
        print(f"✅ Rendered {total_pages} page(s)")

        # Parse which pages to include
        page_numbers = parse_page_range(pages_spec, total_pages)
        print(f"📋 Using pages: {page_numbers}")

        for page_num in page_numbers:
            if page_num > total_pages:
                print(f"⚠️ Page {page_num} doesn't exist in {filename}, skipping")
                continue

            img = pages[page_num - 1]  # Convert to 0-based index
            print(f"🔧 Processing page {page_num}...")

            img = img.convert("RGB")
            w, h = img.size

            scale = min(target_width / w, target_height / h)
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)

            background = Image.new("RGB", (target_width, target_height), background_color)
            left = (target_width - new_size[0]) // 2
            top = (target_height - new_size[1]) // 2
            background.paste(img, (left, top))

            output_filename = f"{order:03d} {page_num} {duration}.png"
            output_file = output_path / output_filename
            background.save(output_file, "PNG")
            print(f"💾 Saved: {output_filename}")

    print(f"\n🎬 PNG conversion complete! Slides saved in '{output_path.resolve()}'")


def pngs_to_mp4(config):
    """Convert PNG images to MP4 video."""
    png_dir = config["settings"].get("output_cache", "output_cache/")
    output_filename = config["settings"].get("output_video", "presentation.mp4")
    fps = config["settings"].get("fps", 1)

    png_path = Path(png_dir)

    # Regex: <order> <slide> <duration>.png
    filename_re = re.compile(r'^(\d+)\s+(\d+)\s+(\d+)\.png$')

    print("🎥 Starting PNG → MP4 conversion...")

    slides = []
    for file in sorted(png_path.glob('*.png')):
        m = filename_re.match(file.name)
        if not m:
            print(f"⚠️ Skipping '{file.name}' - unexpected format")
            continue

        order, slide, duration = map(int, m.groups())
        slides.append((order, slide, file, duration))

    # Sort by <order> then <slide>
    slides.sort(key=lambda t: (t[0], t[1]))

    # Build video clips
    clips = [ImageClip(str(f)).with_duration(duration) for _, _, f, duration in slides]

    if clips:
        print(f"🔧 Creating video with {len(clips)} slides...")
        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(output_filename, fps=fps, threads=None)
        print(f"✅ Video saved as '{output_filename}'")
    else:
        print("⚠️ No valid PNG images found")


def load_config(config_file="config.toml"):
    """Load configuration from TOML file."""
    try:
        with open(config_file, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Config file '{config_file}' not found")
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"Invalid TOML in '{config_file}': {e}")


def main():
    """Run the complete pipeline: PDFs → PNGs → MP4."""
    parser = argparse.ArgumentParser(description="Convert PDF presentations to video using TOML config")
    parser.add_argument("directory", nargs="?", default=".",
                       help="Directory to run in (default: current directory)")
    parser.add_argument("--config", "-c", default="config.toml",
                       help="Config file to use (default: config.toml)")

    args = parser.parse_args()

    # Change to the specified directory
    original_dir = os.getcwd()
    os.chdir(args.directory)

    try:
        print(f"🚀 Starting VideoSlides pipeline in '{os.getcwd()}'...")

        # Load configuration
        config = load_config(args.config)
        print(f"📋 Loaded config from '{args.config}'\n")

        # Stage 1: Convert PDFs to PNGs using config
        resolution = config["settings"].get("resolution", [1920, 1080])
        pdfs_to_pngs(config, target_width=resolution[0], target_height=resolution[1])

        # Stage 2: Convert PNGs to MP4
        pngs_to_mp4(config)

        print("\n🎬 VideoSlides pipeline complete!")

    finally:
        # Return to original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
