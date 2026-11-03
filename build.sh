#!/bin/bash
set -e

SPEAKERS=$(python3 -c "
import tomllib
with open('config.toml', 'rb') as f:
    config = tomllib.load(f)
print(' '.join(config['speakers']['list']))
")

echo "Building opening..."
uv run webslides ./public/opening --config config-opening.toml --base-path /opening/

echo "Building closing..."
uv run webslides ./public/closing --config config-closing.toml --base-path /closing/

for speaker in $SPEAKERS; do
    if [ -f "${speaker}.pdf" ]; then
        echo "Building slides for ${speaker}..."
        uv run webslides ./public/${speaker} --config config-${speaker}.toml --base-path /${speaker}/
    else
        echo "Skipping ${speaker} (${speaker}.pdf not found)"
    fi
done

echo "Generating nginx.conf..."
python3 generate_nginx.py

echo "Building combined root view..."
python3 combine.py
