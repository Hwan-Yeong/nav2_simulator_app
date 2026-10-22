#!/usr/bin/env python3
"""Record a demo GIF of one live run, start to goal (server on :8765): docs/media/demo.gif

python3 tests/capture_demo_gif.py [episode_id] [speedup]
"""
import io
import json
import os
import sys
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

B = 'http://localhost:8765'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'docs', 'media')
os.makedirs(OUT, exist_ok=True)
FPS, WIDTH, MAX_S = 2.0, 960, 90


def api(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'content-type': 'application/json'})
    return json.load(urllib.request.urlopen(r))


def main(eid='synth_clutter/dynamic/000', speedup=2.0):
    mid = eid.split('/')[0]
    ep = next(e for e in api('GET', f'/api/scenarios/{mid}') if e['id'] == eid)
    api('POST', '/api/session/start', {'map': mid, 'robot_id': 'everybot', 'stack': 'prod', 'values': {}, 'start': ep['start']})
    for _ in range(60):
        if api('GET', '/api/info')['stack']['status'] == 'ready':
            break
        time.sleep(1)
    api('POST', '/api/scene', {'map': mid, 'start': ep['start'], 'goal': ep['goal'],
                               'static_obs': ep['static_obs'], 'dyn_obs': ep['dyn_obs']})
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={'width': 1440, 'height': 860})
        pg.goto(B + '/#sim')
        pg.wait_for_timeout(3500)
        pg.mouse.move(1430, 850)
        api('POST', '/api/nav/goal', {'pose': ep['goal']})
        frames, t0, done_at = [], time.time(), None
        while time.time() - t0 < MAX_S and (done_at is None or time.time() - done_at < 2.0):
            t = time.time()
            im = Image.open(io.BytesIO(pg.screenshot())).convert('RGB')
            frames.append(im.resize((WIDTH, int(im.height * WIDTH / im.width)), Image.LANCZOS))
            label = pg.locator('.row1 .big').first.text_content() or ''
            if done_at is None and time.time() - t0 > 3 and label not in ('주행 중', '목표 전송'):
                done_at = time.time()
            time.sleep(max(0.0, 1.0 / FPS - (time.time() - t)))
        br.close()
    pal = frames[len(frames) // 2].quantize(colors=96, method=Image.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.NONE) for f in frames]
    path = os.path.join(OUT, 'demo.gif')
    q[0].save(path, save_all=True, append_images=q[1:], duration=int(1000 / FPS / speedup), loop=0, optimize=True)
    print(path, len(frames), 'frames', round(time.time() - t0), 's', label, os.path.getsize(path) // 1024, 'KB')


if __name__ == '__main__':
    main(*sys.argv[1:2], *(float(a) for a in sys.argv[2:3]))
