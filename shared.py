"""Shared utility functions for videoslides and presentslides."""

from pathlib import Path
import hashlib
import tomllib
import fitz  # PyMuPDF


def parse_color(color_str):
    """Convert a color string ('black', 'white', or '#rrggbb') to an RGB tuple."""
    named = {"black": (0, 0, 0), "white": (255, 255, 255)}
    if color_str in named:
        return named[color_str]
    if color_str.startswith("#") and len(color_str) == 7:
        h = color_str[1:]
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (0, 0, 0)


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


def resolve_slides(config):
    """Yield (slide_cfg, pdf_cache_dir, total_pages, page_numbers) for each cached slide."""
    for slide_cfg in config["slides"]:
        filename = slide_cfg["filename"]
        pages_spec = slide_cfg.get("pages", "all")

        pdf_file = Path(filename)
        if not pdf_file.exists():
            print(f"Warning: '{filename}' not found, skipping")
            continue

        pdf_cache_dir = get_pdf_cache_dir(config, pdf_file)
        total_pages = get_cached_page_count(pdf_cache_dir)
        if total_pages is None:
            print(f"Warning: no cache for '{filename}', skipping")
            continue

        page_numbers = parse_page_range(pages_spec, total_pages)
        yield slide_cfg, pdf_cache_dir, total_pages, page_numbers


def load_config(config_file="config.toml"):
    """Load configuration from TOML file."""
    try:
        with open(config_file, "rb") as f:
            config = tomllib.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Config file '{config_file}' not found")
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"Invalid TOML in '{config_file}': {e}")

    # -- Config validation --

    if "slides" not in config or not config["slides"]:
        raise RuntimeError("Config must contain at least one [[slides]] entry")

    KNOWN_SETTINGS = {
        "output_cache", "output_video", "resolution", "fps",
        "keyframe_interval", "background_color",
    }
    KNOWN_SLIDE_KEYS = {
        "filename", "duration", "until", "pages", "title",
        "show_page_number", "show_progress_bar", "show_countdown",
        "progress_bar_color", "progress_bar_height",
    }

    for key in config.get("settings", {}):
        if key not in KNOWN_SETTINGS:
            raise RuntimeError(f"Unknown setting '{key}'")

    res = config.get("settings", {}).get("resolution")
    if res is not None:
        if not (isinstance(res, list) and len(res) == 2
                and all(isinstance(v, int) and v > 0 for v in res)):
            raise RuntimeError(f"'resolution' must be [width, height], got {res}")

    for i, slide in enumerate(config["slides"], 1):
        label = f"Slide {i} ('{slide.get('filename', '?')}')"

        for key in slide:
            if key not in KNOWN_SLIDE_KEYS:
                raise RuntimeError(f"{label}: unknown option '{key}'")

        if "duration" in slide and "until" in slide:
            raise RuntimeError(f"{label}: 'duration' and 'until' are mutually exclusive")

        if "duration" in slide and slide["duration"] < 0:
            raise RuntimeError(f"{label}: 'duration' must be non-negative, got {slide['duration']!r}")

    return config


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

            doc = fitz.open(pdf_file)
            total_pages = len(doc)
            print(f"🔄 Rendering {total_pages} page(s)...")

            bg_rgb = parse_color(background_color)

            for page_idx in range(total_pages):
                print(f"🔧 Rendering page {page_idx + 1}/{total_pages}...")
                page = doc[page_idx]

                # Scale to fit within target while preserving aspect ratio
                zoom = min(target_width / page.rect.width, target_height / page.rect.height)
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)

                # Letterbox: create target-sized pixmap with background color
                bg = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, target_width, target_height), 0)
                bg.set_rect(bg.irect, bg_rgb)

                # Copy rendered page into center
                left = (target_width - pix.width) // 2
                top = (target_height - pix.height) // 2
                src = pix.samples_mv
                dst = bg.samples_mv
                for y in range(pix.height):
                    s = y * pix.stride
                    d = (top + y) * bg.stride + left * 3
                    dst[d:d + pix.width * 3] = src[s:s + pix.width * 3]

                temp_png = pdf_temp_dir / f"{page_idx + 1:03d}.png"
                bg.save(str(temp_png))

            doc.close()

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
