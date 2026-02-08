# VideoSlides

Two tools for working with PDF presentations, sharing the same TOML config and cached slide images.

- **videoslides** -- render a presentation to an MP4/MKV video file
- **presentslides** -- run an interactive full-screen presentation with auto-advance, keyboard navigation, and a slide overview

## Installation

Using [uv](https://github.com/astral-sh/uv):

```bash
# Install dependencies
uv sync

# Or install as package
uv pip install -e .
```

### System Requirements

- Python 3.11+

## Quick Start

Both tools read a `config.toml` that lists PDF files, page ranges, and durations:

```bash
# Render to video
uv run videoslides

# Present interactively
uv run presentslides
```

Both accept the same arguments:

```bash
uv run videoslides /path/to/slides --config myconfig.toml
uv run presentslides /path/to/slides --config myconfig.toml
```

## Configuration

Create a `config.toml` in your slides directory. The `[settings]` section is optional -- all values have defaults.

```toml
[settings]
output_cache = "~/.cache/videoslides"  # default
output_video = "presentation.mkv"  # default; .mp4 also works
resolution = [1920, 1080]    # default
fps = 5                      # default (videoslides only)
keyframe_interval = 15       # default, seconds (videoslides only)
background_color = "black"   # default

[[slides]]
filename = "intro.pdf"
duration = 10
pages = "all"
title = "Introduction"
show_page_number = true
show_progress_bar = true

[[slides]]
filename = "main_content.pdf"
duration = 15
pages = "1-3,5"
title = "Main Topic"
show_progress_bar = true
progress_bar_color = "red"
progress_bar_height = 8

[[slides]]
filename = "conclusion.pdf"
duration = 8
pages = "2"
title = "Summary"
```

### Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `output_cache` | `~/.cache/videoslides` | Directory for cached PNG files |
| `output_video` | `presentation.mkv` | Output video filename; .mp4 also works (videoslides) |
| `resolution` | `[1920, 1080]` | Slide resolution |
| `fps` | `5` | Video frame rate (videoslides) |
| `keyframe_interval` | `15` | Seconds between keyframes (videoslides) |
| `background_color` | `black` | Letterbox fill color |

### Slide Options

Each `[[slides]]` entry supports:

| Option | Default | Description |
|--------|---------|-------------|
| `filename` | *(required)* | PDF file path |
| `duration` | `15` | Seconds per page. `0` = pause-only (presentslides pauses on arrival; unpause to advance) |
| `pages` | `all` | Page selection (see below) |
| `title` | *(inherited)* | Short label shown on the presenter info bar. Carries forward to subsequent sections until changed. |
| `show_page_number` | `false` | Show PDF page number on the presenter info bar |
| `show_progress_bar` | `false` | Animated progress bar at the bottom of the slide |
| `progress_bar_color` | white (presenter) / `#1f4305` (video) | Bar color, hex or named |
| `progress_bar_height` | `6` (presenter) / `16` (video) | Bar height in pixels |

### Page Range Syntax

- `"all"` -- all pages
- `"1"` -- single page
- `"1-3"` -- range (1, 2, 3)
- `"1,3,5"` -- specific pages
- `"1-3,7,10-12"` -- mixed

## videoslides

Renders the presentation to an MP4 or MKV video file.

```bash
uv run videoslides
uv run videoslides /path/to/slides
uv run videoslides --config myconfig.toml
```

### How it works

1. Converts PDF pages to cached PNG images (letterboxed to target resolution)
2. Assembles PNGs into a video with configured durations per slide
3. Optionally overlays per-slide progress bars
4. Encodes with H.264, configurable keyframe interval

## presentslides

Launches an interactive full-screen presentation.

```bash
uv run presentslides
uv run presentslides /path/to/slides
uv run presentslides --config myconfig.toml
```

### Features

- Auto-advances slides based on configured durations
- Per-slide progress bar (when enabled)
- Info bar with slide counter, presentation timer, title, page number, and countdown (press **T** to toggle, shown automatically when paused)
- Slide overview with thumbnails (press **Tab** or **O**)
- Black/white screen blanking for Q&A
- Fullscreen and windowed modes

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Right / Enter | Next slide |
| Left / Backspace | Previous slide |
| Home / End | First / last slide |
| Space / P | Pause / play |
| T | Toggle info bar |
| G | Go to slide by number |
| Tab / O | Slide overview |
| B / W | Black / white screen |
| F / F11 | Toggle fullscreen |
| H / F1 / ? | Help overlay |
| Q / Escape | Quit |

Mouse: left-click = next, right-click = previous.

## Shared Cache

Both tools use the same PNG cache (`~/.cache/videoslides/` by default). PDFs are hashed by content, so the same PDF is only rendered once regardless of which tool you use or how many projects reference it.

## Dependencies

- **PyMuPDF** -- PDF rendering
- **moviepy** -- video encoding (videoslides)
- **pygame** -- interactive display (presentslides)

## License

This project is licensed under the terms included in the LICENSE file.
