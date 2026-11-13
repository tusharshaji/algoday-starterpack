"""Picks the order book implementation.

ALGOMARKET_ENGINE=python forces the reference book (book.py), =native
requires the C++ engine, anything else (default "auto") uses the C++ engine
when it loads and falls back to the reference book.

NAME is "native" or "python". NATIVE_ERROR says why the C++ engine is not in
use (None when it is).
"""
import os

from . import book

NAME = "python"
OrderBook = book.OrderBook
NATIVE_ERROR = None

_choice = os.environ.get("ALGOMARKET_ENGINE", "auto").strip().lower()
if _choice == "python":
    NATIVE_ERROR = "ALGOMARKET_ENGINE=python"
else:
    try:
        from .native import OrderBook as _NativeOrderBook
        OrderBook = _NativeOrderBook
        NAME = "native"
    except ImportError as exc:
        if _choice == "native":
            raise
        NATIVE_ERROR = str(exc)
