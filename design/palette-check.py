#!/usr/bin/env python3
"""
Colour-vision check for the design tokens in README.md.

    python3 palette-check.py

Answers three questions the token tables assert but do not prove:

1. Are the five data series distinguishable from each other under normal vision
   and under the three dichromacies? (CIEDE2000 between every pair.)
2. Is each series visible against the panel it is drawn on? (WCAG contrast.)
3. Is the data palette really disjoint from the state hues, or does it only look
   that way to trichromats?

Dichromat simulation is Viénot, Brettel & Mollon (1999) — the standard linear-RGB
LMS projection. It models *dichromacy*, the severe case; anomalous trichromacy is
milder, so passing here is the conservative result.

Standard library only, on purpose: this is a precursor to the Tier-1 palette lint,
and that lint should not drag in a numerics stack.
"""

from __future__ import annotations

import math
from itertools import combinations

# --- tokens, mirrored from README.md ---------------------------------------
# Kept as literals rather than parsed out of the mockups: if the two ever drift,
# a failing check here is the signal, and a parser would hide it.

# Published Okabe-Ito, minus its bluish-green (the only entry inside the teal band
# the rail reserves) and minus its yellow (unusable on a near-white panel), with the
# neutral promoted into the fifth slot. Identical in both themes: a neutral fifth is
# the only reason that's possible, and it's why the light theme needs no variant.
SERIES = {
    "dark": ["#0072b2", "#e69f00", "#56b4e9", "#d55e00", "#7f7f7f"],
    "light": ["#0072b2", "#e69f00", "#56b4e9", "#d55e00", "#7f7f7f"],
}

STATE = {
    "dark": {"teal": "#57d3cb", "violet": "#a78bfa", "amber": "#e8b568", "red": "#e8737d"},
    "light": {"teal": "#0d8f86", "violet": "#6b4de0", "amber": "#a8730c", "red": "#c33f4b"},
}

PANEL = {"dark": "#17171c", "light": "#faf9f7"}

# Thresholds calibrated against published palettes — run `calibrate` to see the
# working. A flat "10 ΔE00 everywhere" bar is not achievable: no accepted palette
# clears it under tritanopia, and Okabe-Ito 5, the canonical reference, peaks at
# 8.5 there. Red-green deficiency is what "colourblind-safe" means in practice
# (deuteranopia and protanopia together are ~99% of cases), so those get the
# strict bar and tritanopia gets best-in-class.
MIN_DELTA = {
    "normal": 20.0,
    "protanopia": 12.0,
    "deuteranopia": 12.0,
    "tritanopia": 8.0,
}

# WCAG 1.4.11's 3:1 applies to a graphical object that must be distinguished from
# its background to understand the content. A series in a legend-bearing chart is
# distinguished from the *other series*, which is what MIN_DELTA governs; against
# the panel it only needs to be visible. 3:1 is also unmeetable on paper-white for
# any true yellow — Okabe-Ito's own yellow is 1.26:1 on white — so demanding it
# turns every warm hue to mud in light mode.
CONTRAST_MIN = 2.0

# Margin the tuner insists on before it starts trading separation for chroma, so
# the shipped palette is not sitting exactly on the threshold it has to pass.
TARGET_HEADROOM = 0.0


# --- colour conversion -----------------------------------------------------

