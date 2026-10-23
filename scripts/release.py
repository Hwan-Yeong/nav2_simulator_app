#!/usr/bin/env python3
"""Prepare a release: bump the version everywhere and close the CHANGELOG section.

  python3 scripts/release.py 0.3.0

1. moves the CHANGELOG [Unreleased] entries under "## [0.3.0] - <today>" and updates the compare links
2. sets navstudio/__init__.py __version__ and the docker/compose.yml image tag
3. prints what is left (guide rebuild, checks, commit, tag, push) — see docs/RELEASE.md
"""
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'https://github.com/Hwan-Yeong/nav2_simulator_app'


def path(*p):
    return os.path.join(ROOT, *p)


def main(new):
    if not re.fullmatch(r'\d+\.\d+\.\d+', new):
        sys.exit('버전은 MAJOR.MINOR.PATCH 형식이어야 합니다 (예: 0.3.0)')
    init = open(path('navstudio', '__init__.py')).read()
    old = re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1)
    if tuple(map(int, new.split('.'))) <= tuple(map(int, old.split('.'))):
        sys.exit(f'새 버전 {new} 은 현재 버전 {old} 보다 커야 합니다')
    cl = open(path('CHANGELOG.md')).read()
    head, rest = cl.split('## [Unreleased]', 1)
    body, tail = (rest.split('\n## [', 1) + [''])[:2]
    if not body.strip():
        sys.exit('CHANGELOG.md 의 [Unreleased] 가 비어 있습니다. 이번 버전의 변경 사항을 먼저 적으세요.')
    today = datetime.date.today().isoformat()
    section = f'## [Unreleased]\n\n## [{new}] - {today}\n\n{body.strip()}\n'
    cl = f'{head}{section}\n## [{tail}' if tail else f'{head}{section}'
    cl = re.sub(r'^\[Unreleased\]: .*$', f'[Unreleased]: {URL}/compare/v{new}...HEAD\n[{new}]: {URL}/compare/v{old}...v{new}', cl, count=1, flags=re.M)
    open(path('CHANGELOG.md'), 'w').write(cl)
    open(path('navstudio', '__init__.py'), 'w').write(init.replace(f'"{old}"', f'"{new}"'))
    comp = open(path('docker', 'compose.yml')).read()
    open(path('docker', 'compose.yml'), 'w').write(re.sub(r'(everybot/navstudio:)\S+', rf'\g<1>{new}', comp))
    print(f'{old} -> {new}  (CHANGELOG, navstudio/__init__.py, docker/compose.yml)')
    print(f'''다음 단계 (docs/RELEASE.md):
  1. UI 가 바뀌었으면 스크린샷·데모 다시 찍기:  python3 scripts/capture_guide.py all && python3 scripts/capture_demo.py
  2. 사용 가이드 다시 만들기:                  python3 docs/guide/build_guide.py
  3. 검사·테스트:                              python3 scripts/check.py --release && python3 -m pytest
                                               python3 tests/e2e/single_flow.py && python3 tests/e2e/compare_flow.py && python3 tests/e2e/manage_flow.py && python3 tests/e2e/sensor_flow.py
  4. git commit -am "Release {new}" && git tag -a v{new} -m "Nav Studio {new}" && git push --follow-tags''')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
