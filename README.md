# VideoSlides

Three tools for working with PDF presentations, sharing the same TOML config and cached slide images.

- **videoslides** -- render a presentation to an MP4/MKV video file
- **presentslides** -- run an interactive full-screen presentation with auto-advance, keyboard navigation, and a slide overview
- **webslides** -- export a presentation as a self-contained static web site (HTML + PNGs)

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

Export to web:

```bash
uv run webslides /path/to/output [/path/to/slides] --config myconfig.toml
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
show_countdown = true

[[slides]]
filename = "break.pdf"
until = "18:30"
title = "Break"
show_countdown = true

# Pause-only slide: omit both duration and until
[[slides]]
filename = "qa.pdf"
title = "Q&A"
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
| `duration` | *(none)* | Seconds per page. Mutually exclusive with `until`. Omit both for a pause-only slide (presentslides pauses on arrival; unpause to advance). Default `15` for videoslides. |
| `until` | *(none)* | Wall clock deadline in `"HH:MM"` 24-hour format; slide counts down to this time and auto-advances when reached. Mutually exclusive with `duration`. (presentslides) |
| `pages` | `all` | Page selection (see below) |
| `title` | *(inherited)* | Short label shown on the presenter info bar. Carries forward to subsequent sections until changed. |
| `show_page_number` | `false` | Show PDF page number on the presenter info bar |
| `show_progress_bar` | `false` | Animated progress bar at the bottom of the slide |
| `progress_bar_color` | white (presenter) / `#1f4305` (video) | Bar color, hex or named |
| `progress_bar_height` | `6` (presenter) / `16` (video) | Bar height in pixels |
| `show_countdown` | `false` | Show time remaining centred at the bottom instead of a progress bar (presentslides) |

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

## webslides

Exports the presentation as a static web site you can open in any browser or host on a web server.

```bash
uv run webslides /path/to/output
uv run webslides /path/to/output /path/to/slides
uv run webslides /path/to/output --config myconfig.toml
```

The output directory will contain:

```
output/
  index.html     # self-contained presenter (no external dependencies)
  slides/
    0000.png
    0001.png
    ...
```

Open `index.html` directly in a browser (`file://` works) or serve the directory over HTTP.

### Features

- Auto-advances slides based on configured durations
- Per-slide progress bar and countdown (when enabled)
- Info bar with slide counter, presentation timer, title, and page number
- Slide overview with thumbnails (press **Tab** or **O**)
- Preloads all images on page load with a progress indicator
- Fullscreen mode via the browser Fullscreen API

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
| F / F11 | Toggle fullscreen |
| H / F1 / ? | Help overlay |
| Q / Escape | Close tab |

Mouse: left-click = next, right-click = previous.

### Differences from presentslides

- No black/white screen blanking (B/W keys)
- No windowed/fullscreen toggle beyond the browser's own Fullscreen API
- `Q / Escape` calls `window.close()`, which only works in tabs opened by script

## Shared Cache

Both tools use the same PNG cache (`~/.cache/videoslides/` by default). PDFs are hashed by content, so the same PDF is only rendered once regardless of which tool you use or how many projects reference it.

## Dependencies

- **PyMuPDF** -- PDF rendering
- **moviepy** -- video encoding (videoslides)
- **pygame** -- interactive display (presentslides)
- No extra dependencies for webslides (outputs plain HTML + PNG)

## License

This project is licensed under the terms included in the LICENSE file.
