#!/usr/bin/env python3
"""Capture the screenshots used by the user guide (docs/guide/img) plus element boxes for numbered callouts.

python3 tests/capture_guide.py sim|tools|panels|robot|bench|tune   (server on :8765)
"""
import json
import math
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

B = 'http://localhost:8765'
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'docs', 'guide', 'img')
os.makedirs(OUT, exist_ok=True)
BOXES = os.path.join(OUT, 'boxes.json')
VW, VH = 1440, 900


def api(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'content-type': 'application/json'})
    return json.load(urllib.request.urlopen(r))


def wait_ready(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if api('GET', '/api/info')['stack']['status'] == 'ready':
            return
        time.sleep(1)
    raise SystemExit('stack not ready')


def save_boxes(name, pg, sels):
    allb = json.load(open(BOXES)) if os.path.exists(BOXES) else {}
    out = {}
    for key, sel in sels.items():
        b = pg.locator(sel).first.bounding_box()
        if b:
            out[key] = {k: round(v / (VW if k in ('x', 'width') else VH), 4) for k, v in b.items()}
    allb[name] = out
    json.dump(allb, open(BOXES, 'w'), indent=1)


def page(p, url, dark=False):
    br = p.chromium.launch(args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader'])
    pg = br.new_page(viewport={'width': VW, 'height': VH}, device_scale_factor=2, color_scheme='dark' if dark else 'light')
    pg.goto(url)
    pg.wait_for_timeout(3500)
    return br, pg


def sim_start(map_id, ep, extra_static=(), extra_dyn=()):
    api('POST', '/api/session/start', {'map': map_id, 'robot_id': 'everybot', 'stack': 'prod', 'values': {}, 'start': ep['start']})
    wait_ready()
    api('POST', '/api/scene', {'map': map_id, 'start': ep['start'], 'goal': ep['goal'],
                               'static_obs': ep['static_obs'] + list(extra_static), 'dyn_obs': ep['dyn_obs'] + list(extra_dyn)})
    api('POST', '/api/nav/goal', {'pose': ep['goal']})


def shot_sim(p):
    ep = next(e for e in api('GET', '/api/scenarios/synth_clutter') if e['id'] == 'synth_clutter/dynamic/000')
    sim_start('synth_clutter', ep)
    br, pg = page(p, B + '/#sim')
    pg.evaluate("localStorage.clear()")
    pg.wait_for_timeout(16000)
    pg.screenshot(path=os.path.join(OUT, 'sim_overview.png'))
    save_boxes('sim_overview', pg, {
        'tabs': '.ws-tabs', 'chips': '#sessionChips', 'pill': '#stackPill', 'start': '#btnStart', 'left': '#leftTabs',
        'tools': '#tools', 'layers': '#layers', 'runbar': '#runbar', 'nav': '#tNav', 'logs': '#tLogs', 'view': '#stage'})
    br.close()


def shot_tools(p):
    ep = next(e for e in api('GET', '/api/scenarios/synth_narrow') if e['id'] == 'synth_narrow/nominal/000')
    # bottom-left room (0.3..4.7 m): box right of the path, chair left of it, a pedestrian crossing the room
    box = {'type': 'rect', 'x0': 3.0, 'y0': 2.5, 'x1': 3.5, 'y1': 2.95}
    legs = [{'type': 'circle', 'x': 1.0 + dx, 'y': 3.2 + dy, 'r': 0.025, 'g': 'chair1'} for dx in (-0.22, 0.22) for dy in (-0.22, 0.22)]
    ped = {'wps': [[0.8, 1.9], [4.1, 1.9]], 'speed': 0.5, 'r': 0.22, 'phase': 0.1}
    sim_start('synth_narrow', ep, [box] + legs, [ped])
    br, pg = page(p, B + '/#sim')
    pg.click('button[data-tool="person"]')
    pg.mouse.move(1300, 850)
    pg.wait_for_timeout(16000)
    pg.screenshot(path=os.path.join(OUT, 'sim_tools.png'))
    save_boxes('sim_tools', pg, {'tools': '#tools', 'opts': '#toolOpts', 'view': '#stage'})
    br.close()


def shot_panels(p):
    br, pg = page(p, B + '/#sim')
    pg.click('#leftTabs button[data-tab="setup"]')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, 'setup.png'), clip={'x': 0, 'y': 0, 'width': 760, 'height': 900})
    pg.click('#leftTabs button[data-tab="params"]')
    pg.wait_for_timeout(1000)
    pg.evaluate("document.querySelectorAll('#tabParams details').forEach(d => { d.open = d.querySelector('summary').textContent.includes('DWB') || d.querySelector('summary').textContent.includes('속도'); })")
    pg.wait_for_timeout(400)
    pg.locator('.prow:has-text("PathAlign")').first.scroll_into_view_if_needed()
    num = pg.locator('.prow:has-text("PathAlign") input[type=number]').first
    num.fill('24')
    num.dispatch_event('change')
    pg.wait_for_timeout(600)
    pg.screenshot(path=os.path.join(OUT, 'params.png'))
    save_boxes('params', pg, {'panel': '#tabParams', 'changed': '.prow.changed', 'start': '#btnStart', 'badge': '#paramCount',
                              'stackchip': '#sessionChips .chip:last-child'})
    pg.click('button:has-text("YAML 미리보기")')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, 'yaml_diff.png'))
    br.close()


def shot_robot(p):
    br, pg = page(p, B + '/#robot')
    pg.select_option('#robotForm select', 'rect_amr')
    pg.wait_for_timeout(3000)
    pg.screenshot(path=os.path.join(OUT, 'robot.png'))
    save_boxes('robot', pg, {'form': '#robotForm', 'drive': '#robotForm .seg', 'cad': '#cadStage', 'cadtools': '#cadTools', 'three': '#threeWrap', 'derived': '#derived'})
    pg.select_option('#robotForm select', 'ackermann_cart')
    pg.wait_for_timeout(3000)
    pg.screenshot(path=os.path.join(OUT, 'robot_ackermann.png'))
    br.close()


def shot_bench(p):
    runs = [r for r in api('GET', '/api/runs?kind=bench') if r['status'] == 'done']
    br, pg = page(p, B + '/#bench')
    pg.click('#ws-bench .btn.primary.act')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=os.path.join(OUT, 'bench_form.png'))
    if runs:
        pg.click('#ws-bench .opt')
        pg.wait_for_timeout(2500)
        pg.screenshot(path=os.path.join(OUT, 'bench_result.png'))
        save_boxes('bench_result', pg, {'summary': '#ws-bench .panel:nth-child(2)', 'matrix': '#ws-bench .panel:last-child'})
        pg.locator('#ws-bench td.click').nth(5).click()
        pg.wait_for_timeout(5000)
        pg.screenshot(path=os.path.join(OUT, 'replay.png'))
    br.close()


def shot_tune(p):
    runs = [r for r in api('GET', '/api/runs?kind=tune') if r['status'] == 'done']
    br, pg = page(p, B + '/#tune')
    pg.click('#ws-tune .btn.primary.act')
    pg.wait_for_timeout(2000)
    pg.screenshot(path=os.path.join(OUT, 'tune_form.png'))
    if runs:
        pg.click('#ws-tune .opt')
        pg.wait_for_timeout(2500)
        pg.screenshot(path=os.path.join(OUT, 'tune_result.png'), full_page=False)
    br.close()


if __name__ == '__main__':
    with sync_playwright() as p:
        for what in sys.argv[1:]:
            globals()['shot_' + what](p)
            print('captured', what)
