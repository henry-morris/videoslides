#!/usr/bin/env python3

from PyPDF2 import PdfReader, PdfWriter
from pdf2image import convert_from_path
from PIL import Image
from pathlib import Path
import re
import argparse
import os
import tomllib
import hashlib
from moviepy import ImageClip, concatenate_videoclips


def calculate_pdf_hash(pdf_path):
    """Calculate SHA-256 hash of a PDF file."""
    sha256_hash = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


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
    cache_root = Path(config["settings"].get("output_cache", "output_cache/"))
    cache_root.mkdir(exist_ok=True)

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

        # Calculate PDF hash for caching
        pdf_hash = calculate_pdf_hash(pdf_file)
        pdf_cache_dir = cache_root / pdf_hash
        
        # Check if we need to render pages
        pages = None
        total_pages = None
        
        if pdf_cache_dir.exists():
            # Try to get page count from existing cache
            existing_pngs = list(pdf_cache_dir.glob("*.png"))
            if existing_pngs:
                total_pages = max(int(p.stem) for p in existing_pngs)
                print(f"📦 Found cache for '{filename}' (hash: {pdf_hash[:8]}...) with {total_pages} pages")
            else:
                # Cache dir exists but no pages, need to render
                pages = convert_from_path(pdf_file, fmt="png", thread_count=pdf_threads)
                total_pages = len(pages)
                print(f"🔄 Cache directory empty, rendering {total_pages} page(s)")
        else:
            # No cache, need to render
            pdf_cache_dir.mkdir(exist_ok=True)
            pages = convert_from_path(pdf_file, fmt="png", thread_count=pdf_threads)
            total_pages = len(pages)
            print(f"🆕 No cache found, rendering {total_pages} page(s)")

        # Parse which pages to include
        page_numbers = parse_page_range(pages_spec, total_pages)
        print(f"📋 Using pages: {page_numbers}")

        for page_num in page_numbers:
            if page_num > total_pages:
                print(f"⚠️ Page {page_num} doesn't exist in {filename}, skipping")
                continue

            # Check if cached PNG exists (simplified filename)
            cached_png = pdf_cache_dir / f"{page_num:03d}.png"
            
            if cached_png.exists():
                print(f"💾 Using cached page {page_num}")
            else:
                print(f"🔧 Generating page {page_num}...")
                # Generate and cache the page
                if pages is None:
                    # We had a cache hit for page count but this specific page wasn't cached
                    pages = convert_from_path(pdf_file, fmt="png", thread_count=pdf_threads)
                
                img = pages[page_num - 1]  # Convert to 0-based index
                img = img.convert("RGB")
                w, h = img.size

                scale = min(target_width / w, target_height / h)
                new_size = (int(w * scale), int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)

                background = Image.new("RGB", (target_width, target_height), background_color)
                left = (target_width - new_size[0]) // 2
                top = (target_height - new_size[1]) // 2
                background.paste(img, (left, top))
                
                # Save to cache with simple filename
                background.save(cached_png, "PNG")

            print(f"✅ Page {page_num} ready")

    print(f"\n🎬 PNG conversion complete! Slides saved in '{cache_root.resolve()}'")


def pngs_to_mp4(config):
    """Convert PNG images to MP4 video."""
    cache_root = Path(config["settings"].get("output_cache", "output_cache/"))
    output_filename = config["settings"].get("output_video", "presentation.mp4")
    fps = config["settings"].get("fps", 1)

    print("🎥 Starting PNG → MP4 conversion...")

    clips = []
    for order, slide in enumerate(config["slides"], start=1):
        filename = slide["filename"]
        duration = slide.get("duration", 15)
        pages_spec = slide.get("pages", "all")

        pdf_file = Path(filename)
        if not pdf_file.exists():
            print(f"⚠️ Skipping '{filename}' - file not found")
            continue

        # Calculate PDF hash to find cached PNGs
        pdf_hash = calculate_pdf_hash(pdf_file)
        pdf_cache_dir = cache_root / pdf_hash

        if not pdf_cache_dir.exists():
            print(f"⚠️ No cache found for '{filename}' - run PDF processing first")
            continue

        print(f"🎬 Processing '{filename}' (order={order}, duration={duration}s, pages={pages_spec})...")

        # Get total pages from cache
        existing_pngs = list(pdf_cache_dir.glob("*.png"))
        if not existing_pngs:
            print(f"⚠️ Cache directory empty for '{filename}'")
            continue

        total_pages = max(int(p.stem) for p in existing_pngs)
        
        # Parse which pages to include
        page_numbers = parse_page_range(pages_spec, total_pages)
        print(f"📋 Using pages: {page_numbers}")

        for page_num in page_numbers:
            cached_png = pdf_cache_dir / f"{page_num:03d}.png"
            
            if not cached_png.exists():
                print(f"⚠️ Page {page_num} not found in cache for '{filename}', skipping")
                continue

            print(f"🎞️ Adding page {page_num} ({duration}s)")
            clip = ImageClip(str(cached_png)).with_duration(duration)
            clips.append(clip)

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