def to_rgb(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def linearise(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def delinearise(c: float) -> float:
    c = min(max(c, 0.0), 1.0)
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def relative_luminance(hex_colour: str) -> float:
    r, g, b = (linearise(c) for c in to_rgb(hex_colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def to_lab(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = (linearise(c) for c in to_rgb(hex_colour))
    # sRGB -> XYZ, D65
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    # D65 white point
    xn, yn, zn = 0.95047, 1.00000, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(c1: str, c2: str) -> float:
    """CIEDE2000, the current CIE recommendation for perceptual difference."""
    l1, a1, b1 = to_lab(c1)
    l2, a2, b2 = to_lab(c2)

    kl = kc = kh = 1.0
    cc1, cc2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_bar = (cc1 + cc2) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7))) if c_bar else 0.0

    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(ap: float, bp: float) -> float:
        if ap == 0 and bp == 0:
            return 0.0
        return math.degrees(math.atan2(bp, ap)) % 360

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dhp_term = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)

    lp_bar = (l1 + l2) / 2
    cp_bar = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hp_bar = (h1p + h2p + 360) / 2
    else:
        hp_bar = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(hp_bar - 30))
        + 0.24 * math.cos(math.radians(2 * hp_bar))
        + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
        - 0.20 * math.cos(math.radians(4 * hp_bar - 63))
    )
    d_theta = 30 * math.exp(-(((hp_bar - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cp_bar**7 / (cp_bar**7 + 25**7)) if cp_bar else 0.0
    sl = 1 + (0.015 * (lp_bar - 50) ** 2) / math.sqrt(20 + (lp_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc

    return math.sqrt(
        (dlp / (kl * sl)) ** 2
        + (dcp / (kc * sc)) ** 2
        + (dhp_term / (kh * sh)) ** 2
        + rt * (dcp / (kc * sc)) * (dhp_term / (kh * sh))
    )


# --- dichromat simulation --------------------------------------------------
# Viénot, Brettel & Mollon (1999), "Digital video colourmaps for checking the
# legibility of displays by dichromats". Applied to LINEAR rgb — applying it to
# gamma-encoded values is a common bug and shifts every result.

RGB_TO_LMS = (
    (17.8824, 43.5161, 4.11935),
    (3.45565, 27.1554, 3.86714),
    (0.0299566, 0.184309, 1.46709),
)

LMS_TO_RGB = (
    (0.0809444479, -0.130504409, 0.116721066),
    (-0.0102485335, 0.0540193266, -0.113614708),
    (-0.000365296938, -0.00412161469, 0.693511405),
)

CONFUSION = {
    # each maps (l, m, s) -> the dichromat's collapsed (l, m, s)
    "protanopia": lambda l, m, s: (2.02344 * m - 2.52581 * s, m, s),
    "deuteranopia": lambda l, m, s: (l, 0.494207 * l + 1.24827 * s, s),
    "tritanopia": lambda l, m, s: (l, m, -0.395913 * l + 0.801109 * m),
}


def _matmul(matrix, vec):
    return tuple(sum(row[i] * vec[i] for i in range(3)) for row in matrix)


def simulate(hex_colour: str, kind: str) -> str:
    if kind == "normal":
        return hex_colour
    linear = tuple(linearise(c) for c in to_rgb(hex_colour))
    lms = _matmul(RGB_TO_LMS, linear)
    collapsed = CONFUSION[kind](*lms)
    out = _matmul(LMS_TO_RGB, collapsed)
    return "#" + "".join(f"{round(delinearise(c) * 255):02x}" for c in out)


# --- report ----------------------------------------------------------------

VISIONS = ("normal", "protanopia", "deuteranopia", "tritanopia")


def check_series(theme: str) -> list[str]:
    problems = []
    colours = SERIES[theme]
    print(f"\n=== {theme}: series separation (CIEDE2000, {len(colours)} colours) ===")
    for vision in VISIONS:
        sim = [simulate(c, vision) for c in colours]
        pairs = [((i, j), ciede2000(sim[i], sim[j])) for i, j in combinations(range(len(sim)), 2)]
        (i, j), delta = min(pairs, key=lambda p: p[1])
        floor = MIN_DELTA[vision]
        ok = delta >= floor
        print(
            f"  {vision:13s} worst pair series-{i + 1}/series-{j + 1} "
            f"ΔE00 {delta:5.1f} (need {floor:4.1f})  {'ok' if ok else 'FAIL'}"
            f"   first two: {next(d for (p, d) in pairs if p == (0, 1)):5.1f}"
        )
        if not ok:
            problems.append(
                f"{theme}/{vision}: series-{i + 1} vs series-{j + 1} "
                f"ΔE00 {delta:.1f} < {floor:.0f}"
            )
    return problems


def check_contrast(theme: str) -> list[str]:
    problems = []
    panel = PANEL[theme]
    print(f"\n=== {theme}: contrast against panel {panel} (need >= {CONTRAST_MIN}:1) ===")
    for n, colour in enumerate(SERIES[theme], 1):
        ratio = contrast_ratio(colour, panel)
        ok = ratio >= CONTRAST_MIN
        print(f"  series-{n}  {colour}  {ratio:4.2f}:1  {'ok' if ok else 'FAIL'}")
        if not ok:
            problems.append(f"{theme}: series-{n} contrast {ratio:.2f}:1 on {panel}")
    return problems


def check_disjoint(theme: str) -> None:
    print(f"\n=== {theme}: nearest state hue to each series ===")
    for n, colour in enumerate(SERIES[theme], 1):
        row = []
        for vision in VISIONS:
            sim_series = simulate(colour, vision)
            nearest = min(
                ((name, ciede2000(sim_series, simulate(hexv, vision))) for name, hexv in STATE[theme].items()),
                key=lambda pair: pair[1],
            )
            row.append(f"{vision[:5]}:{nearest[0]} {nearest[1]:.0f}")
        print(f"  series-{n}  " + "   ".join(row))


# --- search ----------------------------------------------------------------
# How the palette above was chosen. Dichromacy collapses hue but never lightness,
# so a categorical palette that has to survive it must separate on L* first. The
# search maximises the worst pair distance across all four visions at once.

XYZ_TO_RGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)

RESERVED_HALF_WIDTH = 28.0  # degrees of CIELAB hue kept clear around teal/violet


def lab_to_hex(lab: tuple[float, float, float]) -> str | None:
    """None when the colour falls outside the sRGB gamut."""
    ell, a, b = lab
    fy = (ell + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def g(t: float) -> float:
        return t**3 if t**3 > 216 / 24389 else (108 / 841) * (t - 4 / 29)

    x, y, z = g(fx) * 0.95047, g(fy) * 1.00000, g(fz) * 1.08883
    linear = _matmul(XYZ_TO_RGB, (x, y, z))
    if any(c < -0.001 or c > 1.001 for c in linear):
        return None
    return "#" + "".join(f"{round(delinearise(c) * 255):02x}" for c in linear)


def lab_hue(hex_colour: str) -> float:
    _, a, b = to_lab(hex_colour)
    return math.degrees(math.atan2(b, a)) % 360


def lab_chroma(hex_colour: str) -> float:
    _, a, b = to_lab(hex_colour)
    return math.hypot(a, b)


def hue_is_clear(hue: float, reserved: list[float]) -> bool:
    return all(min(abs(hue - r), 360 - abs(hue - r)) > RESERVED_HALF_WIDTH for r in reserved)


def worst_pair(sims: list[dict[str, str]]) -> float:
    """Smallest CIEDE2000 between any two colours under any vision."""
    return min(
        ciede2000(sims[i][vision], sims[j][vision])
        for i, j in combinations(range(len(sims)), 2)
        for vision in VISIONS
    )


def headroom(sims: list[dict[str, str]]) -> float:
    """
    Worst margin above the per-vision floor. Positive means every pair clears its
    threshold under every vision; maximising this spends effort where the bar is
    actually tight instead of over-serving tritanopia at red-green's expense.
    """
    return min(
        ciede2000(sims[i][vision], sims[j][vision]) - MIN_DELTA[vision]
        for i, j in combinations(range(len(sims)), 2)
        for vision in VISIONS
    )


def search(theme: str, size: int = 5) -> list[str]:
    panel = PANEL[theme]
    reserved = [lab_hue(STATE[theme]["teal"]), lab_hue(STATE[theme]["violet"])]
    lightness = range(34, 90, 3) if theme == "dark" else range(28, 78, 3)

    pool = []
    for ell in lightness:
        for chroma in range(16, 82, 4):
            for hue in range(0, 360, 5):
                if not hue_is_clear(hue, reserved):
                    continue
                lab = (
                    float(ell),
                    chroma * math.cos(math.radians(hue)),
                    chroma * math.sin(math.radians(hue)),
                )
                hexv = lab_to_hex(lab)
                if hexv is None or contrast_ratio(hexv, panel) < CONTRAST_MIN:
                    continue
                pool.append(hexv)
    pool = sorted(set(pool))
    sims = {c: {v: simulate(c, v) for v in VISIONS} for c in pool}
    print(f"  {theme}: {len(pool)} in-gamut candidates outside the reserved hue bands")

    # Farthest-point insertion, then hill-climb one slot at a time. Ties broken
    # toward higher chroma so the winner is vivid rather than merely safe.
    chosen = [max(pool, key=lambda c: contrast_ratio(c, panel))]
    while len(chosen) < size:
        chosen.append(
            max(
                (c for c in pool if c not in chosen),
                key=lambda c: (worst_pair([sims[x] for x in chosen + [c]]), lab_chroma(c)),
            )
        )

    best = worst_pair([sims[c] for c in chosen])
    improved = True
    while improved:
        improved = False
        for slot in range(size):
            for candidate in pool:
                if candidate in chosen:
                    continue
                trial = list(chosen)
                trial[slot] = candidate
                score = worst_pair([sims[c] for c in trial])
                gain = score - best
                if gain > 1e-9 or (
                    abs(gain) < 1e-9
                    and lab_chroma(candidate) > lab_chroma(chosen[slot])
                ):
                    chosen, best = trial, score
                    improved = True

    # Order by lightness so series-1 is the most legible slot.
    chosen.sort(key=lambda c: -to_lab(c)[0] if theme == "dark" else to_lab(c)[0])
    print(f"  {theme}: worst pair across all four visions ΔE00 {best:.1f}")
    print(f"  {theme}: {' '.join(chosen)}")
    return chosen


# --- tune ------------------------------------------------------------------
# The search above maximises the metric and produces acid lime. This mode instead
# starts from Okabe-Ito — a palette with two decades of use behind it — drops the
# one entry that lands in the reserved teal band, and re-tunes lightness and
# chroma per surface while holding the hues fixed. Fixed hues are what make
# series-1 the same series in both themes.

OKABE_ITO = {
    "orange": "#e69f00",
    "sky": "#56b4e9",
    "bluegreen": "#009e73",  # Lab hue 164 — inside the reserved teal band
    "blue": "#0072b2",
    "vermillion": "#d55e00",
    "yellow": "#f0e442",
    "redpurple": "#cc79a7",
}


def tune_theme(theme: str, subset: tuple[str, ...], usable: dict[str, str], verbose: bool = False):
    """
    Fit one surface: hues fixed, lightness and chroma free. Returns
    (palette, headroom, drift) or None when no palette on those hues clears the bar.
    """
    panel = PANEL[theme]
    size = len(subset)
    anchors = [usable[n] for n in subset]
    hues = [lab_hue(a) for a in anchors]

    options = []
    for hue in hues:
        candidates = []
        for ell in range(24, 96, 2):
            for chroma in range(10, 100, 3):
                hexv = lab_to_hex(
                    (
                        float(ell),
                        chroma * math.cos(math.radians(hue)),
                        chroma * math.sin(math.radians(hue)),
                    )
                )
                if hexv and contrast_ratio(hexv, panel) >= CONTRAST_MIN:
                    candidates.append(hexv)
        if not candidates:
            return None
        options.append(sorted(set(candidates)))

    sims = {c: {v: simulate(c, v) for v in VISIONS} for opts in options for c in opts}

    chosen = [max(opts, key=lambda c: contrast_ratio(c, panel)) for opts in options]
    best = headroom([sims[c] for c in chosen])
    improved = True
    while improved:
        improved = False
        for slot in range(size):
            for candidate in options[slot]:
                trial = list(chosen)
                trial[slot] = candidate
                score = headroom([sims[c] for c in trial])
                if score > best + 1e-9:
                    chosen, best, improved = trial, score, True

    if best < TARGET_HEADROOM:
        return None

    def drift(palette: list[str]) -> float:
        return sum(ciede2000(c, a) for c, a in zip(palette, anchors))

    current = drift(chosen)
    improved = True
    while improved:
        improved = False
        for slot in range(size):
            for candidate in options[slot]:
                trial = list(chosen)
                trial[slot] = candidate
                if headroom([sims[c] for c in trial]) < TARGET_HEADROOM:
                    continue
                score = drift(trial)
                if score < current - 1e-9:
                    chosen, current, improved = trial, score, True

    return chosen, headroom([sims[c] for c in chosen]), current


def tune(size: int = 5) -> None:
    reserved = {t: [lab_hue(STATE[t]["teal"]), lab_hue(STATE[t]["violet"])] for t in PANEL}
    usable = {
        name: hexv
        for name, hexv in OKABE_ITO.items()
        if all(hue_is_clear(lab_hue(hexv), reserved[t]) for t in PANEL)
    }
    dropped = sorted(set(OKABE_ITO) - set(usable))
    print(f"dropped for landing in a reserved hue band: {', '.join(dropped) or 'none'}")
    print(f"usable Okabe-Ito hues: {', '.join(sorted(usable))}\n")

    # Choose the hue set on how well it fits BOTH surfaces, not on how it scores
    # on white. A hue that only works on one theme breaks the correspondence that
    # makes series-1 the same series in either theme.
    scored = []
    for subset in combinations(sorted(usable), size):
        fits = {t: tune_theme(t, subset, usable) for t in ("dark", "light")}
        if any(f is None for f in fits.values()):
            print(f"  {', '.join(subset):48s} infeasible on "
                  f"{', '.join(t for t, f in fits.items() if f is None)}")
            continue
        total_drift = sum(f[2] for f in fits.values())  # type: ignore[index]
        scored.append((total_drift, subset, fits))
        print(f"  {', '.join(subset):48s} drift {total_drift:6.0f} ΔE00")

    if not scored:
        print("\nno hue subset clears the bar on both surfaces")
        return
    scored.sort(key=lambda row: row[0])
    total_drift, subset, fits = scored[0]
    print(f"\nchosen: {', '.join(subset)}  (least drift from published: {total_drift:.0f} ΔE00)\n")

    for theme in ("dark", "light"):
        chosen, margin, drift_total = fits[theme]  # type: ignore[misc]
        sims = [{v: simulate(c, v) for v in VISIONS} for c in chosen]
        print(
            f"{theme:5s} headroom {margin:+.1f}  worst pair {worst_pair(sims):.1f}  "
            f"drift from published {drift_total:.0f} ΔE00"
        )
        for name, colour in zip(subset, chosen):
            anchor = usable[name]
            print(
                f"      {name:11s} {colour}  (published {anchor}, "
                f"moved {ciede2000(colour, anchor):4.1f}, "
                f"contrast {contrast_ratio(colour, PANEL[theme]):5.2f}:1)"
            )
        print(f'      {", ".join(chosen)}\n')


# Published palettes, scored with the same metric, to calibrate what "safe"
# actually costs. If the accepted references score below our threshold, the
# threshold is wrong rather than the palette.
REFERENCES = {
    "Okabe-Ito 8": ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7", "#000000"],
    "Okabe-Ito 5": ["#e69f00", "#56b4e9", "#009e73", "#0072b2", "#d55e00"],
    "Tol bright 7": ["#4477aa", "#ee6677", "#228833", "#ccbb44", "#66ccee", "#aa3377", "#bbbbbb"],
    "Tol bright 5": ["#4477aa", "#ee6677", "#228833", "#ccbb44", "#aa3377"],
    "Tol muted 9": ["#332288", "#88ccee", "#44aa99", "#117733", "#999933", "#ddcc77", "#cc6677", "#882255", "#aa4499"],
    "ColorBrewer Dark2 5": ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e"],
    "ColorBrewer Set2 5": ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854"],
    "Tableau 10 (first 5)": ["#4e79a7", "#f28e2c", "#e15759", "#76b7b2", "#59a14f"],
    "ours (current)": SERIES["dark"],
}


def calibrate() -> None:
    print("=== worst pair under any of the four visions (CIEDE2000) ===\n")
    rows = []
    for name, colours in REFERENCES.items():
        sims = [{v: simulate(c, v) for v in VISIONS} for c in colours]
        overall = worst_pair(sims)
        per_vision = {
            vision: min(
                ciede2000(sims[i][vision], sims[j][vision])
                for i, j in combinations(range(len(sims)), 2)
            )
            for vision in VISIONS
        }
        rows.append((name, len(colours), overall, per_vision))
    rows.sort(key=lambda r: -r[2])
    header = "  ".join(v[:6].rjust(6) for v in VISIONS)
    print(f"  {'palette':22s} n  worst   {header}")
    for name, n, overall, per in rows:
        cells = "  ".join(f"{per[v]:6.1f}" for v in VISIONS)
        print(f"  {name:22s} {n}  {overall:5.1f}   {cells}")


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        calibrate()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "tune":
        tune()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        print("=== searching for a palette that survives all three dichromacies ===")
        for theme in ("dark", "light"):
            search(theme)
        return

    problems: list[str] = []
    for theme in ("dark", "light"):
        problems += check_series(theme)
        problems += check_contrast(theme)
        check_disjoint(theme)

    print("\n" + "=" * 68)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    floors = ", ".join(f"{v[:6]} {MIN_DELTA[v]:.0f}" for v in VISIONS)
    print(
        f"pass. closest pair clears every floor ({floors}) and every series "
        f"is >= {CONTRAST_MIN:.0f}:1 on its panel."
    )


if __name__ == "__main__":
    main()
