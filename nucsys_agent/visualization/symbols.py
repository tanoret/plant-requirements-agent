"""
IEC-60617 / IEEE-315 compliant symbol library for nuclear P&ID single-line diagrams.

Each draw_* function adds a symbol to a matplotlib Axes at centre (cx, cy) with
the given half-size, and returns the axis-aligned bounding box
``(x_left, x_right, y_bottom, y_top)`` in data coordinates.

Symbol reference
----------------
- Pump (centrifugal)   : IEC-60617-S00298  — circle + filled impeller wedge
- Heat exchanger / SG  : IEC-60617-S00480  — two overlapping circles
- Turbine              : IEC-60617-S00436  — filled left-pointing triangle
- Valve (gate / globe) : IEC-60617-S00180  — bow-tie (two triangles at apex)
- Reactor core         : custom / IAEA     — concentric circles + fission arrows
- Condenser            : IEC-60617-S00484  — rectangle, dividing line, wavy coolant
- Pressurizer          : custom            — tall capsule + level line + heater coils
"""
from __future__ import annotations

import numpy as np
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, Polygon, FancyBboxPatch

BBox = tuple[float, float, float, float]   # x_left, x_right, y_bot, y_top


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _style(edge: str, face: str, lw: float) -> dict:
    return dict(edgecolor=edge, facecolor=face, linewidth=lw, zorder=3)


# ---------------------------------------------------------------------------
# Symbol functions
# ---------------------------------------------------------------------------

