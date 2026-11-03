#!/usr/bin/env python3
"""Build public/root/index.html by combining per-speaker slide data — no PNG copying."""
import json
import re
import shutil
import tomllib
from pathlib import Path

with open('config.toml', 'rb') as f:
    _config = tomllib.load(f)
SPEAKERS = ['opening'] + _config['speakers']['list'] + ['closing']
PUBLIC = Path('public')

all_slides = []
all_sections = []
slide_offset = 0
template_html = None

for speaker in SPEAKERS:
    html_path = PUBLIC / speaker / 'index.html'
    if not html_path.exists():
        print(f'Skipping {speaker} (not built yet)')
        continue

    html = html_path.read_text()

    if template_html is None:
        template_html = html

    slides = json.loads(re.search(r'const SLIDES = (\[.*?\]);', html, re.DOTALL).group(1))
    sections_match = re.search(r'const SECTIONS = (\[.*?\]);', html, re.DOTALL)
    sections = json.loads(sections_match.group(1)) if sections_match else []

    for section in sections:
        section['start'] += slide_offset
        section['end'] += slide_offset

    all_slides.extend(slides)
    all_sections.extend(sections)
    slide_offset += len(slides)
    print(f'  {speaker}: {len(slides)} slides')

if not template_html or not all_slides:
    print('No slides found.')
    raise SystemExit(1)

combined = re.sub(
    r'const SLIDES = \[.*?\];',
    f'const SLIDES = {json.dumps(all_slides, indent=2)};',
    template_html,
    flags=re.DOTALL,
)
combined = re.sub(
    r'const SECTIONS = \[.*?\];',
    f'const SECTIONS = {json.dumps(all_sections, indent=2)};',
    combined,
    flags=re.DOTALL,
)

root_dir = PUBLIC / 'root'
shutil.rmtree(root_dir, ignore_errors=True)
root_dir.mkdir()
(root_dir / 'index.html').write_text(combined)
print(f'Combined {len(all_slides)} slides → public/root/index.html')
