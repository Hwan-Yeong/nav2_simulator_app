"""A clean, isolated ROS 2 environment for Nav Studio processes.

Users often source several overlays (other Nav2 builds, robot workspaces) and DDS profiles that point at a real
robot. Nav Studio runs everything from a minimal environment: /opt/ros/<distro> + the Nav Studio plugin overlay,
ROS_LOCALHOST_ONLY=1 and its own ROS_DOMAIN_ID, so a simulation never talks to (or is disturbed by) a robot.
"""
import os
import subprocess
import sys

from . import paths

ROS_DISTRO = os.environ.get('NAVSTUDIO_ROS_DISTRO', 'humble')
KEEP = ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TERM', 'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
        'PYTHONUSERBASE', 'NAVSTUDIO_HOME', 'NAVSTUDIO_ROS_DISTRO', 'NAVSTUDIO_OVERLAY')


def ros_setup():
    return f'/opt/ros/{ROS_DISTRO}/setup.bash'


def overlay_setup():
    o = os.environ.get('NAVSTUDIO_OVERLAY', paths.user('overlay', 'install', 'setup.bash'))
    return o if os.path.exists(o) else None


def pkg_root():
    """Directory that contains the navstudio package (for PYTHONPATH in dev / editable installs)."""
    return os.path.dirname(paths.PKG)


def clean_env(domain, inherit=False):
    """Environment dict with ROS sourced. inherit=True keeps the caller's environment as the starting point."""
    base = dict(os.environ) if inherit else {k: os.environ[k] for k in KEEP if k in os.environ}
    base.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
    if not inherit:
        base['PATH'] = '/usr/local/bin:/usr/bin:/bin'
    base.setdefault('LANG', 'C.UTF-8')
    script = f'source {ros_setup()}'
    ov = overlay_setup()
    if ov:
        script += f' && source {ov}'
    script += ' && env -0'
    out = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], env=base, capture_output=True, check=True).stdout
    env = dict(kv.split('=', 1) for kv in out.decode().split('\0') if '=' in kv)
    env.pop('FASTRTPS_DEFAULT_PROFILES_FILE', None)
    env.pop('CYCLONEDDS_URI', None)
    env.update(ROS_DOMAIN_ID=str(domain), ROS_LOCALHOST_ONLY='1', RCUTILS_COLORIZED_OUTPUT='0',
               PYTHONWARNINGS='ignore', PYTHONUNBUFFERED='1')
    env.setdefault('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp')
    pp = [pkg_root()] + [p for p in env.get('PYTHONPATH', '').split(':') if p]
    env['PYTHONPATH'] = ':'.join(dict.fromkeys(pp))
    if 'PYTHONUSERBASE' not in env:
        env['PYTHONUSERBASE'] = os.path.expanduser('~/.local')
    return env


def reexec_in_clean_env(domain, argv=None):
    """Replace this process with itself running inside clean_env (once)."""
    if os.environ.get('NAVSTUDIO_CLEAN_ENV') == '1':
        return
    if not os.path.exists(ros_setup()):
        sys.exit(f'ROS 2 {ROS_DISTRO} 를 찾을 수 없습니다 ({ros_setup()}). ROS 2 를 설치하거나 Docker 이미지를 사용하세요.')
    env = clean_env(domain)
    env['NAVSTUDIO_CLEAN_ENV'] = '1'
    argv = argv or sys.argv
    os.execve(sys.executable, [sys.executable, '-m', 'navstudio'] + argv[1:], env)
