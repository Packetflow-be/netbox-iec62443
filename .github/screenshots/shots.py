"""Screenshots of the demo plant for the README and docs/.

Usage: shots.py <base url> <urls.json> <out dir>
Needs a NetBox with the plugin, `manage.py ot_demo` run, and a user demo/demo-password-for-ci.

Each screenshot shows one part of a page, without NetBox's menu, top bar and footer, at twice the pixel density so
that the text stays sharp when GitHub scales the image down. Writes <out>/<name>.png for every entry of SHOTS; copy
the ones that changed to docs/.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, urls_file, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
urls = json.loads(urls_file.read_text().strip().splitlines()[-1])
site = urls['site']

VIEWPORT = {'width': 1280, 'height': 900}  # the content column is then about 980 px wide
SCALE = 2
PAD = 12

# (file name, page, element the shot ends with, most CSS pixels to show)
# Every shot starts at the page title; it ends at the bottom of the element (or the end of the content).
SHOTS = [
    ('access-map', f'/dcim/sites/{site}/access-map/', '.ot-map-card', None),
    ('overview', f'/dcim/sites/{site}/ot-overview/', '#levels', None),
    ('flow', urls['remote_flow'], None, None),
    ('zone', urls['cell_zone'], None, 1500),
    ('register', f'/dcim/sites/{site}/ot-register/', None, 1300),
    ('checks', f'/plugins/ot/checks/?site_id={site}', None, 1250),
    ('industrial-services', '/plugins/ot/industrial-services/', None, 1000),
    ('risk-assessment', urls['risk_assessment'], None, 1150),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=VIEWPORT, color_scheme='light', device_scale_factor=SCALE)
    page = ctx.new_page()
    page.goto(base + '/login/')
    page.fill('input[name=username]', 'demo')
    page.fill('input[name=password]', 'demo-password-for-ci')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    assert '/login' not in page.url, 'login failed'

    for name, path, until, most in SHOTS:
        response = page.goto(base + path)
        assert response.status == 200, f'{path}: HTTP {response.status}'
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(300)
        column = page.locator('.page-wrapper').bounding_box()
        top = page.locator('.page-header').bounding_box()['y']
        end = page.locator(until).first if until else page.locator('.page-body')
        bottom = end.bounding_box()
        height = bottom['y'] + bottom['height'] - top + PAD
        if most:
            height = min(height, most)
        clip = {'x': column['x'], 'y': top, 'width': column['width'], 'height': height}
        page.screenshot(path=str(out / f'{name}.png'), clip=clip, full_page=True)
        print(f'{name}: {round(clip["width"])}x{round(height)} CSS px, {page.title()}')

    browser.close()
