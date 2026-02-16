#!/usr/bin/env uv run

# /// script
# requires-python = "==3.11.*"
# dependencies = [
#   "PyMuPDF==1.27.1",
# ]
# ///

"""Export a VideoSlides presentation as a static web site."""

import argparse
import json
import os
import shutil
from pathlib import Path

from shared import (
    prepare_slide_images,
    load_config,
    resolve_slides,
)


def build_slide_list(config):
    """Build an ordered list of slide metadata from config, referencing cached PNGs."""
    slides = []
    prev_title = None
    for slide_cfg, pdf_cache_dir, total_pages, page_numbers in resolve_slides(config):
        until = slide_cfg.get("until", None)
        duration = slide_cfg.get("duration", None)
        if until:
            duration = duration or 0
        elif duration is None:
            duration = 0
        show_progress_bar = slide_cfg.get("show_progress_bar", False)
        bar_color = slide_cfg.get("progress_bar_color", None)
        bar_height = slide_cfg.get("progress_bar_height", None)
        title = slide_cfg.get("title", prev_title)
        prev_title = title
        show_page_number = slide_cfg.get("show_page_number", False)
        show_countdown = slide_cfg.get("show_countdown", False)

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
                    "show_countdown": show_countdown,
                    "until": until,
                    "page": page_num,
                    "total_pages": total_pages,
                })

    return slides


def build_sections(slides):
    """Build section list with start/end indices, matching presentslides logic."""
    sections = []
    _sentinel = object()
    current_title = _sentinel
    start_idx = 0

    for i, slide in enumerate(slides):
        title = slide.get("title")
        if title != current_title:
            if current_title is not _sentinel:
                sections.append({"title": current_title, "start": start_idx, "end": i})
            current_title = title
            start_idx = i

    if current_title is not _sentinel:
        sections.append({"title": current_title, "start": start_idx, "end": len(slides)})

    return sections


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presentation</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  background: #000;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  font-family: sans-serif;
  user-select: none;
  cursor: none;
}

/* ── Present mode ── */
#present-view {
  position: absolute;
  inset: 0;
  background: #000;
}
#slide-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

/* Info bar */
#info-bar {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  background: rgba(0,0,0,0.55);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 1.4vw;
  color: #fff;
  text-shadow: 1px 1px 0 #000;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.1s;
}
#info-bar.visible { opacity: 1; }

#info-left, #info-center, #info-right {
  flex: 1;
  white-space: nowrap;
}
#info-left { text-align: left; }
#info-center { text-align: center; }
#info-right  { text-align: right; }

.status-paused  { color: #ffc800; }
.status-waiting { color: #64c8ff; }
.status-running { color: #50dc64; }

/* Progress bar */
#progress-bar-wrap {
  position: absolute;
  bottom: 20px; left: 0; right: 0;
  pointer-events: none;
  display: none;
}
#progress-bar-fill {
  height: 16px;
  background: rgb(31,67,5);
  width: 0%;
}

/* Countdown */
#countdown-bar {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  background: rgba(0,0,0,0.55);
  padding: 6px 0;
  text-align: center;
  font-size: 1.9vw;
  font-weight: bold;
  color: #fff;
  text-shadow: 1px 1px 0 #000;
  pointer-events: none;
  display: none;
}

