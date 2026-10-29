"""QSettings wrapper with the prefix "MouseNav3D/". qt is imported inside `_store` only.

Keys: `enabled`, `limb_side` ("right" default). The built-in reader (fallback mode) keeps its own keys under
`fallback/` (reverse_<axis>, sensitivity_<axis>, speed, dead_zone, rotation_lock) through the same get/set.
"""
PREFIX = "MouseNav3D/"
DEFAULTS = {"enabled": True, "limb_side": "right"}


def _store():
    import qt
    return qt.QSettings()


def _coerce(value, default):
    """QSettings may hand back strings (ini backends); convert to the type of `default`. Bad values give `default`."""
    if default is None or isinstance(value, type(default)) and not isinstance(default, bool):
        return value
    try:
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes")
            return bool(value)
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
    except (TypeError, ValueError):
        return default
    return value


def get(key, default=None):
    if default is None:
        default = DEFAULTS.get(key)
    value = _store().value(PREFIX + key, default)
    if value is None:
        return default
    return _coerce(value, default)


def set(key, value):  # noqa: A001 - the module API is settings.set
    _store().setValue(PREFIX + key, value)


# --- fallback mode: the built-in reader's settings live in Slicer (the driver's live in 3Dconnexion's app):
# fallback/reverse_<axis>, fallback/sensitivity_<axis>, fallback/speed, fallback/dead_zone, fallback/rotation_lock -
def fallback_axis_settings():
    """The fallback reader's per-axis settings as a motion.AxisSettings (defaults: no reverse, sensitivity 1.0, speed
    1.0, the standard dead zone)."""
    from .fallback import motion
    return motion.AxisSettings(
        reverse={a: bool(get(f"fallback/reverse_{a}", False)) for a in motion.AXES},
        sensitivity={a: float(get(f"fallback/sensitivity_{a}", 1.0)) for a in motion.AXES},
        speed=float(get("fallback/speed", 1.0)),
        dead_zone=float(get("fallback/dead_zone", motion.DEAD_ZONE)))


def fallback_rotation_lock():
    return bool(get("fallback/rotation_lock", False))


def set_fallback_rotation_lock(value):
    set("fallback/rotation_lock", bool(value))
