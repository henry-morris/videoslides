#!/usr/bin/env uv run

# /// script
# requires_python = "==3.11.*"
# dependencies = [
#   "moviepy",
#   "PyMuPDF",
# ]
# ///

from pathlib import Path
import argparse
import os
import numpy as np
from moviepy import ImageClip, concatenate_videoclips, CompositeVideoClip, VideoClip

from shared import load_config, prepare_slide_images, resolve_slides


def _parse_color_to_rgb(color_str):
    """Convert a color string to an (R, G, B) tuple for numpy."""
    named = {
        "white": (255, 255, 255), "black": (0, 0, 0),
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    }
    if color_str in named:
        return named[color_str]
    if color_str.startswith("#") and len(color_str) == 7:
        h = color_str[1:]
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (255, 255, 255)


def create_progress_bar_clip(width, height, duration, progress_color="white", bar_height=10):
    """Create a progress bar clip that fills from left to right over the duration."""
    rgb = _parse_color_to_rgb(progress_color)

    def make_frame(t):
        progress = min(t / duration, 1.0)
        progress_width = int(width * progress)

        if progress_width == 0:
            return np.zeros((bar_height, 1, 3), dtype=np.uint8)

        frame = np.empty((bar_height, progress_width, 3), dtype=np.uint8)
        frame[:, :] = rgb
        return frame

    return VideoClip(make_frame, duration=duration)


def pngs_to_video(config):
    """Convert PNG images to video (MP4 or MKV)."""
    output_filename = config["settings"].get("output_video", "presentation.mkv")

    fps = config["settings"].get("fps", 5)
    keyframe_seconds = config["settings"].get("keyframe_interval", 15)
    resolution = config["settings"].get("resolution", [1920, 1080])

    output_ext = Path(output_filename).suffix.lstrip(".").upper()
    print(f"🎥 Starting PNG → {output_ext} conversion...")

    clips = []
    for slide, pdf_cache_dir, total_pages, page_numbers in resolve_slides(config):
        duration = slide.get("duration", 15) or 15

        print(f"🎬 Processing '{slide['filename']}' (duration={duration}s, pages={page_numbers})...")

        # Check if this slide should have a progress bar
        show_progress_bar = slide.get("show_progress_bar", False)
        progress_bar_color = slide.get("progress_bar_color", "#1f4305")
        progress_bar_height = slide.get("progress_bar_height", 16)

        for page_num in page_numbers:
            cached_png = pdf_cache_dir / f"{page_num:03d}.png"

            if not cached_png.exists():
                print(f"⚠️ Page {page_num} not found in cache for '{slide['filename']}', skipping")
                continue

            print(f"🎞️ Adding page {page_num} ({duration}s)")
            clip = ImageClip(str(cached_png)).with_duration(duration)

            # For long slides, note that keyframes will be added during encoding
            if duration > keyframe_seconds:
                keyframe_count = duration // keyframe_seconds + 1
                print(f"🔑 Long slide detected - will add ~{keyframe_count} keyframes during encoding")

            # Add progress bar to this clip if requested
            if show_progress_bar:
                print(f"🎯 Adding progress bar to page {page_num}...")

                # Create progress bar for this clip
                progress_bar = create_progress_bar_clip(
                    width=resolution[0],
                    height=resolution[1],
                    duration=duration,
                    progress_color=progress_bar_color,
                    bar_height=progress_bar_height
                )

                # Position progress bar at bottom left of screen
                progress_bar = progress_bar.with_position((0, resolution[1] - progress_bar_height - 20))

                # Composite slide with progress bar
                clip = CompositeVideoClip([clip, progress_bar])

            clips.append(clip)

    if clips:
        print(f"🔧 Creating video with {len(clips)} slides...")
        final = concatenate_videoclips(clips, method="compose")

        # Set codec and keyframe interval based on format
        keyframe_interval = fps * keyframe_seconds

        final.write_videofile(
            output_filename,
            fps=fps,
            threads=None,
            codec='libx264',
            ffmpeg_params=['-g', str(keyframe_interval), '-keyint_min', str(keyframe_interval), '-sc_threshold', '0']
        )

        print(f"✅ Video saved as '{output_filename}'")
    else:
        print("⚠️ No valid PNG images found")


def main():
    """Run the complete pipeline: PDFs → PNGs → Video."""
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
        prepare_slide_images(config)

        # Stage 2: Convert PNGs to video
        pngs_to_video(config)

        print("\n🎬 VideoSlides pipeline complete!")

    finally:
        # Return to original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
