#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""Sina KLC payload decoder with reusable MiniRacer contexts.

The KLC decoder is expensive to initialize because every context must evaluate
the large ``hk_js_decode`` script.  Reusing warmed contexts avoids repeated V8
initialization and keeps macOS stable without forcing all decode work through a
single global lock.
"""

from __future__ import annotations

import os
import platform
from queue import LifoQueue
import threading

from akshare.stock.cons import hk_js_decode


def _import_mini_racer():
    try:
        from py_mini_racer import MiniRacer
    except ImportError:  # pragma: no cover - non-Linux dependency name
        from mini_racer import MiniRacer
    return MiniRacer


def _default_pool_size() -> int:
    env_value = os.getenv("AKSHARE_SINA_KLC_DECODER_POOL_SIZE")
    if env_value:
        return max(int(env_value), 1)

    cpu_count = os.cpu_count() or 1
    system_name = platform.system().lower()
    if system_name == "darwin":
        return max(1, min(cpu_count, 4))
    return max(1, min(cpu_count, 8))


class _MiniRacerContextPool:
    """Small thread-safe pool of warmed MiniRacer contexts."""

    def __init__(self, size: int | None = None):
        self._size = max(int(size or _default_pool_size()), 1)
        self._contexts = LifoQueue(maxsize=self._size)
        self._initialized = False
        self._init_lock = threading.Lock()

    def _create_context(self):
        MiniRacer = _import_mini_racer()
        context = MiniRacer()
        context.eval(hk_js_decode)
        return context

    def _ensure_initialized(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            for _ in range(self._size):
                self._contexts.put(self._create_context())
            self._initialized = True

    def call(self, function_name: str, *args):
        self._ensure_initialized()
        context = self._contexts.get()
        try:
            return context.call(function_name, *args)
        finally:
            self._contexts.put(context)


_KLC_DECODER_POOL = _MiniRacerContextPool()


def decode_sina_klc_payload(encoded_payload: str):
    """Decode a Sina KLC encoded payload into Python objects."""
    return _KLC_DECODER_POOL.call("d", encoded_payload)
