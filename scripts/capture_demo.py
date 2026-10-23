#!/usr/bin/env python3
"""Record the README demo (docs/media/demo.gif): three settings leave together in comparison mode, start to finish.

python3 scripts/capture_demo.py [episode_id] [speedup]     (server on :8765)
"""
import io
import json
import os
import sys
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

B = os.environ.get('NAVSTUDIO_URL', 'http://localhost:8765')
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'docs', 'media')
os.makedirs(OUT, exist_ok=True)
FPS, WIDTH, MAX_S = 2.0, 960, 120
SLOTS = ('운영 설정', 'MPPI', 'Regulated Pure Pursuit')


def api(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'content-type': 'application/json'})
    return json.load(urllib.request.urlopen(r))


def state(pg):
    return json.loads(pg.evaluate("document.getElementById('nsdebug').textContent || '{}'"))


# small but important colours (slot A–D, accent, goal, good/bad) must survive the 128-colour GIF palette
KEY_COLOURS = ['#1c7ed6', '#e8940a', '#2f9e44', '#ae3ec9', '#0d7ea6', '#d6336c', '#1d8550', '#c23f2b', '#e0f0f6', '#e1f3e8']


def quantize(frames, colors=128):
    w, h = frames[0].size
    sample = Image.new('RGB', (w, h * 3 + 40), 'white')
    for k, f in enumerate((frames[0], frames[len(frames) // 2], frames[-1])):
        sample.paste(f, (0, h * k))
    step = w // len(KEY_COLOURS)
    for k, c in enumerate(KEY_COLOURS * 1):
        sample.paste(Image.new('RGB', (step, 40), c), (k * step, h * 3))
    pal = sample.quantize(colors=colors, method=Image.MEDIANCUT)
    return [f.quantize(palette=pal, dither=Image.NONE) for f in frames]


def main(eid='synth_clutter/dynamic/001', speedup=2.0):
    mid = eid.split('/')[0]
    ep = next(e for e in api('GET', f'/api/scenarios/{mid}') if e['id'] == eid)
    api('POST', '/api/session/stop', {})
    sc = {'start': ep['start'], 'goal': ep['goal'], 'static_obs': ep['static_obs'], 'dyn_obs': ep['dyn_obs']}
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={'width': 1440, 'height': 860})
        pg.goto(B + '/?debug#sim')
        pg.wait_for_timeout(1500)
        pg.evaluate(f"localStorage.setItem('ns.scene.{mid}', JSON.stringify({json.dumps(sc)})); localStorage.setItem('ns.sel', JSON.stringify({{map: '{mid}', robotId: 'everybot'}}))")
        pg.reload()
        pg.wait_for_timeout(3000)
        pg.click(f'.seg.slots button[data-n="{len(SLOTS)}"]')
        for i, label in enumerate(SLOTS):
            pg.click(f'#vhead{i} .cfgname')
            pg.click(f'.menu button:has(b:text-is("{label}"))')
            pg.wait_for_timeout(300)
        pg.click('#btnStart')
        t0 = time.time()
        while not all(s['status'] == 'ready' for s in state(pg)['slots']):
            if time.time() - t0 > 90:
                raise SystemExit('slots not ready')
            pg.wait_for_timeout(500)
        pg.wait_for_timeout(1500)
        pg.mouse.move(1430, 850)
        pg.click('#runbar button:has-text("동시 출발")')
        frames, t0, done_at = [], time.time(), None
        while time.time() - t0 < MAX_S and (done_at is None or time.time() - done_at < 3.0):
            t = time.time()
            im = Image.open(io.BytesIO(pg.screenshot())).convert('RGB')
            frames.append(im.resize((WIDTH, int(im.height * WIDTH / im.width)), Image.LANCZOS))
            if done_at is None and time.time() - t0 > 3 and all(s.get('result') for s in state(pg)['slots']):
                done_at = time.time()
            time.sleep(max(0.0, 1.0 / FPS - (time.time() - t)))
        results = [s.get('result') for s in state(pg)['slots']]
        api('POST', '/api/session/stop', {})
        br.close()
    q = quantize(frames)
    path = os.path.join(OUT, 'demo.gif')
    q[0].save(path, save_all=True, append_images=q[1:], duration=int(1000 / FPS / speedup), loop=0, optimize=True)
    print(path, len(frames), 'frames', round(time.time() - t0), 's', results, os.path.getsize(path) // 1024, 'KB')


if __name__ == '__main__':
    main(*sys.argv[1:2], *(float(a) for a in sys.argv[2:3]))
