"""Unit tests run without ROS: every test gets an empty NAVSTUDIO_HOME (set before navstudio is imported)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ['NAVSTUDIO_HOME'] = tempfile.mkdtemp(prefix='navstudio-test-')

import pytest  # noqa: E402

from navstudio import maps, paths  # noqa: E402


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """A fresh user workspace per test (paths.HOME is read at call time through paths.user)."""
    monkeypatch.setattr(paths, 'HOME', str(tmp_path))
    paths.ensure_user_dirs()
    maps._cache.clear()
    maps.grid_png.cache_clear()
    maps.thumb_png.cache_clear()
    return tmp_path
