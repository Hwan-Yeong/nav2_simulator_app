"""navstudio command line.

  navstudio                 start the app (same as `navstudio run`)
  navstudio run [--port 8765] [--host 127.0.0.1] [--domain 91] [--no-browser]
  navstudio doctor          check ROS 2 / Nav2 / plugins / Python packages
  navstudio build-plugins   build the Everybot planner/BT plugins into ~/.navstudio/overlay
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

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


def cmd_run(a):
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
    a = ap.parse_args(argv)
    if a.cmd == 'doctor':
        return cmd_doctor(a)
    if a.cmd == 'build-plugins':
        return cmd_build_plugins(a)
    return cmd_run(a)


if __name__ == '__main__':
    sys.exit(main())
