"""Shared utility functions for videoslides and presentslides."""

from pathlib import Path
import hashlib
import tomllib
from pdf2image import convert_from_path
from PIL import Image


def calculate_pdf_hash(pdf_path):
    """Calculate SHA-256 hash of a PDF file."""
    sha256_hash = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def get_cache_root(config):
    """Get the cache root directory from config, with default fallback."""
    default_cache = Path.home() / ".cache" / "videoslides"
    return Path(config["settings"].get("output_cache", str(default_cache)))


def get_pdf_cache_dir(config, pdf_file):
    """Get the cache directory for a specific PDF file."""
    cache_root = get_cache_root(config)
    pdf_hash = calculate_pdf_hash(pdf_file)
    return cache_root / pdf_hash


def get_cached_page_count(pdf_cache_dir):
    """Get the total number of pages from a PDF cache directory.

    Returns None if the cache directory doesn't exist or is empty.
    """
    if not pdf_cache_dir.exists():
        return None

    existing_pngs = list(pdf_cache_dir.glob("*.png"))
    if not existing_pngs:
        return None

    return max(int(p.stem) for p in existing_pngs)


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


def load_config(config_file="config.toml"):
    """Load configuration from TOML file."""
    try:
        with open(config_file, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Config file '{config_file}' not found")
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"Invalid TOML in '{config_file}': {e}")


def prepare_slide_images(config):
    """Prepare slide images from PDFs using config settings.

    Extracts resolution from config and ensures all PDFs are converted to PNGs.
    """
    resolution = config["settings"].get("resolution", [1920, 1080])
    pdfs_to_pngs(config, target_width=resolution[0], target_height=resolution[1])


def pdfs_to_pngs(config, target_width=1920, target_height=1080):
    """Convert PDF files to PNG images based on config."""
    cache_root = get_cache_root(config)
    cache_root.mkdir(parents=True, exist_ok=True)

    pdf_threads = config["settings"].get("pdf_threads", 4)
    background_color = config["settings"].get("background_color", "black")

    print("🧩 Starting PDF → PNG conversion from config...")

    for order, slide in enumerate(config["slides"], start=1):
        filename = slide["filename"]
        duration = slide.get("duration", 15) or 15
        pages_spec = slide.get("pages", "all")

        pdf_file = Path(filename)
        if not pdf_file.exists():
            print(f"⚠️ Skipping '{filename}' - file not found")
            continue

        print(f"\n📄 Processing '{filename}' (order={order}, duration={duration}s, pages={pages_spec})...")

        # Calculate PDF hash for caching
        pdf_hash = calculate_pdf_hash(pdf_file)
        pdf_cache_dir = get_pdf_cache_dir(config, pdf_file)
        pdf_temp_dir = cache_root / f"{pdf_hash}.tmp"

        # Check if we need to render pages
        total_pages = get_cached_page_count(pdf_cache_dir)
        if total_pages is not None:
            # Cache exists with pages
            print(f"📦 Found cache for '{filename}' (hash: {pdf_hash[:8]}...) with {total_pages} pages")
        else:
            # No cache, need to render all pages
            print(f"🆕 No cache found, rendering all pages for '{filename}' (hash: {pdf_hash[:8]}...)")

            # Create temporary directory
            pdf_temp_dir.mkdir(exist_ok=True)

            # Convert all pages to temporary directory
            pages = convert_from_path(pdf_file, fmt="png", thread_count=pdf_threads)
            total_pages = len(pages)
            print(f"🔄 Rendering all {total_pages} page(s)...")

            for page_idx, page in enumerate(pages, start=1):
                print(f"🔧 Processing page {page_idx}/{total_pages}...")

                img = page.convert("RGB")
                w, h = img.size

                scale = min(target_width / w, target_height / h)
                new_size = (int(w * scale), int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)

                background = Image.new("RGB", (target_width, target_height), background_color)
                left = (target_width - new_size[0]) // 2
                top = (target_height - new_size[1]) // 2
                background.paste(img, (left, top))

                # Save to temporary directory
                temp_png = pdf_temp_dir / f"{page_idx:03d}.png"
                background.save(temp_png, "PNG")

            # Atomically move temporary directory to final location
            pdf_temp_dir.rename(pdf_cache_dir)
            print(f"✅ Cache created for '{filename}' with {total_pages} pages")

        # Parse which pages to include for this slide
        page_numbers = parse_page_range(pages_spec, total_pages)
        print(f"📋 Using pages: {page_numbers}")

        # Verify all requested pages exist in cache
        for page_num in page_numbers:
            if page_num > total_pages:
                print(f"⚠️ Page {page_num} doesn't exist in {filename}, skipping")
                continue

            cached_png = pdf_cache_dir / f"{page_num:03d}.png"
            if not cached_png.exists():
                print(f"⚠️ Page {page_num} missing from cache for '{filename}'")
            else:
                print(f"✅ Page {page_num} ready")

    print(f"\n🎬 PNG conversion complete! Slides saved in '{cache_root.resolve()}'")
