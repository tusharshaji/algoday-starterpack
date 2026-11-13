/* AlgoDay replay player (market/viewer/player.js).
 *
 * Plays one match replay (schema v1: DESIGN.md section 14, in the organisers'
 * design notes, which are not in the starter kit) for a room on a projector:
 * price chart, PnL race, order book, trade tape and the final results. Plain
 * JS + canvas, no dependencies. Defines one global, AlgoReplay (and
 * module.exports under CommonJS); nothing touches the page until mount() is
 * called, so it is safe to load anywhere.
 *
 *   const player = AlgoReplay.mount(container, replay, options);
 *
 * The player fills `container`, so give the container a size (the standalone
 * page uses the whole viewport). Options, all optional:
 *   autoplay        false            start playing at once
 *   speed           1                starting speed, one of `speeds`
 *   speeds          [1, 4, 16, 64]   the speed buttons (keys 1-4)
 *   ticksPerSecond  1000 / 75        ticks per second at 1x (1,000 ticks = 75 s)
 *   keyboard        true             listen for keys on the document
 *   autoReveal      true             reveal the true value at the last tick
 *   showResults     true             final results after the reveal
 *   raceRanks       = showResults    rank numbers and a gold leader in the race
 *                                    (off: an unranked PnL race, e.g. one
 *                                    sample market of a round played over
 *                                    many seeds)
 *   resultsDelay    3.2              seconds from the last tick to the results
 *   resultsLabel    "RESULTS"        the results card's heading (e.g. "FINAL")
 *   brand           {}               top left: {href, logo, logoAlt, label}, a
 *                                    page's logo (an image URL) and wordmark,
 *                                    linking to href. Default: a square and
 *                                    ALGODAY. After a logo the label sits
 *                                    behind a divider, and it is the first
 *                                    thing to go when the header is short of
 *                                    room (before the round's title is cut)
 *   scale           1                size of all text and panels, 0.5-2 (1.25
 *                                    = a quarter bigger, for a low-res
 *                                    projector; browser zoom barely helps).
 *                                    Above 1 only as far as the screen has
 *                                    room: the charts, book and tape keep
 *                                    theirs (two assets need the most, e.g.
 *                                    at most about 1.3 at 1920x1080)
 *   theme           {}               colours: bg panel raise line grid fg muted
 *                                    up down accent gold silver bronze hint
 *                                    (or set --arp-<name> CSS variables)
 *   onTick(t), onEnd()               callbacks
 *
 * The race panel ranks bots by PnL while the match plays; once it settles
 * (with showResults on), teams take their places from the results (ranked
 * by score, ties share a rank), so the race and the results card agree.
 * While playing it re-sorts once a second, and a row passes the one above
 * it only when it leads by more than max($0.50, 1% of the teams' spread),
 * so near-ties don't keep swapping; paused or settled, the order is exact.
 * A crashed/timeout/disqualified mark shows from the participant's
 * stopped_at tick when the replay has one (on its participants or results
 * rows), else from the start. On a narrow screen (a phone) the results card
 * drops Max DD, then PnL, so the names and the score keep their room.
 *
 * The controller: play() pause() toggle() seek(t) step(n) setSpeed(x)
 * restart() reveal(on?) results(on?) fullscreen() getTick() isPlaying()
 * getSpeed() destroy(), and .element (the player's root node, which also
 * carries the controller as .algoReplay for devtools). Ticks are 0-based;
 * the screen shows them 1-based ("0001 / 1000" ... "1000 / 1000").
 * AlgoReplay.validate(replay) lists fatal problems (empty list = playable);
 * mount() throws an Error with that list for an unplayable replay.
 *
 * Keys: space play/pause, left/right step a tick (shift: 50), 1-4 speed,
 * V true value, R restart, Home/End, F fullscreen, Esc close the results.
 * Where the page may not go fullscreen (a frame without permission, such as
 * a VS Code tab), there is no fullscreen button and F does nothing.
 *
 * Drawing: each price chart keeps an offscreen layer of the market marks
 * drawn so far and only adds new ticks to it; the layer is redrawn when the
 * size changes, on a seek back, or once a rescale settles (while the scale
 * eases, the layer is stretched to fit). DOM panels update once per tick.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (root && typeof root === "object") {
    root.AlgoReplay = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const VERSION = "1.5.0";
  const STYLE_ID = "algoreplay-style-6";
  const TAU = Math.PI * 2;
  const DASH = "—";
  const MINUS = "−";
  const TIMES = "×";
  const SANS = "\"IBM Plex Sans\", \"Segoe UI\", \"Helvetica Neue\", Arial, system-ui, sans-serif";
  const MONO = "\"IBM Plex Mono\", \"Cascadia Mono\", Consolas, \"SF Mono\", Menlo, \"Liberation Mono\", monospace";
  const REVEAL_MS = 1700;
  // a chart's hover readout lapses this long after the mouse last moved,
  // while playing (a pointer left resting on the projector)
  const HOVER_IDLE_MS = 2500;
  // smallest text in px (times options.scale), however small the screen
  const FONT_MIN = 10;
  // While playing, the race re-sorts this often (each move is a 0.5 s
  // slide), and a row passes the one above it only by more than this margin:
  // dollars, or a share of the teams' spread (see sortRace).
  const RACE_SORT_MS = 1000;
  const RACE_MARGIN = 0.5;
  const RACE_MARGIN_SHARE = 0.01;

  // The competition site's palette (navy, violet accent, lime and red, gold),
  // so a team's local replay looks like the projector's. The site's
  // globals.css and floor/player.ts hold the same values. A page can override
  // any of these with --arp-<name> CSS variables, a mount with options.theme.
  const THEME = {
    bg: "#050714",
    panel: "#0b1024",
    raise: "#121a36",
    line: "#222d54",
    grid: "#151c37",
    fg: "#f5f7ff",
    muted: "#8d98bc",
    up: "#a7ef6b",
    down: "#ff6b7a",
    accent: "#7c6cff",
    gold: "#f5d76e",
    silver: "#c8cfdb",
    bronze: "#cf8957",
    hint: "#5cc8ff",
  };

  const DEFAULTS = {
    autoplay: false,
    speed: 1,
    speeds: [1, 4, 16, 64],
    ticksPerSecond: 1000 / 75,
    keyboard: true,
    autoReveal: true,
    showResults: true,
    // null: the same as showResults
    raceRanks: null,
    resultsDelay: 3.2,
    resultsLabel: "RESULTS",
    scale: 1,
    theme: null,
    onTick: null,
    onEnd: null,
  };

  // Status: a shape as well as a colour, so it reads without colour vision.
  const STATUS = {
    ok: { tone: "up", icon: "ok" },
    crashed: { tone: "down", icon: "crashed" },
    timeout: { tone: "accent", icon: "timeout" },
    disqualified: { tone: "down", icon: "disqualified" },
  };

  const ICON = {
    play: "<svg viewBox=\"0 0 16 16\"><path d=\"M4 2.5v11l9.5-5.5z\" fill=\"currentColor\"/></svg>",
    pause: "<svg viewBox=\"0 0 16 16\"><path d=\"M3.5 2.5h3.2v11H3.5zM9.3 2.5h3.2v11H9.3z\" fill=\"currentColor\"/></svg>",
    restart: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"square\"><path d=\"M3.2 8.6A5 5 0 1 0 4.9 4.1\"/><path d=\"M4.6 1.6v2.8h2.8\"/></svg>",
    eye: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\"><path d=\"M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z\"/><circle cx=\"8\" cy=\"8\" r=\"2.1\"/></svg>",
    full: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"square\"><path d=\"M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10\"/></svg>",
    close: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\" stroke-linecap=\"square\"><path d=\"M4 4l8 8M12 4l-8 8\"/></svg>",
    house: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"square\"><path d=\"M2.5 7.6 8 3l5.5 4.6M4.2 6.4v7.1h7.6V6.4\"/></svg>",
    trophy: "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"square\"><path d=\"M4.5 2.5h7v3.2a3.5 3.5 0 0 1-7 0zM4.5 4H2.5v1.2a2 2 0 0 0 2 2M11.5 4h2v1.2a2 2 0 0 1-2 2M8 9.2v3M5.5 13.5h5\"/></svg>",
  };

  const STATUS_ICON = {
    ok: "<svg viewBox=\"0 0 12 12\"><circle cx=\"6\" cy=\"6\" r=\"4\" fill=\"currentColor\"/></svg>",
    crashed: "<svg viewBox=\"0 0 12 12\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"square\"><path d=\"M2.6 2.6l6.8 6.8M9.4 2.6 2.6 9.4\"/></svg>",
    timeout: "<svg viewBox=\"0 0 12 12\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\"><circle cx=\"6\" cy=\"6\" r=\"4.3\"/><path d=\"M6 3.3V6h2.2\" stroke-linecap=\"square\"/></svg>",
    disqualified: "<svg viewBox=\"0 0 12 12\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\"><circle cx=\"6\" cy=\"6\" r=\"4.3\"/><path d=\"M3 9l6-6\"/></svg>",
    unknown: "<svg viewBox=\"0 0 12 12\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.6\"><circle cx=\"6\" cy=\"6\" r=\"3.4\"/></svg>",
  };

  // Hint markers: one hollow shape per source (trades are filled triangles).
  const SOURCE_SHAPES = { analyst: 0, insider: 1, newswire: 2, rumour: 3 };
  const SHAPE_SVG = [
    "<circle cx=\"8\" cy=\"8\" r=\"4.6\"/>",
    "<path d=\"M8 2.4 13.6 8 8 13.6 2.4 8z\"/>",
    "<path d=\"M3.8 3.8h8.4v8.4H3.8z\"/>",
    "<path d=\"M8 2.6v10.8M2.6 8h10.8\"/>",
    "<path d=\"M8 2.6l4.7 2.7v5.4L8 13.4l-4.7-2.7V5.3z\"/>",
    "<path d=\"M3.8 3.8l8.4 8.4M12.2 3.8l-8.4 8.4\"/>",
    "<path d=\"M8 2.8l5.2 9.4H2.8z\"/>",
  ];
  const SHAPE_COUNT = SHAPE_SVG.length;

  const LEGEND_SVG = {
    band: "<svg viewBox=\"0 0 16 16\"><rect x=\"1\" y=\"4.5\" width=\"14\" height=\"7\" fill=\"currentColor\" opacity=\".22\"/><path d=\"M1 4.5h14\" style=\"stroke:var(--c-down)\" stroke-width=\"1.5\"/><path d=\"M1 11.5h14\" style=\"stroke:var(--c-up)\" stroke-width=\"1.5\"/></svg>",
    mid: "<svg viewBox=\"0 0 16 16\"><path d=\"M1 8h14\" stroke=\"currentColor\" stroke-width=\"2.2\"/></svg>",
    buy: "<svg viewBox=\"0 0 16 16\"><path d=\"M8 2.5l5.6 10H2.4z\" fill=\"currentColor\"/></svg>",
    sell: "<svg viewBox=\"0 0 16 16\"><path d=\"M8 13.5l5.6-10H2.4z\" fill=\"currentColor\"/></svg>",
    tv: "<svg viewBox=\"0 0 16 16\"><path d=\"M1 8h14\" stroke=\"currentColor\" stroke-width=\"3\"/></svg>",
  };

  // ---------------------------------------------------------------- helpers

  function isNum(v) {
    return typeof v === "number" && Number.isFinite(v);
  }

  function toNum(v) {
    return isNum(v) ? v : NaN;
  }

  function clamp(v, lo, hi) {
    if (v < lo) {
      return lo;
    }
    return v > hi ? hi : v;
  }

  function asArray(v) {
    return Array.isArray(v) ? v : [];
  }

  function asObject(v) {
    return v && typeof v === "object" && !Array.isArray(v) ? v : {};
  }

  function pidKeyed(obj, pid) {
    const src = asObject(obj);
    if (Object.prototype.hasOwnProperty.call(src, String(pid))) {
      return src[String(pid)];
    }
    return Array.isArray(obj) ? obj[pid] : undefined;
  }

  function groupInt(digits) {
    let out = "";
    let count = 0;
    for (let i = digits.length - 1; i >= 0; i--) {
      out = digits[i] + out;
      count += 1;
      if (count % 3 === 0 && i > 0) {
        out = "," + out;
      }
    }
    return out;
  }

  // $1,234.56 / +$12 / -$3.4k (true minus sign). mode: 2, 0 or "k".
  function fmtMoney(v, mode, signed) {
    if (!isNum(v)) {
      return DASH;
    }
    const abs = Math.abs(v);
    let body;
    let suffix = "";
    if (mode === "k") {
      body = (abs / 1000).toFixed(1);
      suffix = "k";
    } else {
      body = abs.toFixed(mode);
    }
    const zero = Number(body) === 0;
    const dot = body.indexOf(".");
    const text = dot < 0 ? groupInt(body) : groupInt(body.slice(0, dot)) + body.slice(dot);
    let sign = "";
    if (!zero && v < 0) {
      sign = MINUS;
    }
    if (!zero && v > 0 && signed) {
      sign = "+";
    }
    return sign + "$" + text + suffix;
  }

  function signOf(v, mode) {
    const shown = mode === "k" ? Math.round(v / 100) : Math.round(v * Math.pow(10, mode));
    if (shown > 0) {
      return 1;
    }
    return shown < 0 ? -1 : 0;
  }

  function fmtPrice(v) {
    return isNum(v) ? v.toFixed(2) : DASH;
  }

  function fmtQty(q) {
    return isNum(q) ? groupInt(String(Math.round(q))) : "";
  }

  function niceStep(range, target) {
    const raw = range / Math.max(1, target);
    if (!(raw > 0)) {
      return 1;
    }
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / mag;
    let step = 10;
    if (n <= 1) {
      step = 1;
    } else if (n <= 2) {
      step = 2;
    } else if (n <= 2.5) {
      step = 2.5;
    } else if (n <= 5) {
      step = 5;
    }
    return step * mag;
  }

  function easeInOut(p) {
    return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  }

  // Count of entries in a tick-sorted Int32Array with tick <= t, per t.
  function endIndex(ticks, n, T) {
    const end = new Int32Array(T);
    let k = 0;
    for (let t = 0; t < T; t++) {
      while (k < n && ticks[k] <= t) {
        k += 1;
      }
      end[t] = k;
    }
    return end;
  }

  function aggressorOf(v) {
    if (v === "buy" || v === "BUY" || v === "b" || v === 0) {
      return 1;
    }
    if (v === "sell" || v === "SELL" || v === "s" || v === 1) {
      return -1;
    }
    return 0;
  }

  function statusInfo(status) {
    const known = Object.prototype.hasOwnProperty.call(STATUS, status);
    return known ? STATUS[status] : { tone: "muted", icon: "unknown" };
  }

  // Normalise any CSS colour through a canvas: "#rrggbb" or "rgba(...)".
  function rgbOf(ctx, value, fallback) {
    ctx.fillStyle = fallback;
    ctx.fillStyle = value || fallback;
    const s = String(ctx.fillStyle);
    if (s.charAt(0) === "#") {
      return [parseInt(s.slice(1, 3), 16), parseInt(s.slice(3, 5), 16), parseInt(s.slice(5, 7), 16)];
    }
    const m = s.match(/[\d.]+/g);
    return m ? [Number(m[0]), Number(m[1]), Number(m[2])] : [0, 0, 0];
  }

  function rgba(rgb, a) {
    return "rgba(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + "," + a + ")";
  }

  // `top` at opacity a over `base`, as one opaque colour (opaque strokes can
  // overlap at joints without beading)
  function blend(top, base, a) {
    const out = [];
    for (let i = 0; i < 3; i++) {
      out.push(Math.round(base[i] + (top[i] - base[i]) * a));
    }
    return rgba(out, 1);
  }

  function safely(fn, arg) {
    try {
      fn(arg);
    } catch (err) {
      if (typeof console !== "undefined") {
        console.error("AlgoReplay callback failed:", err);
      }
    }
  }

  // ------------------------------------------------------------ the replay

  function countTicks(replay, assets) {
    const meta = asObject(replay.meta);
    if (Number.isInteger(meta.ticks) && meta.ticks > 0) {
      return meta.ticks;
    }
    let T = 0;
    for (const a of assets) {
      for (const src of [replay.true_value, replay.best_bid, replay.best_ask, replay.books]) {
        T = Math.max(T, asArray(asObject(src)[a]).length);
      }
    }
    const equity = asObject(replay.equity);
    for (const k of Object.keys(equity)) {
      T = Math.max(T, asArray(equity[k]).length);
    }
    return T;
  }

  function assetNames(replay) {
    const meta = asObject(replay.meta);
    const names = [];
    for (const a of asArray(meta.assets)) {
      if (typeof a === "string" && a && names.indexOf(a) < 0) {
        names.push(a);
      }
    }
    if (!names.length) {
      for (const src of [replay.true_value, replay.best_bid, replay.best_ask, replay.books]) {
        for (const k of Object.keys(asObject(src))) {
          if (names.indexOf(k) < 0) {
            names.push(k);
          }
        }
      }
    }
    return names;
  }

  /** Fatal problems only; anything else is filled with sensible defaults. */
  function validate(replay) {
    if (!replay || typeof replay !== "object" || Array.isArray(replay)) {
      return ["expected a JSON object"];
    }
    const problems = [];
    const assets = assetNames(replay);
    if (!assets.length) {
      problems.push("no assets");
    }
    if (countTicks(replay, assets) < 1) {
      problems.push("no ticks");
    }
    if (replay.version !== undefined && replay.version !== 1 && typeof console !== "undefined") {
      console.warn("AlgoReplay: replay version " + replay.version + ", expected 1; trying anyway");
    }
    return problems;
  }

  // Float64Array per tick; null/missing -> NaN, or carried forward if fill.
  function seriesOf(obj, key, T, fill) {
    const src = asArray(asObject(obj)[key]);
    const out = new Float64Array(T);
    let last = NaN;
    for (let t = 0; t < T; t++) {
      const v = toNum(src[t]);
      if (isNum(v)) {
        last = v;
      }
      out[t] = isNum(v) ? v : (fill ? last : NaN);
    }
    if (fill) {
      let next = NaN;
      for (let t = T - 1; t >= 0; t--) {
        if (isNum(out[t])) {
          next = out[t];
        } else {
          out[t] = next;
        }
      }
    }
    return out;
  }

  // A row's pid (a number or a numeric string), else NaN.
  function pidOf(row) {
    const v = asObject(row).pid;
    const ok = typeof v === "number" || (typeof v === "string" && v.trim() !== "");
    const pid = ok ? Number(v) : NaN;
    return Number.isInteger(pid) ? pid : NaN;
  }

  // The tick a bot was stopped at (0 = it never started), or null when it
  // ran to the end or the replay doesn't say.
  function stopTick(v, T) {
    return Number.isInteger(v) && v >= 0 ? Math.min(v, T - 1) : null;
  }

  // Race money format for these participants: cents while every value stays
  // under $1,000, then whole dollars, then thousands.
  function eqModeOf(parts, T) {
    let max = 0;
    for (const p of parts) {
      for (let t = 0; t < T; t++) {
        max = Math.max(max, Math.abs(p.eq[t]));
      }
    }
    if (max < 1000) {
      return 2;
    }
    return max < 100000 ? 0 : "k";
  }

  function prepare(replay) {
    const meta = asObject(replay.meta);
    const names = assetNames(replay);
    const T = Math.max(1, countTicks(replay, names));
    const M = {
      T: T,
      tMax: Math.max(1, T - 1),
      digits: String(T).length,
      title: typeof meta.title === "string" && meta.title ? meta.title
        : (meta.round ? String(meta.round) : "Replay"),
      seed: meta.seed === undefined || meta.seed === null ? null : String(meta.seed),
      lambda: isNum(meta.lambda) ? meta.lambda : null,
      parts: [],
      assets: [],
      sources: [],
    };

    // participants (fall back to results, then equity keys)
    const byPid = new Map();
    function addPart(row) {
      const p = asObject(row);
      const pid = pidOf(p);
      if (!Number.isInteger(pid) || byPid.has(pid)) {
        return;
      }
      const part = {
        pid: pid,
        index: M.parts.length,
        name: typeof p.name === "string" && p.name ? p.name : "#" + pid,
        kind: p.kind === "house" ? "house" : "team",
        status: typeof p.status === "string" && p.status ? p.status : "ok",
        detail: typeof p.detail === "string" ? p.detail : null,
        stoppedAt: stopTick(p.stopped_at, T),
        rank: null,
        resultPos: 0,
        eq: null,
      };
      M.parts.push(part);
      byPid.set(pid, part);
    }
    for (const p of asArray(replay.participants)) {
      addPart(p);
    }
    for (const r of asArray(replay.results)) {
      addPart(r);
    }
    for (const k of Object.keys(asObject(replay.equity))) {
      addPart({ pid: Number(k) });
    }
    // stopped_at may be on the results rows instead of the participants
    for (const r of asArray(replay.results)) {
      const part = byPid.get(pidOf(r));
      if (part && part.stoppedAt === null) {
        part.stoppedAt = stopTick(r.stopped_at, T);
      }
    }
    M.statuses = new Set();
    for (const part of M.parts) {
      const src = asArray(pidKeyed(replay.equity, part.pid));
      const eq = new Float64Array(T);
      let last = 0;
      for (let t = 0; t < T; t++) {
        const v = toNum(src[t]);
        if (isNum(v)) {
          last = v;
        }
        eq[t] = last;
      }
      part.eq = eq;
      M.statuses.add(part.status);
    }
    M.teams = M.parts.filter(function (p) { return p.kind !== "house"; });
    M.house = M.parts.filter(function (p) { return p.kind === "house"; });
    function isTeam(pid) {
      const p = byPid.get(pid);
      return p ? p.kind !== "house" : false;
    }

    // hint sources: known names keep their shapes, others take free ones
    const hintRows = [];
    const srcNames = [];
    for (const h of asArray(replay.hints)) {
      let row = null;
      if (Array.isArray(h)) {
        row = { t: h[0], a: h[1], v: h[2], s: h[3] };
      } else if (h && typeof h === "object") {
        row = { t: h.t !== undefined ? h.t : h.tick, a: h.asset, v: h.value, s: h.source };
      }
      if (row) {
        const ai = names.indexOf(row.a);
        const src = typeof row.s === "string" && row.s ? row.s : "hint";
        if (Number.isInteger(row.t) && row.t >= 0 && row.t < T && ai >= 0 && isNum(row.v)) {
          hintRows.push({ t: row.t, ai: ai, v: row.v, s: src });
          if (srcNames.indexOf(src) < 0) {
            srcNames.push(src);
          }
        }
      }
    }
    const usedShapes = new Set();
    const shapeOf = {};
    for (const s of srcNames) {
      const known = SOURCE_SHAPES[s.toLowerCase()];
      if (known !== undefined && !usedShapes.has(known)) {
        shapeOf[s] = known;
        usedShapes.add(known);
      }
    }
    for (const s of srcNames) {
      if (shapeOf[s] === undefined) {
        let shape = -1;
        for (let k = 0; k < SHAPE_COUNT; k++) {
          if (shape < 0 && !usedShapes.has(k)) {
            shape = k;
          }
        }
        if (shape < 0) {
          shape = srcNames.indexOf(s) % SHAPE_COUNT;
        }
        shapeOf[s] = shape;
        usedShapes.add(shape);
      }
    }
    for (const s of srcNames) {
      M.sources.push({ name: s, shape: shapeOf[s], count: 0, rare: false });
    }
    hintRows.sort(function (x, y) { return x.t - y.t; });
    for (const h of hintRows) {
      M.sources[srcNames.indexOf(h.s)].count += 1;
    }
    for (const s of M.sources) {
      // rare sources (insider, newswire) get a short direct label when they
      // fire; frequent ones (rumour) are drawn quieter
      s.rare = s.count > 0 && T / s.count >= 25;
      s.frequent = s.count > T * 0.15;
      // the more often a source fires, the fainter each of its marks
      s.alpha = s.frequent ? clamp(0.62 - 0.32 * s.count / T, 0.3, 0.55) : 1;
    }

    // trades
    const tradeRows = [];
    for (const tr of asArray(replay.trades)) {
      let row = null;
      if (Array.isArray(tr)) {
        row = { t: tr[0], a: tr[1], p: tr[2], q: tr[3], b: tr[4], s: tr[5], g: tr[6] };
      } else if (tr && typeof tr === "object") {
        row = {
          t: tr.t !== undefined ? tr.t : tr.tick, a: tr.asset, p: tr.price, q: tr.qty,
          b: tr.buyer !== undefined ? tr.buyer : tr.buyer_pid,
          s: tr.seller !== undefined ? tr.seller : tr.seller_pid, g: tr.aggressor,
        };
      }
      if (row) {
        const ai = names.indexOf(row.a);
        if (Number.isInteger(row.t) && row.t >= 0 && row.t < T && ai >= 0 && isNum(row.p)) {
          tradeRows.push({
            t: row.t, ai: ai, p: row.p, q: isNum(row.q) && row.q > 0 ? row.q : 1,
            b: Number.isInteger(row.b) ? row.b : -1, s: Number.isInteger(row.s) ? row.s : -1,
            g: aggressorOf(row.g),
          });
        }
      }
    }
    tradeRows.sort(function (x, y) { return x.t - y.t; });
    const n = tradeRows.length;
    const all = {
      n: n, t: new Int32Array(n), ai: new Int16Array(n), p: new Float64Array(n),
      q: new Float64Array(n), b: new Int32Array(n), s: new Int32Array(n), g: new Int8Array(n),
    };
    for (let i = 0; i < n; i++) {
      const r = tradeRows[i];
      all.t[i] = r.t;
      all.ai[i] = r.ai;
      all.p[i] = r.p;
      all.q[i] = r.q;
      all.b[i] = r.b;
      all.s[i] = r.s;
      all.g[i] = r.g;
    }
    M.trades = all;
    M.tradeEnd = endIndex(all.t, n, T);

    // per asset
    for (let ai = 0; ai < names.length; ai++) {
      const name = names[ai];
      const bid = seriesOf(replay.best_bid, name, T, false);
      const ask = seriesOf(replay.best_ask, name, T, false);
      const tv = seriesOf(replay.true_value, name, T, true);
      const mid = new Float64Array(T);
      for (let t = 0; t < T; t++) {
        mid[t] = isNum(bid[t]) && isNum(ask[t]) ? (bid[t] + ask[t]) / 2 : NaN;
      }
      const mine = tradeRows.filter(function (r) { return r.ai === ai; });
      const m = mine.length;
      const tr = {
        n: m, t: new Int32Array(m), p: new Float64Array(m), q: new Float64Array(m),
        g: new Int8Array(m), team: new Uint8Array(m),
      };
      const qs = new Float64Array(m);
      for (let i = 0; i < m; i++) {
        const r = mine[i];
        tr.t[i] = r.t;
        tr.p[i] = r.p;
        tr.q[i] = r.q;
        tr.g[i] = r.g;
        tr.team[i] = isTeam(r.b) || isTeam(r.s) ? 1 : 0;
        qs[i] = r.q;
      }
      qs.sort();
      const qRef = m ? Math.max(1, qs[Math.min(m - 1, Math.floor(m * 0.98))]) : 1;
      const hs = hintRows.filter(function (h) { return h.ai === ai; });
      const hn = hs.length;
      const hints = { n: hn, t: new Int32Array(hn), v: new Float64Array(hn), s: new Int16Array(hn) };
      for (let i = 0; i < hn; i++) {
        hints.t[i] = hs[i].t;
        hints.v[i] = hs[i].v;
        hints.s[i] = srcNames.indexOf(hs[i].s);
      }
      // running price range (bid, ask, trades) and true value range
      const rlo = new Float64Array(T);
      const rhi = new Float64Array(T);
      const tvLo = new Float64Array(T);
      const tvHi = new Float64Array(T);
      let lo = Infinity;
      let hi = -Infinity;
      let vlo = Infinity;
      let vhi = -Infinity;
      let k = 0;
      for (let t = 0; t < T; t++) {
        if (isNum(bid[t])) {
          lo = Math.min(lo, bid[t]);
          hi = Math.max(hi, bid[t]);
        }
        if (isNum(ask[t])) {
          lo = Math.min(lo, ask[t]);
          hi = Math.max(hi, ask[t]);
        }
        while (k < m && tr.t[k] <= t) {
          lo = Math.min(lo, tr.p[k]);
          hi = Math.max(hi, tr.p[k]);
          k += 1;
        }
        if (isNum(tv[t])) {
          vlo = Math.min(vlo, tv[t]);
          vhi = Math.max(vhi, tv[t]);
        }
        rlo[t] = lo;
        rhi[t] = hi;
        tvLo[t] = vlo;
        tvHi[t] = vhi;
      }
      let center = hn ? hints.v[0] : tv[0];
      if (!isNum(center)) {
        center = 100;
      }
      const books = asArray(asObject(replay.books)[name]);
      M.assets.push({
        name: name, index: ai, bid: bid, ask: ask, mid: mid, tv: tv, books: books,
        tr: tr, trEnd: endIndex(tr.t, m, T), qRef: qRef,
        hints: hints, hEnd: endIndex(hints.t, hn, T),
        rlo: rlo, rhi: rhi, tvLo: tvLo, tvHi: tvHi, center: center,
      });
    }

    // equity extents per tick, over teams (house noise traders are allowed
    // to run off the edge of the race rather than squash the teams)
    const ranked = M.teams.length ? M.teams : M.parts;
    M.eqLo = new Float64Array(T);
    M.eqHi = new Float64Array(T);
    let maxRanked = 0;
    for (let t = 0; t < T; t++) {
      let lo = 0;
      let hi = 0;
      for (const p of ranked) {
        lo = Math.min(lo, p.eq[t]);
        hi = Math.max(hi, p.eq[t]);
      }
      M.eqLo[t] = lo;
      M.eqHi[t] = hi;
      maxRanked = Math.max(maxRanked, hi - lo);
    }
    // the same for the money format: a house bot passing $1,000 must not
    // cost every team its cents (house rows get their own format)
    M.eqMode = eqModeOf(ranked, T);
    M.houseEqMode = eqModeOf(M.house, T);
    M.eqFloor = Math.max(1, maxRanked * 0.04);

    // results: the replay's own, else computed (DESIGN section 12)
    let rows = [];
    for (const r of asArray(replay.results)) {
      const part = byPid.get(pidOf(r));
      if (part && !rows.some(function (x) { return x.part === part; })) {
        rows.push({
          part: part, pnl: toNum(r.pnl), mdd: toNum(r.max_drawdown), score: toNum(r.score),
          rank: Number.isInteger(r.rank) && r.rank > 0 && part.kind !== "house" ? r.rank : null,
          status: typeof r.status === "string" && r.status ? r.status : part.status,
        });
      }
    }
    if (!rows.length) {
      for (const part of M.parts) {
        let peak = 0;
        let mdd = 0;
        for (let t = 0; t < T; t++) {
          peak = Math.max(peak, part.eq[t]);
          mdd = Math.max(mdd, peak - part.eq[t]);
        }
        const pnl = part.eq[T - 1];
        rows.push({
          part: part, pnl: pnl, mdd: mdd, score: pnl - (M.lambda || 0) * mdd, rank: null,
          status: part.status,
        });
      }
    }
    if (!rows.some(function (r) { return r.rank !== null; })) {
      // DESIGN section 16: ranks use scores rounded to cents, ties share
      const teamRows = rows.filter(function (r) { return r.part.kind !== "house" && isNum(r.score); });
      teamRows.sort(function (x, y) { return (y.score - x.score) || (x.part.index - y.part.index); });
      for (let i = 0; i < teamRows.length; i++) {
        const tied = i > 0 && Math.round(teamRows[i].score * 100) === Math.round(teamRows[i - 1].score * 100);
        teamRows[i].rank = tied ? teamRows[i - 1].rank : i + 1;
      }
    }
    function group(r) {
      if (r.part.kind === "house") {
        return 2;
      }
      return r.rank === null ? 1 : 0;
    }
    rows.sort(function (x, y) {
      const gx = group(x);
      const gy = group(y);
      if (gx !== gy) {
        return gx - gy;
      }
      if (gx === 0) {
        return x.rank - y.rank;
      }
      const sx = isNum(x.score) ? x.score : -Infinity;
      const sy = isNum(y.score) ? y.score : -Infinity;
      return (sy - sx) || (x.part.index - y.part.index);
    });
    M.results = rows;
    // where each team sits once the match settles (see sortRace)
    for (const part of M.parts) {
      part.resultPos = rows.length + part.index;
    }
    for (let i = 0; i < rows.length; i++) {
      rows[i].part.rank = rows[i].rank;
      rows[i].part.resultPos = i;
    }
    M.hasRanks = M.teams.some(function (p) { return p.rank !== null; });
    return M;
  }

  // ------------------------------------------------------------------ styles

  function css() {
    let tokens = "";
    for (const k of Object.keys(THEME)) {
      tokens += "--c-" + k + ":var(--arp-" + k + "," + THEME[k] + ");";
    }
    const sans = "var(--arp-sans," + SANS + ")";
    const mono = "var(--arp-mono," + MONO + ")";
    return [
      ".arp{" + tokens + "--u:16px;--fmin:" + FONT_MIN + "px;--gap:calc(var(--u)*.7);--pad:calc(var(--u)*.9);position:relative;box-sizing:border-box;width:100%;height:100%;min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;background:var(--c-bg);color:var(--c-fg);font-family:" + sans + ";font-size:var(--u);line-height:1.25;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}",
      ".arp *,.arp *::before,.arp *::after{box-sizing:border-box}",
      // :where() keeps these resets weaker than any single class below
      ":where(.arp) button{font:inherit;color:inherit;background:none;border:0;border-radius:0;margin:0;padding:0;cursor:pointer}",
      ":where(.arp) button:focus-visible{outline:2px solid var(--c-accent);outline-offset:2px}",
      ":where(.arp) svg{display:block;width:100%;height:100%;overflow:visible}",
      ".arp .arp-m{font-family:" + mono + ";font-variant-numeric:tabular-nums}",
      ".arp-noanim,.arp-noanim *{transition:none!important}",
      ".arp-k-up{color:var(--c-up)}.arp-k-down{color:var(--c-down)}.arp-k-accent{color:var(--c-accent)}.arp-k-muted{color:var(--c-muted)}.arp-k-fg{color:var(--c-fg)}.arp-k-hint{color:var(--c-hint)}",
      // header
      ".arp-head{flex:none;display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;column-gap:calc(var(--u)*1.5);height:calc(var(--u)*4.4);padding:0 var(--pad)}",
      ".arp-hl{min-width:0;display:flex;align-items:center;gap:calc(var(--u)*1.2)}",
      ".arp-brand{flex:none;display:flex;align-items:center;gap:calc(var(--u)*.5);font-family:" + mono + ";font-size:calc(var(--u)*.78);font-weight:600;letter-spacing:.16em;color:var(--c-muted)}",
      ".arp-brand i{display:block;width:calc(var(--u)*.75);height:calc(var(--u)*.75);background:var(--c-accent)}",
      "a.arp-brand{color:var(--c-muted);text-decoration:none}",
      "a.arp-brand:hover{color:var(--c-fg)}",
      // 14px at least: in a small window (a laptop, a VS Code tab) the logo's thin letters stay readable
      ".arp-brand-logo{display:block;flex:none;height:max(calc(var(--u)*1.25),14px);width:auto}",
      // after a logo, the label is a wordmark behind a divider, as in the site's header
      // (its shadow is 2px at 1080p and grows and shrinks with everything else)
      ".arp-brand-logo+.arp-brand-label{flex:none;white-space:nowrap;padding-left:.9em;border-left:1px solid var(--c-line);color:var(--c-fg);letter-spacing:.06em;text-shadow:calc(var(--u)*.125) calc(var(--u)*.125) 0 color-mix(in srgb,var(--c-accent) 70%,transparent)}",
      // A logo and its wordmark are wide. Short of room, this brand shrinks
      // long before the round's title does (the huge flex-shrink), and the
      // wordmark wraps below the logo, out of sight. clip-path and not
      // overflow, so the brand's smallest width stays the logo's.
      ".arp-brand-mark{flex:0 99999 auto;flex-wrap:wrap;align-content:flex-start;height:max(calc(var(--u)*1.25),14px);clip-path:inset(-3px calc(var(--u)*-.3) -3px -3px)}",
      ".arp-tb{flex:1 1 auto;min-width:0;display:flex;align-items:center;gap:calc(var(--u)*.7);height:calc(var(--u)*2.4);padding-left:calc(var(--u)*1.2);border-left:1px solid var(--c-line)}",
      ".arp-title{min-width:0;font-size:calc(var(--u)*1.6);font-weight:600;letter-spacing:-.015em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".arp-chip{flex:none;font-size:calc(var(--u)*.8);font-weight:600;letter-spacing:.08em;padding:calc(var(--u)*.15) calc(var(--u)*.45);background:var(--c-raise);border:1px solid var(--c-line)}",
      ".arp-seed{flex:none;font-size:calc(var(--u)*.78);color:var(--c-muted)}",
      ".arp-clock{flex:none;display:flex;align-items:baseline;gap:calc(var(--u)*.4);white-space:nowrap}",
      ".arp-tl{font-size:calc(var(--u)*.78);font-weight:600;letter-spacing:.12em;color:var(--c-muted)}",
      ".arp-tnow{font-size:calc(var(--u)*2.3);font-weight:600;line-height:1;transition:color .3s}",
      ".arp-tof{font-size:calc(var(--u)*1.05);color:var(--c-muted)}",
      ".arp-late .arp-tnow,.arp-final .arp-tnow{color:var(--c-accent)}",
      ".arp-badge{display:none;align-self:center;margin-left:calc(var(--u)*.5);padding:calc(var(--u)*.22) calc(var(--u)*.5);background:var(--c-accent);color:var(--c-bg);font-size:calc(var(--u)*.72);font-weight:600;letter-spacing:.16em}",
      ".arp-final .arp-badge{display:block}",
      ".arp-ctrls{justify-self:end;display:flex;align-items:center;gap:calc(var(--u)*.4)}",
      ".arp-btn{flex:none;display:grid;place-items:center;width:calc(var(--u)*2.5);height:calc(var(--u)*2.5);border:1px solid var(--c-line);background:var(--c-panel);color:var(--c-fg)}",
      ".arp-btn:hover{border-color:var(--c-muted)}",
      ".arp-btn>span{display:block;width:calc(var(--u)*1.05);height:calc(var(--u)*1.05)}",
      ".arp-btn.arp-on{color:var(--c-accent);border-color:var(--c-accent)}",
      ".arp-play{background:var(--c-accent);border-color:var(--c-accent);color:var(--c-bg)}",
      ".arp-play:hover{border-color:var(--c-fg)}",
      ".arp-speeds{flex:none;display:flex;height:calc(var(--u)*2.5);border:1px solid var(--c-line)}",
      ".arp-speeds button{min-width:calc(var(--u)*2.8);font-size:calc(var(--u)*.85);color:var(--c-muted);background:var(--c-panel)}",
      ".arp-speeds button+button{border-left:1px solid var(--c-line)}",
      ".arp-speeds button:hover{color:var(--c-fg)}",
      ".arp-speeds button.arp-on{color:var(--c-bg);background:var(--c-fg)}",
      // scrubber
      ".arp-scrub{flex:none;position:relative;height:calc(var(--u)*1.2);margin:0 var(--pad);cursor:pointer;touch-action:none}",
      ".arp-track{position:absolute;left:0;right:0;top:50%;height:calc(var(--u)*.28);margin-top:calc(var(--u)*-.14);background:var(--c-raise)}",
      ".arp-fill{position:absolute;left:0;top:0;bottom:0;width:0;background:var(--c-accent)}",
      ".arp-knob{position:absolute;top:50%;left:0;width:calc(var(--u)*.36);height:calc(var(--u)*1.05);margin:calc(var(--u)*-.525) 0 0 calc(var(--u)*-.18);background:var(--c-fg)}",
      // body grid
      ".arp-body{position:relative;flex:1 1 auto;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) calc(var(--u)*33);grid-template-rows:minmax(0,1fr) calc(var(--u)*19);grid-template-areas:\"charts race\" \"bottom race\";gap:var(--gap);padding:calc(var(--u)*.35) var(--pad) var(--pad)}",
      ".arp-panel{position:relative;min-width:0;min-height:0;display:flex;flex-direction:column;background:var(--c-panel);border:1px solid var(--c-line)}",
      ".arp-ph{flex:none;display:flex;align-items:center;gap:calc(var(--u)*.7);height:calc(var(--u)*2.3);padding:0 calc(var(--u)*.8);border-bottom:1px solid var(--c-line);font-size:max(var(--fmin),calc(var(--u)*.74));font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--c-muted);white-space:nowrap;overflow:hidden}",
      ".arp-sym{color:var(--c-fg);font-size:calc(var(--u)*1.02);letter-spacing:.08em}",
      ".arp-px{color:var(--c-fg);font-size:calc(var(--u)*1.02);font-weight:500;letter-spacing:0;text-transform:none}",
      ".arp-tvl{display:none;color:var(--c-accent)}",
      ".arp-tvon .arp-tvl{display:inline}",
      ".arp-legend{margin-left:auto;min-width:0;display:flex;align-items:center;gap:calc(var(--u)*.85);overflow:hidden;font-size:max(var(--fmin),calc(var(--u)*.76));font-weight:400;letter-spacing:.02em;text-transform:none}",
      ".arp-legend>span{flex:none;display:flex;align-items:center;gap:calc(var(--u)*.3)}",
      ".arp-legend i{display:block;flex:none;width:calc(var(--u)*.9);height:calc(var(--u)*.9)}",
      ".arp-legend .arp-lgtv{display:none}",
      ".arp-tvon .arp-legend .arp-lgtv{display:flex}",
      ".arp-charts{grid-area:charts;position:relative;min-height:0;display:flex;flex-direction:column;gap:var(--gap)}",
      ".arp-chart{flex:1 1 0}",
      ".arp-cv{position:relative;flex:1 1 auto;min-height:0}",
      ".arp-cv canvas{position:absolute;left:0;top:0;width:100%;height:100%;display:block}",
      ".arp-settle{animation:arp-flash 1.8s ease-out}",
      "@keyframes arp-flash{0%,25%{border-color:var(--c-accent);box-shadow:inset 0 0 0 2px var(--c-accent)}100%{border-color:var(--c-line);box-shadow:inset 0 0 0 2px rgba(0,0,0,0)}}",
      ".arp-big{position:absolute;left:50%;top:50%;z-index:2;width:calc(var(--u)*5);height:calc(var(--u)*5);margin:calc(var(--u)*-2.5) 0 0 calc(var(--u)*-2.5);display:grid;place-items:center;background:var(--c-accent);color:var(--c-bg)}",
      ".arp-big>span{display:block;width:calc(var(--u)*2.1);height:calc(var(--u)*2.1);margin-left:calc(var(--u)*.25)}",
      ".arp-big::after{content:\"SPACE\";position:absolute;top:calc(100% + var(--u)*.7);left:50%;transform:translateX(-50%);font-family:" + mono + ";font-size:calc(var(--u)*.72);font-weight:600;letter-spacing:.24em;color:var(--c-muted)}",
      ".arp-started .arp-big{display:none}",
      ".arp-tip{position:absolute;z-index:3;display:none;pointer-events:none;min-width:calc(var(--u)*10);padding:calc(var(--u)*.45) calc(var(--u)*.65);background:var(--c-bg);border:1px solid var(--c-line);font-size:calc(var(--u)*.8)}",
      ".arp-tip div{display:flex;justify-content:space-between;gap:calc(var(--u)*1.2);line-height:1.55}",
      ".arp-tip span{color:var(--c-muted)}",
      ".arp-tip b{font-family:" + mono + ";font-weight:600;font-variant-numeric:tabular-nums}",
      // race
      ".arp-race{grid-area:race}",
      ".arp-rows{position:relative;flex:1 1 auto;min-height:0;overflow:hidden}",
      // two lines per row (name + value, then a full-width bar); one line when
      // crowded. Opaque, so two rows passing each other never overprint.
      ".arp-row{position:absolute;left:0;right:0;top:0;height:var(--rh);display:grid;grid-template-columns:calc(var(--u)*2.1) calc(var(--u)*1.05) minmax(0,1fr) auto;grid-template-areas:\"rank st name val\" \". . bar bar\";column-gap:calc(var(--u)*.6);row-gap:calc(var(--rh)*.1);align-content:center;align-items:center;padding:0 calc(var(--u)*.9);background:var(--c-panel);border-bottom:1px solid var(--c-grid);transition:transform .5s cubic-bezier(.2,.75,.2,1)}",
      ".arp-compact .arp-row{grid-template-columns:calc(var(--u)*2.1) calc(var(--u)*1.05) minmax(0,1fr) minmax(0,.8fr) calc(var(--u)*6.8);grid-template-areas:\"rank st name bar val\";row-gap:0}",
      ".arp-row>.arp-rank{grid-area:rank;font-size:min(calc(var(--u)*1),calc(var(--rh)*.3));color:var(--c-muted)}",
      ".arp-rank>span{display:block;width:calc(var(--u)*1.05);height:calc(var(--u)*1.05)}",
      ".arp-st{display:block;width:calc(var(--u)*.95);height:calc(var(--u)*.95)}",
      ".arp-row>.arp-st{grid-area:st}",
      ".arp-row>.arp-name{grid-area:name;min-width:0;font-size:min(calc(var(--u)*1.45),calc(var(--rh)*.33));font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".arp-compact .arp-name{font-size:min(calc(var(--u)*1.25),calc(var(--rh)*.42))}",
      ".arp-house .arp-name{font-weight:400;color:var(--c-muted)}",
      ".arp-row>.arp-bb{grid-area:bar;position:relative;height:min(calc(var(--u)*.55),calc(var(--rh)*.14))}",
      ".arp-compact .arp-bb{height:min(calc(var(--u)*1.1),calc(var(--rh)*.36))}",
      ".arp-zero{position:absolute;top:-45%;bottom:-45%;width:1px;margin-left:-.5px;background:var(--c-muted);opacity:.6}",
      ".arp-bar{position:absolute;top:0;bottom:0;left:0;width:0;background:var(--c-up)}",
      ".arp-bar.arp-neg{background:var(--c-down)}",
      ".arp-house .arp-bar{opacity:.38}",
      ".arp-row>.arp-val{grid-area:val;text-align:right;white-space:nowrap;font-size:min(calc(var(--u)*1.3),calc(var(--rh)*.31))}",
      ".arp-compact .arp-val{font-size:min(calc(var(--u)*1.15),calc(var(--rh)*.4))}",
      ".arp-pos{color:var(--c-up)}.arp-neg{color:var(--c-down)}",
      ".arp-house .arp-val{opacity:.72}",
      ".arp-lead{background:var(--c-raise)}",
      ".arp-lead::before{content:\"\";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c-gold)}",
      ".arp-lead .arp-rank{color:var(--c-gold);font-weight:600}",
      // settled: the race takes the results' order (see sortRace)
      ".arp-rby{display:none;margin-left:auto;color:var(--c-accent)}",
      ".arp-final .arp-rby{display:inline}",
      ".arp-rfoot{flex:none;display:flex;flex-wrap:wrap;gap:calc(var(--u)*.4) calc(var(--u)*1.1);padding:calc(var(--u)*.55) calc(var(--u)*.8);border-top:1px solid var(--c-line);font-size:max(var(--fmin),calc(var(--u)*.74));color:var(--c-muted)}",
      ".arp-rfoot>span{display:flex;align-items:center;gap:calc(var(--u)*.35)}",
      ".arp-rfoot i{display:block;width:calc(var(--u)*.85);height:calc(var(--u)*.85)}",
      // order book and tape
      // books at most 18u, and at most ~a quarter each, so a scaled-up or
      // narrow screen still leaves the tape some room
      ".arp-bottom{grid-area:bottom;min-height:0;display:grid;grid-template-columns:repeat(var(--na),minmax(0,min(calc(var(--u)*18),24%))) minmax(0,1fr);gap:var(--gap)}",
      ".arp-ladder{flex:1 1 auto;min-height:0;display:grid;grid-template-rows:repeat(11,minmax(0,1fr));padding:calc(var(--u)*.35) 0}",
      ".arp-lr{display:grid;grid-template-columns:minmax(0,1fr) calc(var(--u)*5.6) minmax(0,1fr);font-size:max(var(--fmin),calc(var(--u)*.95))}",
      ".arp-lq{position:relative;display:flex;align-items:center;padding:0 calc(var(--u)*.55);overflow:hidden}",
      ".arp-lq.arp-b{justify-content:flex-end}",
      ".arp-lq i{position:absolute;top:12%;bottom:12%;width:0;opacity:.3}",
      ".arp-lq.arp-b i{right:0;background:var(--c-up)}",
      ".arp-lq.arp-a i{left:0;background:var(--c-down)}",
      ".arp-lq span{position:relative}",
      ".arp-lp{display:flex;align-items:center;justify-content:center}",
      ".arp-ask .arp-lp{color:var(--c-down)}.arp-bid .arp-lp{color:var(--c-up)}",
      ".arp-best{background:var(--c-raise)}.arp-best .arp-lp{font-weight:600}",
      ".arp-lmid{display:flex;align-items:center;gap:calc(var(--u)*.5);padding:0 calc(var(--u)*.8);font-size:max(var(--fmin),calc(var(--u)*.74));color:var(--c-muted);white-space:nowrap}",
      ".arp-lmid::before,.arp-lmid::after{content:\"\";flex:1;height:1px;background:var(--c-line)}",
      ".arp-trows{flex:1 1 auto;min-height:0;overflow:hidden;padding:calc(var(--u)*.2) 0}",
      ".arp-tr{display:grid;grid-template-columns:var(--tcols);column-gap:calc(var(--u)*.6);align-items:center;height:var(--trh,calc(var(--u)*1.5));padding:0 calc(var(--u)*.8);font-size:max(var(--fmin),calc(var(--u)*.92));white-space:nowrap}",
      ".arp-tr>span{min-width:0;overflow:hidden;text-overflow:ellipsis}",
      ".arp-thead{flex:none;height:calc(var(--u)*1.7);border-bottom:1px solid var(--c-grid);font-size:max(var(--fmin),calc(var(--u)*.66));font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--c-muted)}",
      ".arp-tt,.arp-ta{color:var(--c-muted)}",
      ".arp-td>span{display:block;width:calc(var(--u)*.8);height:calc(var(--u)*.8)}",
      ".arp-tn{font-family:" + sans + "}",
      ".arp-tn.arp-th{color:var(--c-muted)}",
      ".arp-tn.arp-tag{font-weight:600}",
      ".arp-tar{color:var(--c-muted);text-align:center}",
      ".arp-tq,.arp-tp{text-align:right}",
      // results
      ".arp-res{position:absolute;inset:0;z-index:5;display:none;align-items:center;justify-content:center;padding:var(--pad);background:var(--c-bg)}",
      ".arp-res.arp-open{display:flex}",
      ".arp-card{position:relative;width:min(calc(var(--u)*64),100%);max-height:100%;display:flex;flex-direction:column;background:var(--c-panel);border:1px solid var(--c-line);border-top:3px solid var(--c-accent)}",
      ".arp-card-h{flex:none;display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.9) calc(var(--u)*1.4);border-bottom:1px solid var(--c-line)}",
      ".arp-card-h>.arp-troph{flex:none;width:calc(var(--u)*1.6);height:calc(var(--u)*1.6);color:var(--c-gold)}",
      ".arp-card-h .arp-k{flex:none;font-family:" + mono + ";font-size:calc(var(--u)*.85);font-weight:600;letter-spacing:.2em;text-transform:uppercase;white-space:nowrap;color:var(--c-accent)}",
      ".arp-card-h .arp-rt{min-width:0;font-size:calc(var(--u)*1.5);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".arp-card-h .arp-btn{margin-left:auto}",
      ".arp-tbl{flex:1 1 auto;min-height:0;overflow-y:auto;padding:calc(var(--u)*.3) 0 calc(var(--u)*.5)}",
      ".arp-rr{position:relative;display:grid;grid-template-columns:calc(var(--u)*3) calc(var(--u)*1.1) minmax(0,1fr) calc(var(--u)*8.6) calc(var(--u)*8.6) calc(var(--u)*9.2);column-gap:calc(var(--u)*.9);align-items:center;height:var(--rrh,calc(var(--u)*2.6));padding:0 calc(var(--u)*1.4);font-size:calc(var(--u)*1.12)}",
      ".arp-rr.arp-hd{height:calc(var(--u)*2.1);font-size:max(var(--fmin),calc(var(--u)*.7));font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--c-muted)}",
      ".arp-rr>span{min-width:0}",
      ".arp-num{text-align:right;white-space:nowrap}",
      ".arp-rk{font-weight:600;color:var(--c-muted)}",
      ".arp-rk>span{width:calc(var(--u)*1.05);height:calc(var(--u)*1.05);display:block}",
      ".arp-nm{display:flex;align-items:center;gap:calc(var(--u)*.5);font-weight:600;white-space:nowrap;overflow:hidden}",
      ".arp-nm>b{min-width:0;font-weight:inherit;overflow:hidden;text-overflow:ellipsis}",
      ".arp-nm>span{flex:none;width:calc(var(--u)*1.1);height:calc(var(--u)*1.1);color:var(--c-gold)}",
      ".arp-sc{font-weight:600}",
      ".arp-p1 .arp-rk{color:var(--c-gold)}.arp-p2 .arp-rk{color:var(--c-silver)}.arp-p3 .arp-rk{color:var(--c-bronze)}",
      ".arp-win{height:calc(var(--rrh,calc(var(--u)*2.6))*1.3);background:var(--c-raise);font-size:calc(var(--u)*1.4)}",
      ".arp-win::before{content:\"\";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--c-gold)}",
      ".arp-hse{color:var(--c-muted)}.arp-hse .arp-nm{font-weight:400}.arp-hse .arp-pos,.arp-hse .arp-neg{color:var(--c-muted)}",
      ".arp-sep{height:1px;margin:calc(var(--u)*.4) calc(var(--u)*1.4);background:var(--c-line)}",
      ".arp-card-f{flex:none;display:flex;flex-wrap:wrap;gap:calc(var(--u)*.4) calc(var(--u)*1.6);padding:calc(var(--u)*.7) calc(var(--u)*1.4);border-top:1px solid var(--c-line);font-size:max(var(--fmin),calc(var(--u)*.8));color:var(--c-muted)}",
      // a narrow card (a phone) drops Max DD, then PnL, so the names and
      // the score keep their room (see layout())
      ".arp-rmid .arp-rr{grid-template-columns:calc(var(--u)*2.2) calc(var(--u)*1.1) minmax(0,1fr) calc(var(--u)*6.6) calc(var(--u)*6.6);column-gap:calc(var(--u)*.6);padding:0 calc(var(--u)*.9)}",
      ".arp-rmid .arp-cdd{display:none}",
      ".arp-rmid .arp-card-h,.arp-rmid .arp-card-f{padding-left:calc(var(--u)*.9);padding-right:calc(var(--u)*.9)}",
      ".arp-rmid .arp-sep{margin-left:calc(var(--u)*.9);margin-right:calc(var(--u)*.9)}",
      ".arp-rmin .arp-rr{grid-template-columns:calc(var(--u)*2.2) calc(var(--u)*1.1) minmax(0,1fr) calc(var(--u)*6.6)}",
      ".arp-rmin .arp-cpnl{display:none}",
      ".arp-res.arp-open .arp-anim{animation:arp-in .5s cubic-bezier(.2,.75,.2,1) both;animation-delay:var(--d,0s)}",
      "@keyframes arp-in{from{opacity:0;transform:translateY(calc(var(--u)*.8))}to{opacity:1;transform:none}}",
      // narrow screens: stack and scroll
      ".arp-narrow .arp-head{display:flex;flex-wrap:wrap;justify-content:space-between;height:auto;row-gap:calc(var(--u)*.6);padding:calc(var(--u)*.7) var(--pad)}",
      ".arp-narrow .arp-hl{order:-1;flex-basis:100%}",
      ".arp-narrow .arp-body{display:flex;flex-direction:column;overflow-y:auto}",
      ".arp-narrow.arp-resopen .arp-body{overflow-y:hidden}",
      ".arp-narrow .arp-charts{flex:none;height:calc(var(--u)*24*var(--na))}",
      ".arp-narrow .arp-race{flex:none}",
      ".arp-narrow .arp-rows{flex:none;height:calc(var(--rh)*var(--np))}",
      ".arp-narrow .arp-bottom{flex:none;display:flex;flex-direction:column}",
      ".arp-narrow .arp-book,.arp-narrow .arp-tape{height:calc(var(--u)*18)}",
      "@media (prefers-reduced-motion:reduce){.arp *{animation:none!important;transition:none!important}}",
    ].join("\n");
  }

  function injectStyle(doc) {
    if (doc.getElementById(STYLE_ID)) {
      return;
    }
    const style = doc.createElement("style");
    style.id = STYLE_ID;
    style.textContent = css();
    (doc.head || doc.documentElement).appendChild(style);
  }

  // ------------------------------------------------------------ canvas marks

  function shapePath(ctx, shape, x, y, r) {
    if (shape === 0) {
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, TAU);
    } else if (shape === 1) {
      const d = r * 1.22;
      ctx.moveTo(x, y - d);
      ctx.lineTo(x + d, y);
      ctx.lineTo(x, y + d);
      ctx.lineTo(x - d, y);
      ctx.closePath();
    } else if (shape === 2) {
      const d = r * 0.9;
      ctx.rect(x - d, y - d, d * 2, d * 2);
    } else if (shape === 3) {
      const d = r * 1.15;
      ctx.moveTo(x - d, y);
      ctx.lineTo(x + d, y);
      ctx.moveTo(x, y - d);
      ctx.lineTo(x, y + d);
    } else if (shape === 4) {
      for (let k = 0; k < 6; k++) {
        const a = -Math.PI / 2 + k * Math.PI / 3;
        if (k === 0) {
          ctx.moveTo(x + r * 1.05 * Math.cos(a), y + r * 1.05 * Math.sin(a));
        } else {
          ctx.lineTo(x + r * 1.05 * Math.cos(a), y + r * 1.05 * Math.sin(a));
        }
      }
      ctx.closePath();
    } else if (shape === 5) {
      const d = r * 0.85;
      ctx.moveTo(x - d, y - d);
      ctx.lineTo(x + d, y + d);
      ctx.moveTo(x + d, y - d);
      ctx.lineTo(x - d, y + d);
    } else {
      ctx.moveTo(x, y - r * 1.1);
      ctx.lineTo(x + r, y + r * 0.75);
      ctx.lineTo(x - r, y + r * 0.75);
      ctx.closePath();
    }
  }

  // Trades: up triangle = buyer crossed the spread, down = seller did.
  function tradePath(ctx, dir, x, y, r) {
    if (dir > 0) {
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r * 0.95, y + r * 0.7);
      ctx.lineTo(x - r * 0.95, y + r * 0.7);
      ctx.closePath();
    } else if (dir < 0) {
      ctx.moveTo(x, y + r);
      ctx.lineTo(x + r * 0.95, y - r * 0.7);
      ctx.lineTo(x - r * 0.95, y - r * 0.7);
      ctx.closePath();
    } else {
      ctx.moveTo(x + r * 0.7, y);
      ctx.arc(x, y, r * 0.7, 0, TAU);
    }
  }

  // One closed band between ask (top) and bid (bottom) over ticks a..b.
  function bandSegment(ctx, a, b, bid, ask, X, Y, kx) {
    if (a === b) {
      const half = Math.max(0.75, kx / 2);
      ctx.rect(X(a) - half, Y(ask[a]), half * 2, Y(bid[a]) - Y(ask[a]));
      return;
    }
    ctx.moveTo(X(a), Y(ask[a]));
    for (let i = a + 1; i <= b; i++) {
      ctx.lineTo(X(i), Y(ask[i]));
    }
    for (let i = b; i >= a; i--) {
      ctx.lineTo(X(i), Y(bid[i]));
    }
    ctx.closePath();
  }

  // A line through series[from..to], broken wherever the value is missing.
  function strokeSeries(ctx, series, from, to, X, Y, style, width) {
    ctx.beginPath();
    let pen = false;
    for (let i = from; i <= to; i++) {
      const v = series[i];
      if (v === v) {
        if (pen) {
          ctx.lineTo(X(i), Y(v));
        } else {
          ctx.moveTo(X(i), Y(v));
          pen = true;
        }
      } else {
        pen = false;
      }
    }
    ctx.strokeStyle = style;
    ctx.lineWidth = width;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
  }

  // Trades i0..i1-1 that involve a team (team = 1) or only house bots
  // (team = 0), one batched path per direction. ring > 0 draws a surface-
  // coloured ring first so overlapping marks stay readable.
  function drawTrades(ctx, tr, i0, i1, team, X, Y, radius, alpha, ring, colors) {
    const dirs = [1, -1, 0];
    for (const dir of dirs) {
      ctx.beginPath();
      let any = false;
      for (let i = i0; i < i1; i++) {
        if (tr.team[i] === team && tr.g[i] === dir) {
          tradePath(ctx, dir, X(tr.t[i]), Y(tr.p[i]), radius(tr.q[i]));
          any = true;
        }
      }
      if (any) {
        if (ring > 0) {
          ctx.lineJoin = "round";
          ctx.lineWidth = ring;
          ctx.strokeStyle = colors.panel;
          ctx.stroke();
        }
        const tone = dir > 0 ? colors.rgb.up : (dir < 0 ? colors.rgb.down : colors.rgb.fg);
        ctx.fillStyle = rgba(tone, alpha);
        ctx.fill();
      }
    }
  }

  // A hint marker, or a chevron on the edge when it is off the scale.
  function hintMark(ctx, shape, x, y, r, top, bottom) {
    if (y < top + r) {
      const yy = top + r * 0.6;
      ctx.moveTo(x - r, yy + r * 0.5);
      ctx.lineTo(x, yy - r * 0.5);
      ctx.lineTo(x + r, yy + r * 0.5);
    } else if (y > bottom - r) {
      const yy = bottom - r * 0.6;
      ctx.moveTo(x - r, yy - r * 0.5);
      ctx.lineTo(x, yy + r * 0.5);
      ctx.lineTo(x + r, yy - r * 0.5);
    } else {
      shapePath(ctx, shape, x, y, r);
    }
  }

  function priceTag(ctx, y, text, bg, fg, x, width, height, u) {
    ctx.fillStyle = bg;
    ctx.fillRect(x, Math.round(y - height / 2), width, height);
    ctx.fillStyle = fg;
    ctx.fillText(text, x + u * 0.6, y + 0.5);
  }

  // ------------------------------------------------------------------ mount

  function mount(container, replay, options) {
    if (!container || container.nodeType !== 1) {
      throw new Error("AlgoReplay.mount needs a DOM element to draw into");
    }
    const problems = validate(replay);
    if (problems.length) {
      throw new Error("Not a playable replay: " + problems.join("; "));
    }
    const opts = Object.assign({}, DEFAULTS, options || {});
    const speeds = [];
    for (const v of asArray(opts.speeds)) {
      if (isNum(v) && v > 0 && speeds.length < 9) {
        speeds.push(v);
      }
    }
    if (!speeds.length) {
      speeds.push.apply(speeds, DEFAULTS.speeds);
    }
    const tps = isNum(opts.ticksPerSecond) && opts.ticksPerSecond > 0 ? opts.ticksPerSecond : DEFAULTS.ticksPerSecond;
    const askedScale = Number(opts.scale);
    const scale = isNum(askedScale) && askedScale > 0 ? clamp(askedScale, 0.5, 2) : 1;
    // times the scale in effect (layout() may give less than asked for)
    let fontMin = Math.round(FONT_MIN * scale);
    const doc = container.ownerDocument;
    const win = doc.defaultView || window;
    injectStyle(doc);
    const M = prepare(replay);
    const multi = M.assets.length > 1;

    function mk(tag, cls, parent, text) {
      const node = doc.createElement(tag);
      if (cls) {
        node.className = cls;
      }
      if (text !== undefined && text !== null) {
        node.textContent = text;
      }
      if (parent) {
        parent.appendChild(node);
      }
      return node;
    }

    // markup is always one of the constant icons above, never replay data
    function icon(markup, cls, parent, tag) {
      const node = mk(tag || "span", cls, parent);
      node.innerHTML = markup;
      return node;
    }

    function button(parent, cls, markup, title, onClick) {
      const b = mk("button", cls, parent);
      b.type = "button";
      b.title = title;
      b.setAttribute("aria-label", title);
      icon(markup, null, b);
      b.addEventListener("click", function () {
        onClick();
        b.blur();
      });
      return b;
    }

    const S = {
      pos: 0, tick: 0, playing: false, speed: speeds[0], started: false,
      peek: false, final: false, revealAt: 0, revealP: 0, resultsAt: 0,
      resultsOpen: false, resultsShown: false, snap: true, forceDom: true,
      needLayout: false, lastSort: -1e9, raceChanged: true, frames: 0,
    };
    if (speeds.indexOf(opts.speed) >= 0) {
      S.speed = opts.speed;
    }
    let U = 16;
    let RH = 40;
    let axisSample = "000.00";
    let destroyed = false;
    let raf = 0;
    let lastNow = 0;
    let errorLogged = false;
    let dprSeen = win.devicePixelRatio || 1;

    // the clock requestAnimationFrame's timestamps use
    function clockNow() {
      return win.performance ? win.performance.now() : Date.now();
    }

    // ---------------------------------------------------------- the page
    const rootEl = mk("div", "arp arp-noanim");
    rootEl.setAttribute("role", "application");
    rootEl.setAttribute("aria-label", "Replay: " + M.title);
    rootEl.style.setProperty("--na", String(M.assets.length));
    rootEl.style.setProperty("--np", String(M.parts.length));
    rootEl.style.setProperty("--fmin", fontMin + "px");
    for (const k of Object.keys(asObject(opts.theme))) {
      if (THEME[k] !== undefined) {
        rootEl.style.setProperty("--arp-" + k, String(opts.theme[k]));
      }
    }

    // header
    const head = mk("header", "arp-head", rootEl);
    const hl = mk("div", "arp-hl", head);
    // Top left: a square and ALGODAY, or what the page passes as
    // opts.brand = {href, logo, logoAlt, label} (the site's logo, linking home).
    const brandOpt = asObject(opts.brand);
    const brandHref = typeof brandOpt.href === "string" ? brandOpt.href : "";
    const brandLogo = typeof brandOpt.logo === "string" ? brandOpt.logo : "";
    const brand = mk(brandHref ? "a" : "div", brandLogo ? "arp-brand arp-brand-mark" : "arp-brand", hl);
    if (brandHref) {
      brand.href = brandHref;
    }
    if (brandLogo) {
      const logo = mk("img", "arp-brand-logo", brand);
      logo.src = brandLogo;
      logo.alt = typeof brandOpt.logoAlt === "string" ? brandOpt.logoAlt : "";
      // An image can be dragged, and a page may take any drop for a replay
      // file (the VS Code tab's page and the site's Replays tab do).
      logo.draggable = false;
    } else {
      mk("i", null, brand);
    }
    const brandLabel = typeof brandOpt.label === "string" ? brandOpt.label : "ALGODAY";
    if (brandLabel) {
      mk("span", "arp-brand-label", brand, brandLabel);
    }
    const tb = mk("div", "arp-tb", hl);
    const titleEl = mk("div", "arp-title", tb, M.title);
    titleEl.title = M.title;
    for (const A of M.assets) {
      mk("span", "arp-chip arp-m", tb, A.name);
    }
    if (M.seed !== null) {
      mk("span", "arp-seed arp-m", tb, "seed " + M.seed);
    }
    const clock = mk("div", "arp-clock arp-m", head);
    mk("span", "arp-tl", clock, "TICK");
    const tNow = mk("span", "arp-tnow", clock, "");
    mk("span", "arp-tof", clock, "/ " + M.T);
    mk("span", "arp-badge", clock, "SETTLED");
    const ctrls = mk("div", "arp-ctrls", head);
    button(ctrls, "arp-btn", ICON.restart, "Restart (R)", function () { ctl.restart(); });
    const bPlay = button(ctrls, "arp-btn arp-play", ICON.play, "Play / pause (space)", function () { ctl.toggle(); });
    const speedBox = mk("div", "arp-speeds arp-m", ctrls);
    const speedBtns = [];
    for (let i = 0; i < speeds.length; i++) {
      const v = speeds[i];
      const b = mk("button", null, speedBox, v + TIMES);
      b.type = "button";
      b.title = "Speed " + v + TIMES + (i < 9 ? " (" + (i + 1) + ")" : "");
      b.addEventListener("click", function () {
        ctl.setSpeed(v);
        b.blur();
      });
      speedBtns.push(b);
    }
    const bEye = button(ctrls, "arp-btn", ICON.eye, "Show true value (V)", function () { ctl.reveal(); });
    // No button where the page may not go fullscreen (a frame without
    // permission, such as a VS Code tab): it would do nothing.
    if (doc.fullscreenEnabled !== false) {
      button(ctrls, "arp-btn", ICON.full, "Fullscreen (F)", function () { ctl.fullscreen(); });
    }

    // scrubber
    const scrub = mk("div", "arp-scrub", rootEl);
    scrub.setAttribute("role", "slider");
    scrub.setAttribute("aria-label", "Tick");
    scrub.setAttribute("aria-valuemin", "1");
    scrub.setAttribute("aria-valuemax", String(M.T));
    const track = mk("div", "arp-track", scrub);
    const fill = mk("div", "arp-fill", track);
    const knob = mk("div", "arp-knob", track);

    // body
    const body = mk("div", "arp-body", rootEl);
    const chartsBox = mk("div", "arp-charts", body);
    const charts = [];
    for (let ai = 0; ai < M.assets.length; ai++) {
      charts.push(makeChart(ai));
    }
    button(chartsBox, "arp-big", ICON.play, "Play (space)", function () { ctl.play(); });

    const raceP = mk("section", "arp-panel arp-race", body);
    const rph = mk("div", "arp-ph", raceP);
    mk("span", null, rph, "PnL");
    // rank numbers and a gold leader, unless this is an unranked PnL race
    // (by default when there is no results card: e.g. one sample market of
    // a round, whose order isn't the round's)
    const raceRanks = opts.raceRanks === null || opts.raceRanks === undefined ? !!opts.showResults : !!opts.raceRanks;
    // settled, the race takes the results card's order (see sortRace)
    const rankedRace = M.hasRanks && !!opts.showResults && raceRanks;
    if (rankedRace) {
      mk("span", "arp-rby", rph, "ranked by score");
    }
    const rowsBox = mk("div", "arp-rows", raceP);
    const rows = [];
    for (const part of M.parts) {
      rows.push(makeRaceRow(part));
    }
    // The legend: house first, then each status, shown once some row shows
    // it (so a bot that crashes late isn't given away at tick 1). Hidden
    // items keep their space, so the footer never changes height.
    const legendItems = {};
    const shownStatuses = ["ok", "crashed", "timeout", "disqualified"].filter(function (s) { return M.statuses.has(s); });
    if (shownStatuses.length > 1 || M.house.length) {
      const foot = mk("div", "arp-rfoot", raceP);
      if (M.house.length) {
        const item = mk("span", null, foot);
        icon(ICON.house, null, item, "i");
        mk("span", null, item, "house bot");
      }
      for (const s of shownStatuses) {
        const item = mk("span", null, foot);
        icon(STATUS_ICON[s], "arp-k-" + STATUS[s].tone, item, "i");
        mk("span", null, item, s);
        legendItems[s] = item;
      }
    }
    updateLegend();

    const bottom = mk("div", "arp-bottom", body);
    const books = [];
    for (let ai = 0; ai < M.assets.length; ai++) {
      books.push(makeBook(ai));
    }
    const tapeP = mk("section", "arp-panel arp-tape", bottom);
    const tph = mk("div", "arp-ph", tapeP);
    mk("span", null, tph, "Tape");
    // A narrow tape with several assets tags them with the shortest prefix
    // that tells them apart (WDCC/UOA -> W/U), leaving room for names.
    function prefixesDiffer(len) {
      const seen = new Set();
      for (const A of M.assets) {
        seen.add(A.name.slice(0, len));
      }
      return seen.size === M.assets.length;
    }
    let tagLen = 1;
    while (tagLen < 3 && !prefixesDiffer(tagLen)) {
      tagLen += 1;
    }
    const canTag = multi && prefixesDiffer(tagLen);
    let tapeTags = false;
    function setTapeCols(tags) {
      tapeTags = tags;
      let tcols = "calc(var(--u)*3.6) ";
      if (multi) {
        // in tape-row font units (.arp-tr), so the header lines up too
        const tagW = "calc(max(var(--fmin),calc(var(--u)*.92))*" + (tagLen * 0.62 + 0.3).toFixed(2) + ") ";
        tcols += tags ? tagW : "calc(var(--u)*4.6) ";
      }
      tcols += "calc(var(--u)*.8) minmax(0,1fr) calc(var(--u)*.9) minmax(0,1fr) calc(var(--u)*2.6) calc(var(--u)*5)";
      tapeP.style.setProperty("--tcols", tcols);
    }
    setTapeCols(false);
    const thead = mk("div", "arp-tr arp-thead", tapeP);
    mk("span", null, thead, "t");
    if (multi) {
      mk("span", null, thead, "");
    }
    mk("span", null, thead, "");
    mk("span", null, thead, "buyer");
    mk("span", null, thead, "");
    mk("span", null, thead, "seller");
    mk("span", "arp-tq", thead, "qty");
    mk("span", "arp-tp", thead, "price");
    const tapeBox = mk("div", "arp-trows arp-m", tapeP);
    let tapeRows = [];
    let tapeEnd = -1;

    const res = mk("div", "arp-res", body);
    buildResults();

    container.appendChild(rootEl);

    // colours for the canvas, resolved from the CSS variables
    const C = { rgb: {} };
    (function readColors() {
      const probe = doc.createElement("canvas").getContext("2d");
      const cs = win.getComputedStyle(rootEl);
      for (const k of Object.keys(THEME)) {
        const rgb = probe ? rgbOf(probe, cs.getPropertyValue("--c-" + k).trim(), THEME[k]) : [128, 128, 128];
        C.rgb[k] = rgb;
        C[k] = rgba(rgb, 1);
      }
      C.askLine = blend(C.rgb.down, C.rgb.panel, 0.5);
      C.bidLine = blend(C.rgb.up, C.rgb.panel, 0.5);
    })();

    // ------------------------------------------------------------ builders

    function makeChart(ai) {
      const A = M.assets[ai];
      const panel = mk("section", "arp-panel arp-chart", chartsBox);
      const ph = mk("div", "arp-ph", panel);
      mk("span", "arp-sym arp-m", ph, A.name);
      const px = mk("span", "arp-px arp-m", ph, "");
      const tvl = mk("span", "arp-px arp-tvl arp-m", ph, "");
      if (ai === 0) {
        buildLegend(ph);
      }
      const box = mk("div", "arp-cv", panel);
      const canvas = mk("canvas", null, box);
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", A.name + " price chart");
      const tip = mk("div", "arp-tip", box);
      // offscreen copy of the market marks drawn so far (see drawMarket)
      const layer = doc.createElement("canvas");
      const c = {
        ai: ai, A: A, panel: panel, px: px, tvl: tvl, box: box, canvas: canvas,
        ctx: canvas.getContext("2d"), tip: tip, w: 0, h: 0, dpr: 1, lo: NaN, hi: NaN,
        tLo: NaN, tHi: NaN, layer: layer, lctx: layer.getContext("2d"), layerKey: "",
        layerTick: -1, hoverX: -1, hoverY: -1, hoverAt: 0, dirty: true,
        showX: ai === M.assets.length - 1, pxText: null, tvText: null, tipKey: "",
      };
      canvas.addEventListener("pointermove", function (e) {
        const r = canvas.getBoundingClientRect();
        c.hoverX = e.clientX - r.left;
        c.hoverY = e.clientY - r.top;
        c.hoverAt = clockNow();
        c.dirty = true;
      });
      canvas.addEventListener("pointerleave", function () {
        c.hoverX = -1;
        c.dirty = true;
      });
      return c;
    }

    function legendItem(parent, markup, tone, label) {
      const item = mk("span", null, parent);
      icon(markup, tone, item, "i");
      mk("span", null, item, label);
      return item;
    }

    function buildLegend(ph) {
      const lg = mk("div", "arp-legend", ph);
      legendItem(lg, LEGEND_SVG.band, "arp-k-fg", "bid/ask");
      legendItem(lg, LEGEND_SVG.mid, "arp-k-fg", "mid");
      legendItem(lg, LEGEND_SVG.buy, "arp-k-up", "buy");
      legendItem(lg, LEGEND_SVG.sell, "arp-k-down", "sell");
      for (const s of M.sources) {
        const markup = "<svg viewBox=\"0 0 16 16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\">" + SHAPE_SVG[s.shape] + "</svg>";
        legendItem(lg, markup, "arp-k-hint", s.name);
      }
      legendItem(lg, LEGEND_SVG.tv, "arp-k-accent", "true value").classList.add("arp-lgtv");
    }

    function makeRaceRow(part) {
      const house = part.kind === "house";
      const r = mk("div", "arp-row" + (house ? " arp-house" : ""), rowsBox);
      const rank = mk("span", "arp-rank arp-m", r);
      if (house) {
        icon(ICON.house, null, rank);
        rank.title = "house bot";
      }
      const st = mk("span", "arp-st", r);
      const name = mk("span", "arp-name", r, part.name);
      name.title = part.name;
      const bb = mk("span", "arp-bb", r);
      const zero = mk("i", "arp-zero", bb);
      const bar = mk("i", "arp-bar", bb);
      const val = mk("span", "arp-val arp-m", r, "");
      const row = {
        part: part, house: house, el: r, rank: rank, st: st, stShown: "", bar: bar, zero: zero,
        val: val, v: NaN, slot: -1, valText: "", valSign: 2, rankText: "", lead: false,
        barNeg: false, barL: "", barW: "", zeroL: "",
      };
      setRowStatus(row, statusAt(part, 0));
      return row;
    }

    // ok until the tick the bot was stopped at, then its final status
    function statusAt(part, t) {
      return part.stoppedAt !== null && t < part.stoppedAt ? "ok" : part.status;
    }

    function setRowStatus(r, status) {
      const info = statusInfo(status);
      r.stShown = status;
      r.st.className = "arp-st arp-k-" + info.tone;
      r.st.innerHTML = STATUS_ICON[info.icon];
      r.st.title = status + (status === r.part.status && r.part.detail ? " (" + r.part.detail + ")" : "");
    }

    function updateLegend() {
      const showing = new Set();
      for (const r of rows) {
        showing.add(r.stShown);
      }
      for (const s of Object.keys(legendItems)) {
        legendItems[s].style.visibility = showing.has(s) ? "" : "hidden";
      }
    }

    // a ring in the status colour as a bot is stopped mid-match
    function flashRow(r, status) {
      if (typeof r.el.animate === "function") {
        const tone = C.rgb[statusInfo(status).tone] || C.rgb.down;
        r.el.animate([{ boxShadow: "inset 0 0 0 2px " + rgba(tone, 0.95) }, { boxShadow: "inset 0 0 0 2px " + rgba(tone, 0) }],
          { duration: 1600, easing: "ease-out" });
      }
    }

    function makeBook(ai) {
      const A = M.assets[ai];
      const p = mk("section", "arp-panel arp-book", bottom);
      const ph = mk("div", "arp-ph", p);
      mk("span", null, ph, "Book");
      mk("span", "arp-sym arp-m", ph, A.name);
      const ladder = mk("div", "arp-ladder arp-m", p);
      const lrows = [];
      let spread = null;
      for (let i = 0; i < 11; i++) {
        if (i === 5) {
          spread = mk("div", "arp-lmid", ladder, "");
        } else {
          const r = mk("div", "arp-lr " + (i < 5 ? "arp-ask" : "arp-bid"), ladder);
          const bq = mk("span", "arp-lq arp-b", r);
          const bbar = mk("i", null, bq);
          const btxt = mk("span", null, bq);
          const pr = mk("span", "arp-lp", r);
          const aq = mk("span", "arp-lq arp-a", r);
          const abar = mk("i", null, aq);
          const atxt = mk("span", null, aq);
          lrows.push({ el: r, bbar: bbar, btxt: btxt, pr: pr, abar: abar, atxt: atxt, key: "" });
        }
      }
      return { A: A, rows: lrows, spread: spread, spreadText: null };
    }

    function buildResults() {
      const card = mk("div", "arp-card", res);
      const ch = mk("div", "arp-card-h", card);
      icon(ICON.trophy, "arp-troph", ch);
      // "RESULTS" unless the page says what this match is (e.g. "FINAL")
      const label = typeof opts.resultsLabel === "string" ? opts.resultsLabel.trim().slice(0, 24) : "";
      mk("span", "arp-k", ch, label || DEFAULTS.resultsLabel);
      mk("span", "arp-rt", ch, M.title);
      button(ch, "arp-btn", ICON.close, "Close (Esc)", function () { ctl.results(false); });
      const tbl = mk("div", "arp-tbl", card);
      const hd = mk("div", "arp-rr arp-hd", tbl);
      mk("span", null, hd, "#");
      mk("span", null, hd, "");
      mk("span", null, hd, "Team");
      mk("span", "arp-num arp-cpnl", hd, "PnL");
      mk("span", "arp-num arp-cdd", hd, "Max DD");
      mk("span", "arp-num", hd, "Score");
      const teamRows = M.results.filter(function (r) { return r.part.kind !== "house"; });
      const nTeams = teamRows.length;
      let seenHouse = false;
      for (const R of M.results) {
        const house = R.part.kind === "house";
        if (house && !seenHouse && nTeams) {
          mk("div", "arp-sep", tbl);
        }
        seenHouse = seenHouse || house;
        let cls = "arp-rr arp-anim";
        if (house) {
          cls += " arp-hse";
        }
        if (!house && R.rank !== null && R.rank <= 3) {
          cls += " arp-p" + R.rank;
        }
        const win1 = !house && R.rank === 1;
        if (win1) {
          cls += " arp-win";
        }
        const r = mk("div", cls, tbl);
        const rk = mk("span", "arp-rk arp-m", r);
        if (house) {
          icon(ICON.house, null, rk);
        } else {
          rk.textContent = R.rank === null ? DASH : String(R.rank);
        }
        const info = statusInfo(R.status);
        const st = icon(STATUS_ICON[info.icon], "arp-st arp-k-" + info.tone, r);
        st.title = R.status;
        const nm = mk("span", "arp-nm", r);
        if (win1) {
          icon(ICON.trophy, null, nm);
        }
        const nb = mk("b", null, nm, R.part.name);
        nb.title = R.part.name;
        moneyCell(r, R.pnl, true, "arp-num arp-m arp-cpnl");
        moneyCell(r, isNum(R.mdd) ? -R.mdd : NaN, false, "arp-num arp-m arp-cdd");
        moneyCell(r, R.score, true, "arp-num arp-m arp-sc");
        // rows arrive bottom-up: last place first, the winner last
        let delay = 0.1;
        if (!house) {
          const j = teamRows.indexOf(R);
          delay = 0.35 + (nTeams - 1 - j) * 0.2 + (win1 ? 0.55 : 0);
        }
        r.style.setProperty("--d", delay.toFixed(2) + "s");
      }
      const cf = mk("div", "arp-card-f arp-m", card);
      if (M.lambda !== null) {
        mk("span", null, cf, "score = PnL " + MINUS + " " + M.lambda + " " + TIMES + " max drawdown");
      }
      if (M.seed !== null) {
        mk("span", null, cf, "seed " + M.seed);
      }
      mk("span", null, cf, M.T + " ticks");
      res.addEventListener("click", function (e) {
        if (e.target === res) {
          ctl.results(false);
        }
      });
    }

    function moneyCell(parent, v, signed, cls) {
      const sign = isNum(v) ? signOf(v, 2) : 0;
      let c = cls;
      if (sign > 0 && signed) {
        c += " arp-pos";
      }
      if (sign < 0) {
        c += " arp-neg";
      }
      return mk("span", c, parent, fmtMoney(v, 2, signed));
    }

    // ------------------------------------------------------------- layout

    function layout() {
      S.needLayout = false;
      const W = rootEl.clientWidth;
      const H = rootEl.clientHeight;
      if (!W || !H) {
        return;
      }
      const narrow = W < 900;
      rootEl.classList.toggle("arp-narrow", narrow);
      // 16px at 1920x1080; shrinks a little slower than the screen so a
      // laptop stays readable (the chart takes up the slack). options.scale
      // on top: browser zoom shrinks the CSS viewport, so it barely helps.
      // A scale above 1 goes only as far as the screen has room for.
      const base = narrow ? 12 : clamp(16 * Math.pow(Math.min(W / 1920, H / 1080), 0.8), 9, 40);
      U = base * scale;
      if (scale > 1) {
        U = Math.max(base, fitU(W, H, narrow, base, U));
      }
      rootEl.style.setProperty("--u", U.toFixed(3) + "px");
      fontMin = Math.round(FONT_MIN * U / base);
      rootEl.style.setProperty("--fmin", fontMin + "px");
      // the results card's width in u: a narrow one drops Max DD, then PnL,
      // so each name keeps 8u (css(): the full row takes 37.8u, without
      // Max DD 20.7u, the score alone 13.5u)
      const cardU = Math.min(64, W / U - 1.8);
      rootEl.classList.toggle("arp-rmid", cardU < 46);
      rootEl.classList.toggle("arp-rmin", cardU < 28.7);
      const n = Math.max(1, M.parts.length);
      RH = narrow ? U * 3.4 : Math.min(U * 4.8, rowsBox.clientHeight / n);
      rowsBox.style.setProperty("--rh", RH.toFixed(2) + "px");
      rowsBox.classList.toggle("arp-compact", RH < U * 2.9);
      // results rows share what the card leaves: its padding, head, table
      // header, separator, footer line and borders (see css())
      let wide = 0;
      for (const R of M.results) {
        wide += R.part.kind !== "house" && R.rank === 1 ? 0.3 : 0;
      }
      const resFixed = U * 11.2 + 1.25 * Math.max(fontMin, U * 0.8) + 10;
      const resRows = Math.max(1, M.results.length + wide);
      res.style.setProperty("--rrh", clamp((body.clientHeight - resFixed) / resRows, U * 1.6, U * 2.9).toFixed(2) + "px");
      if (canTag && tapeP.clientWidth > 0 && (tapeP.clientWidth < U * 36) !== tapeTags) {
        setTapeCols(!tapeTags);
        tapeEnd = -1;
      }
      buildTapeRows();
      for (const c of charts) {
        resizeChart(c);
      }
      for (const r of rows) {
        r.slot = -1;
      }
      S.forceDom = true;
    }

    // The biggest u from `base` (scale 1) up to `hi` that the screen has
    // room for. A stacked (narrow) layout needs 30u across. The wide one
    // needs 72u across for the header, each tape name 4.5u and each book
    // quantity 2.4u, and the charts at least 30% of the height. In step with
    // css(): .arp-head 4.4u, .arp-scrub 1.2u, the body's padding and gaps,
    // its 33u race column and 19u bottom row, .arp-ph 2.3u, the books'
    // 18u/24% cap and the tape's columns (setTapeCols). No room even for
    // base: base.
    function fitU(W, H, narrow, base, hi) {
      if (narrow) {
        return Math.min(hi, W / 30);
      }
      if (roomFor(hi, W, H, base)) {
        return hi;
      }
      let a = base;
      let b = hi;
      for (let i = 0; i < 24; i++) {
        const mid = (a + b) / 2;
        if (roomFor(mid, W, H, base)) {
          a = mid;
        } else {
          b = mid;
        }
      }
      return a;
    }

    function roomFor(u, W, H, base) {
      const na = M.assets.length;
      const main = W - u * 35.5;
      const book = Math.min(u * 18, main * 0.24);
      const tape = main - na * (book + u * 0.7) - 2;
      let fixed = u * 18.1;
      if (multi) {
        const tagged = canTag && tape < u * 36;
        const tagW = Math.max(Math.round(FONT_MIN * u / base), u * 0.92) * (tagLen * 0.62 + 0.3);
        fixed += u * 0.6 + (tagged ? tagW : u * 4.6);
      }
      const names = (tape - fixed) / 2;
      const qty = (book - 2) / 2 - u * 2.8;
      const charts = H - u * (26.55 + (na - 1) * 0.7 + na * 2.3) - na * 2;
      return W >= u * 72 && names >= u * 4.5 && qty >= u * 2.4 && charts >= H * 0.3;
    }

    function resizeChart(c) {
      const w = c.box.clientWidth;
      const h = c.box.clientHeight;
      const dpr = win.devicePixelRatio || 1;
      if (w === c.w && h === c.h && dpr === c.dpr) {
        return;
      }
      c.w = w;
      c.h = h;
      c.dpr = dpr;
      c.canvas.width = Math.max(1, Math.round(w * dpr));
      c.canvas.height = Math.max(1, Math.round(h * dpr));
      c.layer.width = c.canvas.width;
      c.layer.height = c.canvas.height;
      c.layerKey = "";
      c.dirty = true;
    }

    function buildTapeRows() {
      const avail = tapeBox.clientHeight;
      const want = clamp(Math.floor(avail / (U * 1.45)), 1, 10);
      tapeBox.style.setProperty("--trh", (avail > 0 ? Math.min(U * 1.9, avail / want) : U * 1.5).toFixed(2) + "px");
      if (want === tapeRows.length) {
        return;
      }
      while (tapeBox.firstChild) {
        tapeBox.removeChild(tapeBox.firstChild);
      }
      tapeRows = [];
      for (let i = 0; i < want; i++) {
        const r = mk("div", "arp-tr", tapeBox);
        const row = {
          el: r, t: mk("span", "arp-tt", r), a: multi ? mk("span", "arp-ta", r) : null,
          d: mk("span", "arp-td", r), b: mk("span", "arp-tn", r), arrow: mk("span", "arp-tar", r, "→"),
          s: mk("span", "arp-tn", r), q: mk("span", "arp-tq", r), p: mk("span", "arp-tp", r), dir: 2,
        };
        tapeRows.push(row);
      }
      tapeEnd = -1;
    }

    // -------------------------------------------------------- dom updates

    function tvVisible() {
      return S.peek || S.final;
    }

    function updateClock() {
      tNow.textContent = String(S.tick + 1).padStart(M.digits, "0");
      scrub.setAttribute("aria-valuenow", String(S.tick + 1));
      rootEl.classList.toggle("arp-late", !S.final && M.T >= 20 && S.tick >= Math.floor(M.T * 0.95));
    }

    function updateScrub() {
      const pct = (M.T > 1 ? S.pos / (M.T - 1) * 100 : 100).toFixed(3) + "%";
      if (fill.style.width !== pct) {
        fill.style.width = pct;
        knob.style.left = pct;
      }
    }

    function updateRaceValues(now, force) {
      const t = S.tick;
      let statusMoved = false;
      for (const r of rows) {
        const v = r.part.eq[t];
        if (v !== r.v || force) {
          r.v = v;
          S.raceChanged = true;
          const mode = r.house ? M.houseEqMode : M.eqMode;
          const text = fmtMoney(v, mode, true);
          if (text !== r.valText) {
            r.valText = text;
            r.val.textContent = text;
          }
          const sign = signOf(v, mode);
          if (sign !== r.valSign) {
            r.valSign = sign;
            r.val.className = "arp-val arp-m" + (sign > 0 ? " arp-pos" : (sign < 0 ? " arp-neg" : ""));
          }
        }
        const status = statusAt(r.part, t);
        if (status !== r.stShown) {
          setRowStatus(r, status);
          statusMoved = true;
          if (status !== "ok" && S.playing && !S.snap) {
            flashRow(r, status);
          }
        }
      }
      if (statusMoved) {
        updateLegend();
      }
      if (force || !S.playing || now - S.lastSort >= RACE_SORT_MS) {
        S.lastSort = now;
        sortRace(force || !S.playing);
      }
    }

    // A PnL race while the match plays. Once it has settled, teams take
    // their places from the results instead (ranked by score, ties share a
    // rank, gold on the winner), house bots below, so the race never
    // contradicts the results card. Without a results card it stays a PnL
    // race to the end (unranked, unless raceRanks says otherwise).
    // exact: sort strictly by PnL. Otherwise (playing) a row passes the one
    // above it only when it leads by more than the margin, so rows a cent
    // apart don't swap places at every sort.
    let raceOrder = rows.slice();
    function sortRace(exact) {
      const official = S.final && rankedRace;
      let order = rows.slice();
      if (exact || S.final) {
        order.sort(function (a, b) {
          if (official && a.house !== b.house) {
            return a.house ? 1 : -1;
          }
          if (official && !a.house) {
            return a.part.resultPos - b.part.resultPos;
          }
          return (b.v - a.v) || (a.part.index - b.part.index);
        });
      } else {
        const spread = M.eqHi[S.tick] - M.eqLo[S.tick];
        const margin = Math.max(RACE_MARGIN, spread * RACE_MARGIN_SHARE);
        order = raceOrder.slice();
        for (let i = 1; i < order.length; i++) {
          const r = order[i];
          let j = i;
          while (j > 0 && r.v - order[j - 1].v > margin) {
            order[j] = order[j - 1];
            j -= 1;
          }
          order[j] = r;
        }
      }
      raceOrder = order;
      let teamRank = 0;
      for (let i = 0; i < order.length; i++) {
        const r = order[i];
        if (r.slot !== i) {
          r.slot = i;
          r.el.style.transform = "translateY(" + (i * RH).toFixed(2) + "px)";
        }
        if (!r.house) {
          teamRank += 1;
          let text = raceRanks ? String(teamRank).padStart(2, "0") : "";
          let lead = raceRanks && teamRank === 1 && S.tick > 0 && r.v > 0;
          if (official) {
            text = r.part.rank === null ? DASH : String(r.part.rank).padStart(2, "0");
            lead = r.part.rank === 1;
          }
          if (text !== r.rankText) {
            r.rankText = text;
            r.rank.textContent = text;
          }
          if (lead !== r.lead) {
            r.lead = lead;
            r.el.classList.toggle("arp-lead", lead);
          }
        }
      }
    }

    let raceLo = 0;
    let raceHi = 0;
    function updateRaceBars(dt, force) {
      const t = S.tick;
      const tLo = Math.max(0, -M.eqLo[t]);
      const tHi = Math.max(0, M.eqHi[t]);
      let changed = force || S.raceChanged;
      if (S.snap) {
        changed = changed || raceLo !== tLo || raceHi !== tHi;
        raceLo = tLo;
        raceHi = tHi;
      } else {
        const dl = tLo - raceLo;
        const dh = tHi - raceHi;
        const eps = Math.max(1e-6, (raceLo + raceHi) * 2e-4);
        if (Math.abs(dl) > eps || Math.abs(dh) > eps) {
          const k = 1 - Math.exp(-dt * 6);
          raceLo += dl * k;
          raceHi += dh * k;
          changed = true;
        } else if (dl !== 0 || dh !== 0) {
          raceLo = tLo;
          raceHi = tHi;
          changed = true;
        }
      }
      if (!changed) {
        return;
      }
      S.raceChanged = false;
      const total = Math.max(raceLo + raceHi, M.eqFloor);
      const z = raceLo / total;
      const zl = (z * 100).toFixed(2) + "%";
      for (const r of rows) {
        const v = r.v;
        let a = z;
        let b = z;
        if (v > 0) {
          b = z + v / total;
        } else if (v < 0) {
          a = z + v / total;
        }
        a = clamp(a, 0, 1);
        b = clamp(b, 0, 1);
        const left = (a * 100).toFixed(2) + "%";
        const width = ((b - a) * 100).toFixed(2) + "%";
        if (left !== r.barL) {
          r.barL = left;
          r.bar.style.left = left;
        }
        if (width !== r.barW) {
          r.barW = width;
          r.bar.style.width = width;
        }
        if (zl !== r.zeroL) {
          r.zeroL = zl;
          r.zero.style.left = zl;
        }
        const neg = v < 0;
        if (neg !== r.barNeg) {
          r.barNeg = neg;
          r.bar.classList.toggle("arp-neg", neg);
        }
      }
    }

    function bookSide(entry, side) {
      const out = [];
      const levels = Array.isArray(entry) ? asArray(entry[side]) : [];
      for (const lv of levels) {
        if (Array.isArray(lv) && isNum(lv[0]) && isNum(lv[1]) && out.length < 5) {
          out.push(lv);
        }
      }
      return out;
    }

    function updateBook(b) {
      const entry = b.A.books[S.tick];
      const bids = bookSide(entry, 0);
      const asks = bookSide(entry, 1);
      let maxQ = 1;
      for (const lv of bids) {
        maxQ = Math.max(maxQ, lv[1]);
      }
      for (const lv of asks) {
        maxQ = Math.max(maxQ, lv[1]);
      }
      for (let i = 0; i < 5; i++) {
        setLevel(b.rows[i], null, asks[4 - i] || null, maxQ, i === 4);
        setLevel(b.rows[5 + i], bids[i] || null, null, maxQ, i === 0);
      }
      let text = "spread " + DASH;
      if (bids.length && asks.length) {
        text = "spread " + (asks[0][0] - bids[0][0]).toFixed(2);
      }
      if (text !== b.spreadText) {
        b.spreadText = text;
        b.spread.textContent = text;
      }
    }

    function setLevel(row, bid, ask, maxQ, best) {
      const lv = bid || ask;
      const key = (bid ? "b" : "a") + (lv ? lv[0] + ":" + lv[1] : "-") + (best ? "*" : "") + ":" + maxQ;
      if (key === row.key) {
        return;
      }
      row.key = key;
      row.pr.textContent = lv ? fmtPrice(lv[0]) : (best ? DASH : "");
      row.btxt.textContent = bid ? fmtQty(bid[1]) : "";
      row.atxt.textContent = ask ? fmtQty(ask[1]) : "";
      row.bbar.style.width = bid ? (bid[1] / maxQ * 100).toFixed(1) + "%" : "0";
      row.abar.style.width = ask ? (ask[1] / maxQ * 100).toFixed(1) + "%" : "0";
      row.el.classList.toggle("arp-best", best && !!lv);
    }

    function updateTape(force) {
      const end = M.tradeEnd[S.tick];
      if (end === tapeEnd && !force) {
        return;
      }
      const fresh = S.playing && tapeEnd >= 0 && end > tapeEnd && S.speed <= 4 ? Math.min(end - tapeEnd, tapeRows.length) : 0;
      tapeEnd = end;
      const all = M.trades;
      for (let i = 0; i < tapeRows.length; i++) {
        const row = tapeRows[i];
        const idx = end - 1 - i;
        if (idx < 0) {
          row.el.style.visibility = "hidden";
        } else {
          row.el.style.visibility = "";
          row.t.textContent = String(all.t[idx] + 1);
          if (row.a) {
            const asset = M.assets[all.ai[idx]].name;
            row.a.textContent = tapeTags ? asset.slice(0, tagLen) : asset;
            row.a.title = asset;
          }
          const g = all.g[idx];
          if (g !== row.dir) {
            row.dir = g;
            row.d.innerHTML = "";
            if (g !== 0) {
              icon(g > 0 ? LEGEND_SVG.buy : LEGEND_SVG.sell, g > 0 ? "arp-k-up" : "arp-k-down", row.d);
            }
          }
          tapeName(row.b, all.b[idx], g > 0);
          tapeName(row.s, all.s[idx], g < 0);
          row.q.textContent = fmtQty(all.q[idx]);
          row.p.textContent = fmtPrice(all.p[idx]);
          if (i < fresh && typeof row.el.animate === "function") {
            row.el.animate([{ backgroundColor: C.raise }, { backgroundColor: "rgba(0,0,0,0)" }], { duration: 700, easing: "ease-out" });
          }
        }
      }
    }

    const partByPid = new Map();
    for (const p of M.parts) {
      partByPid.set(p.pid, p);
    }

    function tapeName(node, pid, aggressor) {
      const part = partByPid.get(pid);
      const name = part ? part.name : (pid >= 0 ? "#" + pid : DASH);
      if (node.textContent !== name) {
        node.textContent = name;
        node.title = name;
      }
      node.className = "arp-tn" + (part && part.kind === "house" ? " arp-th" : "") + (aggressor ? " arp-tag" : "");
    }

    function updateChartHead(c) {
      const A = c.A;
      const t = S.tick;
      let price = A.mid[t];
      if (!isNum(price)) {
        price = isNum(A.bid[t]) ? A.bid[t] : A.ask[t];
      }
      const text = fmtPrice(price);
      if (text !== c.pxText) {
        c.pxText = text;
        c.px.textContent = text;
      }
      let tvText = "";
      if (S.final && S.revealP >= 1) {
        tvText = "true " + fmtPrice(A.tv[M.T - 1]);
      } else if (S.peek && !S.final) {
        tvText = "true " + fmtPrice(A.tv[t]);
      }
      if (tvText !== c.tvText) {
        c.tvText = tvText;
        c.tvl.textContent = tvText;
      }
    }

    // ------------------------------------------------------------- chart

    // Price range to show: bid, ask and trades so far (plus the true value
    // once it's visible), padded. It only moves when the data gets near an
    // edge, so the cached market layer is rarely redrawn from scratch.
    function chartTarget(c) {
      const A = c.A;
      const t = S.tick;
      let lo = A.rlo[t];
      let hi = A.rhi[t];
      if (tvVisible()) {
        const k = S.final ? M.T - 1 : t;
        lo = Math.min(isNum(lo) ? lo : Infinity, A.tvLo[k]);
        hi = Math.max(isNum(hi) ? hi : -Infinity, A.tvHi[k]);
      }
      if (!isNum(lo) || !isNum(hi)) {
        lo = A.center - 0.5;
        hi = A.center + 0.5;
      }
      const minSpan = Math.max(0.2, Math.abs(lo + hi) / 2 * 0.004);
      if (hi - lo < minSpan) {
        const mid = (lo + hi) / 2;
        lo = mid - minSpan / 2;
        hi = mid + minSpan / 2;
      }
      if (!S.snap && isNum(c.tLo)) {
        const span = c.tHi - c.tLo;
        const margin = span * 0.03;
        if (lo >= c.tLo + margin && hi <= c.tHi - margin && hi - lo > span * 0.4) {
          return [c.tLo, c.tHi];
        }
      }
      const pad = (hi - lo) * 0.14;
      c.tLo = lo - pad;
      c.tHi = hi + pad;
      return [c.tLo, c.tHi];
    }

    function updateChartScale(c, dt) {
      const target = chartTarget(c);
      if (S.snap || !isNum(c.lo)) {
        const moved = c.lo !== target[0] || c.hi !== target[1];
        c.lo = target[0];
        c.hi = target[1];
        return moved;
      }
      const dl = target[0] - c.lo;
      const dh = target[1] - c.hi;
      const eps = (c.hi - c.lo) * 2e-3;
      if (Math.abs(dl) < eps && Math.abs(dh) < eps) {
        if (dl !== 0 || dh !== 0) {
          c.lo = target[0];
          c.hi = target[1];
          return true;
        }
        return false;
      }
      const k = 1 - Math.exp(-dt * 9);
      c.lo += dl * k;
      c.hi += dh * k;
      return true;
    }

    // Plot geometry for chart c showing prices lo..hi.
    function geometry(c, lo, hi) {
      const w = c.w;
      const h = c.h;
      if (!c.ctx || w < 40 || h < 40) {
        return null;
      }
      const u = U;
      const dpr = c.dpr;
      const fs = Math.max(fontMin, Math.round(u * 0.8));
      const font = "500 " + fs + "px " + MONO;
      c.ctx.font = font;
      const axisW = Math.ceil(c.ctx.measureText(axisSample).width + u * 1.4);
      const L = Math.round(u * 0.6);
      const R = Math.round(w - axisW);
      const top = Math.round(u * 0.9);
      const B = Math.round(h - (c.showX ? u * 1.8 : u * 0.9));
      if (R - L < 20 || B - top < 20) {
        return null;
      }
      const ky = (B - top) / (hi - lo);
      const kx = (R - L) / M.tMax;
      return {
        w: w, h: h, u: u, dpr: dpr, fs: fs, font: font, fontBold: "600 " + fs + "px " + MONO,
        axisW: axisW, L: L, R: R, top: top, B: B, kx: kx,
        X: function (i) { return L + i * kx; },
        Y: function (p) { return B - (p - lo) * ky; },
        crisp: function (v) { return (Math.round(v * dpr) + 0.5) / dpr; },
        hint: Math.max(3.5, u * 0.4),
      };
    }

    function tradeRadius(c, G) {
      const rMin = Math.max(1.4, G.u * 0.13);
      const rMax = Math.max(3.2, G.u * 0.4);
      const qRef = c.A.qRef;
      return function (q) { return Math.min(rMax, rMin + (rMax - rMin) * Math.sqrt(q / qRef)); };
    }

    // The market marks for ticks a..b (band, bid/ask, trades, hints). Drawn
    // onto the chart's offscreen layer, where each tick is drawn once and
    // kept; while the scale is easing, the newest ticks go straight onto ctx.
    function drawMarket(ctx, c, G, a, b) {
      const A = c.A;
      const rgb = C.rgb;
      const X = G.X;
      const Y = G.Y;
      const u = G.u;
      ctx.save();
      ctx.beginPath();
      ctx.rect(G.L, G.top - u * 0.5, G.R - G.L + u * 0.5, G.B - G.top + u);
      ctx.clip();
      const from = Math.max(0, a - 1);
      const bid = A.bid;
      const ask = A.ask;
      ctx.fillStyle = rgba(rgb.fg, 0.11);
      ctx.beginPath();
      let s0 = -1;
      for (let i = from; i <= b + 1; i++) {
        const ok = i <= b && isNum(bid[i]) && isNum(ask[i]);
        if (ok && s0 < 0) {
          s0 = i;
        }
        if (!ok && s0 >= 0) {
          bandSegment(ctx, s0, i - 1, bid, ask, X, Y, G.kx);
          s0 = -1;
        }
      }
      ctx.fill();
      const edge = Math.max(1, u * 0.075);
      strokeSeries(ctx, ask, from, b, X, Y, C.askLine, edge);
      strokeSeries(ctx, bid, from, b, X, Y, C.bidLine, edge);

      const tr = A.tr;
      const i0 = a > 0 ? A.trEnd[a - 1] : 0;
      const i1 = A.trEnd[b];
      const radius = tradeRadius(c, G);
      drawTrades(ctx, tr, i0, i1, 0, X, Y, radius, 0.24, 0, C);
      drawTrades(ctx, tr, i0, i1, 1, X, Y, radius, 0.82, Math.max(1, u * 0.08), C);

      const H = A.hints;
      const h0 = a > 0 ? A.hEnd[a - 1] : 0;
      const h1 = A.hEnd[b];
      const hlw = Math.max(1.4, u * 0.11);
      for (let si = 0; si < M.sources.length; si++) {
        const src = M.sources[si];
        const r = src.frequent ? G.hint * 0.72 : G.hint;
        ctx.beginPath();
        let any = false;
        for (let i = h0; i < h1; i++) {
          if (H.s[i] === si) {
            any = true;
            hintMark(ctx, src.shape, X(H.t[i]), Y(H.v[i]), r, G.top, G.B);
          }
        }
        if (any) {
          ctx.lineJoin = "miter";
          if (!src.frequent) {
            ctx.strokeStyle = C.panel;
            ctx.lineWidth = hlw + Math.max(2, u * 0.16);
            ctx.stroke();
          }
          ctx.strokeStyle = src.frequent ? rgba(rgb.hint, src.alpha) : C.hint;
          ctx.lineWidth = src.frequent ? hlw * 0.8 : hlw;
          ctx.stroke();
        }
      }
      ctx.restore();
    }

    function drawChart(c) {
      c.dirty = false;
      const G = geometry(c, c.lo, c.hi);
      if (!G) {
        return;
      }
      const ctx = c.ctx;
      const lctx = c.lctx;
      const A = c.A;
      const t = S.tick;
      const pos = S.pos;
      const u = G.u;
      const fs = G.fs;
      const X = G.X;
      const Y = G.Y;
      const L = G.L;
      const R = G.R;
      const top = G.top;
      const B = G.B;
      const crisp = G.crisp;
      const hair = 1 / G.dpr;
      const rgb = C.rgb;

      // The cached market layer. New ticks are appended; it is redrawn from
      // scratch when the size changes, on a seek back, or once a rescale
      // has settled. While the scale eases, the old layer is stretched to
      // the new scale and only the newest ticks are drawn live.
      const sizeKey = [G.w, G.h, G.dpr, L, R, top, B].join("|");
      const sameScale = c.layerLo === c.lo && c.layerHi === c.hi;
      const settledScale = c.lo === c.tLo && c.hi === c.tHi;
      const ratio = (c.layerHi - c.layerLo) / (c.hi - c.lo);
      if (sizeKey !== c.layerKey || t < c.layerTick
          || (!sameScale && (settledScale || !(ratio > 0.5 && ratio < 2)))) {
        c.layerKey = sizeKey;
        c.layerLo = c.lo;
        c.layerHi = c.hi;
        lctx.setTransform(1, 0, 0, 1, 0, 0);
        lctx.clearRect(0, 0, c.layer.width, c.layer.height);
        lctx.setTransform(G.dpr, 0, 0, G.dpr, 0, 0);
        c.layerTick = -1;
      }
      const stale = c.layerLo !== c.lo || c.layerHi !== c.hi;
      if (!stale && t > c.layerTick) {
        drawMarket(lctx, c, G, c.layerTick + 1, t);
        c.layerTick = t;
      }

      ctx.setTransform(G.dpr, 0, 0, G.dpr, 0, 0);
      ctx.clearRect(0, 0, G.w, G.h);

      // grid, axes, labels
      const yStep = niceStep(c.hi - c.lo, Math.max(2, Math.floor((B - top) / (u * 3))));
      const yFirst = Math.ceil(c.lo / yStep - 1e-9);
      const yLast = Math.floor(c.hi / yStep + 1e-9);
      const xStep = niceStep(M.T, Math.max(2, Math.floor((R - L) / (u * 8))));
      ctx.lineWidth = hair;
      ctx.strokeStyle = C.grid;
      ctx.beginPath();
      for (let k = yFirst; k <= yLast; k++) {
        const y = crisp(Y(k * yStep));
        ctx.moveTo(L, y);
        ctx.lineTo(R, y);
      }
      for (let k = 1; k * xStep < M.T; k++) {
        const x = crisp(X(k * xStep));
        ctx.moveTo(x, top);
        ctx.lineTo(x, B);
      }
      ctx.stroke();
      ctx.strokeStyle = C.line;
      ctx.beginPath();
      ctx.moveTo(L, crisp(B));
      ctx.lineTo(R, crisp(B));
      ctx.moveTo(crisp(R), top);
      ctx.lineTo(crisp(R), B);
      ctx.stroke();
      ctx.font = G.font;
      ctx.fillStyle = C.muted;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      for (let k = yFirst; k <= yLast; k++) {
        const y = Y(k * yStep);
        if (y > top - 2 && y < B + 2) {
          ctx.fillText(fmtPrice(k * yStep), R + u * 0.6, y);
        }
      }
      if (c.showX) {
        ctx.textBaseline = "top";
        for (let k = 0; k * xStep <= M.T; k++) {
          const v = k * xStep;
          const x = X(Math.min(v, M.tMax));
          let align = "center";
          if (k === 0) {
            align = "left";
          } else if (x > R - u * 1.5) {
            align = "right";
          }
          ctx.textAlign = align;
          ctx.fillText(String(v), x, B + u * 0.45);
        }
      }

      // where we are
      ctx.strokeStyle = rgba(rgb.fg, 0.14);
      ctx.beginPath();
      ctx.moveTo(crisp(X(t)), top);
      ctx.lineTo(crisp(X(t)), B);
      ctx.stroke();

      // once the true value sweeps in, the market steps back
      const dim = S.final ? 1 - 0.6 * S.revealP : 1;
      ctx.save();
      if (stale) {
        // y_now = a * y_layer + b maps the layer's price scale onto this one
        const kyNow = (B - top) / (c.hi - c.lo);
        const a = kyNow * (c.layerHi - c.layerLo) / (B - top);
        const b = B - (c.layerLo - c.lo) * kyNow - B * a;
        ctx.setTransform(1, 0, 0, a, 0, b * G.dpr);
      } else {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
      }
      ctx.globalAlpha = dim;
      ctx.drawImage(c.layer, 0, 0);
      ctx.restore();
      if (stale && t > c.layerTick) {
        ctx.save();
        ctx.globalAlpha = dim;
        drawMarket(ctx, c, G, c.layerTick + 1, t);
        ctx.restore();
      }

      ctx.save();
      ctx.beginPath();
      ctx.rect(L, top - u * 0.5, R - L + u * 0.5, B - top + u);
      ctx.clip();

      // fresh team trades ring out briefly
      const tr = A.tr;
      const nT = A.trEnd[t];
      const radius = tradeRadius(c, G);
      const popT = 6;
      ctx.lineWidth = Math.max(1, u * 0.08);
      for (let i = nT - 1; i >= 0 && tr.t[i] > pos - popT && !S.final; i--) {
        if (tr.team[i]) {
          const f = 1 - clamp(pos - tr.t[i], 0, popT) / popT;
          const tone = tr.g[i] > 0 ? rgb.up : (tr.g[i] < 0 ? rgb.down : rgb.fg);
          ctx.strokeStyle = rgba(tone, 0.6 * f);
          ctx.beginPath();
          ctx.arc(X(tr.t[i]), Y(tr.p[i]), radius(tr.q[i]) + u * 0.15 + (1 - f) * u * 0.6, 0, TAU);
          ctx.stroke();
        }
      }

      // the mid price on top of the market, with a dark casing
      const midW = Math.max(1.6, u * 0.13);
      strokeSeries(ctx, A.mid, 0, t, X, Y, rgba(rgb.bg, 0.85 * dim), midW + Math.max(2.5, u * 0.2));
      strokeSeries(ctx, A.mid, 0, t, X, Y, rgba(rgb.fg, Math.max(0.45, 0.95 * dim)), midW);

      // new hints pop; rare sources (insider, newswire) get a direct label
      const H = A.hints;
      const nH = A.hEnd[t];
      const hr = G.hint;
      const hlw = Math.max(1.4, u * 0.11);
      const popH = 14;
      const labelT = 45;
      const labelled = new Set();
      for (let i = nH - 1; i >= 0 && H.t[i] > pos - labelT && !S.final; i--) {
        const age = clamp(pos - H.t[i], 0, labelT);
        const src = M.sources[H.s[i]];
        const x = X(H.t[i]);
        const y = clamp(Y(H.v[i]), top + hr, B - hr);
        if (age < popH && !src.frequent) {
          const f = 1 - age / popH;
          ctx.beginPath();
          shapePath(ctx, src.shape, x, y, hr * (1 + 1.4 * f));
          ctx.strokeStyle = rgba(rgb.hint, 0.85 * f);
          ctx.lineWidth = hlw;
          ctx.stroke();
        }
        if (src.rare && !labelled.has(H.s[i]) && S.speed <= 4) {
          labelled.add(H.s[i]);
          const alpha = age < labelT * 0.6 ? 1 : 1 - (age - labelT * 0.6) / (labelT * 0.4);
          const text = src.name + " " + fmtPrice(H.v[i]);
          ctx.font = G.fontBold;
          const tw = ctx.measureText(text).width;
          let lx = x + hr * 2;
          if (lx + tw + u * 0.8 > R) {
            lx = x - hr * 2 - tw - u * 0.6;
          }
          ctx.fillStyle = rgba(rgb.panel, 0.9 * alpha);
          ctx.fillRect(lx - u * 0.3, y - fs * 0.75, tw + u * 0.6, fs * 1.5);
          ctx.fillStyle = rgba(rgb.fg, alpha);
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(text, lx, y);
        }
      }

      // the true value: hidden until the end (or V)
      let tvY = NaN;
      if (tvVisible()) {
        const tv = A.tv;
        const endF = S.final ? S.revealP * M.tMax : t;
        const endI = Math.floor(endF);
        const tvw = Math.max(2.4, u * 0.22);
        ctx.beginPath();
        for (let i = 0; i <= endI; i++) {
          if (i === 0) {
            ctx.moveTo(X(i), Y(tv[i]));
          } else {
            ctx.lineTo(X(i), Y(tv[i]));
          }
        }
        let headY = Y(tv[endI]);
        if (endF > endI && endI + 1 < M.T) {
          const f = endF - endI;
          headY = Y(tv[endI] + (tv[endI + 1] - tv[endI]) * f);
          ctx.lineTo(X(endF), headY);
        }
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.strokeStyle = C.bg;
        ctx.lineWidth = tvw + Math.max(3, u * 0.22);
        ctx.stroke();
        ctx.strokeStyle = S.final ? C.accent : rgba(rgb.accent, 0.8);
        ctx.lineWidth = tvw;
        ctx.stroke();
        if (S.final && S.revealP < 1) {
          const s = Math.max(5, u * 0.5);
          ctx.fillStyle = C.accent;
          ctx.fillRect(X(endF) - s / 2, headY - s / 2, s, s);
        }
        if (S.final && S.revealP >= 1) {
          tvY = Y(tv[M.T - 1]);
          ctx.setLineDash([u * 0.45, u * 0.35]);
          ctx.strokeStyle = rgba(rgb.accent, 0.55);
          ctx.lineWidth = Math.max(1, u * 0.09);
          ctx.beginPath();
          ctx.moveTo(L, crisp(tvY));
          ctx.lineTo(R, crisp(tvY));
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.font = G.fontBold;
          const label = "TRUE VALUE";
          const lw = ctx.measureText(label).width;
          const above = tvY - top > fs * 2.4;
          const ly = above ? tvY - u * 0.45 - fs * 0.5 : tvY + u * 0.45 + fs * 0.5;
          const lx = R - u * 0.8 - lw;
          ctx.fillStyle = C.panel;
          ctx.fillRect(lx - u * 0.35, ly - fs * 0.75, lw + u * 0.7, fs * 1.5);
          ctx.fillStyle = C.accent;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(label, lx, ly);
        } else if (S.peek && !S.final) {
          tvY = Y(tv[t]);
        }
      }

      // head of the mid line
      const mt = A.mid[t];
      if (isNum(mt)) {
        const s = Math.max(4, u * 0.36);
        ctx.fillStyle = C.fg;
        ctx.fillRect(X(t) - s / 2, Y(mt) - s / 2, s, s);
      }
      ctx.restore();

      // price tags on the axis
      const tagH = Math.round(u * 1.3);
      let midY = isNum(mt) ? Y(mt) : NaN;
      if (isNum(midY) && isNum(tvY) && Math.abs(midY - tvY) < tagH) {
        midY = tvY + (midY >= tvY ? tagH : -tagH);
      }
      ctx.font = G.fontBold;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      if (isNum(midY)) {
        priceTag(ctx, clamp(midY, top, B), fmtPrice(mt), C.fg, C.bg, R, G.axisW, tagH, u);
      }
      if (isNum(tvY)) {
        const v = S.final ? A.tv[M.T - 1] : A.tv[t];
        priceTag(ctx, clamp(tvY, top, B), fmtPrice(v), C.accent, C.bg, R, G.axisW, tagH, u);
      }

      // hover: crosshair snapped to a tick, readout beside it
      if (c.hoverX >= L && c.hoverX <= R) {
        const ht = clamp(Math.round((c.hoverX - L) / G.kx), 0, t);
        const x = crisp(X(ht));
        ctx.strokeStyle = rgba(rgb.fg, 0.45);
        ctx.lineWidth = hair;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, B);
        ctx.stroke();
        showTip(c, ht, x, top);
      } else if (c.tip.style.display !== "none") {
        c.tip.style.display = "none";
        c.tipKey = "";
      }
    }

    function showTip(c, ht, x, top) {
      const A = c.A;
      const key = ht + ":" + (tvVisible() ? 1 : 0);
      if (key !== c.tipKey) {
        c.tipKey = key;
        const lines = [["t", String(ht + 1)], ["bid", fmtPrice(A.bid[ht])], ["ask", fmtPrice(A.ask[ht])]];
        const last = A.trEnd[ht] - 1;
        if (last >= 0) {
          lines.push(["last", fmtQty(A.tr.q[last]) + " @ " + fmtPrice(A.tr.p[last])]);
        }
        if (tvVisible() && (S.final || ht <= S.tick)) {
          lines.push(["true", fmtPrice(A.tv[ht])]);
        }
        while (c.tip.firstChild) {
          c.tip.removeChild(c.tip.firstChild);
        }
        for (const line of lines) {
          const row = mk("div", null, c.tip);
          mk("span", null, row, line[0]);
          mk("b", null, row, line[1]);
        }
      }
      c.tip.style.display = "block";
      const tw = c.tip.offsetWidth;
      const th = c.tip.offsetHeight;
      let left = x + U * 0.8;
      if (left + tw > c.w - U * 0.3) {
        left = x - U * 0.8 - tw;
      }
      c.tip.style.left = Math.max(0, left).toFixed(0) + "px";
      c.tip.style.top = clamp(c.hoverY - th / 2, top, Math.max(top, c.h - th - U * 0.3)).toFixed(0) + "px";
    }

    function dirtyCharts() {
      for (const c of charts) {
        c.dirty = true;
      }
    }

    // ------------------------------------------------------- reveal/end

    function settle(now) {
      S.final = true;
      S.revealAt = now;
      S.revealP = 0;
      S.resultsShown = false;
      S.resultsAt = now + Math.max(0, Number(opts.resultsDelay) || 0) * 1000;
      rootEl.classList.add("arp-final");
      rootEl.classList.remove("arp-late");
      sortRace(true);
      dirtyCharts();
      if (typeof opts.onEnd === "function") {
        safely(opts.onEnd);
      }
    }

    function unsettle() {
      S.final = false;
      S.revealP = 0;
      S.resultsShown = false;
      rootEl.classList.remove("arp-final");
      rootEl.classList.toggle("arp-tvon", S.peek);
      setResults(false);
      sortRace(true);
      dirtyCharts();
    }

    function settled() {
      rootEl.classList.add("arp-tvon");
      for (const c of charts) {
        updateChartHead(c);
        c.panel.classList.remove("arp-settle");
        void c.panel.offsetWidth;
        c.panel.classList.add("arp-settle");
      }
    }

    function setResults(on) {
      S.resultsOpen = !!on;
      res.classList.toggle("arp-open", S.resultsOpen);
      // a stacked (narrow) body scrolls, and the card covers its top: back
      // to the top, held there while the card is open
      rootEl.classList.toggle("arp-resopen", S.resultsOpen);
      if (S.resultsOpen) {
        body.scrollTop = 0;
      }
    }

    // -------------------------------------------------------------- loop

    function onTick(now, force) {
      updateClock();
      updateRaceValues(now, force);
      for (const b of books) {
        updateBook(b);
      }
      updateTape(force);
      if (S.final && S.tick < M.T - 1) {
        unsettle();
      }
      if (!S.final && S.tick >= M.T - 1 && opts.autoReveal && S.started) {
        settle(now);
      }
      for (const c of charts) {
        updateChartHead(c);
        c.dirty = true;
      }
      if (typeof opts.onTick === "function") {
        safely(opts.onTick, S.tick);
      }
    }

    function step(now) {
      const dt = lastNow ? clamp((now - lastNow) / 1000, 0, 0.1) : 0;
      lastNow = now;
      S.frames += 1;
      if (S.frames === 3) {
        rootEl.classList.remove("arp-noanim");
      }
      const dpr = win.devicePixelRatio || 1;
      if (dpr !== dprSeen || S.needLayout) {
        dprSeen = dpr;
        layout();
      }
      if (S.playing) {
        S.pos += dt * tps * S.speed;
        if (S.pos >= M.T - 1) {
          S.pos = M.T - 1;
          setPlaying(false);
        }
      }
      const tick = clamp(Math.floor(S.pos + 1e-9), 0, M.T - 1);
      const force = S.forceDom || S.snap;
      if (tick !== S.tick || force) {
        S.tick = tick;
        S.forceDom = false;
        onTick(now, force);
      }
      if (S.final) {
        const p = M.T > 1 ? clamp((now - S.revealAt) / REVEAL_MS, 0, 1) : 1;
        const eased = easeInOut(p);
        if (eased !== S.revealP) {
          const was = S.revealP;
          S.revealP = eased;
          dirtyCharts();
          if (eased >= 1 && was < 1) {
            settled();
          }
        }
        if (opts.showResults && !S.resultsShown && now >= S.resultsAt) {
          S.resultsShown = true;
          setResults(true);
        }
      }
      updateRaceBars(dt, force);
      updateScrub();
      // a mouse left resting on a chart: drop its readout once playback
      // moves on (hiding the cursor fires no pointerleave)
      if (S.playing) {
        for (const c of charts) {
          if (c.hoverX >= 0 && now - c.hoverAt > HOVER_IDLE_MS) {
            c.hoverX = -1;
            c.dirty = true;
          }
        }
      }
      // one price-axis width for every chart, so stacked charts share an x axis
      const redraw = [];
      let widest = 0;
      for (const c of charts) {
        redraw.push(updateChartScale(c, dt) || c.dirty || S.playing);
        widest = Math.max(widest, fmtPrice(Math.max(Math.abs(c.lo), Math.abs(c.hi))).length);
      }
      const sample = "0".repeat(Math.max(1, widest - 3)) + ".00";
      const resized = sample !== axisSample;
      axisSample = sample;
      for (let i = 0; i < charts.length; i++) {
        if (redraw[i] || resized) {
          drawChart(charts[i]);
        }
      }
      S.snap = false;
    }

    function frame(now) {
      if (destroyed) {
        return;
      }
      raf = win.requestAnimationFrame(frame);
      try {
        step(now);
      } catch (err) {
        if (!errorLogged && typeof console !== "undefined") {
          errorLogged = true;
          console.error("AlgoReplay frame failed:", err);
        }
      }
    }

    // ---------------------------------------------------------- controls

    function renderPlay() {
      bPlay.firstChild.innerHTML = S.playing ? ICON.pause : ICON.play;
    }

    function renderSpeeds() {
      for (let i = 0; i < speedBtns.length; i++) {
        speedBtns[i].classList.toggle("arp-on", speeds[i] === S.speed);
      }
    }

    function setPlaying(on) {
      const want = !!on && M.T > 1;
      if (want === S.playing) {
        return;
      }
      S.playing = want;
      if (want) {
        S.started = true;
        rootEl.classList.add("arp-started");
        setResults(false);
      } else {
        // a paused race shows the exact order (see sortRace)
        S.forceDom = true;
      }
      renderPlay();
    }

    function seekTo(p) {
      S.pos = clamp(isNum(p) ? p : 0, 0, M.T - 1);
      S.snap = true;
      S.started = true;
      rootEl.classList.add("arp-started");
    }

    let dragging = false;
    let wasPlaying = false;
    function seekFromPointer(e) {
      const r = track.getBoundingClientRect();
      if (r.width > 0) {
        seekTo(Math.round(clamp((e.clientX - r.left) / r.width, 0, 1) * (M.T - 1)));
      }
    }
    scrub.addEventListener("pointerdown", function (e) {
      dragging = true;
      wasPlaying = S.playing;
      setPlaying(false);
      if (scrub.setPointerCapture) {
        scrub.setPointerCapture(e.pointerId);
      }
      seekFromPointer(e);
      e.preventDefault();
    });
    scrub.addEventListener("pointermove", function (e) {
      if (dragging) {
        seekFromPointer(e);
      }
    });
    function endDrag() {
      if (dragging) {
        dragging = false;
        if (wasPlaying && S.pos < M.T - 1) {
          setPlaying(true);
        }
      }
    }
    scrub.addEventListener("pointerup", endDrag);
    scrub.addEventListener("pointercancel", endDrag);

    function onKey(e) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) {
        return;
      }
      const target = e.target;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || ""))) {
        return;
      }
      const k = e.key;
      let handled = true;
      if (k === " " || k === "Spacebar" || k === "k" || k === "K") {
        ctl.toggle();
      } else if (k === "ArrowRight") {
        ctl.step(e.shiftKey ? 50 : 1);
      } else if (k === "ArrowLeft") {
        ctl.step(e.shiftKey ? -50 : -1);
      } else if (k.length === 1 && k >= "1" && k <= "9" && Number(k) <= speeds.length) {
        ctl.setSpeed(speeds[Number(k) - 1]);
      } else if (k === "v" || k === "V") {
        ctl.reveal();
      } else if (k === "r" || k === "R") {
        ctl.restart();
      } else if (k === "Home") {
        ctl.seek(0);
      } else if (k === "End") {
        ctl.seek(M.T - 1);
      } else if (k === "f" || k === "F") {
        ctl.fullscreen();
      } else if (k === "Escape" && S.resultsOpen) {
        ctl.results(false);
      } else {
        handled = false;
      }
      if (handled) {
        e.preventDefault();
      }
    }
    if (opts.keyboard) {
      doc.addEventListener("keydown", onKey);
    }

    const ro = typeof win.ResizeObserver === "function" ? new win.ResizeObserver(function () {
      S.needLayout = true;
    }) : null;
    if (ro) {
      ro.observe(rootEl);
      for (const c of charts) {
        ro.observe(c.box);
      }
      ro.observe(tapeBox);
    } else {
      win.addEventListener("resize", onResize);
    }
    function onResize() {
      S.needLayout = true;
    }
    function onFonts() {
      if (!destroyed) {
        S.needLayout = true;
        dirtyCharts();
      }
    }
    if (doc.fonts) {
      if (doc.fonts.addEventListener) {
        doc.fonts.addEventListener("loadingdone", onFonts);
      }
      if (doc.fonts.ready) {
        doc.fonts.ready.then(onFonts);
      }
    }

    const ctl = {
      element: rootEl,
      play: function () {
        if (S.pos >= M.T - 1) {
          seekTo(0);
        }
        setPlaying(true);
      },
      pause: function () {
        setPlaying(false);
      },
      toggle: function () {
        if (S.playing) {
          ctl.pause();
        } else {
          ctl.play();
        }
      },
      seek: function (t) {
        seekTo(Math.round(Number(t)) || 0);
      },
      step: function (n) {
        setPlaying(false);
        seekTo(Math.floor(S.pos + 1e-9) + (Math.round(Number(n)) || 0));
      },
      setSpeed: function (x) {
        const v = Number(x);
        if (isNum(v) && v > 0) {
          S.speed = v;
          renderSpeeds();
        }
      },
      restart: function () {
        seekTo(0);
        setPlaying(true);
      },
      reveal: function (on) {
        S.peek = on === undefined ? !S.peek : !!on;
        rootEl.classList.toggle("arp-tvon", S.peek || (S.final && S.revealP >= 1));
        bEye.classList.toggle("arp-on", S.peek);
        for (const c of charts) {
          updateChartHead(c);
        }
        dirtyCharts();
      },
      results: function (on) {
        setResults(on === undefined ? !S.resultsOpen : !!on);
      },
      fullscreen: function () {
        let done = null;
        if (doc.fullscreenElement) {
          done = doc.exitFullscreen ? doc.exitFullscreen() : null;
        } else if (rootEl.requestFullscreen) {
          done = rootEl.requestFullscreen();
        }
        if (done && typeof done.catch === "function") {
          done.catch(function () {});
        }
      },
      getTick: function () {
        return S.tick;
      },
      isPlaying: function () {
        return S.playing;
      },
      getSpeed: function () {
        return S.speed;
      },
      destroy: function () {
        if (destroyed) {
          return;
        }
        destroyed = true;
        win.cancelAnimationFrame(raf);
        if (ro) {
          ro.disconnect();
        } else {
          win.removeEventListener("resize", onResize);
        }
        doc.removeEventListener("keydown", onKey);
        if (doc.fonts && doc.fonts.removeEventListener) {
          doc.fonts.removeEventListener("loadingdone", onFonts);
        }
        if (rootEl.parentNode) {
          rootEl.parentNode.removeChild(rootEl);
        }
      },
    };

    // reachable from devtools: document.querySelector(".arp").algoReplay
    rootEl.algoReplay = ctl;

    // first frame right away, so the page is never blank
    renderPlay();
    renderSpeeds();
    layout();
    step(win.performance ? win.performance.now() : Date.now());
    lastNow = 0;
    raf = win.requestAnimationFrame(frame);
    if (opts.autoplay) {
      ctl.play();
    }
    return ctl;
  }

  return {
    version: VERSION,
    mount: mount,
    validate: validate,
    prepare: prepare,
    defaults: Object.assign({}, DEFAULTS),
  };
}));
