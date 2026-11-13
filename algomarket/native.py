"""The C++ order book (market/engine/) with the same API and behaviour as book.py.

Build it from market/ with `python scripts/build_engine.py`. Importing this
module raises ImportError, with a message saying what to do, when the compiled
engine is missing, fails to load, is stale, or plays differently from book.py;
engine.py treats that as "use book.py instead" (engine.NATIVE_ERROR).
"""
import copy as _copy
import importlib.machinery as _machinery
import os as _os

from . import book as _book
from .book import BUY, IOC_REMAINDER, MAX_ORDER_ID, MAX_TRADER, MAX_VALUE, SELF_TRADE, SELL

_NATIVE_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_native")


def _load_failure(exc):
    """Why `from ._native import _algoengine` failed: no build for this Python,
    or a build that is there but won't load (truncated copy, antivirus...)."""
    try:
        names = sorted(_os.listdir(_NATIVE_DIR))
    except OSError:
        names = []
    candidates = ["_algoengine" + suffix for suffix in _machinery.EXTENSION_SUFFIXES]
    mine = [name for name in candidates if name in names]
    if mine:
        return (f"the C++ order book (algomarket/_native/{mine[0]}) failed to load ({exc}); "
                "copy it again or rebuild it: python scripts/build_engine.py")
    others = [name for name in names
              if name.startswith("_algoengine.") and name.endswith((".pyd", ".so"))]
    found = f" (found only {', '.join(others)}, built for another Python)" if others else ""
    return f"the C++ order book is not built for this Python{found}; run: python scripts/build_engine.py"


try:
    from ._native import _algoengine as _core
except ImportError as exc:
    raise ImportError(_load_failure(exc)) from exc

# Must match kEngineVersion in engine/src/python_module.cpp. A mismatch means
# an old build is lying around: refuse it rather than run stale semantics.
ENGINE_VERSION = 1
if getattr(_core, "ENGINE_VERSION", None) != ENGINE_VERSION:
    raise ImportError(
        f"the C++ order book build is stale (version {getattr(_core, 'ENGINE_VERSION', None)}, "
        f"need {ENGINE_VERSION}); run: python scripts/build_engine.py")

COMPILER = _core.COMPILER

__all__ = ["OrderBook", "BUY", "SELL", "SELF_TRADE", "IOC_REMAINDER",
           "MAX_ORDER_ID", "MAX_TRADER", "MAX_VALUE"]


class OrderBook(_core.OrderBook):
    """Limit order book in C++: same methods, results and errors as book.OrderBook.

    A Python subclass so instances take attributes like book.py's do, and so
    copies and pickles keep the subclass and its attributes. Copies are
    independent books (book.py's shallow copy would share its internal dicts).
    """

    def __copy__(self):
        new = type(self)()
        new._assign(self)
        new.__dict__.update(self.__dict__)
        return new

    def __deepcopy__(self, memo):
        new = type(self)()
        memo[id(self)] = new
        new._assign(self)
        for key, value in self.__dict__.items():
            new.__dict__[key] = _copy.deepcopy(value, memo)
        return new

    def __reduce__(self):
        # Resting orders in priority order plus pending events; see _load().
        return (_rebuild, (type(self), self._state(), self.__dict__ or None))


def _rebuild(cls, state, attrs):
    """Unpickles an OrderBook (state from OrderBook._state())."""
    book = cls()
    book._load(state)
    if attrs:
        book.__dict__.update(attrs)
    return book


# ------------------------------------------------------------- self-check
#
# book.py is the spec. At import, a short session touching every rule in
# DESIGN.md section 5 (the organisers' notes) is played on book.py and on
# this build (about 0.2 ms), and a build that answers any call differently
# is refused (book.py edited after the build, say). Whichever book a
# machine ends up with, it plays book.py's rules. The thorough check is
# tests/test_book_diff.py, which scripts/build_engine.py runs on every build.

