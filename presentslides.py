#!/usr/bin/env uv run

# /// script
# requires_python = "==3.11.*"
# dependencies = [
#   "pygame",
#   "pdf2image",
#   "Pillow",
# ]
# ///

"""Interactive slide presenter - reads VideoSlides config files."""

import argparse
import math
import os
from pathlib import Path

import pygame

from shared import (
    parse_page_range,
    prepare_slide_images,
    load_config,
    get_pdf_cache_dir,
    get_cached_page_count,
)


# Layout constants
OVERVIEW_COLS = 8
OVERVIEW_PADDING = 20
FONT_SIZE_INFO = 24
FONT_SIZE_HELP = 20
FONT_SIZE_BIG = 48
FONT_SIZE_SECTION = 30

# Default progress bar style (used when slides don't specify their own)
DEFAULT_PROGRESS_COLOR = (31, 67, 5)
DEFAULT_PROGRESS_HEIGHT = 16

def color_from_str(color_str):
    """Convert a color string (hex or named) to an (R, G, B) tuple."""
    try:
        c = pygame.Color(color_str)
        return (c.r, c.g, c.b)
    except (ValueError, TypeError):
        return DEFAULT_PROGRESS_COLOR


def build_slide_list(config):
    """Build an ordered list of slide metadata from config, referencing cached PNGs."""
    slides = []
    prev_title = None
    for slide_cfg in config["slides"]:
        filename = slide_cfg["filename"]
        duration = slide_cfg.get("duration", 15)
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

        show_progress_bar = slide_cfg.get("show_progress_bar", False)
        bar_color = slide_cfg.get("progress_bar_color", None)
        bar_height = slide_cfg.get("progress_bar_height", None)
        title = slide_cfg.get("title", prev_title)
        prev_title = title
        show_page_number = slide_cfg.get("show_page_number", False)

        for page_num in page_numbers:
            cached_png = pdf_cache_dir / f"{page_num:03d}.png"
            if cached_png.exists():
                slides.append({
                    "path": cached_png,
                    "duration": duration,
                    "show_progress_bar": show_progress_bar,
                    "bar_color": bar_color,
                    "bar_height": bar_height,
                    "title": title,
                    "show_page_number": show_page_number,
                    "source": filename,
                    "page": page_num,
                    "total_pages": total_pages,
                })

    return slides


