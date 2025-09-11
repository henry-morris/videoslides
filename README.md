# VideoSlides

Convert PDF presentations to video with configurable slide order, durations, and page ranges.

## Features

- Convert multiple PDFs to a single MP4 video
- Configurable slide order and duration per slide
- Flexible page selection (all, ranges, specific pages)
- Letterboxed output with customizable resolution
- TOML configuration for easy management

## Installation

Using [uv](https://github.com/astral-sh/uv):

```bash
# Install dependencies
uv sync

# Or install as package
uv pip install -e .
```

## Usage

### Basic Usage

```bash
# Run with default config.toml in current directory
uv run videoslides

# Run in different directory (default: current directory)
uv run videoslides /path/to/slides

# Use custom config file (default: config.toml)
uv run videoslides --config myconfig.toml

# Combine directory and config
uv run videoslides /path/to/slides --config myconfig.toml
```

### Configuration

Create a `config.toml` file to define your presentation. The `[settings]` section is optional since all parameters have defaults:

```toml
# Optional settings section - all values have defaults
[settings]
output_dir = "pngs"           # default
output_video = "presentation.mp4"  # default
resolution = [1920, 1080]    # default
fps = 1                      # default
background_color = "black"   # default
pdf_threads = 4              # default

# Minimal example - only slides are required
[[slides]]
filename = "intro.pdf"
duration = 10
pages = "all"

[[slides]]
filename = "main_content.pdf"
duration = 15
pages = "1-3,5"

[[slides]]
filename = "conclusion.pdf"
duration = 8
pages = "2"
```

### Page Range Syntax

- `"all"` - Include all pages
- `"1"` - Single page
- `"1-3"` - Range of pages (1, 2, 3)
- `"1,3,5"` - Specific pages
- `"1-3,7,10-12"` - Mixed ranges and specific pages

### Configuration Options

#### Settings
All settings have default values and are optional:
- `output_dir`: Directory for generated PNG files (default: "pngs")
- `output_video`: Output video filename (default: "presentation.mp4")
- `resolution`: Video resolution as [width, height] (default: [1920, 1080])
- `fps`: Video frame rate (default: 1)
- `background_color`: Background color for letterboxing (default: "black")
- `pdf_threads`: Number of threads for PDF processing (default: 4)

#### Slides
Each `[[slides]]` entry defines:
- `filename`: PDF file to process (required)
- `duration`: Seconds to display each page from this PDF (default: 15)
- `pages`: Which pages to include (default: "all") - see Page Range Syntax above

## How It Works

1. **PDF to PNG**: Converts specified pages from each PDF to PNG images with letterboxing
2. **PNG to MP4**: Combines PNG images into a video where each image displays for its configured duration
3. **Ordering**: Slides appear in the video in the order defined in the config file

## Dependencies

- PyPDF2: PDF processing
- pdf2image: PDF to image conversion
- Pillow: Image manipulation
- moviepy: Video generation

## System Requirements

- Python 3.11+
- poppler-utils (for pdf2image)
  - macOS: `brew install poppler`
  - Ubuntu: `sudo apt-get install poppler-utils`
  - Windows: Download from https://blog.alivate.com.au/poppler-windows/

## License

This project is licensed under the terms included in the LICENSE file.