_CHECK = (
    # Resting book: bids 9900 (1, then 2), 9800; asks 10100 (4, then 6), 10200.
    ("add", (1, 1, BUY, 9900, 5)), ("add", (2, 2, BUY, 9900, 3)), ("add", (3, 1, BUY, 9800, 4)),
    ("add", (4, 3, SELL, 10100, 2)), ("add", (6, 2, SELL, 10100, 1)), ("add", (5, 3, SELL, 10200, 6)),
    ("best_bid", ()), ("best_ask", ()), ("order_count", ()), ("order", (2,)), ("order", (99,)),
    ("depth", (BUY, 5)), ("depth", (SELL, 1)), ("depth", (SELL, 0)),
    ("open_orders", (1,)), ("open_qty", (1, BUY)), ("open_qty", (3, SELL)),
    # A sell sweeps 9900 in time order, then part of 9800, at the makers' prices.
    ("add", (7, 4, SELL, 9800, 10)), ("take_fills", ()), ("take_fills", ()), ("depth", (BUY, 5)),
    # Trader 3 buys through its own asks: 4 and 5 are cancelled (self-trade),
    # 6 trades, and the rest rests as a bid.
    ("add", (8, 3, BUY, 10200, 4)), ("take_fills", ()), ("take_cancels", ()), ("take_cancels", ()),
    ("best_bid", ()), ("best_ask", ()), ("open_orders", (3,)),
    # IOC: partly filled (remainder cancelled), nothing to hit, fully filled,
    # and a self-trade cancel before the remainder.
    ("add", (9, 2, SELL, 9800, 10, True)), ("add", (10, 2, BUY, 5000, 1, True)),
    ("add", (11, 1, SELL, 10500, 4)), ("add", (12, 2, BUY, 10500, 4, True)),
    ("add", (13, 1, SELL, 10600, 2)), ("add", (14, 1, BUY, 10700, 5, True)),
    ("take_fills", ()), ("take_cancels", ()), ("order_count", ()),
    # A self-trade cancel reports what was left of a partly filled order.
    ("add", (19, 5, BUY, 9500, 6)), ("add", (20, 6, SELL, 9500, 2)), ("add", (21, 5, SELL, 9400, 3)),
    ("take_fills", ()), ("take_cancels", ()), ("cancel", (21,)),
    # Ids: a filled or cancelled id can be reused, a resting one can't.
    ("add", (1, 4, BUY, 9000, 2)), ("add", (1, 4, BUY, 9000, 2)), ("cancel", (1,)), ("cancel", (1,)),
    ("add", (1, 4, SELL, 30000, 1)), ("cancel", (12345,)), ("add", (15, 4, BUY, 8000, 1)),
    ("add", (16, 4, SELL, 20000, 1)), ("cancel_all", (4,)), ("cancel_all", (4,)), ("cancel_all", (99,)),
    # Limits and validation.
    ("add", (MAX_ORDER_ID, MAX_TRADER, BUY, 1, MAX_VALUE)), ("add", (17, 0, SELL, MAX_VALUE, MAX_VALUE)),
    ("depth", (BUY, 10)), ("depth", (SELL, 10)), ("open_orders", (MAX_TRADER,)), ("open_qty", (MAX_TRADER, BUY)),
    ("add", (MAX_ORDER_ID + 1, 1, BUY, 100, 1)), ("add", (0, 1, BUY, 100, 1)),
    ("add", (18, MAX_TRADER + 1, BUY, 100, 1)), ("add", (18, -1, BUY, 100, 1)),
    ("add", (18, 1, 2, 100, 1)), ("add", (18, 1, True, 100, 1)), ("add", (18, 1, BUY, 0, 1)),
    ("add", (18, 1, BUY, MAX_VALUE + 1, 1)), ("add", (18, 1, BUY, 100, 0)),
    ("add", (18, 1, BUY, 100, MAX_VALUE + 1)), ("add", (18, 1, BUY, 100.0, 1)),
    ("depth", (BUY, -1)), ("depth", (2, 1)),
    ("cancel", (MAX_ORDER_ID,)), ("cancel_all", (0,)),
    ("order_count", ()), ("best_bid", ()), ("best_ask", ()), ("depth", (BUY, 100)), ("depth", (SELL, 100)),
    ("open_orders", (0,)), ("open_qty", (0, SELL)), ("take_fills", ()), ("take_cancels", ()),
)


def _typed(value):
    """value with its types spelled out, so 1, True and 1.0 never compare equal."""
    if type(value) in (list, tuple):
        return (type(value).__name__, [_typed(item) for item in value])
    return (type(value).__name__, value)


def _outcome(book, name, args):
    try:
        return ("ok", _typed(getattr(book, name)(*args)))
    except Exception as exc:
        return ("raise", type(exc).__name__, str(exc))


def _first_difference(reference_cls, candidate_cls):
    """None when both classes answer every call in _CHECK the same way (results,
    types and error messages), else which call differs and how."""
    reference, candidate = reference_cls(), candidate_cls()
    first = None
    for step, (name, args) in enumerate(_CHECK):
        want = _outcome(reference, name, args)
        got = _outcome(candidate, name, args)
        if first is None and want != got:
            shown = ", ".join([repr(arg) for arg in args])
            first = f"call {step + 1}, {name}({shown}): book.py gave {want!r}, the C++ book {got!r}"
    return first


try:
    _difference = _first_difference(_book.OrderBook, OrderBook)
except Exception as exc:  # never let a broken build or book.py take engine.py down
    _difference = f"the check itself failed: {exc!r}"
if _difference is not None:
    raise ImportError(f"the C++ order book plays differently from book.py ({_difference[:400]}); "
                      "update engine/ to match book.py and rebuild: python scripts/build_engine.py")