class Presenter:
    """Full-screen interactive presentation viewer."""

    MODE_PRESENT = "present"
    MODE_OVERVIEW = "overview"
    MODE_HELP = "help"
    MODE_GOTO = "goto"

    def __init__(self, slides, config):
        self.slides = slides
        self.config = config
        self.resolution = tuple(config["settings"].get("resolution", [1920, 1080]))

        # Presentation state
        self.current = 0
        self.paused = False
        self.auto_paused = False  # True when paused by a duration-0 slide, not user
        self.slide_time = 0.0
        self.mode = self.MODE_PRESENT
        self.blank = None  # None | "black" | "white"
        self.goto_text = ""
        self.running = True
        self.fullscreen = True
        self.show_info = False
        self.windowed_size = (self.resolution[0] * 2 // 3, self.resolution[1] * 2 // 3)
        self.overview_selected = 0
        self.overview_scroll = 0
        self.overview_preferred_col = 0  # Remember column position for up/down navigation
        self._sections_cache = None
        self._overview_mousedown_idx = None
        self._overview_thumb_cache = {}

        # Pygame objects (initialized in init_pygame)
        self.screen = None
        self.clock = None
        self.screen_w = 0
        self.screen_h = 0
        self.font = None
        self.small_font = None
        self.big_font = None
        self.slide_surfaces = []
        self.thumb_surfaces = []
        self._scale_cache = {}

        # Mouse repeat state
        self._mouse_held = None  # None, "next", or "prev"
        self._mouse_hold_time = 0.0
        self._mouse_repeat_delay = 0.4  # seconds before repeat starts
        self._mouse_repeat_interval = 0.1  # seconds between repeats
        self._mouse_next_repeat = 0.0

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_pygame(self):
        pygame.init()
        pygame.display.set_caption("VideoSlides Presenter")

        # Capture native desktop resolution before creating any window
        info = pygame.display.Info()
        self.native_w = info.current_w
        self.native_h = info.current_h

        if self.fullscreen:
            self.screen_w = self.native_w
            self.screen_h = self.native_h
            self.screen = pygame.display.set_mode(
                (self.screen_w, self.screen_h), pygame.FULLSCREEN
            )
        else:
            self.screen = pygame.display.set_mode(self.resolution, pygame.RESIZABLE)
            self.screen_w, self.screen_h = self.resolution

        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("sans", FONT_SIZE_INFO)
        self.small_font = pygame.font.SysFont("sans", FONT_SIZE_HELP)
        self.big_font = pygame.font.SysFont("sans", FONT_SIZE_BIG)
        self.section_font = pygame.font.SysFont("sans", FONT_SIZE_SECTION)

        self._load_images()
        pygame.mouse.set_visible(False)
        pygame.key.set_repeat(400, 100)

    def _load_images(self):
        self.slide_surfaces = []
        self.thumb_surfaces = []
        for slide in self.slides:
            img = pygame.image.load(str(slide["path"])).convert()
            self.slide_surfaces.append(img)

            # Thumbnail for overview (fixed height, proportional width)
            th = 150
            tw = int(img.get_width() * th / img.get_height())
            self.thumb_surfaces.append(pygame.transform.smoothscale(img, (tw, th)))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _scaled_surface(self, index):
        """Return the slide surface scaled to current screen, with caching."""
        key = (index, self.screen_w, self.screen_h)
        if key not in self._scale_cache:
            src = self.slide_surfaces[index]
            iw, ih = src.get_size()
            scale = min(self.screen_w / iw, self.screen_h / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            self._scale_cache[key] = pygame.transform.smoothscale(src, (nw, nh))
        return self._scale_cache[key]

    def _text_with_shadow(self, font, text, color, pos, shadow_color=(0, 0, 0)):
        sx, sy = pos
        shadow = font.render(text, True, shadow_color)
        main = font.render(text, True, color)
        self.screen.blit(shadow, (sx + 1, sy + 1))
        self.screen.blit(main, (sx, sy))
        return main

    def _bar_style(self, slide):
        color = color_from_str(slide["bar_color"]) if slide["bar_color"] else DEFAULT_PROGRESS_COLOR
        height = slide["bar_height"] if slide["bar_height"] else DEFAULT_PROGRESS_HEIGHT
        return color, height

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _leave_slide(self):
        """Clean up when leaving the current slide."""
        # Only unpause if it was an auto-pause from duration-0, not a user pause
        if self.auto_paused:
            self.paused = False
            self.auto_paused = False

    def next_slide(self):
        if self.current < len(self.slides) - 1:
            self._leave_slide()
            self.current += 1
            self.slide_time = 0.0
            self.blank = None

    def prev_slide(self):
        if self.current > 0:
            self._leave_slide()
            self.current -= 1
            self.slide_time = 0.0
            self.blank = None

    def goto_slide(self, index):
        index = max(0, min(index, len(self.slides) - 1))
        if index != self.current:
            self._leave_slide()
        self.current = index
        self.slide_time = 0.0
        self.blank = None

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._scale_cache = {}
        if self.fullscreen:
            # Remember current windowed size before going fullscreen
            self.windowed_size = (self.screen_w, self.screen_h)
            self.screen_w = self.native_w
            self.screen_h = self.native_h
            self.screen = pygame.display.set_mode(
                (self.screen_w, self.screen_h), pygame.FULLSCREEN
            )
            if self.mode == self.MODE_PRESENT:
                pygame.mouse.set_visible(False)
        else:
            self.screen_w, self.screen_h = self.windowed_size
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
            pygame.mouse.set_visible(True)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.screen_w, self.screen_h = event.w, event.h
                self.screen = pygame.display.set_mode(
                    (event.w, event.h), pygame.RESIZABLE
                )
                self._scale_cache = {}

            elif event.type == pygame.KEYDOWN:
                self._on_key(event)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                self._on_click(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button in (1, 3):
                    self._mouse_held = None
                if self.mode == self.MODE_OVERVIEW and event.button == 1:
                    self._on_overview_mouseup(event)

    def _on_key(self, event):
        if self.mode == self.MODE_GOTO:
            self._key_goto(event)
        elif self.mode == self.MODE_HELP:
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif self.mode == self.MODE_OVERVIEW:
            self._key_overview(event)
        else:
            self._key_present(event)

    def _key_present(self, event):
        key = event.key
        uni = event.unicode

        # Navigation
        if key in (pygame.K_RIGHT, pygame.K_RETURN, pygame.K_PAGEDOWN):
            self.next_slide()
        elif key in (pygame.K_LEFT, pygame.K_BACKSPACE, pygame.K_PAGEUP):
            self.prev_slide()
        elif key == pygame.K_HOME:
            self.goto_slide(0)
        elif key == pygame.K_END:
            self.goto_slide(len(self.slides) - 1)

        # Pause / Play
        elif key in (pygame.K_SPACE, pygame.K_p):
            if self.paused and self.slides[self.current]["duration"] == 0:
                if self.auto_paused:
                    # Ready state: advance to next slide
                    self.auto_paused = False
                    self.paused = False
                    if self.current < len(self.slides) - 1:
                        self.next_slide()
                else:
                    # User-paused on duration-0: transition to Ready
                    self.auto_paused = True
            else:
                self.paused = not self.paused

        # Toggle info overlay
        elif key == pygame.K_t:
            self.show_info = not self.show_info

        # Goto
        elif key == pygame.K_g:
            self.mode = self.MODE_GOTO
            self.goto_text = ""

        # Overview
        elif key in (pygame.K_TAB, pygame.K_o):
            self.mode = self.MODE_OVERVIEW
            self.overview_selected = self.current
            self._sections_cache = self._overview_sections()  # Cache sections
            self._overview_thumb_cache = {}  # Clear thumb cache for new size
            self._overview_pregenerate_thumbs()  # Pre-generate all thumbnails
            # Initialize preferred column from current position
            _, _, col = self._overview_find_position(self.current)
            if col is not None:
                self.overview_preferred_col = col
            self._overview_ensure_visible_or_center()
            pygame.mouse.set_visible(True)
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

        # Help
        elif key in (pygame.K_h, pygame.K_F1) or uni == "?":
            self.mode = self.MODE_HELP

        # Blank
        elif key == pygame.K_b:
            self.blank = "black" if self.blank != "black" else None
        elif key == pygame.K_w:
            self.blank = "white" if self.blank != "white" else None

        # Fullscreen
        elif key in (pygame.K_f, pygame.K_F11):
            self.toggle_fullscreen()

        # Quit
        elif key in (pygame.K_q, pygame.K_ESCAPE):
            self.running = False

    def _overview_layout(self):
        """Return (thumb_w, thumb_h, cell_h) for the current screen size."""
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING
        avail_w = self.screen_w - pad * (cols + 1)
        tw = avail_w // cols
        th = int(tw * 9 / 16)
        cell_h = th + pad + 30
        return tw, th, cell_h

    def _overview_pregenerate_thumbs(self):
        """Pre-generate all thumbnails at the current overview size for fast drawing."""
        tw, th, _ = self._overview_layout()
        for i in range(len(self.slides)):
            cache_key = (i, tw, th)
            self._overview_thumb_cache[cache_key] = pygame.transform.smoothscale(
                self.thumb_surfaces[i], (tw, th)
            )

    def _overview_find_position(self, slide_idx):
        """Find (section_idx, row_in_section, col_in_section) for a slide."""
        sections = self._overview_sections()
        cols = OVERVIEW_COLS

        for sec_idx, section in enumerate(sections):
            if section["start"] <= slide_idx < section["end"]:
                pos_in_section = slide_idx - section["start"]
                row = pos_in_section // cols
                col = pos_in_section % cols
                return sec_idx, row, col
        return None, None, None

    def _overview_find_slide(self, section_idx, row, col):
        """Find slide index at (section_idx, row, col), or closest valid slide."""
        sections = self._overview_sections()
        cols = OVERVIEW_COLS

        if section_idx < 0 or section_idx >= len(sections):
            return None

        section = sections[section_idx]
        section_slides = section["end"] - section["start"]
        rows_in_section = (section_slides + cols - 1) // cols

        # Clamp row to valid range
        if row < 0:
            return None
        if row >= rows_in_section:
            return None

        # Find slide at (row, col) or closest in that row
        pos_in_section = row * cols + col
        if pos_in_section >= section_slides:
            # Column doesn't exist in this row, use last slide in row
            pos_in_section = min(row * cols + cols - 1, section_slides - 1)

        return section["start"] + pos_in_section

    def _overview_sections(self):
        """Build list of sections with their slide ranges."""
        if self._sections_cache is not None:
            return self._sections_cache

        sections = []
        current_title = None
        start_idx = 0

        for i, slide in enumerate(self.slides):
            title = slide.get("title")
            if title != current_title:
                if current_title is not None:
                    sections.append({
                        "title": current_title,
                        "start": start_idx,
                        "end": i
                    })
                current_title = title
                start_idx = i

        # Add the last section
        if current_title is not None:
            sections.append({
                "title": current_title,
                "start": start_idx,
                "end": len(self.slides)
            })

        return sections

    def _overview_slide_position(self, slide_idx):
        """Calculate (x, y) position for a slide in the sectioned layout."""
        tw, th, cell_h = self._overview_layout()
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING
        heading_h = 75

        sections = self._overview_sections()
        y_offset = pad

        for section in sections:
            # Add heading height
            y_offset += heading_h

            if slide_idx < section["start"]:
                break
            elif slide_idx < section["end"]:
                # Slide is in this section
                pos_in_section = slide_idx - section["start"]
                row_in_section = pos_in_section // cols
                col = pos_in_section % cols

                x = pad + col * (tw + pad)
                y = y_offset + row_in_section * cell_h
                return x, y
            else:
                # Skip past this section
                section_slides = section["end"] - section["start"]
                rows_in_section = (section_slides + cols - 1) // cols
                y_offset += rows_in_section * cell_h

        return None, None

    def _overview_max_scroll(self):
        """Maximum scroll offset so last row stays visible."""
        _, _, cell_h = self._overview_layout()
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING
        heading_h = 75

        sections = self._overview_sections()
        content_h = pad

        for section in sections:
            content_h += heading_h
            section_slides = section["end"] - section["start"]
            rows_in_section = (section_slides + cols - 1) // cols
            content_h += rows_in_section * cell_h

        return max(0, content_h - self.screen_h)

    def _overview_ensure_visible(self):
        """Scroll to keep overview_selected on screen, with section title visible."""
        heading_h = 75
        _, _, cell_h = self._overview_layout()
        _, item_top = self._overview_slide_position(self.overview_selected)

        if item_top is None:
            return

        item_bottom = item_top + cell_h

        # Find if this is row 0 of its section (needs title visible)
        _, row_in_sec, _ = self._overview_find_position(self.overview_selected)
        heading_top = item_top - row_in_sec * cell_h - heading_h

        if item_top < self.overview_scroll:
            # Scrolling up — show section title if first row
            if row_in_sec == 0:
                self.overview_scroll = heading_top - OVERVIEW_PADDING
            else:
                self.overview_scroll = item_top
        elif item_bottom > self.overview_scroll + self.screen_h:
            self.overview_scroll = item_bottom - self.screen_h

        self.overview_scroll = max(0, min(self.overview_scroll, self._overview_max_scroll()))

    def _overview_ensure_visible_or_center(self):
        """Keep previous scroll if selected slide is comfortably on screen, otherwise center."""
        _, _, cell_h = self._overview_layout()
        heading_h = 75
        _, item_top = self._overview_slide_position(self.overview_selected)

        if item_top is None:
            return

        item_bottom = item_top + cell_h
        view_top = self.overview_scroll
        view_bottom = self.overview_scroll + self.screen_h

        # Find the section heading position for this slide's section
        sec_idx, row_in_sec, _ = self._overview_find_position(self.overview_selected)
        heading_top = item_top - row_in_sec * cell_h - heading_h

        # The slide must not be in the top or bottom visible row.
        # Also the section title must be visible if this is the top row of its section.
        margin = cell_h  # one row of margin from top and bottom edges
        comfortable = (
            item_top >= view_top + margin
            and item_bottom <= view_bottom - margin
            and (row_in_sec > 0 or heading_top >= view_top)
        )

        if not comfortable:
            # Center the slide vertically
            center = item_top + cell_h // 2
            self.overview_scroll = center - self.screen_h // 2
            # But don't scroll past the section title for row 0
            if row_in_sec == 0:
                self.overview_scroll = min(self.overview_scroll, heading_top - OVERVIEW_PADDING)
            self.overview_scroll = max(0, min(self.overview_scroll, self._overview_max_scroll()))

    def _key_overview(self, event):
        key = event.key
        cols = OVERVIEW_COLS

        if key in (pygame.K_ESCAPE, pygame.K_TAB, pygame.K_o):
            # Pre-scale current slide for instant display
            self._scaled_surface(self.current)
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_RETURN:
            self.goto_slide(self.overview_selected)
            # Pre-scale selected slide for instant display
            self._scaled_surface(self.overview_selected)
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_RIGHT:
            if self.overview_selected < len(self.slides) - 1:
                self.overview_selected += 1
                # Update preferred column when moving horizontally
                _, _, col = self._overview_find_position(self.overview_selected)
                if col is not None:
                    self.overview_preferred_col = col
            self._overview_ensure_visible()
        elif key == pygame.K_LEFT:
            if self.overview_selected > 0:
                self.overview_selected -= 1
                # Update preferred column when moving horizontally
                _, _, col = self._overview_find_position(self.overview_selected)
                if col is not None:
                    self.overview_preferred_col = col
            self._overview_ensure_visible()
        elif key == pygame.K_DOWN:
            # Move to next row, maintaining preferred column
            sec_idx, row, col = self._overview_find_position(self.overview_selected)
            if sec_idx is not None:
                sections = self._overview_sections()
                # Try next row in same section
                new_idx = self._overview_find_slide(sec_idx, row + 1, self.overview_preferred_col)
                if new_idx is None and sec_idx + 1 < len(sections):
                    # Move to first row of next section
                    new_idx = self._overview_find_slide(sec_idx + 1, 0, self.overview_preferred_col)
                if new_idx is not None:
                    self.overview_selected = new_idx
            self._overview_ensure_visible()
        elif key == pygame.K_UP:
            # Move to previous row, maintaining preferred column
            sec_idx, row, col = self._overview_find_position(self.overview_selected)
            if sec_idx is not None:
                sections = self._overview_sections()
                # Try previous row in same section
                new_idx = self._overview_find_slide(sec_idx, row - 1, self.overview_preferred_col)
                if new_idx is None and sec_idx > 0:
                    # Move to last row of previous section
                    prev_section = sections[sec_idx - 1]
                    prev_section_slides = prev_section["end"] - prev_section["start"]
                    last_row = (prev_section_slides - 1) // cols
                    new_idx = self._overview_find_slide(sec_idx - 1, last_row, self.overview_preferred_col)
                if new_idx is not None:
                    self.overview_selected = new_idx
            self._overview_ensure_visible()
        elif key == pygame.K_q:
            self.running = False

    def _key_goto(self, event):
        key = event.key

        if key == pygame.K_RETURN:
            try:
                num = int(self.goto_text)
                self.goto_slide(num - 1)
            except ValueError:
                pass
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_ESCAPE:
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_BACKSPACE:
            self.goto_text = self.goto_text[:-1]
        elif event.unicode.isdigit():
            self.goto_text += event.unicode

    def _on_click(self, event):
        if self.mode == self.MODE_HELP:
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif self.mode == self.MODE_OVERVIEW:
            self._click_overview(event)
        else:
            if event.button == 1:
                self.next_slide()
                self._mouse_held = "next"
                self._mouse_hold_time = 0.0
                self._mouse_next_repeat = self._mouse_repeat_delay
            elif event.button == 3:
                self.prev_slide()
                self._mouse_held = "prev"
                self._mouse_hold_time = 0.0
                self._mouse_next_repeat = self._mouse_repeat_delay

    def _click_overview(self, event):
        if event.button == 1:
            idx = self._overview_hit(event.pos)
            if idx is not None:
                # Update selection and redraw immediately
                self.overview_selected = idx
                self._overview_mousedown_idx = idx
                # Force immediate visual update
                self._draw_overview()
                pygame.display.flip()
        # Mouse wheel scrolling
        elif event.button == 4:
            self.overview_scroll = max(0, self.overview_scroll - 60)
        elif event.button == 5:
            self.overview_scroll = min(self.overview_scroll + 60, self._overview_max_scroll())

    def _on_overview_mouseup(self, event):
        idx = self._overview_hit(event.pos)
        # Navigate if releasing on the same slide we pressed
        if idx is not None and idx == self._overview_mousedown_idx:
            self.goto_slide(idx)
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        self._overview_mousedown_idx = None

    def _overview_hit(self, pos):
        """Return slide index at screen position, or None."""
        mx, my = pos
        tw, th, _ = self._overview_layout()

        sections = self._overview_sections()
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING
        heading_h = 75
        cell_h = th + pad + 30

        y_offset = pad - self.overview_scroll

        for section in sections:
            # Skip heading
            y_offset += heading_h

            # Check slides in this section
            for i in range(section["start"], section["end"]):
                pos_in_section = i - section["start"]
                row_in_section = pos_in_section // cols
                col = pos_in_section % cols

                x = pad + col * (tw + pad)
                y = y_offset + row_in_section * cell_h

                if x <= mx <= x + tw and y <= my <= y + th:
                    return i

            # Move past this section
            section_slides = section["end"] - section["start"]
            rows_in_section = (section_slides + cols - 1) // cols
            y_offset += rows_in_section * cell_h

        return None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt):
        # Update cursor in overview mode based on hover
        if self.mode == self.MODE_OVERVIEW:
            mouse_pos = pygame.mouse.get_pos()
            hovered_idx = self._overview_hit(mouse_pos)
            if hovered_idx is not None:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND)
            else:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)

        # Mouse hold-to-repeat
        if self._mouse_held and self.mode == self.MODE_PRESENT:
            self._mouse_hold_time += dt
            if self._mouse_hold_time >= self._mouse_next_repeat:
                if self._mouse_held == "next":
                    self.next_slide()
                elif self._mouse_held == "prev":
                    self.prev_slide()
                self._mouse_next_repeat += self._mouse_repeat_interval

        if self.mode != self.MODE_PRESENT:
            return
        if self.paused or self.blank:
            return

        duration = self.slides[self.current]["duration"]

        # Pause-only slide: auto-pause on arrival (only if not already user-paused)
        if duration == 0:
            if not self.paused:
                self.paused = True
                self.auto_paused = True
            return

        self.slide_time += dt

        if self.slide_time >= duration:
            if self.current < len(self.slides) - 1:
                self.current += 1
                self.slide_time = 0.0
            else:
                self.slide_time = duration
                self.paused = True

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self):
        if self.mode == self.MODE_PRESENT:
            self._draw_presentation()
        elif self.mode == self.MODE_OVERVIEW:
            self._draw_overview()
        elif self.mode == self.MODE_HELP:
            self._draw_presentation()
            self._draw_help_overlay()
        elif self.mode == self.MODE_GOTO:
            self._draw_presentation()
            self._draw_goto_overlay()

    def _draw_presentation(self):
        self.screen.fill((0, 0, 0))

        if self.blank == "black":
            self._draw_info()
            return
        if self.blank == "white":
            self.screen.fill((255, 255, 255))
            self._draw_info()
            return

        # Slide image
        surf = self._scaled_surface(self.current)
        x = (self.screen_w - surf.get_width()) // 2
        y = (self.screen_h - surf.get_height()) // 2
        self.screen.blit(surf, (x, y))

        # Progress bar (only when config enables it)
        if self.slides[self.current]["show_progress_bar"]:
            self._draw_progress_bar()

        # Info overlay
        self._draw_info()

    def _draw_progress_bar(self):
        slide = self.slides[self.current]
        duration = slide["duration"]
        progress = min(self.slide_time / duration, 1.0) if duration > 0 else 1.0

        color, height = self._bar_style(slide)
        bar_y = self.screen_h - height - 20

        # Fill
        fill_w = int(self.screen_w * progress)
        if fill_w > 0:
            pygame.draw.rect(self.screen, color, (0, bar_y, fill_w, height))

    def _presentation_position(self):
        """Elapsed presentation time based on slide positions + current slide progress."""
        pos = sum(s["duration"] for s in self.slides[:self.current])
        pos += min(self.slide_time, self.slides[self.current]["duration"])
        return pos

    def _presentation_total(self):
        return sum(s["duration"] for s in self.slides)

    def _draw_info(self):
        # Determine visibility
        if not self.show_info and not self.paused:
            return

        slide = self.slides[self.current]

        # Bar dimensions (fixed position regardless of progress bar)
        text_h = self.font.render("Xg", True, (255, 255, 255)).get_height()
        bar_h = text_h + 16
        bar_y = self.screen_h - bar_h

        # Auto-paused on duration-0: nothing to show unless T toggled
        if self.auto_paused and not self.show_info:
            return

        # Semi-transparent background
        bg = pygame.Surface((self.screen_w, bar_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        self.screen.blit(bg, (0, bar_y))

        text_y = bar_y + (bar_h - text_h) // 2

        # Left side: title + page number + seconds remaining on slide
        left_parts = []
        if slide.get("title"):
            left_parts.append(slide["title"])
        if slide.get("show_page_number"):
            left_parts.append(f"{slide['page']}/{slide['total_pages']}")
        if slide["duration"] > 0:
            remaining = max(1, math.ceil(slide["duration"] - self.slide_time))
            if remaining >= 60:
                mins = remaining // 60
                secs = remaining % 60
                if secs > 0:
                    left_parts.append(f"{mins}m {secs}s")
                else:
                    left_parts.append(f"{mins}m")
            else:
                left_parts.append(f"{remaining}s")
        left_str = "   ".join(left_parts)
        if left_str:
            self._text_with_shadow(self.font, left_str, (255, 255, 255), (16, text_y))

        # Center: status indicator
        if self.auto_paused:
            pw = self.font.render("WAITING", True, (0, 0, 0)).get_width()
            self._text_with_shadow(
                self.font, "WAITING", (100, 200, 255),
                ((self.screen_w - pw) // 2, text_y),
            )
        elif self.paused:
            pw = self.font.render("PAUSED", True, (0, 0, 0)).get_width()
            self._text_with_shadow(
                self.font, "PAUSED", (255, 200, 0),
                ((self.screen_w - pw) // 2, text_y),
            )
        elif self.show_info and slide["duration"] > 0:
            pw = self.font.render("RUNNING", True, (0, 0, 0)).get_width()
            self._text_with_shadow(
                self.font, "RUNNING", (80, 220, 100),
                ((self.screen_w - pw) // 2, text_y),
            )

        # Right side: slide counter + overall presentation time
        pos = self._presentation_position()
        total = self._presentation_total()
        p_min, p_sec = divmod(int(pos), 60)
        t_min, t_sec = divmod(int(total), 60)
        right_str = (
            f"{self.current + 1}/{len(self.slides)}"
            f"   {p_min:02d}:{p_sec:02d} / {t_min:02d}:{t_sec:02d}"
        )
        rw = self.font.render(right_str, True, (0, 0, 0)).get_width()
        self._text_with_shadow(
            self.font, right_str, (200, 200, 200),
            (self.screen_w - rw - 16, text_y),
        )

    def _draw_overview(self):
        self.screen.fill((30, 30, 30))
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING
        heading_h = 75

        tw, th, cell_h = self._overview_layout()
        sections = self._overview_sections()

        # Determine hovered slide for highlighting
        mouse_pos = pygame.mouse.get_pos()
        hovered_idx = self._overview_hit(mouse_pos)

        y_offset = pad - self.overview_scroll

        for section in sections:
            # Draw section heading with cumulative time
            heading_y = y_offset
            if heading_y + heading_h > 0 and heading_y < self.screen_h:
                title_text = section["title"] if section["title"] else "Untitled"
                title_surf = self.section_font.render(title_text, True, (140, 140, 140))
                title_y = heading_y + 22
                self.screen.blit(title_surf, (pad, title_y))

                # Calculate cumulative time up to this section
                cumulative_time = sum(self.slides[j]["duration"] for j in range(section["start"]))
                mins = int(cumulative_time) // 60
                secs = int(cumulative_time) % 60
                time_text = f"{mins}:{secs:02d}"
                time_surf = self.small_font.render(time_text, True, (100, 100, 100))
                time_x = pad + title_surf.get_width() + 16
                # Align baselines of title and time
                title_baseline = title_y + self.section_font.get_ascent()
                time_y = title_baseline - self.small_font.get_ascent()
                self.screen.blit(time_surf, (time_x, time_y))

            y_offset += heading_h

            # Draw slides in this section
            for i in range(section["start"], section["end"]):
                pos_in_section = i - section["start"]
                row_in_section = pos_in_section // cols
                col = pos_in_section % cols

                x = pad + col * (tw + pad)
                y = y_offset + row_in_section * cell_h

                if y + cell_h < 0 or y > self.screen_h:
                    continue

                # Border
                if i == self.overview_selected:
                    border_color = (0, 120, 255)
                    border_w = 4
                elif i == self.current:
                    border_color = (255, 180, 0)
                    border_w = 3
                else:
                    border_color = (70, 70, 70)
                    border_w = 1

                pygame.draw.rect(
                    self.screen,
                    border_color,
                    (x - border_w, y - border_w, tw + border_w * 2, th + border_w * 2),
                    border_w,
                )

                # Hover highlight
                if i == hovered_idx and i != self.overview_selected and i != self.current:
                    hover_w = 2
                    pygame.draw.rect(
                        self.screen,
                        (120, 120, 120),
                        (x - hover_w, y - hover_w, tw + hover_w * 2, th + hover_w * 2),
                        hover_w,
                    )

                # Thumbnail (cached for performance)
                cache_key = (i, tw, th)
                if cache_key not in self._overview_thumb_cache:
                    self._overview_thumb_cache[cache_key] = pygame.transform.smoothscale(
                        self.thumb_surfaces[i], (tw, th)
                    )
                thumb = self._overview_thumb_cache[cache_key]
                self.screen.blit(thumb, (x, y))

                # Duration 0 badge (pause icon)
                if self.slides[i]["duration"] == 0:
                    badge_size = 24
                    badge_x = x + tw - badge_size - 4
                    badge_y = y + 4
                    # Semi-transparent background
                    badge_surf = pygame.Surface((badge_size, badge_size), pygame.SRCALPHA)
                    pygame.draw.circle(badge_surf, (0, 0, 0, 160), (badge_size // 2, badge_size // 2), badge_size // 2)
                    self.screen.blit(badge_surf, (badge_x, badge_y))
                    # Draw pause icon (two vertical bars)
                    bar_w = 3
                    bar_h = 10
                    bar_spacing = 3
                    bar_y = badge_y + (badge_size - bar_h) // 2
                    bar1_x = badge_x + (badge_size - bar_w * 2 - bar_spacing) // 2
                    bar2_x = bar1_x + bar_w + bar_spacing
                    pygame.draw.rect(self.screen, (255, 200, 0), (bar1_x, bar_y, bar_w, bar_h))
                    pygame.draw.rect(self.screen, (255, 200, 0), (bar2_x, bar_y, bar_w, bar_h))

                # Page number label (only when show_page_number is set)
                if self.slides[i].get("show_page_number"):
                    label = self.small_font.render(str(self.slides[i]["page"]), True, (180, 180, 180))
                    self.screen.blit(label, (x + 4, y + th + 4))

                # Duration label (for slides > 15 seconds)
                duration = self.slides[i]["duration"]
                if duration > 15:
                    if duration >= 60:
                        mins = duration // 60
                        secs = duration % 60
                        if secs > 0:
                            dur_text = f"{mins}m {secs}s"
                        else:
                            dur_text = f"{mins}m"
                    else:
                        dur_text = f"{duration}s"
                    dur_label = self.small_font.render(dur_text, True, (150, 150, 150))
                    self.screen.blit(dur_label, (x + tw - dur_label.get_width() - 4, y + th + 4))

            # Move past this section
            section_slides = section["end"] - section["start"]
            rows_in_section = (section_slides + cols - 1) // cols
            y_offset += rows_in_section * cell_h

    def _draw_help_overlay(self):
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))

        lines = [
            ("heading", "", "Playback"),
            ("item", "Space / P", "Pause / Play"),
            ("item", "Right / Enter", "Next slide"),
            ("item", "Left / Backspace", "Previous slide"),
            ("item", "Home", "First slide"),
            ("item", "End", "Last slide"),
            ("item", "G", "Go to slide number"),
            ("item", "Left click", "Next slide"),
            ("item", "Right click", "Previous slide"),
            ("blank", "", ""),
            ("heading", "", "View"),
            ("item", "T", "Toggle info bar"),
            ("item", "B", "Black screen"),
            ("item", "W", "White screen"),
            ("item", "F / F11", "Toggle fullscreen"),
            ("item", "Tab / O", "Slide overview"),
            ("item", "H / F1 / ?", "This help"),
            ("blank", "", ""),
            ("item", "Q / Escape", "Quit"),
            ("blank", "", ""),
            ("dim", "", "Press any key to dismiss"),
        ]

        line_h = 30
        gap = 24  # pixels between key column and description column

        # Measure widest key to set the divider point
        max_key_w = 0
        for kind, key, desc in lines:
            if kind == "item" and key:
                kw = self.small_font.render(key, True, (0, 0, 0)).get_width()
                max_key_w = max(max_key_w, kw)

        # Measure widest description
        max_desc_w = 0
        for kind, key, desc in lines:
            if kind == "item" and desc:
                dw = self.small_font.render(desc, True, (0, 0, 0)).get_width()
                max_desc_w = max(max_desc_w, dw)

        total_w = max_key_w + gap + max_desc_w
        center_x = self.screen_w // 2
        divider_x = center_x - total_w // 2 + max_key_w
        rule_x1 = center_x - total_w // 2
        rule_x2 = rule_x1 + total_w

        # Headings take extra vertical space for rule + breathing room
        heading_extra = line_h // 2
        total_h = sum(
            line_h + heading_extra if k == "heading" else line_h
            for k, _, _ in lines
        )
        y = (self.screen_h - total_h) // 2

        for kind, key, desc in lines:
            if kind == "heading":
                s = self.section_font.render(desc, True, (140, 140, 140))
                self.screen.blit(s, ((self.screen_w - s.get_width()) // 2, y))
                rule_y = y + s.get_height() + 4
                pygame.draw.line(self.screen, (60, 60, 60), (rule_x1, rule_y), (rule_x2, rule_y))
                y += line_h + heading_extra
            elif kind == "item":
                ks = self.small_font.render(key, True, (220, 220, 220))
                self.screen.blit(ks, (divider_x - ks.get_width(), y))
                ds = self.small_font.render(desc, True, (150, 150, 150))
                self.screen.blit(ds, (divider_x + gap, y))
                y += line_h
            elif kind == "dim":
                s = self.small_font.render(desc, True, (140, 140, 140))
                self.screen.blit(s, ((self.screen_w - s.get_width()) // 2, y))
                y += line_h
            else:
                y += line_h

    def _draw_goto_overlay(self):
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        label = f"Go to slide (1\u2013{len(self.slides)}):"
        ls = self.font.render(label, True, (200, 200, 200))

        display = self.goto_text + "\u2502"  # block cursor
        ds = self.big_font.render(display, True, (255, 255, 255))

        # Size box to fit content
        pad = 24
        gap = 10
        min_input_w = self.big_font.render("000\u2502", True, (0, 0, 0)).get_width()
        content_w = max(ls.get_width(), ds.get_width(), min_input_w)
        box_w = content_w + pad * 2
        box_h = ls.get_height() + ds.get_height() + pad * 2 + gap

        bx = (self.screen_w - box_w) // 2
        by = (self.screen_h - box_h) // 2

        pygame.draw.rect(self.screen, (40, 40, 40), (bx, by, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, (100, 100, 100), (bx, by, box_w, box_h), 2, border_radius=8)

        self.screen.blit(ls, (bx + pad, by + pad))
        self.screen.blit(ds, (bx + pad, by + pad + ls.get_height() + gap))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        self.init_pygame()

        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()
            pygame.display.flip()

        pygame.quit()


def main():
    parser = argparse.ArgumentParser(
        description="Interactive slide presenter (reads VideoSlides config)"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing PDFs and config (default: current directory)",
    )
    parser.add_argument(
        "--config", "-c", default="config.toml", help="Config file (default: config.toml)"
    )

    args = parser.parse_args()

    original_dir = os.getcwd()
    os.chdir(args.directory)

    try:
        print("Loading configuration...")
        config = load_config(args.config)

        # Stage 1: ensure PNGs are cached (reuses videoslides caching)
        print("Preparing slide images...")
        prepare_slide_images(config)

        # Build slide list from cached PNGs
        slides = build_slide_list(config)
        if not slides:
            print("No slides found. Check your config and PDF files.")
            return

        print(f"Loaded {len(slides)} slides. Launching presenter...")
        print("Press H or F1 for keyboard shortcuts.")

        presenter = Presenter(slides, config)
        presenter.run()

    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