/* ── Overview mode ── */
#overview-view {
  position: absolute;
  inset: 0;
  background: #1e1e1e;
  overflow-y: scroll;
  padding: 20px;
  display: none;
  cursor: default;
}
.section-heading {
  height: 75px;
  display: flex;
  align-items: flex-start;
  padding-top: 1.15vw;
  gap: 12px;
}
.section-title {
  font-size: 1.6vw;
  color: #8c8c8c;
  line-height: 1;
}
.section-duration {
  font-size: 1.1vw;
  color: #646464;
  line-height: 1;
  padding-bottom: 2px;
}
.section-rule {
  border: none;
  border-top: 1px solid #3c3c3c;
  margin: 0 0 4px 0;
}
.thumb-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 20px;
  margin-bottom: 0;
}
.thumb-cell {
  display: flex;
  flex-direction: column;
  cursor: pointer;
}
.thumb-img-wrap {
  position: relative;
  aspect-ratio: 16/9;
  overflow: hidden;
  border: 1px solid #464646;
}
.thumb-cell:hover .thumb-img-wrap { border-color: #787878; }
.thumb-cell.selected .thumb-img-wrap  { border: 4px solid #0078ff; }
.thumb-cell.current .thumb-img-wrap   { border: 3px solid #ffb400; }
.thumb-img-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-label {
  display: flex;
  font-size: 0.85vw;
  color: #b4b4b4;
  padding: 3px 2px 0;
  height: 22px;
  align-items: center;
}
.label-left  { flex: 1; }
.label-mid   { flex: 1; display: flex; justify-content: center; align-items: center; }
.label-right { flex: 1; display: flex; justify-content: flex-end; align-items: center; }

/* ── Help overlay ── */
#help-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.78);
  display: none;
  align-items: center;
  justify-content: center;
  cursor: default;
}
#help-box {
  color: #fff;
  min-width: 32vw;
}
.help-heading {
  font-size: 1.6vw;
  color: #8c8c8c;
  margin-bottom: 0.8vw;
  text-align: center;
}
.help-rule {
  border: none;
  border-top: 1px solid #3c3c3c;
  margin: 0 0 6px 0;
}
.help-row {
  display: flex;
  gap: 1.25vw;
  padding: 3px 0;
  font-size: 1.1vw;
}
.help-key  { text-align: right; flex: 1; color: #dcdcdc; }
.help-desc { flex: 2; color: #969696; }
.help-blank { height: 10px; }
.help-dim { text-align: center; color: #8c8c8c; font-size: 1.1vw; padding-top: 4px; }

/* ── Goto overlay ── */
#goto-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.59);
  display: none;
  align-items: center;
  justify-content: center;
}
#goto-box {
  background: #282828;
  border: 2px solid #646464;
  border-radius: 8px;
  padding: 24px;
  min-width: 200px;
  text-align: left;
}
#goto-label {
  font-size: 1.1vw;
  color: #c8c8c8;
  margin-bottom: 8px;
}
#goto-input-display {
  font-size: 2.5vw;
  color: #fff;
  min-height: 40px;
  letter-spacing: 2px;
}

/* ── Loading overlay ── */
#loading-overlay {
  position: absolute;
  inset: 0;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
#loading-box {
  text-align: center;
  color: #fff;
  width: 30vw;
  min-width: 260px;
}
#loading-text {
  font-size: 1.4vw;
  color: #c8c8c8;
  margin-bottom: 16px;
}
#loading-bar-wrap {
  height: 6px;
  background: #333;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 10px;
}
#loading-bar-fill {
  height: 100%;
  background: #0078ff;
  border-radius: 3px;
  width: 0%;
  transition: width 0.1s linear;
}
#loading-count {
  font-size: 1.1vw;
  color: #646464;
}
</style>
</head>
<body>

<!-- Present view -->
<div id="present-view">
  <img id="slide-img" src="" alt="slide">
  <div id="progress-bar-wrap">
    <div id="progress-bar-fill"></div>
  </div>
  <div id="countdown-bar"></div>
  <div id="info-bar">
    <div id="info-left"></div>
    <div id="info-center"></div>
    <div id="info-right"></div>
  </div>
</div>

<!-- Overview view -->
<div id="overview-view"></div>

<!-- Help overlay -->
<div id="help-overlay">
  <div id="help-box">
    <div class="help-heading">Playback</div>
    <hr class="help-rule">
    <div class="help-row"><span class="help-key">Space / P</span><span class="help-desc">Pause / Play</span></div>
    <div class="help-row"><span class="help-key">→ / Enter</span><span class="help-desc">Next slide</span></div>
    <div class="help-row"><span class="help-key">← / Backspace</span><span class="help-desc">Previous slide</span></div>
    <div class="help-row"><span class="help-key">Home</span><span class="help-desc">First slide</span></div>
    <div class="help-row"><span class="help-key">End</span><span class="help-desc">Last slide</span></div>
    <div class="help-row"><span class="help-key">G</span><span class="help-desc">Go to slide number</span></div>
    <div class="help-row"><span class="help-key">Left click</span><span class="help-desc">Next slide</span></div>
    <div class="help-row"><span class="help-key">Right click</span><span class="help-desc">Previous slide</span></div>
    <div class="help-blank"></div>
    <div class="help-heading">View</div>
    <hr class="help-rule">
    <div class="help-row"><span class="help-key">T</span><span class="help-desc">Toggle info bar</span></div>
    <div class="help-row"><span class="help-key">Tab / O</span><span class="help-desc">Slide overview</span></div>
    <div class="help-row"><span class="help-key">F / F11</span><span class="help-desc">Toggle fullscreen</span></div>
    <div class="help-row"><span class="help-key">H / F1 / ?</span><span class="help-desc">This help</span></div>
    <div class="help-blank"></div>
    <div class="help-row"><span class="help-key">Q / Escape</span><span class="help-desc">Quit (close tab)</span></div>
    <div class="help-blank"></div>
    <div class="help-dim">Press any key to dismiss</div>
  </div>
