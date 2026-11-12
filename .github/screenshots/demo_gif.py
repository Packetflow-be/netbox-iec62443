"""Screenshots of the demo plant and the README's demo.gif.

Usage: demo_gif.py <base url> <urls.json> <out dir>
Needs a NetBox with the plugin, `manage.py ot_demo` run, and a user demo/demo-password-for-ci.
Writes <out>/frame-N.png (full size) and <out>/demo.gif.
"""
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

base, urls_file, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
urls = json.loads(urls_file.read_text().strip().splitlines()[-1])
site = urls['site']

WIDTH, HEIGHT = 1280, 800
GIF_WIDTH = 1024

# (path, scroll to this selector or None, caption, seconds on screen)
FRAMES = [
    (f'/dcim/sites/{site}/access-map/', None,
     'Access map: every flow into the controller zones, worst first, with who decided it', 4.5),
    (f'/dcim/sites/{site}/access-map/', 'text=Diagram',
     'The same flows by Purdue level: red not allowed or expired, amber unknown, dashed remote access', 4.0),
    (urls['remote_flow'], None,
     'A flow: from a supplier zone into the DMZ, RDP on tcp/3389, remote access, in a conduit', 3.5),
    (urls['remote_flow'], '.card-header:text-is("Verdict")',
     'Its verdict: allowed, by whom, until when, and the path it takes: tunnel, jump host, firewall', 4.0),
    (urls['cell_zone'], None,
     'A zone: type, Purdue level, accountable person, SL-T, SL-A and SL-C per foundational requirement', 4.0),
    (f'/dcim/sites/{site}/ot-register/', None,
     'Zone register: the audit deliverable, printable and exported as CSV or JSON', 4.0),
    (f'/plugins/ot/checks/?site_id={site}', None,
     'Consistency checks: what is inconsistent, and what an audit will ask for and is missing', 4.5),
]

CAPTION_JS = """caption => {
  const bar = document.createElement('div');
  bar.textContent = caption;
  Object.assign(bar.style, {
    position: 'fixed', left: '0', right: '0', bottom: '0', zIndex: '100000',
    padding: '14px 24px', background: 'rgba(26, 24, 21, 0.92)', color: '#fff',
    font: '600 19px/1.3 Inter, system-ui, sans-serif', textAlign: 'center',
  });
  document.body.appendChild(bar);
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={'width': WIDTH, 'height': HEIGHT}, color_scheme='light',
                              device_scale_factor=1)
    page = ctx.new_page()
    page.goto(base + '/login/')
    page.fill('input[name=username]', 'demo')
    page.fill('input[name=password]', 'demo-password-for-ci')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    assert '/login' not in page.url, 'login failed'

    shots = []
    for n, (path, scroll_to, caption, seconds) in enumerate(FRAMES, start=1):
        response = page.goto(base + path)
        assert response.status == 200, f'{path}: HTTP {response.status}'
        page.wait_for_load_state('networkidle')
        if scroll_to:
            page.locator(scroll_to).first.evaluate(
                'e => window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 80)')
        page.evaluate(CAPTION_JS, caption)
        page.wait_for_timeout(300)
        frame = out / f'frame-{n}.png'
        page.screenshot(path=str(frame))
        shots.append((frame, seconds))
        print(n, response.status, page.title(), path)
    browser.close()

images = []
for frame, _ in shots:
    im = Image.open(frame).convert('RGB')
    im = im.resize((GIF_WIDTH, round(im.height * GIF_WIDTH / im.width)), Image.LANCZOS)
    images.append(im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE))
images[0].save(out / 'demo.gif', save_all=True, append_images=images[1:], loop=0, optimize=True,
               duration=[int(seconds * 1000) for _, seconds in shots], disposal=1)
print(f"demo.gif: {(out / 'demo.gif').stat().st_size // 1024} KiB")
