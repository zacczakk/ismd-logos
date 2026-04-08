#!/usr/bin/env python3
"""Export SAI logo variants as standalone SVGs and PNGs.

Produces files in sai/export/:
  sai-logo-{C,D}-{dark,light}-{color,mono}.svg
  sai-logo-C-{dark,light}-{color,mono}.png        (when --png or --all)

PNGs are only generated for static variants (C). Animated variant D
is SVG-only since the knowledge-flow wave animation cannot be captured
in a single raster frame.

Layout matches CSAR.ai spec (1275x500pt artboard, Poppins-Light 80pt,
identical separator/padding/icon placement). All backgrounds transparent.

Variant C = static hex grid.  Variant D = animated knowledge-flow wave.

Usage:
  python sai/export.py              # SVGs only
  python sai/export.py --png        # PNGs only (requires rsvg-convert)
  python sai/export.py --all        # SVGs + PNGs
  python sai/export.py --dry-run    # prints filenames without writing
  python sai/export.py --scale 3    # PNG scale factor (default 3 = 3x)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Layout constants — extracted from CSAR.ai via PyMuPDF
# ---------------------------------------------------------------------------

ARTBOARD_W = 1275
ARTBOARD_H = 500

# Separator bar
SEP_X = 457.07
SEP_W = 5.5
SEP_Y0 = 125
SEP_Y1 = 375
SEP_H = SEP_Y1 - SEP_Y0  # 250

# Wordmark
TEXT_X = 507.1
TEXT_BASELINES = (189.37, 279.37, 369.37)
TEXT_WORDS = ("Structural", "Analysis", "Intelligence")
FONT_SIZE = 80
FONT_FAMILY = "Poppins, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
FONT_WEIGHT = 300

# Icon transform — scale 42-unit hex grid to fill separator height
GRID_CONTENT_H = 40  # y spans 1..41
SCALE = SEP_H / GRID_CONTENT_H  # 6.25
ICON_CX = 270  # horizontal center matching CSAR icon bbox midpoint
ICON_CY = ARTBOARD_H / 2  # vertical center
GRID_CENTER = 21  # center of 42-unit grid
TX = ICON_CX - GRID_CENTER * SCALE  # 138.75
TY = ICON_CY - GRID_CENTER * SCALE  # 118.75

# ---------------------------------------------------------------------------
# Hexagon geometry
# ---------------------------------------------------------------------------

HEX = {
    "TL": "7,1 12.20,4 12.20,10 7,13 1.80,10 1.80,4",
    "TC": "21,1 26.20,4 26.20,10 21,13 15.80,10 15.80,4",
    "TR": "35,1 40.20,4 40.20,10 35,13 29.80,10 29.80,4",
    "LC": "7,15 12.20,18 12.20,24 7,27 1.80,24 1.80,18",
    "C": "21,15 26.20,18 26.20,24 21,27 15.80,24 15.80,18",
    "RC": "35,15 40.20,18 40.20,24 35,27 29.80,24 29.80,18",
    "BL": "7,29 12.20,32 12.20,38 7,41 1.80,38 1.80,32",
    "BC": "21,29 26.20,32 26.20,38 21,41 15.80,38 15.80,32",
    "BR": "35,29 40.20,32 40.20,38 35,41 29.80,38 29.80,32",
}

CONNECTOR_EDGES_ACCENT = [
    (10.80, 10.80, 17.20, 17.20),
    (24.80, 17.20, 31.20, 10.80),
    (35, 13, 35, 15),
    (31.20, 24.80, 24.80, 31.20),
]

CONNECTOR_EDGES_SECONDARY = [
    (26.20, 7, 29.80, 7),
    (12.20, 21, 15.80, 21),
    (7, 29, 7, 27),
    (26.20, 35, 29.80, 35),
]

# Clip-path IDs for outline hexagons
CLIPPED_HEXES = ("TC", "TR", "LC", "C", "RC", "BL", "BR")

WAVE_PATH = "M 7,7 L 21,21 L 35,7 L 35,21 L 21,35"

WAVE_FILLS = [
    ("TL", 0.0),
    ("BC", 0.73),
]

WAVE_STROKES = [
    ("C", 0.20),
    ("TR", 0.40),
    ("RC", 0.54),
]


# ---------------------------------------------------------------------------
# Color scheme
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Colors:
    accent: str
    secondary: str
    text: str  # wordmark + separator


PALETTES: dict[str, Colors] = {
    "dark-color": Colors(accent="#005AA9", secondary="#b8b8bc", text="#ffffff"),
    "light-color": Colors(accent="#005AA9", secondary="#909094", text="#1a1a2e"),
    "dark-mono": Colors(accent="#b8b8bc", secondary="#606064", text="#ffffff"),
    "light-mono": Colors(accent="#3a3a3e", secondary="#909094", text="#1a1a2e"),
}


# ---------------------------------------------------------------------------
# SVG fragment builders
# ---------------------------------------------------------------------------


def _line(x1: float, y1: float, x2: float, y2: float, color: str) -> str:
    return (
        f'    <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{color}" stroke-width="1.5" stroke-linecap="round"/>'
    )


def _hex_filled(name: str, color: str) -> str:
    return f'    <polygon points="{HEX[name]}" fill="{color}"/>'


def _hex_outline(name: str, color: str) -> str:
    return (
        f'    <polygon points="{HEX[name]}" fill="none" '
        f'stroke="{color}" stroke-width="3" clip-path="url(#{name})"/>'
    )


def clip_path_defs() -> str:
    return "\n".join(
        f'      <clipPath id="{name}"><polygon points="{HEX[name]}"/></clipPath>'
        for name in CLIPPED_HEXES
    )


def hex_grid_c(c: Colors) -> str:
    """Variant C — static grid. Accent edges + filled TL/BC, secondary outlines."""
    parts: list[str] = []
    for edge in CONNECTOR_EDGES_ACCENT:
        parts.append(_line(*edge, c.accent))
    for edge in CONNECTOR_EDGES_SECONDARY:
        parts.append(_line(*edge, c.secondary))
    parts.append(_hex_filled("TL", c.accent))
    parts.append(_hex_outline("TC", c.secondary))
    parts.append(_hex_outline("TR", c.accent))
    parts.append(_hex_outline("LC", c.secondary))
    parts.append(_hex_outline("C", c.accent))
    parts.append(_hex_outline("RC", c.accent))
    parts.append(_hex_outline("BL", c.secondary))
    parts.append(_hex_filled("BC", c.accent))
    parts.append(_hex_outline("BR", c.secondary))
    return "\n".join(parts)


def hex_grid_d(c: Colors) -> str:
    """Variant D — animated wave. All base elements secondary; wave overlays accent."""
    parts: list[str] = []
    for edge in CONNECTOR_EDGES_ACCENT + CONNECTOR_EDGES_SECONDARY:
        parts.append(_line(*edge, c.secondary))
    parts.append(_hex_filled("TL", c.secondary))
    for name in CLIPPED_HEXES:
        parts.append(_hex_outline(name, c.secondary))
    parts.append(_hex_filled("BC", c.secondary))
    # Wave layer
    parts.append('    <g mask="url(#hex-hole-mask)">')
    parts.append(f'      <path d="{WAVE_PATH}" class="flow-wave-tail"/>')
    parts.append(f'      <path d="{WAVE_PATH}" class="flow-wave"/>')
    parts.append("    </g>")
    for name, delay in WAVE_FILLS:
        parts.append(
            f'    <polygon points="{HEX[name]}" class="wave-fill" '
            f'style="animation-delay:{delay}s; fill:url(#flow-grad)"/>'
        )
    for name, delay in WAVE_STROKES:
        parts.append(
            f'    <polygon points="{HEX[name]}" class="wave-stroke" '
            f'clip-path="url(#{name})" '
            f'style="animation-delay:{delay}s; stroke:url(#flow-grad)"/>'
        )
    return "\n".join(parts)


def animation_defs(wave_color: str) -> str:
    return f"""\
    <radialGradient id="flow-grad" cx="50%" cy="50%" r="90%">
      <stop offset="60%" stop-color="{wave_color}" stop-opacity="1"/>
      <stop offset="100%" stop-color="{wave_color}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="tail-fade" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="white" stop-opacity="0"/>
      <stop offset="100%" stop-color="white" stop-opacity="1"/>
    </linearGradient>
    <mask id="tail-mask">
      <rect width="100%" height="100%" fill="url(#tail-fade)"/>
    </mask>
    <mask id="hex-hole-mask">
      <rect x="-50%" y="-50%" width="200%" height="200%" fill="white"/>
{chr(10).join(f'      <polygon points="{HEX[n]}" fill="black"/>' for n in HEX)}
    </mask>
    <style>
      @keyframes sweepWave {{
        0%   {{ stroke-dashoffset: 156; opacity: 0; }}
        1%   {{ opacity: 1; }}
        80%  {{ stroke-dashoffset: -204; opacity: 1; }}
        100% {{ stroke-dashoffset: -204; opacity: 0; }}
      }}
      @keyframes sweepTail {{
        0%   {{ stroke-dashoffset: 216; opacity: 0; }}
        1%   {{ opacity: 1; }}
        80%  {{ stroke-dashoffset: -144; opacity: 1; }}
        100% {{ stroke-dashoffset: -144; opacity: 0; }}
      }}
      @keyframes hexWave {{
        0%   {{ opacity: 0; }}
        4%   {{ opacity: 1; }}
        30%  {{ opacity: 1; }}
        38%  {{ opacity: 0; }}
        100% {{ opacity: 0; }}
      }}
      .flow-wave {{
        stroke: {wave_color}; stroke-width: 1.5;
        stroke-linecap: round; stroke-linejoin: round; fill: none;
        stroke-dasharray: 156 500; stroke-dashoffset: 156;
        animation: sweepWave 4.5s linear infinite;
      }}
      .flow-wave-tail {{
        stroke: {wave_color}; stroke-width: 1.25;
        stroke-linecap: round; stroke-linejoin: round; fill: none;
        stroke-dasharray: 216 500; stroke-dashoffset: 216;
        mask: url(#tail-mask);
        animation: sweepTail 4.5s linear infinite;
      }}
      .wave-fill {{
        fill: {wave_color};
        animation: hexWave 4.5s linear infinite; opacity: 0;
      }}
      .wave-stroke {{
        fill: none; stroke: {wave_color}; stroke-width: 3;
        animation: hexWave 4.5s linear infinite; opacity: 0;
      }}
    </style>"""


def wordmark(c: Colors) -> str:
    return "\n".join(
        f'  <text x="{TEXT_X}" y="{y}" fill="{c.text}" '
        f'font-family="{FONT_FAMILY}" font-weight="{FONT_WEIGHT}" '
        f'font-size="{FONT_SIZE}">{word}</text>'
        for word, y in zip(TEXT_WORDS, TEXT_BASELINES)
    )


# ---------------------------------------------------------------------------
# Full SVG assembly
# ---------------------------------------------------------------------------


def build_svg(variant: str, palette_key: str) -> str:
    c = PALETTES[palette_key]
    animated = variant == "D"
    theme = "dark" if "dark" in palette_key else "light"
    mode = "mono" if "mono" in palette_key else "color"

    top_defs = animation_defs(c.accent) if animated else ""
    grid = hex_grid_d(c) if animated else hex_grid_c(c)
    label = f"SAI Logo - Variant {variant} - {theme} - {mode}"
    if animated:
        label += " - animated"

    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ARTBOARD_W} {ARTBOARD_H}"
     width="{ARTBOARD_W}" height="{ARTBOARD_H}" aria-label="{label}">
  <defs>
{top_defs}
  </defs>

  <g transform="translate({TX:.2f},{TY:.2f}) scale({SCALE:.4f})">
    <defs>
{clip_path_defs()}
    </defs>
{grid}
  </g>

  <rect x="{SEP_X}" y="{SEP_Y0}" width="{SEP_W}" height="{SEP_H}" fill="{c.text}"/>

{wordmark(c)}
</svg>
"""


# ---------------------------------------------------------------------------
# PNG rasterization
# ---------------------------------------------------------------------------

RSVG_BIN = "rsvg-convert"


def check_rsvg() -> str:
    """Return path to rsvg-convert or raise."""
    path = shutil.which(RSVG_BIN)
    if not path:
        raise SystemExit(
            f"  error: {RSVG_BIN} not found. Install librsvg:\n    brew install librsvg"
        )
    return path


def svg_to_png(svg_path: Path, png_path: Path, scale: int, rsvg: str) -> None:
    """Rasterize an SVG to PNG at the given scale factor."""
    subprocess.run(
        [
            rsvg,
            str(svg_path),
            "--output",
            str(png_path),
            "--zoom",
            str(scale),
        ],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print filenames without writing",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: sai/export/ relative to this script)",
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--png",
        action="store_true",
        help="Export PNGs only (requires rsvg-convert)",
    )
    fmt.add_argument(
        "--all",
        action="store_true",
        help="Export both SVGs and PNGs",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=3,
        metavar="N",
        help="PNG scale factor (default: 3 → 3825x1500px)",
    )
    args = parser.parse_args()

    do_svg = not args.png
    do_png = args.png or getattr(args, "all")

    out = args.output_dir or Path(__file__).parent / "export"

    rsvg = None
    if do_png and not args.dry_run:
        rsvg = check_rsvg()

    out.mkdir(parents=True, exist_ok=True)

    svg_count = 0
    png_count = 0

    for variant in ("C", "D"):
        for palette_key in PALETTES:
            stem = f"sai-logo-{variant}-{palette_key}"
            svg_path = out / f"{stem}.svg"
            png_path = out / f"{stem}.png"
            svg = build_svg(variant, palette_key)

            if do_svg:
                if args.dry_run:
                    print(f"  {svg_path.name}  ({len(svg)} bytes)")
                else:
                    svg_path.write_text(svg)
                    print(f"  {svg_path.name}  ({len(svg)} bytes)")
                svg_count += 1

            if do_png and variant != "D":
                if args.dry_run:
                    w = ARTBOARD_W * args.scale
                    h = ARTBOARD_H * args.scale
                    print(f"  {png_path.name}  ({w}x{h}px @ {args.scale}x)")
                else:
                    # always write SVG to disk first (needed by rsvg-convert)
                    if not do_svg:
                        svg_path.write_text(svg)
                    svg_to_png(svg_path, png_path, args.scale, rsvg)
                    size = png_path.stat().st_size
                    print(f"  {png_path.name}  ({size / 1024:.1f} KB)")
                    # clean up SVG if we only wanted PNGs
                    if not do_svg:
                        svg_path.unlink()
                png_count += 1

    if not args.dry_run:
        parts = []
        if svg_count:
            parts.append(f"{svg_count} SVGs")
        if png_count:
            parts.append(f"{png_count} PNGs")
        print(f"\n  {' + '.join(parts)} written to {out}/")


if __name__ == "__main__":
    main()
