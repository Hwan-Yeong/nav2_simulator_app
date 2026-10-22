#!/usr/bin/env python3
"""Capture the user-guide screenshots (docs/guide/img, element boxes in boxes.json for the numbered callouts) and the
README images (docs/img), from a running server on :8765.

python3 scripts/capture_guide.py all | prepare | sim tools panels compare maps robot bench tune | readme

Run it against a clean NAVSTUDIO_HOME so old runs or private maps do not show up, e.g.
  NAVSTUDIO_HOME=/tmp/ns-capture NAVSTUDIO_OVERLAY=~/.navstudio/overlay/install/setup.bash navstudio run --no-browser
`prepare` creates what the screenshots show: a saved config set, a user map, a finished benchmark and tuning run.
"""
import io
import json
import os
import sys
import tempfile
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

B = 'http://localhost:8765'
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'guide', 'img')
README_IMG = os.path.join(ROOT, 'docs', 'img')
BOXES = os.path.join(OUT, 'boxes.json')
VW, VH = 1440, 900
os.makedirs(OUT, exist_ok=True)


def api(method, path, body=None):
    r = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                               headers={'content-type': 'application/json'})
    return json.load(urllib.request.urlopen(r))


def wait_slots(n, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if all(s['status'] == 'ready' for s in api('GET', '/api/info')['slots'][:n]):
            return
        time.sleep(1)
    raise SystemExit('slots not ready')


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


def shot(pg, name, clip=None):
    pg.screenshot(path=os.path.join(OUT, name), clip=clip)


def around(pg, sel, pad=16, extra=None):
    """Clip rectangle around an element (and optionally a second one)."""
    boxes = [pg.locator(s).first.bounding_box() for s in ([sel] + ([extra] if extra else []))]
    x0, y0 = min(b['x'] for b in boxes) - pad, min(b['y'] for b in boxes) - pad
    x1, y1 = max(b['x'] + b['width'] for b in boxes) + pad, max(b['y'] + b['height'] for b in boxes) + pad
    return {'x': max(0, x0), 'y': max(0, y0), 'width': min(VW, x1) - max(0, x0), 'height': min(VH, y1) - max(0, y0)}


def episode(map_id, eid):
    return next(e for e in api('GET', f'/api/scenarios/{map_id}') if e['id'] == eid)


def scene(map_id, ep, extra_static=(), extra_dyn=()):
    api('POST', '/api/scene', {'map': map_id, 'start': ep['start'], 'goal': ep['goal'],
                               'static_obs': ep['static_obs'] + list(extra_static), 'dyn_obs': ep['dyn_obs'] + list(extra_dyn)})


def sim_start(map_id, ep, extra_static=(), extra_dyn=()):
    api('POST', '/api/session/stop', {})
    api('POST', '/api/session/start', {'slot': 0, 'map': map_id, 'robot_id': 'everybot', 'stack': 'prod', 'values': {}, 'start': ep['start']})
    wait_slots(1)
    scene(map_id, ep, extra_static, extra_dyn)
    api('POST', '/api/nav/goal', {'pose': ep['goal']})


def load_scene_in_ui(pg, map_id, ep, extra_static=(), extra_dyn=()):
    """Put the scene into the page's own storage too, so the UI shows the same obstacles before anything runs."""
    sc = {'start': ep['start'], 'goal': ep['goal'], 'static_obs': ep['static_obs'] + list(extra_static), 'dyn_obs': ep['dyn_obs'] + list(extra_dyn)}
    pg.evaluate(f"localStorage.setItem('ns.scene.{map_id}', JSON.stringify({json.dumps(sc)})); localStorage.setItem('ns.sel', JSON.stringify({{map: '{map_id}', robotId: 'everybot'}}))")


# ---------------------------------------------------------------- data the screenshots show
def prepare():
    sets = api('GET', '/api/presets')
    if not any(s['name'] == 'DWB 빠르게' for s in sets):
        api('POST', '/api/presets', {'name': 'DWB 빠르게', 'description': '최대 속도·경로 추종 가중치 올림', 'stack': 'prod',
                                     'values': {'dwb_max_vel_x': 0.45, 'dwb_path_align': 24.0, 'dwb_path_dist': 26.0}})
    maps = api('GET', '/api/maps')
    if not any(not m['builtin'] for m in maps):
        z = urllib.request.urlopen(B + '/api/maps/synth_warehouse/export.zip').read()
        boundary = 'navstudio'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="warehouse.zip"\r\nContent-Type: application/zip\r\n\r\n').encode() + z + \
            (f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n물류 센터 2층\r\n--{boundary}--\r\n').encode()
        urllib.request.urlopen(urllib.request.Request(B + '/api/maps', data=body, headers={'content-type': f'multipart/form-data; boundary={boundary}'}))
    robot = {'robot_id': 'everybot', 'robot': None}
    runs = api('GET', '/api/runs')
    if not any(r['kind'] == 'bench' and r['status'] == 'done' for r in runs):
        rid = api('POST', '/api/bench/start', {'name': '스택 비교 (좁은 문 · 테이블·의자)', 'workers': 4, 'configs': [
            {'name': '운영 설정', **robot, 'stack': 'prod', 'values': {}, 'raw': ''},
            {'name': '튜닝안 A', **robot, 'stack': 'prod', 'values': next(s['values'] for s in api('GET', '/api/presets') if s['id'] == 'tuned_a'), 'raw': ''},
            {'name': 'MPPI', **robot, 'stack': 'mppi', 'values': {}, 'raw': ''}],
            'episodes': {'source': 'bundled', 'maps': ['synth_narrow', 'synth_clutter'], 'categories': ['nominal', 'unmapped', 'dynamic'], 'per_map': 4, 'seed': 1}})['id']
        _wait_run(rid)
    if not any(r['kind'] == 'tune' and r['status'] == 'done' for r in runs):
        rid = api('POST', '/api/tune/start', {'name': '경로 추종 가중치 튜닝', 'base': {'name': '기준', **robot, 'stack': 'prod', 'values': {}, 'raw': ''},
                                               'params': [{'id': 'dwb_path_align', 'low': 10, 'high': 40, 'log': False, 'default': 32},
                                                          {'id': 'dwb_path_dist', 'low': 10, 'high': 40, 'log': False, 'default': 32},
                                                          {'id': 'dwb_base_obstacle', 'low': 0.01, 'high': 0.5, 'log': True, 'default': 0.02}],
                                               'weights': {'success': 1, 'speed': 1, 'clearance': 1, 'smooth': 1}, 'trials': 8, 'parallel': 2, 'workers': 2,
                                               'episodes': {'source': 'bundled', 'maps': ['synth_clutter'], 'categories': ['unmapped', 'dynamic'], 'per_map': 4, 'seed': 1}})['id']
        _wait_run(rid)


