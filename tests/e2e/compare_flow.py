#!/usr/bin/env python3
"""Comparison flow: three slots with different settings start together, leave together and are compared.

1. three views; slot B gets a config set, slot C a different stack, each from its header menu
2. '모두 시작' starts every slot; '동시 출발' sends all robots from the same start at the same moment
3. every slot arrives (or stops); the comparison table fills in; one slot is stopped and restarted on its own
"""
import sys

from playwright.sync_api import sync_playwright

from common import api, dbg, open_app, wait

OUT = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ns_compare'


def pick(pg, slot, label):
    pg.click(f'#vhead{slot} .cfgname')
    pg.click(f'.menu button:has(b:text-is("{label}"))')
    pg.wait_for_timeout(300)


def main():
    api('POST', '/api/session/stop', {})
    with sync_playwright() as p:
        br, pg, errors = open_app(p)
        pg.click('#leftTabs button[data-tab="map"]')
        pg.click('.mapcard:has-text("좁은 문")')
        wait(pg, lambda d: d.get('map') == 'synth_narrow' and d.get('mapLoaded'), 10, 'map selected')
        pg.click('.scen:has-text("nominal / 000")')
        pg.click('.seg.slots button[data-n="3"]')
        wait(pg, lambda d: d.get('nSlots') == 3, 5, 'three views')
        pick(pg, 0, '운영 설정')
        pick(pg, 1, '튜닝안 A (파라미터만)')
        pick(pg, 2, 'Regulated Pure Pursuit')
        names = [pg.inner_text(f'#vhead{i} .cfgname') for i in range(3)]
        assert '튜닝안 A' in names[1] and 'Regulated' in names[2], names
        print('ok  three slots:', [n.strip() for n in names])

        pg.click('#btnStart')
        wait(pg, lambda d: [s['status'] for s in d['slots']] == ['ready'] * 3, 90, 'all slots ready')
        print('ok  모두 시작 -> 3 slots ready')
        pg.click('#runbar button:has-text("동시 출발")')
        wait(pg, lambda d: all(s['nav'] in ('navigating', 'sending') for s in d['slots']), 20, 'all slots driving')
        print('ok  동시 출발 -> all driving')
        pg.wait_for_timeout(6000)
        pg.screenshot(path=OUT + '_driving.png')
        d = wait(pg, lambda d: all(s['result'] in ('succeeded', 'aborted') for s in d['slots']), 180, 'all slots finished')
        print('ok  finished:', [s['result'] for s in d['slots']])
        cells = pg.locator('#cTable td').all_inner_texts()
        assert any(c not in ('–', '') for c in cells[9:]), cells
        best = pg.locator('#cTable td.best').count()
        print(f'ok  comparison table filled ({best} best cells marked)')
        pg.screenshot(path=OUT + '_done.png')

        pg.click('#vhead1 button[title="끄기"]')
        wait(pg, lambda d: d['slots'][1]['status'] == 'stopped' and d['slots'][0]['status'] == 'ready', 20, 'slot B stopped alone')
        print('ok  slot B stopped, A and C still running')
        pg.click('#vhead1 button[title="시작"]')
        wait(pg, lambda d: d['slots'][1]['status'] == 'ready', 60, 'slot B restarted')
        params = api('GET', '/api/session/params.yaml?slot=1')
        assert 'controller_server' in params
        print('ok  slot B restarted on its own')
        pg.click('#vhead2 button[title^="이 슬롯만"]')
        wait(pg, lambda d: d['slots'][2]['nav'] in ('navigating', 'sending') and d['slots'][0]['nav'] not in ('navigating', 'sending'), 15, 'slot C drives alone')
        print('ok  slot C drives alone')
        pg.click('#btnStop')
        wait(pg, lambda d: all(s['status'] == 'stopped' for s in d['slots']), 30, 'all stopped')
        print('ok  모두 정지')
        pg.click('.seg.slots button[data-n="1"]')
        wait(pg, lambda d: d.get('nSlots') == 1, 5, 'back to one view')
        br.close()
    print('page errors:', errors or 'none')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
