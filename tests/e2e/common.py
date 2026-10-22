"""Shared helpers for the Playwright end-to-end tests (they drive a running server: python3 -m navstudio run)."""
import json
import os
import time
import urllib.request

B = os.environ.get('NAVSTUDIO_URL', 'http://localhost:8765')


def api(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'content-type': 'application/json'})
    data = urllib.request.urlopen(r).read()
    try:
        return json.loads(data)
    except ValueError:
        return data.decode()


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


def drag_world(pg, a, b, canvas='view'):
    """Drag on a view canvas between two world points (uses the ?debug viewport hook; views share one transform)."""
    pts = [pg.evaluate(f"(() => {{ const r = document.getElementById('{canvas}').getBoundingClientRect();"
                       f" const p = window.__vp.toS({x}, {y}); return [p[0] + r.left, p[1] + r.top]; }})()") for x, y in (a, b)]
    pg.mouse.move(*pts[0])
    pg.mouse.down()
    pg.mouse.move(*pts[1], steps=8)
    pg.mouse.up()


def open_app(p, hash_='sim', viewport=(1500, 900)):
    br = p.chromium.launch()
    pg = br.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.goto(f'{B}/?debug#{hash_}')
    pg.wait_for_timeout(2500)
    return br, pg, errors