</div>

<!-- Loading overlay -->
<div id="loading-overlay">
  <div id="loading-box">
    <div id="loading-text">Loading slides…</div>
    <div id="loading-bar-wrap"><div id="loading-bar-fill"></div></div>
    <div id="loading-count"></div>
  </div>
</div>

<!-- Goto overlay -->
<div id="goto-overlay">
  <div id="goto-box">
    <div id="goto-label"></div>
    <div id="goto-input-display"></div>
  </div>
</div>

<script>
const SLIDES = __SLIDES_DATA__;
const SECTIONS = __SECTIONS_DATA__;
const OVERVIEW_COLS = 8;

// ── State ──────────────────────────────────────────────────────────────────
let current = 0;
let mode = 'present'; // 'present' | 'overview' | 'help' | 'goto'
let paused = false;
let autoPaused = false;
let showInfo = false;
let gotoText = '';
let overviewSelected = 0;
let slideStartTime = null;   // performance.now() when slide began
let slideElapsed = 0;        // seconds already elapsed on this slide before last pause
let animFrameId = null;
let progressBarStyle = null; // { color, height } for current slide

// ── DOM refs ───────────────────────────────────────────────────────────────
const presentView   = document.getElementById('present-view');
const overviewView  = document.getElementById('overview-view');
const helpOverlay   = document.getElementById('help-overlay');
const gotoOverlay   = document.getElementById('goto-overlay');
const slideImg      = document.getElementById('slide-img');
const infoBar       = document.getElementById('info-bar');
const infoLeft      = document.getElementById('info-left');
const infoCenter    = document.getElementById('info-center');
const infoRight     = document.getElementById('info-right');
const progressWrap  = document.getElementById('progress-bar-wrap');
const progressFill  = document.getElementById('progress-bar-fill');
const countdownBar  = document.getElementById('countdown-bar');
const gotoLabel     = document.getElementById('goto-label');
const gotoDisplay   = document.getElementById('goto-input-display');

