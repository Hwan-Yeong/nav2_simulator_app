#!/usr/bin/env python3
"""End-to-end UI flow in headless Chromium against a running server (python3 -m navstudio run).

1. pick a map, start the simulation from the top-bar button
2. pick the goal tool and drag on the canvas -> robot drives
3. change a parameter -> the top button offers '변경 적용', apply -> Nav2 restarts with the change
"""
import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

B = 'http://localhost:8765'
OUT = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ns_e2e'


def dbg(pg):
    return json.loads(pg.evaluate("document.getElementById('nsdebug').textContent || '{}'"))


def wait(pg, cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = dbg(pg)
        if cond(d):
            return d
        pg.wait_for_timeout(500)
    raise SystemExit(f'FAIL: {what} (last state {dbg(pg)}; toasts: {pg.inner_text("#toasts")!r})')


def drag_world(pg, a, b):
    sa = pg.evaluate(f"(() => {{ const r = document.getElementById('view').getBoundingClientRect(); const p = window.__vp.toS({a[0]}, {a[1]}); return [p[0] + r.left, p[1] + r.top]; }})()")
    sb = pg.evaluate(f"(() => {{ const r = document.getElementById('view').getBoundingClientRect(); const p = window.__vp.toS({b[0]}, {b[1]}); return [p[0] + r.left, p[1] + r.top]; }})()")
    pg.mouse.move(*sa)
    pg.mouse.down()
    pg.mouse.move(*sb, steps=8)
    pg.mouse.up()


def main():
    urllib.request.urlopen(urllib.request.Request(B + '/api/session/stop', data=b'{}', headers={'content-type': 'application/json'}))
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={'width': 1500, 'height': 900})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        pg.goto(B + '/?debug#sim')
        pg.wait_for_timeout(2500)
        pg.click('#leftTabs button[data-tab="map"]')
        pg.click('.mapcard:has-text("좁은 문")')
        wait(pg, lambda d: d.get('map') == 'synth_narrow' and d.get('mapLoaded'), 10, 'map selected')
        print('ok  map selected')
        pg.click('#btnStart')
        wait(pg, lambda d: d.get('status') == 'ready' and d.get('live'), 60, 'simulation ready')
        print('ok  simulation started from the button')
        pg.click('button[data-tool="goal"]')
        drag_world(pg, (2.0, 2.0), (2.0, 3.0))
        d = wait(pg, lambda d: (d.get('metrics') or {}).get('path_len', 0) > 1.0, 40, 'robot moving to the goal')
        print('ok  goal by drag -> robot moving', d['nav'], d['metrics'])
        pg.screenshot(path=OUT + '_driving.png')
        pg.click('#leftTabs button[data-tab="params"]')
        pg.wait_for_timeout(800)
        num = pg.locator('.prow:has-text("최대 전진 속도") input[type=number]').first
        new = '0.35' if num.input_value() != '0.35' else '0.3'
        num.fill(new)
        num.dispatch_event('change')
        pg.wait_for_timeout(500)
        label = pg.inner_text('#btnStart')
        assert '변경 적용' in label, f'top button should offer apply, got {label!r}'
        print('ok  parameter change -> button:', label.strip())
        pg.click('#btnStart')
        wait(pg, lambda d: d.get('status') == 'starting', 10, 'restart begins')
        wait(pg, lambda d: d.get('status') == 'ready', 60, 'restarted')
        params = urllib.request.urlopen(B + '/api/session/params.yaml').read().decode()
        assert f'max_vel_x: {new}' in params, 'restarted stack must use the new value'
        print(f'ok  applied: generated params contain max_vel_x: {new}')
        pg.screenshot(path=OUT + '_applied.png')
        print('page errors:', errors or 'none')
        br.close()


if __name__ == '__main__':
    main()
