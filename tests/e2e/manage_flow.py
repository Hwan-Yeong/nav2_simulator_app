#!/usr/bin/env python3
"""Config sets and map management through the UI.

1. change a parameter, save it as a config set, reset, load the set back, delete it
2. add a map from an exported zip and from a loose YAML + image pair, rename one, delete both
"""
import os
import sys
import tempfile
import urllib.request

from playwright.sync_api import sync_playwright

from common import B, api, dbg, open_app, wait

NAME = 'E2E 테스트 세트'


def main():
    for s in api('GET', '/api/presets'):
        if s['name'] == NAME:
            api('DELETE', f"/api/presets/{s['id']}")
    tmp = tempfile.mkdtemp()
    zip_path = os.path.join(tmp, 'synth_corridor.zip')
    open(zip_path, 'wb').write(urllib.request.urlopen(B + '/api/maps/synth_corridor/export.zip').read())
    with sync_playwright() as p:
        br, pg, errors = open_app(p)
        # ---------------------------------------------------------------- config sets
        pg.click('#leftTabs button[data-tab="params"]')
        pg.wait_for_timeout(600)
        num = pg.locator('.prow:has-text("최대 전진 속도") input[type=number]').first
        num.fill('0.33')
        num.dispatch_event('change')
        pg.click('.setbar button:has-text("저장")')
        pg.fill('#setName', NAME)
        pg.fill('#setDesc', '속도만 낮춤')
        pg.click('#modalFoot button:has-text("새 세트로 저장")')
        pg.wait_for_timeout(600)
        saved = next(s for s in api('GET', '/api/presets') if s['name'] == NAME)
        assert saved['values'] == {'max_vel_x': 0.33} or abs(list(saved['values'].values())[0] - 0.33) < 1e-9, saved
        assert NAME in pg.inner_text('.setbar')
        print('ok  saved config set', saved['id'], saved['values'])
        pg.click('#leftTabs button[data-tab="setup"]')
        pg.click('#setsSec .opt:has-text("스택 기본값")')
        pg.wait_for_timeout(400)
        assert pg.locator('#paramCount').is_hidden()
        pg.click(f'#setsSec .opt:has-text("{NAME}")')
        pg.wait_for_timeout(600)
        assert pg.inner_text('#paramCount') == '1'
        print('ok  reset to stack defaults, loaded the set back (1 change)')
        pg.click(f'#setsSec .setitem:has-text("{NAME}") button[title="설정 세트 지우기"]')
        pg.click('#modalFoot button:has-text("지우기")')
        pg.wait_for_timeout(600)
        assert not any(s['name'] == NAME for s in api('GET', '/api/presets'))
        assert pg.locator(f'#setsSec .opt:has-text("{NAME}")').count() == 0
        print('ok  deleted the set')

        # ---------------------------------------------------------------- maps
        pg.click('#leftTabs button[data-tab="map"]')
        before = {m['id'] for m in api('GET', '/api/maps')}
        pg.click('#tabMap button:has-text("맵 추가")')
        pg.set_input_files('#upFiles', zip_path)
        pg.click('#modalFoot button:has-text("추가")')
        wait(pg, lambda d: d.get('map') not in before and d.get('mapLoaded'), 10, 'zip map imported and selected')
        zid = dbg(pg)['map']
        print('ok  imported zip ->', zid)
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'navstudio', 'data', 'maps', 'synth_clutter')
        y = open(os.path.join(src, 'map.yaml')).read()
        img = [f for f in os.listdir(src) if f != 'map.yaml'][0]
        open(os.path.join(tmp, 'office3.yaml'), 'w').write(y.replace(img, 'office3' + os.path.splitext(img)[1]))
        open(os.path.join(tmp, 'office3' + os.path.splitext(img)[1]), 'wb').write(open(os.path.join(src, img), 'rb').read())
        pg.click('#tabMap button:has-text("맵 추가")')
        pg.set_input_files('#upFiles', [os.path.join(tmp, 'office3.yaml'), os.path.join(tmp, 'office3' + os.path.splitext(img)[1])])
        pg.fill('#upName', '3층 사무실')
        pg.click('#modalFoot button:has-text("추가")')
        wait(pg, lambda d: d.get('map') == 'office3', 10, 'yaml + image imported')
        assert pg.locator('.mapcard:has-text("3층 사무실")').count() == 1
        print('ok  imported YAML + image as office3 (3층 사무실)')
        pg.hover('.mapitem:has-text("3층 사무실")')
        pg.click('.mapitem:has-text("3층 사무실") .mapmore')
        pg.click('.menu button:has-text("이름 바꾸기")')
        pg.fill('#modalBody input', '3층 사무실 (테스트)')
        pg.click('#modalFoot button:has-text("바꾸기")')
        pg.wait_for_timeout(600)
        assert pg.locator('.mapcard:has-text("3층 사무실 (테스트)")').count() == 1
        print('ok  renamed')
        for mid in ('office3', zid):
            name = next(m['name'] for m in api('GET', '/api/maps') if m['id'] == mid)
            card = pg.locator('.mapitem', has=pg.locator(f'img[src^="/api/maps/{mid}/"]'))
            card.hover()
            card.locator('.mapmore').click()
            pg.click('.menu button:has-text("지우기")')
            pg.click('#modalFoot button:has-text("지우기")')
            pg.wait_for_timeout(800)
            assert mid not in {m['id'] for m in api('GET', '/api/maps')}, mid
            print('ok  deleted', mid, f'({name})')
        assert dbg(pg)['map'] in before
        br.close()
    print('page errors:', errors or 'none')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