// ── Helpers ────────────────────────────────────────────────────────────────
function formatDuration(secs) {
  secs = Math.max(0, Math.round(secs));
  if (secs >= 60) {
    const m = Math.floor(secs / 60), s = secs % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  return `${secs}s`;
}

function endTimeRemaining(slide) {
  if (!slide.until) return null;
  const [h, m] = slide.until.split(':').map(Number);
  const now = new Date();
  const target = new Date(now);
  target.setHours(h, m, 0, 0);
  if (target < now) return 0;
  return Math.max(0, (target - now) / 1000);
}

function currentElapsed() {
  if (slideStartTime === null) return slideElapsed;
  return slideElapsed + (performance.now() - slideStartTime) / 1000;
}

function slideRemaining(slide) {
  const et = endTimeRemaining(slide);
  if (et !== null) return et;
  if (slide.duration <= 0) return 0;
  return Math.max(0, slide.duration - currentElapsed());
}

function slideProgress(slide) {
  const et = endTimeRemaining(slide);
  if (et !== null) {
    // Can't easily track end_time_duration in web; use 0..1 based on remaining/total
    // Store total when slide starts
    if (_endTimeDuration > 0) return 1 - et / _endTimeDuration;
    return et <= 0 ? 1 : 0;
  }
  if (slide.duration > 0) return Math.min(currentElapsed() / slide.duration, 1);
  return 1;
}

function presentationPosition() {
  let pos = 0;
  for (let i = 0; i < current; i++) pos += SLIDES[i].duration;
  pos += Math.min(currentElapsed(), SLIDES[current].duration);
  return pos;
}

function presentationTotal() {
  return SLIDES.reduce((s, sl) => s + sl.duration, 0);
}

function hhmmss(secs) {
  secs = Math.floor(secs);
  const m = Math.floor(secs / 60), s = secs % 60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// ── Slide management ───────────────────────────────────────────────────────
let _endTimeDuration = 0;

function initEndTime() {
  const slide = SLIDES[current];
  const rem = endTimeRemaining(slide);
  _endTimeDuration = (rem !== null) ? rem : 0;
}

function leaveSlide() {
  if (autoPaused) { paused = false; autoPaused = false; }
  stopAnimation();
}

function gotoSlide(idx) {
  idx = Math.max(0, Math.min(idx, SLIDES.length - 1));
  leaveSlide();
  current = idx;
  slideElapsed = 0;
  slideStartTime = null;
  initEndTime();
  renderPresent();
  if (!paused) startAnimation();
}

function nextSlide() { if (current < SLIDES.length - 1) gotoSlide(current + 1); }
function prevSlide() { if (current > 0) gotoSlide(current - 1); }

// ── Animation loop ─────────────────────────────────────────────────────────
function startAnimation() {
  if (animFrameId !== null) return;
  slideStartTime = performance.now();
  animFrameId = requestAnimationFrame(animationFrame);
}

function stopAnimation() {
  if (animFrameId !== null) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  if (slideStartTime !== null) {
    slideElapsed += (performance.now() - slideStartTime) / 1000;
    slideStartTime = null;
  }
}

function animationFrame(ts) {
  animFrameId = null;
  const slide = SLIDES[current];

  // End-time slide
  const et = endTimeRemaining(slide);
  if (et !== null) {
    if (et <= 0) {
      if (_endTimeDuration > 0) {
        if (current < SLIDES.length - 1) { gotoSlide(current + 1); return; }
        else { paused = true; updateOverlays(); return; }
      } else {
        paused = true; autoPaused = true; updateOverlays(); return;
      }
    }
    updateOverlays();
    animFrameId = requestAnimationFrame(animationFrame);
    return;
  }

  // Duration-0 slide
  if (slide.duration === 0) {
    if (!paused) { paused = true; autoPaused = true; }
    updateOverlays();
    return;
  }

  const elapsed = currentElapsed();
  if (elapsed >= slide.duration) {
    if (current < SLIDES.length - 1) {
      gotoSlide(current + 1);
    } else {
      stopAnimation();
      slideElapsed = slide.duration;
      paused = true;
      updateOverlays();
    }
    return;
  }

  updateOverlays();
  animFrameId = requestAnimationFrame(animationFrame);
}

// ── Render ─────────────────────────────────────────────────────────────────
function renderPresent() {
  const slide = SLIDES[current];
  slideImg.src = slide.src;
  progressBarStyle = slide.show_progress_bar ? {
    color: slide.bar_color || 'rgb(31,67,5)',
    height: (slide.bar_height || 16) + 'px',
  } : null;
  if (progressBarStyle) {
    progressFill.style.background = progressBarStyle.color;
    progressFill.style.height = progressBarStyle.height;
  }
  updateOverlays();
}

function updateOverlays() {
  if (mode !== 'present') return;
  const slide = SLIDES[current];

  // Progress bar
  if (slide.show_progress_bar && !paused) {
    progressWrap.style.display = 'block';
    progressFill.style.width = (slideProgress(slide) * 100) + '%';
  } else {
    progressWrap.style.display = 'none';
  }

  // Countdown
  if (slide.show_countdown && !paused) {
    const rem = slideRemaining(slide);
    if (rem > 0) {
      countdownBar.style.display = 'block';
      countdownBar.textContent = formatDuration(Math.ceil(rem));
    } else {
      countdownBar.style.display = 'none';
    }
  } else {
    countdownBar.style.display = 'none';
  }

  // Info bar
  const showBar = showInfo || paused;
  if (!showBar || (autoPaused && !showInfo)) {
    infoBar.classList.remove('visible');
    return;
  }
  infoBar.classList.add('visible');

  // Left: title + page + remaining
  const leftParts = [];
  if (slide.title) leftParts.push(slide.title);
  if (slide.show_page_number) leftParts.push(`${slide.page}/${slide.total_pages}`);
  const rem = slideRemaining(slide);
  if (rem > 0) leftParts.push(formatDuration(Math.ceil(rem)));
  infoLeft.textContent = leftParts.join('   ');

  // Center: status
  if (paused) {
    if (autoPaused) {
      infoCenter.innerHTML = '<span class="status-waiting">WAITING</span>';
    } else {
      infoCenter.innerHTML = '<span class="status-paused">PAUSED</span>';
    }
  } else if (showInfo && (slide.duration > 0 || slide.until)) {
    infoCenter.innerHTML = '<span class="status-running">RUNNING</span>';
  } else {
    infoCenter.textContent = '';
  }

  // Right: slide counter + time
  const pos = presentationPosition();
  const total = presentationTotal();
  infoRight.textContent = `${current + 1}/${SLIDES.length}   ${hhmmss(pos)} / ${hhmmss(total)}`;
}

// ── Mode switches ──────────────────────────────────────────────────────────
function enterPresentMode() {
  mode = 'present';
  presentView.style.display = 'flex';
  overviewView.style.display = 'none';
  helpOverlay.style.display = 'none';
  gotoOverlay.style.display = 'none';
  document.body.style.cursor = 'none';
  if (!paused) startAnimation();
}

function enterOverviewMode() {
  mode = 'overview';
  stopAnimation();
  overviewSelected = current;
  presentView.style.display = 'none';
  overviewView.style.display = 'block';
  helpOverlay.style.display = 'none';
  gotoOverlay.style.display = 'none';
  document.body.style.cursor = 'default';
  renderOverview();
  overviewScrollToSelected();
}

function enterHelpMode() {
  mode = 'help';
  stopAnimation();
  helpOverlay.style.display = 'flex';
  document.body.style.cursor = 'default';
}

function enterGotoMode() {
  mode = 'goto';
  stopAnimation();
  gotoText = '';
  gotoLabel.textContent = `Go to slide (1\u2013${SLIDES.length}):`;
  gotoDisplay.textContent = '\u2502';
  gotoOverlay.style.display = 'flex';
  document.body.style.cursor = 'default';
}

function confirmGoto() {
  const num = parseInt(gotoText, 10);
  if (!isNaN(num)) gotoSlide(num - 1);
  enterPresentMode();
}

// ── Overview rendering ─────────────────────────────────────────────────────
function renderOverview() {
  overviewView.innerHTML = '';

  SECTIONS.forEach((section, secIdx) => {
    // Heading
    const heading = document.createElement('div');
    heading.className = 'section-heading';

    const titleEl = document.createElement('span');
    titleEl.className = 'section-title';
    titleEl.textContent = section.title || 'Untitled';
    heading.appendChild(titleEl);

    const sectionDuration = SLIDES.slice(section.start, section.end)
      .reduce((s, sl) => s + sl.duration, 0);
    if (sectionDuration > 0) {
      const durEl = document.createElement('span');
      durEl.className = 'section-duration';
      durEl.textContent = formatDuration(Math.round(sectionDuration));
      heading.appendChild(durEl);
    }

    overviewView.appendChild(heading);

    const rule = document.createElement('hr');
    rule.className = 'section-rule';
    overviewView.appendChild(rule);

    // Grid
    const grid = document.createElement('div');
    grid.className = 'thumb-grid';
    grid.style.marginBottom = '24px';

    for (let i = section.start; i < section.end; i++) {
      const slide = SLIDES[i];
      const cell = document.createElement('div');
      cell.className = 'thumb-cell';
      if (i === overviewSelected) cell.classList.add('selected');
      if (i === current && i !== overviewSelected) cell.classList.add('current');
      cell.dataset.idx = i;

      const wrap = document.createElement('div');
      wrap.className = 'thumb-img-wrap';

      const img = document.createElement('img');
      img.src = slide.src;
      img.alt = `Slide ${i + 1}`;
      img.loading = 'lazy';
      wrap.appendChild(img);
      cell.appendChild(wrap);

      // Label strip: three slots matching pygame's centered/right icon logic
      // centered = show_page_number: icon in middle, page in right
      // not centered:               icon in right
      const label = document.createElement('div');
      label.className = 'thumb-label';

      const hasIcon = slide.show_countdown || slide.show_progress_bar;
      const centered = slide.show_page_number;

      const leftSpan = document.createElement('span');
      leftSpan.className = 'label-left';
      if (slide.until) {
        leftSpan.textContent = slide.until;
      } else if (slide.duration > 0) {
        leftSpan.textContent = formatDuration(Math.round(slide.duration));
      }
      label.appendChild(leftSpan);

      const midSpan = document.createElement('span');
      midSpan.className = 'label-mid';
      if (hasIcon && centered) {
        midSpan.appendChild(slide.show_countdown ? makeClock() : makeBarIcon());
      }
      label.appendChild(midSpan);

      const rightSpan = document.createElement('span');
      rightSpan.className = 'label-right';
      if (centered) {
        rightSpan.textContent = `${slide.page}/${slide.total_pages}`;
      } else if (hasIcon) {
        rightSpan.appendChild(slide.show_countdown ? makeClock() : makeBarIcon());
      }
      label.appendChild(rightSpan);

      cell.appendChild(label);

      cell.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        overviewSelected = i;
        updateOverviewSelection();
      });
      cell.addEventListener('click', (e) => {
        if (e.button !== 0) return;
        gotoSlide(i);
        enterPresentMode();
      });

      grid.appendChild(cell);
    }

    overviewView.appendChild(grid);
  });
}

