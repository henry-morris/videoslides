#!/usr/bin/env python3
"""Generate nginx.conf from the speakers list in config.toml."""
import tomllib
from pathlib import Path

with open('config.toml', 'rb') as f:
    config = tomllib.load(f)

speakers = config['speakers']['list']

blocks = ['server {', '    listen 8080;']

for speaker in speakers:
    blocks += [
        '',
        f'    location = /{speaker} {{',
        f'        root /usr/share/nginx/html;',
        f'        try_files /{speaker}/index.html =404;',
        f'    }}',
        f'    location /{speaker}/ {{',
        f'        alias /usr/share/nginx/html/{speaker}/;',
        f'        index index.html;',
        f'    }}',
    ]

blocks += [
    '',
    '    location = / {',
    '        root /usr/share/nginx/html/root;',
    '        try_files /index.html =404;',
    '    }',
    '',
    '    location /opening/ {',
    '        alias /usr/share/nginx/html/opening/;',
    '        index index.html;',
    '    }',
    '',
    '    location /closing/ {',
    '        alias /usr/share/nginx/html/closing/;',
    '        index index.html;',
    '    }',
    '',
    '    location / {',
    '        return 404;',
    '    }',
    '}',
]

Path('nginx.conf').write_text('\n'.join(blocks) + '\n')
print(f'Generated nginx.conf for {len(speakers)} speakers: {", ".join(speakers)}')
