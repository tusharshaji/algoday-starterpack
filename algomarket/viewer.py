"""Writes a replay as one self-contained HTML page: viewer/template.html with
viewer/player.js and the replay JSON inlined. Opens in any browser from disk,
no server and no network (fonts fall back to system fonts when offline).

    from algomarket import viewer
    viewer.write_html(replay, "out/match.html")

run_local.py doesn't write these pages: it saves each match as an .algoday
file, which the kit's VS Code viewer plays with the same template and
player.

Standard library only (no numpy import); numpy scalars and arrays in the
replay are still accepted.
"""
import json
import math
import pathlib
import re

VIEWER_DIR = pathlib.Path(__file__).resolve().parent.parent / "viewer"
TEMPLATE_PATH = VIEWER_DIR / "template.html"
PLAYER_PATH = VIEWER_DIR / "player.js"

PLAYER_MARKER = "/*__ALGOREPLAY_PLAYER__*/"
DATA_MARKER = "__ALGOREPLAY_DATA__"
_MARKERS = re.compile(re.escape(PLAYER_MARKER) + "|" + re.escape(DATA_MARKER))

# Inside <script> the HTML parser only reacts to "</script", "<script" and
# "<!--". Escaping every <, > and & as a JSON \u escape rules all of them out
# (JSON.parse turns them back). U+2028/2029 are escaped for old JS engines.
_JSON_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    " ": "\\u2028",
    " ": "\\u2029",
}
_JSON_UNSAFE = re.compile("[<>&  ]")


def _plain(value):
    """json.dumps fallback: numpy scalars and arrays have tolist()."""
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def _clean(value):
    """Copy with NaN/inf as None and dict keys as str (JSON has neither)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                key = str(_clean(key))
            out[key] = _clean(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if callable(getattr(value, "tolist", None)):
        return _clean(value.tolist())
    return value


def _dumps(replay):
    return json.dumps(replay, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_plain)


def replay_json(replay):
    """The replay as JSON text that is safe inside a <script> element."""
    try:
        text = _dumps(replay)
    except (ValueError, TypeError):
        # NaN/inf or numpy keys somewhere: the viewer shows nulls as gaps.
        text = _dumps(_clean(replay))
    return _JSON_UNSAFE.sub(lambda m: _JSON_ESCAPES[m.group(0)], text)


def _script_safe(source):
    """JS source that can't end its own <script> element early."""
    source = re.sub(r"</(script)", r"<\\/\1", source, flags=re.IGNORECASE)
    return source.replace("<!--", "<\\!--")


def render_html(replay):
    """The complete page for `replay` (a schema v1 replay dict), as a str."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    parts = {
        PLAYER_MARKER: _script_safe(PLAYER_PATH.read_text(encoding="utf-8")),
        DATA_MARKER: replay_json(replay),
    }
    found = _MARKERS.findall(template)
    if sorted(found) != sorted(parts):
        raise ValueError(f"{TEMPLATE_PATH} must contain each placeholder exactly once")
    # One pass, so inserted text is never searched for placeholders again.
    return _MARKERS.sub(lambda m: parts[m.group(0)], template)


def write_html(replay, path):
    """Write the self-contained replay page to `path` (folders are created).
    Returns the path as a pathlib.Path."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(replay), encoding="utf-8", newline="\n")
    return path