function updateOverviewSelection() {
  overviewView.querySelectorAll('.thumb-cell').forEach(cell => {
    const i = parseInt(cell.dataset.idx, 10);
    cell.classList.toggle('selected', i === overviewSelected);
    cell.classList.toggle('current', i === current && i !== overviewSelected);
  });
}

function overviewScrollToSelected() {
  // Find the selected cell and scroll it into view
  const cell = overviewView.querySelector(`[data-idx="${overviewSelected}"]`);
  if (cell) {
    cell.scrollIntoView({ block: 'center', behavior: 'instant' });
  }
}

// Overview keyboard: arrow keys navigate within grid, respecting sections
function overviewMoveRight() {
  if (overviewSelected < SLIDES.length - 1) {
    overviewSelected++;
    updateOverviewSelection();
    ensureOverviewVisible();
  }
}
function overviewMoveLeft() {
  if (overviewSelected > 0) {
    overviewSelected--;
    updateOverviewSelection();
    ensureOverviewVisible();
  }
}
function overviewMoveDown() {
  // find section and row of current selection
  const { secIdx, row } = findOverviewPos(overviewSelected);
  if (secIdx === null) return;
  const section = SECTIONS[secIdx];
  const secLen = section.end - section.start;
  const rowsInSection = Math.ceil(secLen / OVERVIEW_COLS);
  let newIdx = null;
  if (row + 1 < rowsInSection) {
    // next row in same section, same column (clamped)
    const col = (overviewSelected - section.start) % OVERVIEW_COLS;
    const posInSec = (row + 1) * OVERVIEW_COLS + col;
    newIdx = section.start + Math.min(posInSec, secLen - 1);
  } else if (secIdx + 1 < SECTIONS.length) {
    // first row of next section, same column (clamped)
    const col = (overviewSelected - section.start) % OVERVIEW_COLS;
    const nextSec = SECTIONS[secIdx + 1];
    const nextLen = nextSec.end - nextSec.start;
    newIdx = nextSec.start + Math.min(col, nextLen - 1);
  }
  if (newIdx !== null) {
    overviewSelected = newIdx;
    updateOverviewSelection();
    ensureOverviewVisible();
  }
}
function overviewMoveUp() {
  const { secIdx, row } = findOverviewPos(overviewSelected);
  if (secIdx === null) return;
  const section = SECTIONS[secIdx];
  let newIdx = null;
  if (row > 0) {
    const col = (overviewSelected - section.start) % OVERVIEW_COLS;
    const posInSec = (row - 1) * OVERVIEW_COLS + col;
    const secLen = section.end - section.start;
    newIdx = section.start + Math.min(posInSec, secLen - 1);
  } else if (secIdx > 0) {
    const col = (overviewSelected - section.start) % OVERVIEW_COLS;
    const prevSec = SECTIONS[secIdx - 1];
    const prevLen = prevSec.end - prevSec.start;
    const lastRow = Math.floor((prevLen - 1) / OVERVIEW_COLS);
    const posInSec = lastRow * OVERVIEW_COLS + col;
    newIdx = prevSec.start + Math.min(posInSec, prevLen - 1);
  }
  if (newIdx !== null) {
    overviewSelected = newIdx;
    updateOverviewSelection();
    ensureOverviewVisible();
  }
}

