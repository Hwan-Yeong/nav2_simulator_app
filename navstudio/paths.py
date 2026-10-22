"""Locations of bundled data and the per-user workspace (~/.navstudio, override with NAVSTUDIO_HOME)."""
import os

PKG = os.path.dirname(os.path.realpath(__file__))
HOME = os.environ.get('NAVSTUDIO_HOME', os.path.expanduser('~/.navstudio'))


def data(*p):
    return os.path.join(PKG, 'data', *p)


def user(*p):
    return os.path.join(HOME, *p)


def web(*p):
    return os.path.join(PKG, 'web', *p)


def ensure_user_dirs():
    for d in ('robots', 'maps', 'runs', 'sessions', 'presets'):
        os.makedirs(user(d), exist_ok=True)
