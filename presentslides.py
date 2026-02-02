#!/usr/bin/env python3
"""Interactive slide presenter - reads VideoSlides config files."""

import argparse
import os
import time
from pathlib import Path

import pygame

from videoslides import calculate_pdf_hash, parse_page_range, pdfs_to_pngs, load_config


# Layout constants
OVERVIEW_COLS = 4
OVERVIEW_PADDING = 20
FONT_SIZE_INFO = 24
FONT_SIZE_HELP = 20
FONT_SIZE_BIG = 48

# Default progress bar style (used when slides don't specify their own)
DEFAULT_PROGRESS_COLOR = (255, 255, 255)
DEFAULT_PROGRESS_HEIGHT = 6
DEFAULT_PROGRESS_BG_ALPHA = 40


def color_from_str(color_str):
    """Convert a color string (hex or named) to an (R, G, B) tuple."""
    try:
        c = pygame.Color(color_str)
        return (c.r, c.g, c.b)
    except (ValueError, TypeError):
        return DEFAULT_PROGRESS_COLOR


def build_slide_list(config):
    """Build an ordered list of slide metadata from config, referencing cached PNGs."""
    default_cache = Path.home() / ".cache" / "videoslides"
    cache_root = Path(config["settings"].get("output_cache", str(default_cache)))

    slides = []
    for slide_cfg in config["slides"]:
        filename = slide_cfg["filename"]
        duration = slide_cfg.get("duration", 15)
        pages_spec = slide_cfg.get("pages", "all")

        pdf_file = Path(filename)
        if not pdf_file.exists():
            print(f"Warning: '{filename}' not found, skipping")
            continue

        pdf_hash = calculate_pdf_hash(pdf_file)
        pdf_cache_dir = cache_root / pdf_hash

        if not pdf_cache_dir.exists():
            print(f"Warning: no cache for '{filename}', skipping")
            continue

        existing_pngs = list(pdf_cache_dir.glob("*.png"))
        if not existing_pngs:
            continue

        total_pages = max(int(p.stem) for p in existing_pngs)
        page_numbers = parse_page_range(pages_spec, total_pages)

        bar_color = slide_cfg.get("progress_bar_color", None)
        bar_height = slide_cfg.get("progress_bar_height", None)

        for page_num in page_numbers:
            cached_png = pdf_cache_dir / f"{page_num:03d}.png"
            if cached_png.exists():
                slides.append({
                    "path": cached_png,
                    "duration": duration,
                    "bar_color": bar_color,
                    "bar_height": bar_height,
                    "source": filename,
                    "page": page_num,
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
        self.slide_time = 0.0
        self.mode = self.MODE_PRESENT
        self.blank = None  # None | "black" | "white"
        self.goto_text = ""
        self.running = True
        self.fullscreen = True
        self.start_time = 0.0
        self.overview_selected = 0
        self.overview_scroll = 0

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

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_pygame(self):
        pygame.init()
        pygame.display.set_caption("VideoSlides Presenter")

        info = pygame.display.Info()
        self.screen_w = info.current_w
        self.screen_h = info.current_h

        if self.fullscreen:
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

    def next_slide(self):
        if self.current < len(self.slides) - 1:
            self.current += 1
            self.slide_time = 0.0
            self.blank = None

    def prev_slide(self):
        if self.current > 0:
            self.current -= 1
            self.slide_time = 0.0
            self.blank = None

    def goto_slide(self, index):
        index = max(0, min(index, len(self.slides) - 1))
        self.current = index
        self.slide_time = 0.0
        self.blank = None

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._scale_cache = {}
        if self.fullscreen:
            info = pygame.display.Info()
            self.screen_w = info.current_w
            self.screen_h = info.current_h
            self.screen = pygame.display.set_mode(
                (self.screen_w, self.screen_h), pygame.FULLSCREEN
            )
            if self.mode == self.MODE_PRESENT:
                pygame.mouse.set_visible(False)
        else:
            self.screen_w, self.screen_h = self.resolution
            self.screen = pygame.display.set_mode(self.resolution, pygame.RESIZABLE)
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
        if key in (pygame.K_RIGHT, pygame.K_SPACE, pygame.K_RETURN, pygame.K_PAGEDOWN):
            self.next_slide()
        elif key in (pygame.K_LEFT, pygame.K_BACKSPACE, pygame.K_PAGEUP):
            self.prev_slide()
        elif key == pygame.K_HOME:
            self.goto_slide(0)
        elif key == pygame.K_END:
            self.goto_slide(len(self.slides) - 1)

        # Pause
        elif key == pygame.K_p:
            self.paused = not self.paused

        # Goto
        elif key == pygame.K_g:
            self.mode = self.MODE_GOTO
            self.goto_text = ""

        # Overview
        elif key in (pygame.K_TAB, pygame.K_o):
            self.mode = self.MODE_OVERVIEW
            self.overview_selected = self.current
            self.overview_scroll = 0
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
        elif key == pygame.K_LEFT:
            self.overview_selected = max(self.overview_selected - 1, 0)
        elif key == pygame.K_DOWN:
            self.overview_selected = min(self.overview_selected + cols, len(self.slides) - 1)
        elif key == pygame.K_UP:
            self.overview_selected = max(self.overview_selected - cols, 0)
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
            elif event.button == 3:
                self.prev_slide()

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
            self.overview_scroll += 60

    def _overview_hit(self, pos):
        """Return slide index at screen position, or None."""
        mx, my = pos
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING

        avail_w = self.screen_w - pad * (cols + 1)
        tw = avail_w // cols
        th = int(tw * 9 / 16)
        cell_h = th + pad + 30

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
        if self.mode != self.MODE_PRESENT:
            return
        if self.paused or self.blank:
            return

        self.slide_time += dt
        duration = self.slides[self.current]["duration"]

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

        # Progress bar
        self._draw_progress_bar()

        # Info overlay
        self._draw_info()

    def _draw_progress_bar(self):
        slide = self.slides[self.current]
        duration = slide["duration"]
        progress = min(self.slide_time / duration, 1.0) if duration > 0 else 1.0

        color, height = self._bar_style(slide)
        bar_y = self.screen_h - height

        # Background track
        bg = pygame.Surface((self.screen_w, height), pygame.SRCALPHA)
        bg.fill((*color, DEFAULT_PROGRESS_BG_ALPHA))
        self.screen.blit(bg, (0, bar_y))

        # Fill
        fill_w = int(self.screen_w * progress)
        if fill_w > 0:
            pygame.draw.rect(self.screen, color, (0, bar_y, fill_w, height))

    def _draw_info(self):
        slide = self.slides[self.current]
        _, bar_h = self._bar_style(slide)
        bottom = self.screen_h - bar_h - 8

        # Slide counter - bottom right
        counter = f"{self.current + 1} / {len(self.slides)}"
        cs = self.font.render(counter, True, (255, 255, 255))
        cx = self.screen_w - cs.get_width() - 16
        cy = bottom - cs.get_height()
        self._text_with_shadow(self.font, counter, (255, 255, 255), (cx, cy))

        # Timer - bottom left
        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)
        timer_str = f"{mins:02d}:{secs:02d}"
        self._text_with_shadow(self.font, timer_str, (200, 200, 200), (16, cy))

        # Paused indicator
        if self.paused:
            txt = "PAUSED"
            ps = self.big_font.render(txt, True, (255, 200, 0))
            px = (self.screen_w - ps.get_width()) // 2
            py = 30
            bg = pygame.Surface(
                (ps.get_width() + 40, ps.get_height() + 20), pygame.SRCALPHA
            )
            bg.fill((0, 0, 0, 160))
            self.screen.blit(bg, (px - 20, py - 10))
            self.screen.blit(ps, (px, py))

    def _draw_overview(self):
        self.screen.fill((30, 30, 30))
        cols = OVERVIEW_COLS
        pad = OVERVIEW_PADDING

        avail_w = self.screen_w - pad * (cols + 1)
        tw = avail_w // cols
        th = int(tw * 9 / 16)
        cell_h = th + pad + 30

        for i in range(len(self.slides)):
            col = i % cols
            row = i // cols
            x = pad + col * (tw + pad)
            y = pad + row * cell_h - self.overview_scroll

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
            ("title", "Keyboard Shortcuts"),
            ("blank", ""),
            ("heading", "Navigation"),
            ("item", "Right / Space / Enter     Next slide"),
            ("item", "Left / Backspace          Previous slide"),
            ("item", "Home                      First slide"),
            ("item", "End                       Last slide"),
            ("item", "G                         Go to slide number"),
            ("blank", ""),
            ("heading", "Display"),
            ("item", "P                         Pause / Resume auto-advance"),
            ("item", "B                         Black screen toggle"),
            ("item", "W                         White screen toggle"),
            ("item", "F / F11                   Toggle fullscreen"),
            ("blank", ""),
            ("heading", "Modes"),
            ("item", "Tab / O                   Slide overview"),
            ("item", "H / F1 / ?                This help"),
            ("blank", ""),
            ("item", "Q / Escape                Quit"),
            ("blank", ""),
            ("dim", "Left click = next   Right click = previous"),
            ("dim", "Press any key to dismiss"),
        ]

        total_h = len(lines) * 30
        y = (self.screen_h - total_h) // 2
        center_x = self.screen_w // 2

        for kind, text in lines:
            if kind == "title":
                s = self.big_font.render(text, True, (255, 255, 255))
                self.screen.blit(s, (center_x - s.get_width() // 2, y))
            elif kind == "heading":
                s = self.font.render(text, True, (100, 200, 255))
                self.screen.blit(s, (center_x - 260, y))
            elif kind == "item":
                s = self.small_font.render(text, True, (220, 220, 220))
                self.screen.blit(s, (center_x - 260, y))
            elif kind == "dim":
                s = self.small_font.render(text, True, (140, 140, 140))
                self.screen.blit(s, (center_x - s.get_width() // 2, y))
            y += 30

    def _draw_goto_overlay(self):
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box_w, box_h = 340, 100
        bx = (self.screen_w - box_w) // 2
        by = (self.screen_h - box_h) // 2

        pygame.draw.rect(self.screen, (40, 40, 40), (bx, by, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, (100, 100, 100), (bx, by, box_w, box_h), 2, border_radius=8)

        label = f"Go to slide (1\u2013{len(self.slides)}):"
        ls = self.font.render(label, True, (200, 200, 200))
        self.screen.blit(ls, (bx + 16, by + 14))

        display = self.goto_text + "\u2588"  # block cursor
        ds = self.big_font.render(display, True, (255, 255, 255))
        self.screen.blit(ds, (bx + 16, by + 48))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        self.init_pygame()
        self.start_time = time.time()

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
        resolution = config["settings"].get("resolution", [1920, 1080])
        print("Preparing slide images...")
        pdfs_to_pngs(config, target_width=resolution[0], target_height=resolution[1])

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