function findOverviewPos(idx) {
  for (let s = 0; s < SECTIONS.length; s++) {
    const sec = SECTIONS[s];
    if (idx >= sec.start && idx < sec.end) {
      return { secIdx: s, row: Math.floor((idx - sec.start) / OVERVIEW_COLS) };
    }
  }
  return { secIdx: null, row: null };
}

function ensureOverviewVisible() {
  const cell = overviewView.querySelector(`[data-idx="${overviewSelected}"]`);
  if (cell) cell.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// ── SVG icons for thumbnails ───────────────────────────────────────────────
function makeClock() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', '20'); svg.setAttribute('height', '20');
  svg.setAttribute('viewBox', '0 0 20 20');
  const circle = document.createElementNS(ns, 'circle');
  circle.setAttribute('cx', '10'); circle.setAttribute('cy', '10'); circle.setAttribute('r', '8');
  circle.setAttribute('stroke', '#c8c8c8'); circle.setAttribute('stroke-width', '2'); circle.setAttribute('fill', 'none');
  svg.appendChild(circle);
  // hour hand (~10:00 position)
  const h = document.createElementNS(ns, 'line');
  h.setAttribute('x1', '10'); h.setAttribute('y1', '10');
  h.setAttribute('x2', '10'); h.setAttribute('y2', '4');
  h.setAttribute('stroke', '#c8c8c8'); h.setAttribute('stroke-width', '2');
  svg.appendChild(h);
  const m = document.createElementNS(ns, 'line');
  m.setAttribute('x1', '10'); m.setAttribute('y1', '10');
  m.setAttribute('x2', '16'); m.setAttribute('y2', '10');
  m.setAttribute('stroke', '#c8c8c8'); m.setAttribute('stroke-width', '2');
  svg.appendChild(m);
  return svg;
}

