#!/usr/bin/env python3
"""Sensors through the UI.

1. sensor library: make a ToF model, save it, delete it
2. robot designer (Everybot 홈 로봇): add a sensor from the library, mirror one, side view, detection coverage
3. simulation with that robot: a 5 cm box on the path -> perception confirms it, the robot arrives without touching it;
   draw a drop with the cliff tool
"""
import json
import sys

from playwright.sync_api import sync_playwright

from common import api, dbg, drag_world, open_app, wait

MODEL = 'E2E ToF'


def main():
    for m in api('GET', '/api/sensors'):
        if m['name'] == MODEL and not m['builtin']:
            api('DELETE', f"/api/sensors/{m['id']}")
    api('POST', '/api/session/stop', {})
    meta = api('GET', '/api/maps/synth_warehouse')
    x0, y0, _ = meta['start']
    start, goal = [x0, y0, 0.0], [x0 + 2.6, y0, 0.0]
    low = {'type': 'rect', 'x0': x0 + 1.0, 'y0': y0 - 0.35, 'x1': x0 + 1.2, 'y1': y0 + 0.35, 'z1': 0.05}
    with sync_playwright() as p:
        br, pg, errors = open_app(p, 'robot')
        # ---------------------------------------------------------------- sensor library
        pg.select_option('#robotForm select', 'everybot_home')
        pg.wait_for_timeout(1500)
        pg.click('#robotForm button:has-text("라이브러리")')
        pg.click('.liblist button:has-text("ToF (단일·멀티존)")')
        pg.fill('.libedit input[type=text] >> nth=0', MODEL)
        pg.locator('.libedit label.field:has-text("가로 존 수") input').fill('4')
        pg.locator('.libedit label.field:has-text("세로 존 수") input').fill('4')
        pg.locator('.libedit label.field:has-text("가로 존 수") input').dispatch_event('input')
        pg.click('.libedit button:has-text("저장")')
        pg.wait_for_timeout(800)
        saved = next(m for m in api('GET', '/api/sensors') if m['name'] == MODEL)
        assert saved['type'] == 'tof' and saved['zones_x'] == 4 and not saved['builtin'], saved
        print('ok  sensor model saved to the library')
        pg.click('.libedit button:has-text("지우기")')
        pg.click('#modalFoot button:has-text("지우기")')
        pg.wait_for_timeout(800)
        assert not any(m['name'] == MODEL for m in api('GET', '/api/sensors'))
        print('ok  sensor model deleted')
        pg.keyboard.press('Escape')
        # ---------------------------------------------------------------- robot designer
        n0 = pg.locator('#robotForm .sensor').count()
        pg.click('#robotForm button:has-text("센서 추가")')
        pg.click('.menu button:has-text("초음파")')
        pg.wait_for_timeout(800)
        assert pg.locator('#robotForm .sensor').count() == n0 + 1
        card = pg.locator('#robotForm .sensor').nth(2)
        name = card.locator('input[type=text]').first.input_value()
        card.locator('header button[aria-label$="메뉴"]').click()
        pg.click('.menu button:has-text("좌우 대칭으로 복제")')
        pg.wait_for_timeout(800)
        names = [pg.locator('#robotForm .sensor').nth(i).locator('input[type=text]').first.input_value() for i in range(n0 + 2)]
        assert len(names) == n0 + 2 and len(set(names)) == len(names), names
        print(f'ok  sensors added from the library and mirrored ({name} -> {names[3]})')
        pg.click('#cadTools button:has-text("옆에서")')
        pg.wait_for_timeout(500)
        assert '옆에서' in pg.inner_text('#cadHint')
        pg.click('#cadTools button:has-text("위에서")')
        print('ok  side view')
        # ---------------------------------------------------------------- detection coverage
        pg.click('#cadTools button:has-text("감지 범위")')
        pg.wait_for_selector('.covpanel[data-state="done"]', timeout=60000)
        pg.click('.covpanel .seg button:has-text("단차")')
        pg.wait_for_timeout(300)
        pg.wait_for_selector('.covpanel[data-state="done"]', timeout=60000)
        dyn = pg.inner_text('.covdyn')
        assert '제때 100%' in dyn and 'depth' in dyn, dyn
        pg.click('.covpanel button[aria-label="감지 범위 닫기"]')
        assert pg.locator('.covpanel').is_hidden()
        print('ok  detection coverage: drop seen in time across the corridor')
        # ---------------------------------------------------------------- simulation with range sensors
        scene = {'start': start, 'goal': goal, 'static_obs': [low], 'dyn_obs': []}
        pg.evaluate(f"localStorage.setItem('ns.scene.synth_warehouse', JSON.stringify({json.dumps(scene)}));"
                    "localStorage.setItem('ns.sel', JSON.stringify({map: 'synth_warehouse', robotId: 'everybot_home', robot: null}));"
                    "localStorage.setItem('ns.nSlots', '1')")
        pg.goto(pg.url.replace('#robot', '#sim'))
        pg.reload()
        pg.wait_for_timeout(2500)
        wait(pg, lambda d: d.get('map') == 'synth_warehouse' and d.get('mapLoaded'), 10, 'map selected')
        pg.click('#btnStart')
        wait(pg, lambda d: d.get('status') == 'ready' and d.get('live'), 60, 'simulation ready')
        print('ok  simulation with range sensors started')
        pg.click('button[data-tool="goal"]')
        drag_world(pg, goal[:2], (goal[0] + 0.5, goal[1]))
        d = wait(pg, lambda d: d.get('nav') in ('succeeded', 'aborted'), 90, 'navigation finished')
        m = d.get('metrics') or {}
        panel = pg.inner_text('#tSensors')
        assert d['nav'] == 'succeeded' and m.get('collisions') == 0 and not m.get('falls'), (d, m)
        assert 'mtof_left' in panel and '장애물' in panel and '장애물 0 ' not in panel, panel
        print(f"ok  low box detected and avoided: {d['nav']}, collisions {m.get('collisions')}, panel {panel.splitlines()[-3:-1]}")
        pg.click('button[data-tool="cliff"]')
        drag_world(pg, (x0 + 0.5, y0 + 1.0), (x0 + 1.0, y0 + 1.5))
        pg.wait_for_timeout(800)
        sc = api('GET', '/api/scene')
        assert any(o['type'] == 'cliff' and o.get('depth') for o in sc['static_obs']), sc['static_obs']
        print('ok  drop drawn with the cliff tool')
        api('POST', '/api/session/stop', {})
        if errors:
            raise SystemExit('FAIL: page errors: ' + ' | '.join(errors[:5]))
        br.close()
    print('PASS sensor flow')


if __name__ == '__main__':
    sys.exit(main())
