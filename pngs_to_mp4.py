import re
from pathlib import Path
from moviepy import ImageClip, concatenate_videoclips

PNG_DIR = Path("pngs")
OUTPUT_FILENAME = "output_video.mp4"

# Regex: <order> <slide> <duration>.png
FILENAME_RE = re.compile(r'^(\d+)\s+(\d+)\s+(\d+)\.png$')

slides = []
for file in sorted(PNG_DIR.glob('*.png')):
    m = FILENAME_RE.match(file.name)
    if not m:
        raise RuntimeError(f"Invalid filename format: '{file.name}'. Expected '<order> <slide> <duration>.png'")

    order, slide, duration = map(int, m.groups())
    slides.append((order, slide, file, duration))

# Sort by <order> then <slide>
slides.sort(key=lambda t: (t[0], t[1]))

# Build video clips
clips = [ImageClip(str(f)).with_duration(duration) for _, _, f, duration in slides]

if clips:
    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(OUTPUT_FILENAME, fps=1, threads=None)
    print(f"✅ Video saved as '{OUTPUT_FILENAME}'")
else:
    print("⚠️ No valid PNG images found in 'pngs/'")