function makeBarIcon(slide) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', '30'); svg.setAttribute('height', '10');
  svg.setAttribute('viewBox', '0 0 30 10');
  const rect = document.createElementNS(ns, 'rect');
  rect.setAttribute('x', '0'); rect.setAttribute('y', '0');
  rect.setAttribute('width', '30'); rect.setAttribute('height', '10');
  rect.setAttribute('rx', '2');
  rect.setAttribute('stroke', '#c8c8c8'); rect.setAttribute('stroke-width', '1.5'); rect.setAttribute('fill', 'none');
  svg.appendChild(rect);
  const fill = document.createElementNS(ns, 'rect');
  fill.setAttribute('x', '2'); fill.setAttribute('y', '2');
  fill.setAttribute('width', '10'); fill.setAttribute('height', '6');
  fill.setAttribute('rx', '1'); fill.setAttribute('fill', '#c8c8c8');
  svg.appendChild(fill);
  return svg;
}

// ── Keyboard handling ──────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  // Prevent browser shortcuts for keys we handle
  const handled = handleKey(e);
  if (handled) e.preventDefault();
});

function handleKey(e) {
  const key = e.key;

  if (mode === 'goto') {
    if (key === 'Enter')     { confirmGoto(); return true; }
    if (key === 'Escape')    { enterPresentMode(); return true; }
    if (key === 'Backspace') { gotoText = gotoText.slice(0, -1); gotoDisplay.textContent = gotoText + '\u2502'; return true; }
    if (/^\d$/.test(key))    { gotoText += key; gotoDisplay.textContent = gotoText + '\u2502'; return true; }
    return false;
  }

  if (mode === 'help') {
    enterPresentMode();
    return true;
  }

  if (mode === 'overview') {
    if (key === 'Escape' || key === 'Tab' || key.toLowerCase() === 'o') { enterPresentMode(); return true; }
    if (key === 'Enter')     { gotoSlide(overviewSelected); enterPresentMode(); return true; }
    if (key === 'ArrowRight'){ overviewMoveRight(); return true; }
    if (key === 'ArrowLeft') { overviewMoveLeft();  return true; }
    if (key === 'ArrowDown') { overviewMoveDown();  return true; }
    if (key === 'ArrowUp')   { overviewMoveUp();    return true; }
    if (key.toLowerCase() === 'f' || key === 'F11') { toggleFullscreen(); return true; }
    if (key.toLowerCase() === 'q') { window.close(); return true; }
    return false;
  }

  // Present mode
  if (key === 'ArrowRight' || key === 'Enter' || key === 'PageDown') { nextSlide(); return true; }
  if (key === 'ArrowLeft'  || key === 'Backspace' || key === 'PageUp') { prevSlide(); return true; }
  if (key === 'Home') { gotoSlide(0); return true; }
  if (key === 'End')  { gotoSlide(SLIDES.length - 1); return true; }

  if (key === ' ' || key.toLowerCase() === 'p') {
    const slide = SLIDES[current];
    if (paused && slide.duration === 0) {
      if (autoPaused) {
        autoPaused = false; paused = false;
        if (current < SLIDES.length - 1) { nextSlide(); }
      } else {
        autoPaused = true;
      }
    } else {
      paused = !paused;
      if (!paused) {
        slideStartTime = performance.now();
        startAnimation();
      } else {
        stopAnimation();
      }
    }
    updateOverlays();
    return true;
  }

  if (key.toLowerCase() === 't') { showInfo = !showInfo; updateOverlays(); return true; }
  if (key.toLowerCase() === 'g') { enterGotoMode(); return true; }
  if (key === 'Tab' || key.toLowerCase() === 'o') { enterOverviewMode(); return true; }
  if (key.toLowerCase() === 'h' || key === 'F1' || key === '?') { enterHelpMode(); return true; }
  if (key.toLowerCase() === 'f' || key === 'F11') { toggleFullscreen(); return true; }
  if (key.toLowerCase() === 'q' || key === 'Escape') { window.close(); return true; }

  return false;
}

