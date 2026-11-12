"""Render docs/icon.svg as PNG (512, 128, 48 px, transparent corners) plus a light/dark preview.

Usage: icon.py <icon.svg> <out dir>
"""
import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

svg, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
src = 'data:image/svg+xml;base64,' + base64.b64encode(svg.read_bytes()).decode()

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for size in (512, 128, 48):
        page = browser.new_page(viewport={'width': size, 'height': size})
        page.set_content(f'<body style="margin:0;background:transparent">'
                         f'<img src="{src}" width="{size}" height="{size}" style="display:block"></body>')
        page.screenshot(path=str(out / f'icon-{size}.png'), omit_background=True)
        page.close()
    page = browser.new_page(viewport={'width': 640, 'height': 160})
    tiles = ''.join(
        f'<div style="background:{bg};padding:16px;display:flex;gap:16px;align-items:flex-end">'
        + ''.join(f'<img src="{src}" width="{s}" height="{s}">' for s in (128, 64, 48, 32)) + '</div>'
        for bg in ('#ffffff', '#1e1e1e'))
    page.set_content(f'<body style="margin:0;display:flex">{tiles}</body>')
    page.screenshot(path=str(out / 'icon-preview.png'))
    browser.close()