def _wait_run(rid, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = api('GET', f'/api/runs/{rid}')
        if r['status'] in ('done', 'error', 'canceled'):
            print('  run', rid, r['status'])
            return
        time.sleep(10)
    raise SystemExit(f'run {rid} did not finish')


# ---------------------------------------------------------------- screenshots
def shot_sim(p):
    ep = episode('synth_clutter', 'synth_clutter/dynamic/000')
    sim_start('synth_clutter', ep)
    br, pg = page(p, B + '/#sim')
    pg.wait_for_timeout(14000)
    shot(pg, 'sim_overview.png')
    save_boxes('sim_overview', pg, {
        'tabs': '.ws-tabs', 'chips': '#sessionChips', 'pill': '#stackPill', 'start': '#btnStart', 'left': '#leftTabs',
        'tools': '#tools', 'layers': '#layers', 'runbar': '#runbar', 'nav': '#tNav', 'logs': '#tLogs', 'view': '#stage'})
    br.close()


def shot_tools(p):
    ep = episode('synth_narrow', 'synth_narrow/nominal/000')
    # bottom-left room (0.3..4.7 m): box right of the path, chair left of it, a pedestrian crossing the room
    box = {'type': 'rect', 'x0': 3.0, 'y0': 2.5, 'x1': 3.5, 'y1': 2.95}
    legs = [{'type': 'circle', 'x': 1.0 + dx, 'y': 3.2 + dy, 'r': 0.025, 'g': 'chair1'} for dx in (-0.22, 0.22) for dy in (-0.22, 0.22)]
    ped = {'wps': [[0.8, 1.9], [4.1, 1.9]], 'speed': 0.5, 'r': 0.22, 'phase': 0.1}
    sim_start('synth_narrow', ep, [box] + legs, [ped])
    br, pg = page(p, B + '/#sim')
    pg.click('button[data-tool="person"]')
    pg.mouse.move(1300, 850)
    pg.wait_for_timeout(16000)
    shot(pg, 'sim_tools.png')
    save_boxes('sim_tools', pg, {'tools': '#tools', 'opts': '#toolOpts', 'view': '#stage'})
    br.close()


def shot_panels(p):
    br, pg = page(p, B + '/#sim')
    pg.click('#leftTabs button[data-tab="setup"]')
    pg.click('#setsSec .opt:has-text("DWB 빠르게")')
    pg.wait_for_timeout(1200)
    pg.locator('#setsSec').scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    shot(pg, 'setup_sets.png', clip=around(pg, '#setsSec', 10))
    pg.click('#leftTabs button[data-tab="params"]')
    pg.wait_for_timeout(1000)
    pg.evaluate("document.querySelectorAll('#tabParams details').forEach(d => { d.open = d.querySelector('summary').textContent.includes('DWB') || d.querySelector('summary').textContent.includes('속도'); })")
    pg.wait_for_timeout(400)
    pg.locator('.prow:has-text("PathAlign")').first.scroll_into_view_if_needed()
    num = pg.locator('.prow:has-text("PathAlign") input[type=number]').first
    num.fill('20')
    num.dispatch_event('change')
    pg.evaluate("document.getElementById('tabParams').closest('.side').scrollTop = 0")
    pg.wait_for_timeout(600)
    shot(pg, 'params.png')
    save_boxes('params', pg, {'setbar': '.setbar', 'changed': '.prow.changed', 'start': '#btnStart', 'badge': '#paramCount'})
    br.close()


def shot_compare(p):
    api('POST', '/api/session/stop', {})
    ep = episode('synth_clutter', 'synth_clutter/dynamic/001')
    br, pg = page(p, B + '/#sim')
    load_scene_in_ui(pg, 'synth_clutter', ep)
    pg.reload()
    pg.wait_for_timeout(3000)
    pg.click('.seg.slots button[data-n="3"]')
    pg.wait_for_timeout(800)
    for slot, label in ((0, '운영 설정'), (1, 'MPPI'), (2, 'Regulated Pure Pursuit')):
        pg.click(f'#vhead{slot} .cfgname')
        pg.click(f'.menu button:has(b:text-is("{label}"))')
        pg.wait_for_timeout(300)
    pg.click('#btnStart')
    wait_slots(3)
    pg.wait_for_timeout(1500)
    pg.click('#runbar button:has-text("동시 출발")')
    pg.wait_for_timeout(15000)
    pg.mouse.move(VW - 10, VH - 10)
    pg.click('#vhead1 .sst')     # make B the slot being edited, as in the legend
    pg.wait_for_timeout(600)
    shot(pg, 'sim_compare.png')
    save_boxes('sim_compare', pg, {'slots': '.seg.slots', 'head': '#vhead1', 'slotctl': '#vhead1 button[title="재시작"]',
                                   'slotgo': '#vhead1 button[title^="이 슬롯만"]', 'startall': '#btnStart',
                                   'go': '#runbar button:has-text("동시 출발")', 'compare': '.tele.compare', 'editing': '#editingSlot'})
    pg.click('#vhead2 .cfgname')
    pg.wait_for_timeout(500)
    shot(pg, 'slot_menu.png', clip=around(pg, '.menu', 12, '#vhead2'))
    pg.keyboard.press('Escape')
    api('POST', '/api/session/stop', {})
    br.close()


def shot_maps(p):
    tmp = tempfile.mkdtemp()
    open(os.path.join(tmp, 'site_maps.zip'), 'wb').write(urllib.request.urlopen(B + '/api/maps/synth_corridor/export.zip').read())
    br, pg = page(p, B + '/#sim')
    pg.click('#leftTabs button[data-tab="map"]')
    pg.click('#tabMap button:has-text("맵 추가")')
    pg.set_input_files('#upFiles', os.path.join(tmp, 'site_maps.zip'))
    pg.wait_for_timeout(500)
    shot(pg, 'map_add.png', clip=around(pg, '.modal-card', 0))
    pg.click('#modalFoot button:has-text("취소")')
    user = pg.locator('.mapitem:has-text("물류 센터 2층")')
    user.hover()
    user.locator('.mapmore').click()
    pg.wait_for_timeout(400)
    shot(pg, 'map_menu.png', clip=around(pg, '.menu', 12, '.mapitem:has-text("물류 센터 2층")'))
    br.close()


def shot_robot(p):
    br, pg = page(p, B + '/#robot')
    pg.select_option('#robotForm select', 'rect_amr')
    pg.wait_for_timeout(3000)
    shot(pg, 'robot.png')
    save_boxes('robot', pg, {'form': '#robotForm', 'drive': '#robotForm .seg', 'cad': '#cadStage', 'cadtools': '#cadTools', 'three': '#threeWrap', 'derived': '#derived'})
    pg.select_option('#robotForm select', 'ackermann_cart')
    pg.wait_for_timeout(3000)
    shot(pg, 'robot_ackermann.png')
    br.close()


def shot_bench(p):
    br, pg = page(p, B + '/#bench')
    pg.click('#ws-bench .opt')
    pg.wait_for_timeout(2500)
    shot(pg, 'bench_result.png')
    save_boxes('bench_result', pg, {'summary': '#ws-bench .panel:nth-child(2)', 'matrix': '#ws-bench .panel:last-child'})
    pg.locator('#ws-bench td.click').nth(5).click()
    pg.wait_for_timeout(5000)
    shot(pg, 'replay.png')
    br.close()


def shot_tune(p):
    br, pg = page(p, B + '/#tune')
    pg.click('#ws-tune .btn.primary.act')
    pg.wait_for_timeout(2000)
    shot(pg, 'tune_form.png')
    pg.click('#ws-tune .opt')
    pg.wait_for_timeout(2500)
    shot(pg, 'tune_result.png')
    br.close()


def readme():
    """README images: the same screens at 1x."""
    os.makedirs(README_IMG, exist_ok=True)
    for src, dst in (('sim_overview.png', 'sim.png'), ('sim_compare.png', 'compare.png'), ('robot.png', 'robot_designer.png'),
                     ('bench_result.png', 'benchmark.png'), ('tune_result.png', 'tuning.png')):
        im = Image.open(os.path.join(OUT, src))
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.convert('RGB').save(buf, format='PNG', optimize=True)
        open(os.path.join(README_IMG, dst), 'wb').write(buf.getvalue())
    print('readme images ->', README_IMG)


ORDER = ['sim', 'tools', 'panels', 'compare', 'maps', 'robot', 'bench', 'tune']

if __name__ == '__main__':
    what = sys.argv[1:] or ['all']
    if what == ['all']:
        what = ['prepare'] + ORDER + ['readme']
    with sync_playwright() as p:
        for w in what:
            if w == 'prepare':
                prepare()
            elif w == 'readme':
                readme()
            else:
                globals()['shot_' + w](p)
            print('captured', w)
