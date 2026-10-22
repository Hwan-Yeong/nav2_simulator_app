#!/usr/bin/env python3
"""Repository checks — run before every commit (git hook) and in CI.

  python3 scripts/check.py                 all checks except release-only ones
  python3 scripts/check.py --quick         fast subset for the pre-commit hook
  python3 scripts/check.py --release [--tag v0.2.0]
                                           + CHANGELOG entry for this version, tag = version, guide PDF built from the
                                             current sources (docs/guide/guide.stamp.json)

Exit code 0 when everything passes. No ROS needed.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_URL = 'https://github.com/Hwan-Yeong/nav2_simulator_app'
# names that must not appear in this public repository: the previous contractor / project, the field-site maps
# (kept out of the public repo) and private network addresses. Matched case-insensitively.
BANNED = [r'sk' + r'ix', r'sk' + r'mg', r'namu' + r'hx', r'wa' + r'vem', r'cla' + r'bil', r'\bA1_', r'\bwm_', r'air' + r'bot',
          r'cafe' + r'teria', r'pyeong' + r'chang', r'rd_' + r'center', r'\bai_' + r'lab\b', r'\bsw_' + r'office\b', r'site_' + r'small',
          r'site_' + r'corridor', r'192\.168\.\d+\.\d+', r'/home/(?!everybot\b)[a-z][\w.-]*/']
TEXT_EXT = ('.py', '.js', '.css', '.html', '.md', '.yaml', '.yml', '.json', '.toml', '.xml', '.txt', '.cpp', '.hpp', '.h',
            '.cfg', '.sh', '.launch', '.svg', '')

failures, notes = [], []


def fail(msg):
    failures.append(msg)


def files():
    """Tracked files (git), or every file when not in a git checkout."""
    try:
        out = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [f for f in out.splitlines() if os.path.exists(os.path.join(ROOT, f))]
    except Exception:
        return [os.path.relpath(os.path.join(d, f), ROOT) for d, _, fs in os.walk(ROOT) if '.git' not in d for f in fs]


def read(rel):
    return open(os.path.join(ROOT, rel), encoding='utf-8').read()


def version():
    return re.search(r'__version__\s*=\s*"([^"]+)"', read('navstudio/__init__.py')).group(1)


# ---------------------------------------------------------------- checks
def check_version():
    v = version()
    if not re.fullmatch(r'\d+\.\d+\.\d+', v):
        fail(f'navstudio/__init__.py: version {v!r} is not MAJOR.MINOR.PATCH')
    m = re.search(r'image:\s*everybot/navstudio:(\S+)', read('docker/compose.yml'))
    if not m or m.group(1) != v:
        fail(f'docker/compose.yml image tag {m and m.group(1)!r} != version {v}')
    if 'version = ' in read('pyproject.toml').split('[project]')[1].split('[')[0]:
        fail('pyproject.toml must not hard-code the version (dynamic, from navstudio.__version__)')
    cl = read('CHANGELOG.md')
    if '## [Unreleased]' not in cl:
        fail('CHANGELOG.md: missing "## [Unreleased]" section')
    released = re.findall(r'^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$', cl, re.M)
    if not released:
        fail('CHANGELOG.md: no released version section')
    elif tuple(map(int, released[0][0].split('.'))) > tuple(map(int, v.split('.'))):
        fail(f'CHANGELOG.md: newest section {released[0][0]} is ahead of the package version {v}')
    for ver, _ in released:
        if f'[{ver}]: ' not in cl:
            fail(f'CHANGELOG.md: missing link reference for [{ver}]')
    return v, cl, released


def check_banned(fs):
    pat = re.compile('|'.join(BANNED), re.I)
    for f in fs:
        if f == 'scripts/check.py' or os.path.splitext(f)[1].lower() not in TEXT_EXT or f.endswith('LICENSE'):
            continue
        try:
            for n, line in enumerate(read(f).splitlines(), 1):
                m = pat.search(line)
                if m:
                    fail(f'{f}:{n}: banned name {m.group(0)!r}')
        except UnicodeDecodeError:
            pass


def check_yaml(fs):
    import yaml

    class Unique(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = set()
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in keys:
                raise yaml.constructor.ConstructorError(None, None, f'duplicate key {key!r}', k.start_mark)
            keys.add(key)
        return loader.construct_mapping(node, deep)
    Unique.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    for f in fs:
        if f.endswith(('.yaml', '.yml')):
            try:
                yaml.load(read(f), Loader=Unique)
            except yaml.YAMLError as e:
                fail(f'{f}: {str(e).splitlines()[0]} {getattr(e, "problem_mark", "")}')


def check_python(fs):
    for f in fs:
        if f.endswith('.py'):
            try:
                compile(read(f), f, 'exec')
            except SyntaxError as e:
                fail(f'{f}:{e.lineno}: {e.msg}')


def check_js(fs):
    node = shutil.which('node')
    if not node:
        notes.append('node not found: JavaScript syntax not checked')
        return
    with tempfile.TemporaryDirectory() as tmp:
        for f in fs:
            if f.endswith('.js') and '/vendor/' not in f:
                m = os.path.join(tmp, os.path.basename(f) + '.mjs')
                shutil.copy(os.path.join(ROOT, f), m)
                r = subprocess.run([node, '--check', m], capture_output=True, text=True)
                if r.returncode:
                    fail(f'{f}: ' + ' '.join(r.stderr.strip().splitlines()[-2:]))


def check_links(fs):
    for f in fs:
        if not f.endswith('.md'):
            continue
        text = read(f)
        for target in re.findall(r'\]\(([^)\s]+)\)', text) + re.findall(r'src="([^"]+)"', text) + re.findall(r'href="([^"]+)"', text):
            if re.match(r'(https?:|mailto:|#)', target):
                continue
            p = os.path.normpath(os.path.join(ROOT, os.path.dirname(f), target.split('#')[0]))
            if not os.path.exists(p):
                fail(f'{f}: broken link {target}')


def check_data():
    import yaml
    data = os.path.join(ROOT, 'navstudio', 'data')
    index = yaml.safe_load(open(os.path.join(data, 'maps', 'index.yaml'))) or {}
    for d in sorted(glob.glob(os.path.join(data, 'maps', '*', 'map.yaml'))):
        mid = os.path.basename(os.path.dirname(d))
        meta = yaml.safe_load(open(d))
        if not os.path.exists(os.path.join(os.path.dirname(d), meta['image'])):
            fail(f'map {mid}: image {meta["image"]} missing')
        if mid not in index:
            fail(f'map {mid}: no entry in data/maps/index.yaml')
        if not os.path.exists(os.path.join(data, 'scenarios', mid + '.json')):
            fail(f'map {mid}: no data/scenarios/{mid}.json')
    for mid in index:
        if not os.path.exists(os.path.join(data, 'maps', mid, 'map.yaml')):
            fail(f'data/maps/index.yaml: {mid} has no map directory')
    stacks = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(data, 'stacks', '*.yaml'))}
    for f in glob.glob(os.path.join(data, 'presets', '*.yaml')):
        p = yaml.safe_load(open(f))
        for st in p.get('stacks') or [p.get('stack', 'prod')]:
            if st not in stacks:
                fail(f'{os.path.relpath(f, ROOT)}: unknown stack {st}')
    # every source a plugin's CMakeLists names must be in the repository (a stray ignore rule once dropped src/)
    for cm in glob.glob(os.path.join(data, 'plugins_src', '*', 'CMakeLists.txt')):
        for src in set(re.findall(r'\b((?:src|test)/[\w/.-]+\.(?:cpp|cc|c|hpp|h))\b', open(cm).read())):
            if not os.path.exists(os.path.join(os.path.dirname(cm), src)):
                fail(f'{os.path.relpath(cm, ROOT)}: source {src} is missing')
    ids = [p['id'] for p in yaml.safe_load(open(os.path.join(data, 'param_schema.yaml')))['params']]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        fail(f'param_schema.yaml: duplicate ids {sorted(dup)}')


def guide_inputs_hash():
    h = hashlib.sha256()
    for f in ['docs/guide/build_guide.py', 'navstudio/__init__.py', 'CHANGELOG.md'] + sorted(
            os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, 'docs', 'guide', 'img', '*'))):
        h.update(f.encode())
        h.update(open(os.path.join(ROOT, f), 'rb').read())
    return h.hexdigest()


def check_release(v, cl, released, tag):
    if not released or released[0][0] != v:
        fail(f'CHANGELOG.md: the newest section must be [{v}] for a release (found {released[0][0] if released else None})')
    unrel = cl.split('## [Unreleased]', 1)[1].split('\n## [', 1)[0].strip()
    if unrel:
        fail('CHANGELOG.md: [Unreleased] must be empty in a release (move its entries under the version)')
    if tag and tag != 'v' + v:
        fail(f'tag {tag} does not match version v{v}')
    stamp_f = os.path.join(ROOT, 'docs', 'guide', 'guide.stamp.json')
    if not os.path.exists(stamp_f):
        fail('docs/guide/guide.stamp.json missing: run python3 docs/guide/build_guide.py')
    else:
        st = json.load(open(stamp_f))
        if st.get('version') != v:
            fail(f'user guide was built for {st.get("version")}, not {v}: run python3 docs/guide/build_guide.py')
        elif st.get('inputs') != guide_inputs_hash():
            fail('user guide is older than its sources (build_guide.py, screenshots, CHANGELOG): run python3 docs/guide/build_guide.py')
        if st.get('overflow'):
            fail(f'user guide pages overflow: {st["overflow"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='pre-commit subset')
    ap.add_argument('--release', action='store_true')
    ap.add_argument('--tag', help='release tag to compare with the version (e.g. v0.2.0)')
    a = ap.parse_args()
    fs = files()
    v, cl, released = check_version()
    check_banned(fs)
    check_yaml(fs)
    check_python(fs)
    check_js(fs)
    if not a.quick:
        check_links(fs)
        check_data()
    if a.release:
        check_release(v, cl, released, a.tag)
    for n in notes:
        print('note:', n)
    if failures:
        print(f'{len(failures)} problem(s):')
        for f in failures:
            print('  ' + f)
        return 1
    print(f'ok  navstudio {v}' + (' (release)' if a.release else '') + f' · {len(fs)} files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
