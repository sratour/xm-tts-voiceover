# -*- coding: utf-8 -*-
"""Provider registry.

Add a backend by writing a module that subclasses `Provider` and registering it
in `_load()` below.
"""

import os

from .base import (  # noqa: F401  (re-exported for convenience)
    TICKS_PER_SECOND,
    Provider,
    ProviderError,
    parse_hz,
    parse_percent,
    require_ffmpeg,
)

DEFAULT_PROVIDER = "edge"

#: user-friendly spellings -> canonical provider name
ALIASES = {
    "openai-compatible": "openai",
    "openai_compat": "openai",
    "oai": "openai",
    "os": "system",
    "native": "system",
    "sapi": "system",
    "say": "system",
    "espeak": "system",
    "microsoft": "edge",
    "msedge": "edge",
}

_REGISTRY = {}
_LOADED = False


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


def _load():
    global _LOADED
    if _LOADED:
        return
    from .edge import EdgeProvider
    from .openai_compat import OpenAICompatProvider
    from .system import SystemProvider

    register(EdgeProvider)
    register(OpenAICompatProvider)
    register(SystemProvider)
    _LOADED = True


def names():
    _load()
    return sorted(_REGISTRY)


def canonical(name):
    """Resolve an alias (or None -> $TTS_PROVIDER -> default) to a provider name."""
    key = (name or os.environ.get("TTS_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    return ALIASES.get(key, key)


def get(name=None, options=None):
    """Instantiate a provider. `options` carries CLI flags such as api_key."""
    _load()
    key = canonical(name)
    if key not in _REGISTRY:
        raise ProviderError(
            "未知后端 %r。可用后端：%s" % (key, "、".join(names()))
        )
    return _REGISTRY[key](options)


def describe_all():
    """Return [(name, label, ok, reason, needs_ffmpeg)] for `doctor`."""
    _load()
    rows = []
    for key in names():
        instance = _REGISTRY[key]()
        try:
            ok, reason = instance.available()
        except Exception as exc:  # a broken provider must not break doctor
            ok, reason = False, "%s: %s" % (type(exc).__name__, exc)
        rows.append((key, instance.label, ok, reason, instance.needs_ffmpeg))
    return rows
