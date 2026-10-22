"""navstudio command line.

  navstudio                 start the app (same as `navstudio run`)
  navstudio run [--port 8765] [--host 127.0.0.1] [--domain 91] [--no-browser]
  navstudio doctor          check ROS 2 / Nav2 / plugins / Python packages
  navstudio build-plugins   build the Everybot planner/BT plugins into ~/.navstudio/overlay
  navstudio maps list | import FILE... [--name N] | export ID [-o FILE] | rename ID NAME | remove ID
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

from . import __version__, env as envlib, paths


def _open_browser(url):
    def go():
        time.sleep(1.5)
        try:
            if 'microsoft' in open('/proc/version').read().lower() and shutil.which('cmd.exe'):
                subprocess.Popen(['cmd.exe', '/c', 'start', '', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        except OSError:
            pass
        import webbrowser
        webbrowser.open(url)
    threading.Thread(target=go, daemon=True).start()


def check_domain(domain):
    """Live slots use domain .. domain+3; benchmark and tuning workers use 150 and up."""
    from .stack import MAX_SLOTS
    last = domain + MAX_SLOTS - 1
    if domain < 0 or last > 232 or (domain <= 199 and last >= 150):
        sys.exit(f'--domain {domain}: 실시간 슬롯이 ROS_DOMAIN_ID {domain}~{last} 를 씁니다. '
                 f'0~{150 - MAX_SLOTS} 또는 200~{233 - MAX_SLOTS} 중에서 고르세요 (150~199 는 벤치마크·튜닝용).')


def cmd_run(a):
    check_domain(a.domain)
    envlib.reexec_in_clean_env(a.domain)
    import uvicorn
    from . import server
    app = server.create(dict(os.environ), a.domain)
    url = f'http://{"localhost" if a.host in ("0.0.0.0", "127.0.0.1") else a.host}:{a.port}'
    print(f'Nav Studio {__version__}  →  {url}   (ROS_DOMAIN_ID={a.domain}, localhost only)', flush=True)
    if not a.no_browser:
        _open_browser(url)
    try:
        uvicorn.run(app, host=a.host, port=a.port, log_level='warning')
    finally:
        server.shutdown()


def cmd_doctor(a):
    envlib.reexec_in_clean_env(a.domain)
    ok = True

    def line(good, what, hint=''):
        nonlocal ok
        ok &= good
        print(f"  [{'OK' if good else '!!'}] {what}" + (f'  — {hint}' if hint and not good else ''))

    print(f'Nav Studio {__version__}')
    line(os.path.exists(envlib.ros_setup()), f'ROS 2 {envlib.ROS_DISTRO} ({envlib.ros_setup()})', 'ROS 2 를 설치하세요')
    from . import paramgen
    have = paramgen.available_packages()
    for p in ('nav2_controller', 'nav2_planner', 'nav2_bt_navigator', 'nav2_mppi_controller', 'nav2_smac_planner',
              'nav2_regulated_pure_pursuit_controller', 'nav2_navfn_planner'):
        line(p in have, p, 'sudo apt install ros-humble-navigation2')
    for p in paramgen.CUSTOM_PLUGINS:
        if p in have:
            line(True, p)
        else:
            print(f'  [--] {p} 없음 — navstudio build-plugins 로 빌드하세요 (없으면 표준 Nav2 플래너로 대체됩니다)')
    for m in ('fastapi', 'uvicorn', 'numpy', 'scipy', 'yaml', 'PIL', 'psutil'):
        try:
            __import__(m)
            line(True, f'python: {m}')
        except ImportError:
            line(False, f'python: {m}', 'pip install navstudio 로 설치')
    try:
        __import__('optuna')
        line(True, 'python: optuna (자동 튜닝)')
    except ImportError:
        print('  [--] python: optuna 없음 — 자동 튜닝을 쓰려면 pip install optuna')
    print('모두 정상' if ok else '위 항목을 확인하세요')
    return 0 if ok else 1


def cmd_build_plugins(a):
    src = paths.data('plugins_src')
    if not os.path.isdir(src):
        sys.exit('플러그인 소스를 찾지 못했습니다')
    ws = paths.user('overlay')
    shutil.rmtree(os.path.join(ws, 'src'), ignore_errors=True)
    shutil.copytree(src, os.path.join(ws, 'src'))
    script = (f'source {envlib.ros_setup()} && cd {ws} && colcon build '
              f'--cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF')
    clean = {k: os.environ[k] for k in envlib.KEEP if k in os.environ}
    clean['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    print(f'빌드: {ws}')
    r = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], env=clean)
    if r.returncode == 0:
        print('완료. 다음 실행부터 Everybot 플래너/BT 플러그인을 사용합니다.')
    return r.returncode


def cmd_maps(a):
    from . import maps
    paths.ensure_user_dirs()
    if a.action == 'list':
        for m in maps.list_maps():
            print(f"{m['id']:24} {('기본 · ' if m['builtin'] else '') + m['group']:8} {m['name']}  ({m.get('width_m', '?')} × {m.get('height_m', '?')} m"
                  f"{', 시나리오 ' + str(m['scenarios']) if m['scenarios'] else ''})")
        return 0
    if a.action == 'import':
        files = []
        for f in a.args:
            if os.path.isdir(f):   # a folder is read like a zip: one sub-folder (or the folder itself) per map
                top = os.path.abspath(f)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as z:
                    for root, _, names in os.walk(top):
                        for n in names:
                            z.write(os.path.join(root, n), os.path.relpath(os.path.join(root, n), os.path.dirname(top)))
                files.append((os.path.basename(top) + '.zip', buf.getvalue()))
            else:
                files.append((os.path.basename(f), open(f, 'rb').read()))
        for mid, name in maps.import_files(files, a.name):
            print(f'추가: {mid}  ({name})')
        return 0
    if not a.args:
        sys.exit('맵 id 를 지정하세요')
    mid = a.args[0]
    if a.action == 'export':
        out = a.output or f'{mid}.zip'
        open(out, 'wb').write(maps.export_zip(mid))
        print(out)
    elif a.action == 'rename':
        if len(a.args) < 2:
            sys.exit('새 이름을 지정하세요')
        maps.rename(mid, ' '.join(a.args[1:]))
    elif a.action == 'remove':
        try:
            maps.delete(mid)
        except KeyError:
            sys.exit(f'{mid}: 직접 올린 맵만 지울 수 있습니다')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='navstudio', description='Nav Studio — 2D Nav2 simulation & tuning')
    ap.add_argument('--version', action='version', version=__version__)
    sub = ap.add_subparsers(dest='cmd')
    r = sub.add_parser('run', help='앱 실행')
    for p in (ap, r):
        p.add_argument('--port', type=int, default=8765)
        p.add_argument('--host', default='127.0.0.1')
        p.add_argument('--domain', type=int, default=int(os.environ.get('NAVSTUDIO_DOMAIN', 91)),
                       help='ROS_DOMAIN_ID for the live session (0-101 or 215-232 recommended)')
        p.add_argument('--no-browser', action='store_true')
    d = sub.add_parser('doctor', help='설치 상태 점검')
    d.add_argument('--domain', type=int, default=91)
    sub.add_parser('build-plugins', help='Everybot 플러그인 빌드')
    m = sub.add_parser('maps', help='맵 목록 · 가져오기 · 내보내기 · 이름 바꾸기 · 지우기')
    m.add_argument('action', choices=['list', 'import', 'export', 'rename', 'remove'])
    m.add_argument('args', nargs='*', help='import: 맵 zip · YAML+이미지 · 폴더, 그 밖: 맵 id')
    m.add_argument('--name', help='import: 맵 하나를 가져올 때 표시 이름')
    m.add_argument('-o', '--output', help='export: 저장할 zip 파일')
    a = ap.parse_args(argv)
    if a.cmd == 'maps':
        return cmd_maps(a)
    if a.cmd == 'doctor':
        return cmd_doctor(a)
    if a.cmd == 'build-plugins':
        return cmd_build_plugins(a)
    return cmd_run(a)


if __name__ == '__main__':
    sys.exit(main())
