#!/usr/bin/env python3
"""Open the Nav Studio UI in headless Chromium (real time), report console errors + debug state, save a screenshot.

python3 tests/ui_probe.py [--url http://localhost:8765/?debug#sim] [--wait 6] [--out shot.png] [--dark] [--size 1500x900]
         [--click "css selector" ...] [--eval "js expression"]
"""
import argparse
import json

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost:8765/?debug#sim')
    ap.add_argument('--wait', type=float, default=6)
    ap.add_argument('--out', default='/tmp/ns_probe.png')
    ap.add_argument('--dark', action='store_true')
    ap.add_argument('--size', default='1500x900')
    ap.add_argument('--click', action='append', default=[])
    ap.add_argument('--eval', action='append', default=[])
    a = ap.parse_args()
    w, h = map(int, a.size.split('x'))
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': w, 'height': h}, color_scheme='dark' if a.dark else 'light')
        errs = []
        pg.on('console', lambda m: errs.append(f'{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: errs.append(f'pageerror: {e}'))
        pg.goto(a.url)
        pg.wait_for_timeout(a.wait * 1000)
        for sel in a.click:
            if sel.startswith('wait:'):
                pg.wait_for_timeout(float(sel[5:]) * 1000)
                continue
            pg.click(sel)
            pg.wait_for_timeout(700)
        for ex in a.eval:
            print('eval:', json.dumps(pg.evaluate(ex), ensure_ascii=False)[:2000])
        dbg = pg.evaluate("document.getElementById('nsdebug') ? document.getElementById('nsdebug').textContent : null")
        print('debug:', dbg)
        print('console:', json.dumps(errs, ensure_ascii=False, indent=1)[:3000])
        pg.screenshot(path=a.out)
        b.close()


if __name__ == '__main__':
    main()