def draw_pump(
    ax, cx: float, cy: float, size: float = 0.45,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """IEC-60617 centrifugal pump: circle with filled impeller triangle."""
    ax.add_patch(Circle((cx, cy), size, **_style(edge, face, lw)))
    r = size * 0.58
    verts = np.array([
        [cx + r,        cy],
        [cx - r * 0.55, cy + r * 0.90],
        [cx - r * 0.55, cy - r * 0.90],
    ])
    ax.add_patch(Polygon(verts, closed=True, facecolor=edge, edgecolor=edge, zorder=4))
    # Letter code — top-left quadrant of circle (avoids impeller)
    ax.text(cx - size * 0.45, cy + size * 0.52, "P",
            ha="center", va="center", fontsize=size * 11,
            fontweight="bold", color=edge, zorder=5)
    return cx - size, cx + size, cy - size, cy + size


def draw_steam_generator(
    ax, cx: float, cy: float, size: float = 0.5,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """IEC-60617 shell-and-tube heat exchanger: two overlapping circles."""
    off = size * 0.38
    s = _style(edge, face, lw)
    ax.add_patch(Circle((cx - off, cy), size * 0.75, **s))
    ax.add_patch(Circle((cx + off, cy), size * 0.75, **s))
    # Wavy line on secondary-side circle (right)
    xs = np.linspace(cx + off - size * 0.6, cx + off + size * 0.6, 50)
    ys = cy + (size * 0.18) * np.sin(xs * 14)
    ax.plot(xs, ys, color=edge, lw=lw * 0.7, zorder=4)
    # Letter code — upper portion of left (primary-side) circle
    ax.text(cx - off, cy + size * 0.42, "HX",
            ha="center", va="center", fontsize=size * 9,
            fontweight="bold", color=edge, zorder=5)
    return cx - size, cx + size, cy - size, cy + size


def draw_turbine(
    ax, cx: float, cy: float, size: float = 0.5,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """IEC-60617 turbine: left-pointing triangle (steam left, shaft right)."""
    r = size
    verts = np.array([
        [cx - r, cy + r],
        [cx - r, cy - r],
        [cx + r, cy],
    ])
    ax.add_patch(Polygon(verts, closed=True, **_style(edge, face, lw)))
    # Stylised rotor blade lines
    for t in (0.30, 0.62):
        x0 = cx - r + t * (2 * r * 0.55)
        ax.plot([x0, x0 + 0.01], [cy + r * (1 - t) * 0.8, cy],
                color=edge, lw=lw * 0.65, zorder=4)
    # Letter code — centroid of triangle (shifted left-centre)
    ax.text(cx - r * 0.28, cy, "T",
            ha="center", va="center", fontsize=size * 12,
            fontweight="bold", color=edge, zorder=5)
    return cx - r, cx + r, cy - r, cy + r


def draw_valve(
    ax, cx: float, cy: float, size: float = 0.32,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """IEC-60617 gate/globe valve: bow-tie (left half filled, right open)."""
    r = size
    tl = np.array([[cx - r, cy + r], [cx - r, cy - r], [cx, cy]])
    tr = np.array([[cx + r, cy + r], [cx + r, cy - r], [cx, cy]])
    ax.add_patch(Polygon(tl, closed=True, facecolor=edge,  edgecolor=edge, lw=lw, zorder=3))
    ax.add_patch(Polygon(tr, closed=True, facecolor=face, edgecolor=edge, lw=lw, zorder=3))
    # Letter code — small "V" above the centre apex
    ax.text(cx, cy + r * 1.18, "V",
            ha="center", va="bottom", fontsize=size * 10,
            fontweight="bold", color=edge, zorder=5)
    return cx - r, cx + r, cy - r, cy + r


def draw_reactor_core(
    ax, cx: float, cy: float, size: float = 0.52,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 2.0,
) -> BBox:
    """Nuclear reactor core: concentric circles + fission-product arrows."""
    ax.add_patch(Circle((cx, cy), size, **_style(edge, face, lw * 1.4)))
    ax.add_patch(Circle((cx, cy), size * 0.56,
                        fill=False, edgecolor=edge, lw=lw * 0.8,
                        linestyle="--", zorder=4))
    for deg in (45, 135, 225, 315):
        a = np.radians(deg)
        x0 = cx + size * 0.16 * np.cos(a)
        y0 = cy + size * 0.16 * np.sin(a)
        x1 = cx + size * 0.48 * np.cos(a)
        y1 = cy + size * 0.48 * np.sin(a)
        ax.annotate(
            "", xy=(x1, y1), xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", color=edge, lw=lw * 0.7),
            zorder=5,
        )
    # Letter code — centre of inner circle (reactor designation)
    ax.text(cx, cy, "RX",
            ha="center", va="center", fontsize=size * 10,
            fontweight="bold", color=edge, zorder=6)
    return cx - size, cx + size, cy - size, cy + size


def draw_condenser(
    ax, cx: float, cy: float, size: float = 0.48,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """IEC condenser: rectangle, horizontal dividing line, wavy coolant line."""
    w, h = size * 1.55, size
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.02",
        **_style(edge, face, lw),
    ))
    ax.plot([cx - w / 2 + 0.04, cx + w / 2 - 0.04], [cy, cy],
            color=edge, lw=lw * 0.9, zorder=4)
    xs = np.linspace(cx - w / 2 + 0.06, cx + w / 2 - 0.06, 80)
    ys = (cy - h / 4) + (h * 0.12) * np.sin(xs * 20)
    ax.plot(xs, ys, color=edge, lw=lw * 0.8, zorder=4)
    # Letter code — upper half of rectangle
    ax.text(cx, cy + h * 0.28, "C",
            ha="center", va="center", fontsize=size * 12,
            fontweight="bold", color=edge, zorder=5)
    return cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2


def draw_pressurizer(
    ax, cx: float, cy: float, size: float = 0.48,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """Pressurizer: tall capsule + liquid-level dashed line + heater coils."""
    w, h = size * 0.72, size * 1.65
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.06",
        **_style(edge, face, lw),
    ))
    ax.plot([cx - w / 2 + 0.04, cx + w / 2 - 0.04],
            [cy + h * 0.08, cy + h * 0.08],
            color=edge, lw=lw * 0.8, linestyle="--", zorder=4)
    coil_y = cy - h / 2 + h * 0.18
    for xi in (cx - w * 0.22, cx, cx + w * 0.22):
        ax.plot([xi - 0.04, xi + 0.04], [coil_y, coil_y],
                color=edge, lw=lw * 2.2, solid_capstyle="round", zorder=4)
    # Letter code — upper portion above liquid level
    ax.text(cx, cy + h * 0.32, "PRZ",
            ha="center", va="center", fontsize=size * 7,
            fontweight="bold", color=edge, zorder=5)
    return cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2


def draw_boundary(
    ax, cx: float, cy: float, size: float = 0.32,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """Boundary source / sink: small diamond (system boundary marker)."""
    r = size
    verts = np.array([
        [cx,     cy + r],
        [cx + r, cy],
        [cx,     cy - r],
        [cx - r, cy],
    ])
    ax.add_patch(Polygon(verts, closed=True, **_style(edge, face, lw)))
    return cx - r, cx + r, cy - r, cy + r


# ---------------------------------------------------------------------------
# Dispatch table: resolved symbol-key → draw function
# ---------------------------------------------------------------------------

SYMBOL_DRAW: dict[str, callable] = {
    "pump":            draw_pump,
    "steam_generator": draw_steam_generator,
    "heat_exchanger":  draw_steam_generator,
    "turbine":         draw_turbine,
    "valve":           draw_valve,
    "reactor_core":    draw_reactor_core,
    "condenser":       draw_condenser,
    "pressurizer":     draw_pressurizer,
    "boundary":        draw_boundary,
}


def draw_unknown(
    ax, cx: float, cy: float, size: float = 0.4,
    edge: str = "#1a1a2e", face: str = "#e8f4fd", lw: float = 1.8,
) -> BBox:
    """Fallback: plain rectangle for unrecognised component types."""
    w = h = size * 1.4
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.04",
        **_style(edge, face, lw),
    ))
    ax.text(cx, cy, "?", ha="center", va="center", fontsize=9, color=edge, zorder=5)
    return cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
