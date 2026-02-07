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
        self.overview_enter_time = 0.0

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
            self.overview_scroll = 0
            self.overview_enter_time = 0.0
            self._overview_ensure_visible()
            pygame.mouse.set_visible(True)

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

    def _overview_max_scroll(self):
        """Maximum scroll offset so last row stays visible."""
        _, _, cell_h = self._overview_layout()
        rows = (len(self.slides) + OVERVIEW_COLS - 1) // OVERVIEW_COLS
        content_h = OVERVIEW_PADDING + rows * cell_h
        return max(0, content_h - self.screen_h)

    def _overview_ensure_visible(self):
        """Scroll to keep overview_selected on screen."""
        _, _, cell_h = self._overview_layout()
        row = self.overview_selected // OVERVIEW_COLS
        item_top = OVERVIEW_PADDING + row * cell_h
        item_bottom = item_top + cell_h

        if item_top < self.overview_scroll:
            self.overview_scroll = item_top
        elif item_bottom > self.overview_scroll + self.screen_h:
            self.overview_scroll = item_bottom - self.screen_h

        self.overview_scroll = max(0, min(self.overview_scroll, self._overview_max_scroll()))

    def _key_overview(self, event):
        key = event.key
        cols = OVERVIEW_COLS

        if key in (pygame.K_ESCAPE, pygame.K_TAB, pygame.K_o):
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_RETURN:
            self.goto_slide(self.overview_selected)
            self.mode = self.MODE_PRESENT
            if self.fullscreen:
                pygame.mouse.set_visible(False)
        elif key == pygame.K_RIGHT:
            self.overview_selected = min(self.overview_selected + 1, len(self.slides) - 1)
            self._overview_ensure_visible()
        elif key == pygame.K_LEFT:
            self.overview_selected = max(self.overview_selected - 1, 0)
            self._overview_ensure_visible()
        elif key == pygame.K_DOWN:
            self.overview_selected = min(self.overview_selected + cols, len(self.slides) - 1)
            self._overview_ensure_visible()
        elif key == pygame.K_UP:
            self.overview_selected = max(self.overview_selected - cols, 0)
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
                self.goto_slide(idx)
                self.mode = self.MODE_PRESENT
                if self.fullscreen:
                    pygame.mouse.set_visible(False)
        # Mouse wheel scrolling
        elif event.button == 4:
            self.overview_scroll = max(0, self.overview_scroll - 60)
        elif event.button == 5:
            self.overview_scroll = min(self.overview_scroll + 60, self._overview_max_scroll())

    def _overview_hit(self, pos):
        """Return slide index at screen position, or None."""
        mx, my = pos
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING

        tw, th, cell_h = self._overview_layout()

        for i in range(len(self.slides)):
            col = i % cols
            row = i // cols
            x = pad + col * (tw + pad)
            y = pad + row * cell_h - self.overview_scroll
            if x <= mx <= x + tw and y <= my <= y + th:
                return i
        return None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt):
        # Update overview animation timer
        if self.mode == self.MODE_OVERVIEW:
            self.overview_enter_time += dt

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
            left_parts.append(f"{remaining}s")
        left_str = "   ".join(left_parts)
        if left_str:
            self._text_with_shadow(self.font, left_str, (255, 255, 255), (16, text_y))

        # Center: status indicator
        if self.auto_paused:
            pass
        elif self.paused:
            pw = self.font.render("PAUSED", True, (0, 0, 0)).get_width()
            self._text_with_shadow(
                self.font, "PAUSED", (255, 200, 0),
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

        tw, th, cell_h = self._overview_layout()

        for i in range(len(self.slides)):
            col = i % cols
            row = i // cols
            x = pad + col * (tw + pad)
            y = pad + row * cell_h - self.overview_scroll

            if y + cell_h < 0 or y > self.screen_h:
                continue

            # Border with animated pulse highlight
            if i == self.overview_selected:
                border_color = (0, 120, 255)
                bg_color = (0, 60, 120)
                border_w = 4
            elif i == self.current:
                border_color = (255, 180, 0)
                bg_color = (120, 80, 0)
                border_w = 3
            else:
                border_color = (70, 70, 70)
                bg_color = None
                border_w = 1

            # Draw animated pulse highlight for current/selected (one-off)
            if bg_color:
                pulse_duration = 0.6
                if self.overview_enter_time < pulse_duration:
                    # Pulse: start at full brightness, fade out
                    progress = self.overview_enter_time / pulse_duration
                    alpha = int(180 * (1.0 - progress))
                    highlight_pad = 8
                    pulse_surf = pygame.Surface((tw + highlight_pad * 2, th + highlight_pad * 2), pygame.SRCALPHA)
                    pulse_color = bg_color + (alpha,)
                    pygame.draw.rect(
                        pulse_surf,
                        pulse_color,
                        (0, 0, tw + highlight_pad * 2, th + highlight_pad * 2),
                        0,
                        border_radius=4
                    )
                    self.screen.blit(pulse_surf, (x - highlight_pad, y - highlight_pad))

            pygame.draw.rect(
                self.screen,
                border_color,
                (x - border_w, y - border_w, tw + border_w * 2, th + border_w * 2),
                border_w,
            )

            # Thumbnail
            thumb = pygame.transform.smoothscale(self.thumb_surfaces[i], (tw, th))
            self.screen.blit(thumb, (x, y))

            # Number label
            label = self.small_font.render(str(i + 1), True, (180, 180, 180))
            self.screen.blit(label, (x + 4, y + th + 4))

        # Footer hint
        hint = "Arrow keys / click to select  |  Enter to go  |  Tab / Esc to return"
        hs = self.small_font.render(hint, True, (120, 120, 120))
        self.screen.blit(hs, ((self.screen_w - hs.get_width()) // 2, self.screen_h - 30))

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
                s = self.font.render(desc, True, (100, 230, 120))
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