// ── Mouse handling in present mode ─────────────────────────────────────────
presentView.addEventListener('click', (e) => {
  if (mode !== 'present') return;
  if (e.button === 0) nextSlide();
});
presentView.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  if (mode !== 'present') return;
  prevSlide();
});

// ── Fullscreen ─────────────────────────────────────────────────────────────
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen().catch(() => {});
  } else {
    document.exitFullscreen().catch(() => {});
  }
}

// ── Help overlay click to dismiss ──────────────────────────────────────────
helpOverlay.addEventListener('click', () => enterPresentMode());

// ── Init: preload all images then start ────────────────────────────────────
(function preload() {
  const overlay   = document.getElementById('loading-overlay');
  const barFill   = document.getElementById('loading-bar-fill');
  const countEl   = document.getElementById('loading-count');
  const total     = SLIDES.length;
  let loaded = 0;

  function onDone() {
    loaded++;
    const pct = Math.round(loaded / total * 100);
    barFill.style.width = pct + '%';
    countEl.textContent = loaded + ' / ' + total;
    if (loaded === total) {
      overlay.style.display = 'none';
      enterPresentMode();
      gotoSlide(0);
    }
  }

  SLIDES.forEach(slide => {
    const img = new Image();
    img.onload  = onDone;
    img.onerror = onDone;  // count failures too so we don't hang
    img.src = slide.src;
  });
})();
</script>
</body>
</html>
"""


def default_bar_color_css(bar_color):
    """Convert bar color config value to a CSS string."""
    if not bar_color:
        return "rgb(31,67,5)"
    # Hex or named — pass through as-is; browsers understand both
    return bar_color


def export(config, output_dir: Path):
    slides_raw = build_slide_list(config)
    if not slides_raw:
        print("No slides found.")
        return

    # Create output/slides directory
    slides_out = output_dir / "slides"
    slides_out.mkdir(parents=True, exist_ok=True)

    # Copy PNGs with sequential names
    slide_data = []
    for i, slide in enumerate(slides_raw):
        dst_name = f"{i:04d}.png"
        dst = slides_out / dst_name
        shutil.copy2(slide["path"], dst)

        slide_data.append({
            "src": f"slides/{dst_name}",
            "duration": slide["duration"],
            "until": slide["until"],
            "show_progress_bar": slide["show_progress_bar"],
            "bar_color": default_bar_color_css(slide["bar_color"]),
            "bar_height": slide["bar_height"] or 16,
            "show_countdown": slide["show_countdown"],
            "title": slide["title"],
            "show_page_number": slide["show_page_number"],
            "page": slide["page"],
            "total_pages": slide["total_pages"],
        })

    sections = build_sections(slides_raw)

    # Embed data into HTML
    html = HTML_TEMPLATE.replace("__SLIDES_DATA__", json.dumps(slide_data, indent=2))
    html = html.replace("__SECTIONS_DATA__", json.dumps(sections, indent=2))

    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    print(f"Exported {len(slide_data)} slides to {output_dir.resolve()}")
    print(f"Open: {index_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Export a VideoSlides presentation as a static web site"
    )
    parser.add_argument(
        "output",
        help="Output directory (will be created if needed)",
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
    output_dir = Path(args.output)

    original_dir = os.getcwd()
    os.chdir(args.directory)

    try:
        print("Loading configuration...")
        config = load_config(args.config)

        print("Preparing slide images...")
        prepare_slide_images(config)

        export(config, output_dir)
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
