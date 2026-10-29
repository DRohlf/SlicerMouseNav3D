import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "MouseNav3D"))
from MouseNav3DLib import settings


class FakeStore(dict):
    def value(self, key, default=None):
        return dict.get(self, key, default)

    def setValue(self, key, value):
        self[key] = value


@pytest.fixture()
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(settings, "_store", lambda: s)
    return s


def test_prefix_and_default(store):
    assert settings.get("limb_side", "right") == "right"
    settings.set("limb_side", "left")
    assert store == {"MouseNav3D/limb_side": "left"}
    assert settings.get("limb_side", "right") == "left"


def test_default_for_missing_and_none(store):
    assert settings.get("enabled", True) is True
    store["MouseNav3D/enabled"] = None
    assert settings.get("enabled", True) is True


def test_coerces_to_default_type(store):
    store["MouseNav3D/enabled"] = "false"
    assert settings.get("enabled", True) is False
    store["MouseNav3D/fallback/speed"] = "2.5"
    assert settings.get("fallback/speed", 1.0) == 2.5
    store["MouseNav3D/n"] = "3"
    assert settings.get("n", 0) == 3
    store["MouseNav3D/fallback/speed"] = "garbage"
    assert settings.get("fallback/speed", 1.0) == 1.0


def test_known_keys_listed():
    assert {"enabled", "limb_side"} <= set(settings.DEFAULTS)


def test_fallback_defaults(store):
    s = settings.fallback_axis_settings()
    assert s.speed == 1.0 and s.dead_zone == 0.04
    assert all(v is False for v in s.reverse.values()) and set(s.reverse) == {"tx", "ty", "tz", "rx", "ry", "rz"}
    assert all(v == 1.0 for v in s.sensitivity.values())
    assert settings.fallback_rotation_lock() is False


def test_fallback_keys(store):
    store["MouseNav3D/fallback/reverse_rx"] = "true"
    store["MouseNav3D/fallback/sensitivity_ty"] = "2.5"
    store["MouseNav3D/fallback/speed"] = "1.5"
    store["MouseNav3D/fallback/dead_zone"] = "0.1"
    s = settings.fallback_axis_settings()
    assert s.reverse["rx"] is True and s.reverse["ry"] is False
    assert s.sensitivity["ty"] == 2.5 and s.speed == 1.5 and s.dead_zone == 0.1
    settings.set_fallback_rotation_lock(True)
    assert store["MouseNav3D/fallback/rotation_lock"] is True
    store["MouseNav3D/fallback/rotation_lock"] = "true"
    assert settings.fallback_rotation_lock() is True
