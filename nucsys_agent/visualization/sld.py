"""
Single-Line Diagram (SLD) generator for nucsys-agent loop designs.

Produces P&ID-style single-line diagrams following IEC-60617 and IEEE-315
graphical conventions.

Outputs
-------
- Interactive display via matplotlib (``sld.show()``)
- PDF, SVG, PNG, EPS export (``sld.export(path)``)
- Blueprint PDF (dark-background engineering drawing)
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

try:
    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

from .symbols import SYMBOL_DRAW, draw_unknown, BBox

# ---------------------------------------------------------------------------
# Style palettes
# ---------------------------------------------------------------------------

STYLE_NORMAL: dict[str, Any] = {
    # Backgrounds
    "bg":              "#ffffff",       # white paper
    "building_bg":     "#f5f8ff",       # very subtle zone tint
    "title_bg":        "#e8eef8",
    # Foreground / ink
    "fg":              "#111111",
    "building_fg":     "#1a3a7c",       # zone border + label colour
    "border":          "#111111",
    # Symbol style
    "sym_edge":        "#111111",
    "sym_face":        "#ffffff",       # white fill — clean printed look
    # Pipe colours (ISO convention)
    "pipe":            "#111111",       # primary coolant — black
    "pipe_sec":        "#c41200",       # main steam — red
    "pipe_ret":        "#0044bb",       # feedwater / condensate — blue
    # Labels
    "label_fg":        "#111111",
    "param_fg":        "#1a3a7c",
    "stream_label":    "#555577",
    "tag_bg":          "#fffde7",
    "tag_fg":          "#111111",
    "tag_border":      "#888844",
    # Requirements badges
    "req_edge":        "#0077aa",
    "req_face":        "#d0e8f8",
    "req_gen_edge":    "#1a8a3a",
    "req_gen_face":    "#d0f0dc",
    # Unused in normal but kept for compatibility
    "grid":            "#e8e8e8",
}

STYLE_BLUEPRINT: dict[str, Any] = {
    "bg":              "#0a1628",
    "building_bg":     "#0d1f38",
    "title_bg":        "#0d1f38",
    "fg":              "#c8e0f0",
    "building_fg":     "#5ab3d4",
    "border":          "#5ab3d4",
    "sym_edge":        "#5ab3d4",
    "sym_face":        "#0d2040",
    "pipe":            "#5ab3d4",
    "pipe_sec":        "#8fd47a",
    "pipe_ret":        "#d4a44a",
    "label_fg":        "#e0f0ff",
    "param_fg":        "#80c8e8",
    "stream_label":    "#80a0c0",
    "tag_bg":          "#0d2040",
    "tag_fg":          "#e0f0ff",
    "tag_border":      "#5ab3d4",
    "req_edge":        "#2db8c8",
    "req_face":        "#0d3040",
    "req_gen_edge":    "#2db86e",
    "req_gen_face":    "#0d3a20",
    "grid":            "#1a3a5c",
}

# ---------------------------------------------------------------------------
# Equipment tag-number prefixes by symbol type
# ---------------------------------------------------------------------------

_TAG_PREFIX: dict[str, str] = {
    "reactor_core":    "RX",
    "steam_generator": "SG",
    "heat_exchanger":  "HX",
    "pump":            "P",
    "turbine":         "T",
    "valve":           "V",
    "condenser":       "COND",
    "pressurizer":     "PRZ",
    "boundary":        "",
}

# Sequential counters used to generate unique tags within one diagram
_tag_counters: dict[str, int] = {}


def _make_tag(sym_type: str) -> str:
    prefix = _TAG_PREFIX.get(sym_type, "E")
    if not prefix:
        return ""
    _tag_counters[prefix] = _tag_counters.get(prefix, 0) + 1
    return f"{prefix}-{_tag_counters[prefix]:03d}"


# ---------------------------------------------------------------------------
# Type resolution
# ---------------------------------------------------------------------------

_CANONICAL_TO_SYM: dict[str, str] = {
    "reactor_pressure_vessel": "reactor_core",
    "reactor_core":            "reactor_core",
    "steam_generator":         "steam_generator",
    "heat_exchanger":          "heat_exchanger",
    "pump_primary":            "pump",
    "pump_feedwater":          "pump",
    "pump":                    "pump",
    "turbine_generator":       "turbine",
    "turbine":                 "turbine",
    "valve_control":           "valve",
    "valve":                   "valve",
    "condenser":               "condenser",
    "pressurizer":             "pressurizer",
    "boundary_source":         "boundary",
    "boundary_sink":           "boundary",
}

_IFC_TO_SYM: dict[str, str] = {
    "NUCLEAR_REACTOR_PRESSURE_VESSEL": "reactor_core",
    "NUCLEAR_STEAM_GENERATOR":         "steam_generator",
    "REACTOR_COOLANT_PUMP":            "pump",
    "CENTRIFUGAL_PUMP":                "pump",
    "NUCLEAR_TURBINE_GENERATOR":       "turbine",
    "MOTORIZED_CONTROL_VALVE":         "valve",
    "GATE_VALVE":                      "valve",
    "CHECK_VALVE":                     "valve",
    "CONDENSER":                       "condenser",
    "PRESSURIZER":                     "pressurizer",
}


def _resolve_sym_type(part: dict) -> str:
    props     = part.get("properties", {})
    canonical = props.get("canonical_type", "")
    ifc       = part.get("preset_element_type", "")
    sym = _CANONICAL_TO_SYM.get(canonical)
    if sym:
        return sym
    sym = _IFC_TO_SYM.get(ifc)
    if sym:
        return sym
    for prefix in ("nuclear_", "ifc_", "reactor_"):
        ifc_lc = ifc.lower().replace(prefix, "")
        if ifc_lc in _CANONICAL_TO_SYM:
            return _CANONICAL_TO_SYM[ifc_lc]
    return "unknown"


# ---------------------------------------------------------------------------
# Key sizing parameters per component type
# ---------------------------------------------------------------------------

_PARAM_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "reactor_core": [
        ("thermal_power_MWth",  "Q_th",   "MWth"),
        ("hot_leg_C",           "T_hot",  "°C"),
        ("cold_leg_C",          "T_cold", "°C"),
        ("primary_pressure_MPa","P",      "MPa"),
    ],
    "pump": [
        ("m_dot_kg_s",    "ṁ",    "kg/s"),
        ("delta_p_MPa",   "ΔP",   "MPa"),
        ("shaft_power_MW","P_sh", "MW"),
    ],
    "steam_generator": [
        ("duty_MW",             "Q",       "MW"),
        ("UA_MW_per_K",         "UA",      "MW/K"),
        ("primary_hot_in_C",    "T₁ᵢₙ",   "°C"),
        ("primary_hot_out_C",   "T₁ₒᵤₜ",  "°C"),
        ("secondary_cold_in_C", "T₂ᵢₙ",   "°C"),
        ("secondary_hot_out_C", "T₂ₒᵤₜ",  "°C"),
    ],
    "turbine": [
        ("gross_power_MWe",      "P_gross","MWe"),
        ("net_power_MWe",        "P_net",  "MWe"),
        ("isentropic_efficiency","η_is",   ""),
        ("cycle_efficiency",     "η_cyc",  ""),
    ],
    "valve":          [],
    "condenser":      [("duty_MW", "Q", "MW")],
    "pressurizer":    [],
    "heat_exchanger": [
        ("duty_MW",     "Q",  "MW"),
        ("UA_MW_per_K", "UA", "MW/K"),
    ],
    "boundary":       [],
}

# Components that have a requirements baseline
_REQ_COMPONENT_MAP: dict[str, str] = {
    "Primary Sink": "pump",
    "SG":           "steam_generator",
    "FWP":          "pump",
    "Turbine":      "turbine",
}

# Stream identification labels for pipe runs (covers in-building and cross-building pairs)
_STREAM_LABELS: dict[str, str] = {
    # Primary coolant loop
    ("reactor_core",    "steam_generator"): "PRIMARY COOLANT →",
    ("steam_generator", "pump"):            "PRIMARY COOLANT →",
    ("pump",            "reactor_core"):    "PRIMARY COOLANT →",
    # Steam / power conversion (direct and through throttle admission valve)
    ("steam_generator", "turbine"):         "MAIN STEAM →",
    ("steam_generator", "valve"):           "MAIN STEAM →",   # SG → throttle/admission valve
    ("valve",           "turbine"):         "MAIN STEAM →",   # throttle/admission → turbine
    ("turbine",         "condenser"):       "EXHAUST STEAM →",
    # Feedwater / condensate path
    ("pump",            "steam_generator"): "FEEDWATER →",
    ("pump",            "valve"):           "FEEDWATER →",    # FWP → feedwater control valve
    ("valve",           "steam_generator"): "FEEDWATER →",   # FW control valve → SG
    ("boundary",        "pump"):            "FEEDWATER →",
    ("condenser",       "pump"):            "CONDENSATE →",
    # Terminal connections — no label needed
    ("turbine",         "boundary"):        "",
    ("boundary",        "boundary"):        "",
}

# Streams that carry feedwater/condensate (determine pipe colour on cross-building legs)
_FEEDWATER_STREAMS: frozenset[str] = frozenset(
    {"FEEDWATER →", "CONDENSATE →", "FEEDWATER RETURN"}
)

# Layout constants
_X_STEP    = 3.8    # horizontal spacing between node centres
_Y_STEP    = 6.4    # vertical spacing between building rows
_SYM_SIZE  = 0.50   # symbol half-size
_LABEL_GAP = 0.75   # symbol centre → first label line
_PIPE_LW   = 2.0    # pipe line width (pts)
_RETURN_DY = 2.6    # depth of return-pipe arc below building bottom


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _parse_graph(alchemy_db: dict) -> tuple[dict, list, dict]:
    nodes: dict[int, dict] = {}
    edges: list[tuple[int, int]] = []
    buildings: dict[str, list[int]] = {}

    for bname, bdata in alchemy_db.items():
        if not isinstance(bdata, dict):
            continue
        b_ids: list[int] = []
        for part in bdata.get("parts", []):
            nid = part["id"]
            nodes[nid] = {
                "name":       part.get("name", str(nid)),
                "type":       _resolve_sym_type(part),
                "properties": part.get("properties", {}),
                "building":   bname,
            }
            b_ids.append(nid)
            for tid in part.get("edgesOutgoing", []):
                edges.append((nid, tid))
        buildings[bname] = b_ids

    return nodes, edges, buildings


def _flow_order(node_ids: list[int], edges: list[tuple[int, int]]) -> list[int]:
    id_set = set(node_ids)
    adj: dict[int, list[int]] = {nid: [] for nid in node_ids}
    for fr, to in edges:
        if fr in id_set and to in id_set:
            adj[fr].append(to)

    in_deg: dict[int, int] = {nid: 0 for nid in node_ids}
    for _, targets in adj.items():
        for t in targets:
            if t in in_deg:
                in_deg[t] += 1

    sources = [nid for nid in node_ids if in_deg[nid] == 0]
    start = sources[0] if sources else node_ids[0]

    ordered, visited = [start], {start}
    current = start
    while True:
        nexts = [t for t in adj.get(current, []) if t not in visited]
        if not nexts:
            break
        current = nexts[0]
        ordered.append(current)
        visited.add(current)
    for nid in node_ids:
        if nid not in visited:
            ordered.append(nid)
    return ordered


def _compute_positions(
    nodes: dict, edges: list, buildings: dict
) -> dict[int, tuple[float, float]]:
    pos: dict[int, tuple[float, float]] = {}
    bnames = list(buildings.keys())
    n_b = len(bnames)
    for bi, bname in enumerate(bnames):
        node_ids = buildings[bname]
        ordered = _flow_order(node_ids, edges)
        y = (n_b - 1 - bi) * _Y_STEP
        for xi, nid in enumerate(ordered):
            pos[nid] = (xi * _X_STEP, y)
    return pos


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SingleLineDiagram:
    """
    Single-line diagram for a nucsys-agent loop design.

    Parameters
    ----------
    alchemy_db : dict
        Raw alchemy JSON dict.
    req_info : dict, optional
        {node_name: {"applicable": N, "tbd": M, "generated": bool}}
    blueprint : bool
        Dark-background engineering drawing style.
    title : str, optional
        Diagram title.
    """

    def __init__(
        self,
        alchemy_db: dict,
        req_info: dict | None = None,
        blueprint: bool = False,
        title: str = "Nuclear System — Single-Line Diagram",
    ):
        if not _HAS_MPL:
            raise ImportError(
                "matplotlib is required for diagram generation.\n"
                "Install with:  pip install matplotlib"
            )
        self.alchemy_db = alchemy_db
        self.req_info   = req_info or {}
        self.style      = STYLE_BLUEPRINT if blueprint else STYLE_NORMAL
        self.blueprint  = blueprint
        self.title      = title
        self.fig: plt.Figure | None = None
        self.ax:  plt.Axes  | None = None

        _tag_counters.clear()
        self._nodes, self._edges, self._buildings = _parse_graph(alchemy_db)
        self._pos = _compute_positions(self._nodes, self._edges, self._buildings)
        # Pre-assign tag numbers so they are stable across re-draws
        self._tags: dict[int, str] = {
            nid: _make_tag(node["type"])
            for nid, node in self._nodes.items()
        }

    @classmethod
    def from_agent_result(
        cls, result, req_info=None, blueprint=False,
    ) -> "SingleLineDiagram":
        from nucsys_agent.serializer.alchemy import export_alchemy_db
        db = export_alchemy_db(result.buildings)
        spec = result.spec
        title = (
            f"{spec.thermal_power_MWth} MWth  "
            f"{spec.system.replace('_', ' ').title()} "
            f"({spec.coolant})"
        )
        return cls(db, req_info=req_info, blueprint=blueprint, title=title)

    # ------------------------------------------------------------------
    def draw(self) -> plt.Figure:
        """Render and return the matplotlib Figure."""
        st = self.style

        n_nodes  = len(self._nodes)
        n_build  = len(self._buildings)
        fig_w    = max(14, n_nodes * 2.5)
        fig_h    = max(9,  n_build * _Y_STEP * 0.92 + 4.2)

        self.fig, self.ax = plt.subplots(figsize=(fig_w, fig_h))
        ax, fig = self.ax, self.fig

        fig.patch.set_facecolor(st["bg"])
        ax.set_facecolor(st["bg"])
        ax.set_aspect("equal")
        ax.axis("off")

        if self.blueprint:
            self._draw_grid()

        for bname, node_ids in self._buildings.items():
            self._draw_building_frame(bname, node_ids)

        self._draw_all_pipes()

        for nid, node in self._nodes.items():
            cx, cy = self._pos[nid]
            self._draw_node(nid, node, cx, cy)

        self._draw_legend()
        self._draw_title_block()

        ax.autoscale_view()
        pad = 1.6
        x_min = min(x for x, _ in self._pos.values()) - pad
        x_max = max(x for x, _ in self._pos.values()) + pad + 1.0
        y_min = min(y for _, y in self._pos.values()) - _RETURN_DY - 3.2
        y_max = max(y for _, y in self._pos.values()) + pad
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)

        self._draw_drawing_border()

        fig.tight_layout(pad=0.15)
        return fig

    def show(self) -> None:
        if self.fig is None:
            self.draw()
        plt.show()

    def export(self, path: str | Path, dpi: int = 300) -> None:
        if self.fig is None:
            self.draw()
        path = Path(path)
        self.fig.savefig(
            path, dpi=dpi, bbox_inches="tight",
            facecolor=self.fig.get_facecolor(),
        )

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_grid(self) -> None:
        """Blueprint dot-grid background."""
        st = self.style
        ax = self.ax
        for x in np.arange(-20, 60, 1.0):
            ax.axvline(x, color=st["grid"], lw=0.25, alpha=0.35, zorder=0)
        for y in np.arange(-12, 30, 1.0):
            ax.axhline(y, color=st["grid"], lw=0.25, alpha=0.35, zorder=0)

    # ------------------------------------------------------------------
    def _draw_building_frame(self, bname: str, node_ids: list[int]) -> None:
        """
        P&ID-style zone boundary: thin dashed border with a filled name tab
        at the top-left (ISBL / system boundary convention).
        """
        if not node_ids:
            return
        st = self.style
        ax = self.ax

        xs = [self._pos[nid][0] for nid in node_ids]
        ys = [self._pos[nid][1] for nid in node_ids]
        pad_x, pad_y = 1.0, 1.15
        x0 = min(xs) - pad_x
        y0 = min(ys) - pad_y
        w  = max(xs) - min(xs) + 2 * pad_x
        h  = max(ys) - min(ys) + 2 * pad_y

        # Zone fill (very subtle)
        ax.add_patch(FancyBboxPatch(
            (x0, y0), w, h,
            boxstyle="square,pad=0",
            facecolor=st["building_bg"],
            edgecolor="none",
            zorder=1,
        ))

        # Zone dashed border
        ax.add_patch(FancyBboxPatch(
            (x0, y0), w, h,
            boxstyle="square,pad=0",
            fill=False,
            edgecolor=st["building_fg"],
            linewidth=1.0,
            linestyle=(0, (6, 3)),   # long dash
            zorder=2,
        ))

        # Name tab: filled rectangle at top-left corner
        tab_w  = min(w * 0.38, 3.4)
        tab_h  = 0.40
        tab_x  = x0
        tab_y  = y0 + h
        ax.add_patch(mpatches.Rectangle(
            (tab_x, tab_y), tab_w, tab_h,
            facecolor=st["building_fg"],
            edgecolor=st["building_fg"],
            linewidth=0,
            zorder=3,
            clip_on=False,
        ))
        ax.text(
            tab_x + tab_w / 2, tab_y + tab_h / 2,
            bname.upper(),
            ha="center", va="center",
            fontsize=7.0, fontweight="bold",
            color="#ffffff" if not self.blueprint else st["bg"],
            zorder=4, clip_on=False,
        )

    # ------------------------------------------------------------------
    def _draw_all_pipes(self) -> None:
        st    = self.style
        ax    = self.ax
        drawn: set[tuple[int, int]] = set()

        for bname, node_ids in self._buildings.items():
            ordered = _flow_order(node_ids, self._edges)

            for i in range(len(ordered) - 1):
                fr_id, to_id = ordered[i], ordered[i + 1]
                self._draw_pipe(fr_id, to_id, color=st["pipe"])
                drawn.add((fr_id, to_id))

            if len(ordered) >= 2:
                last_id, first_id = ordered[-1], ordered[0]
                has_return = any(
                    fr == last_id and to == first_id
                    for fr, to in self._edges
                )
                if has_return:
                    self._draw_return_arc(
                        last_id, first_id, bname, node_ids, color=st["pipe_ret"]
                    )
                    drawn.add((last_id, first_id))

        for fr_id, to_id in self._edges:
            if (fr_id, to_id) in drawn:
                continue
            if fr_id not in self._pos or to_id not in self._pos:
                continue
            # Choose pipe colour by stream type (feedwater = blue, steam = red)
            t_fr  = self._nodes[fr_id]["type"]
            t_to  = self._nodes[to_id]["type"]
            slbl  = _STREAM_LABELS.get((t_fr, t_to), "")
            xbclr = st["pipe_ret"] if slbl in _FEEDWATER_STREAMS else st["pipe_sec"]
            self._draw_cross_building_pipe(fr_id, to_id, color=xbclr)
            drawn.add((fr_id, to_id))

    # ------------------------------------------------------------------
    def _draw_pipe(
        self, fr_id: int, to_id: int, color: str, lw: float | None = None
    ) -> None:
        """Straight pipe with mid-point flow arrow and stream label."""
        ax  = self.ax
        lw  = lw or _PIPE_LW
        x0, y0 = self._pos[fr_id]
        x1, y1 = self._pos[to_id]

        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy) or 1e-9
        pad  = _SYM_SIZE + 0.10
        sx, sy = x0 + pad * dx / dist, y0 + pad * dy / dist
        ex, ey = x1 - pad * dx / dist, y1 - pad * dy / dist

        ax.plot([sx, ex], [sy, ey], color=color, lw=lw,
                solid_capstyle="round", zorder=2)

        # Flow arrow (at 55% along the pipe)
        t = 0.55
        mx, my = sx + t * (ex - sx), sy + t * (ey - sy)
        ax.annotate(
            "", xy=(mx + 0.20 * dx / dist, my + 0.20 * dy / dist),
            xytext=(mx, my),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                            mutation_scale=13),
            zorder=3,
        )

        # Stream label (centred above the pipe, small italic)
        t_fr = self._nodes[fr_id]["type"]
        t_to = self._nodes[to_id]["type"]
        slabel = _STREAM_LABELS.get((t_fr, t_to), "")
        if slabel:
            mid_x = (sx + ex) / 2
            mid_y = (sy + ey) / 2 + 0.18
            angle = math.degrees(math.atan2(dy, dx))
            if abs(angle) > 90:
                angle += 180
            ax.text(
                mid_x, mid_y, slabel,
                ha="center", va="bottom",
                fontsize=5.5, style="italic",
                color=self.style["stream_label"],
                rotation=angle,
                rotation_mode="anchor",
                zorder=4,
            )

    # ------------------------------------------------------------------
    def _draw_return_arc(
        self,
        last_id: int,
        first_id: int,
        bname: str,
        node_ids: list[int],
        color: str,
    ) -> None:
        """Orthogonal return pipe (down → across → up) below building."""
        ax = self.ax
        x_last,  y_last  = self._pos[last_id]
        x_first, y_first = self._pos[first_id]
        y_bot = min(self._pos[nid][1] for nid in node_ids) - _RETURN_DY

        pad = _SYM_SIZE + 0.10
        # Four-point orthogonal path with rounded corners
        xs = [x_last,  x_last,  x_first, x_first]
        ys = [y_last - pad, y_bot, y_bot, y_first - pad]
        ax.plot(xs, ys, color=color, lw=_PIPE_LW,
                solid_capstyle="round", solid_joinstyle="round", zorder=2)

        # Return-flow arrow at bottom centre
        mx = (x_last + x_first) / 2
        ax.annotate(
            "", xy=(mx - 0.22, y_bot), xytext=(mx + 0.22, y_bot),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=_PIPE_LW,
                            mutation_scale=12),
            zorder=3,
        )

        # Stream designation label on the return line
        is_primary = "primary" in bname.lower()
        lbl = "RETURN — PRIMARY COOLANT" if is_primary else "FEEDWATER RETURN"
        clr = self.style["stream_label"]
        ax.text(
            mx, y_bot - 0.20, lbl,
            ha="center", va="top",
            fontsize=5.5, style="italic", color=clr, zorder=3,
        )

    # ------------------------------------------------------------------
    def _draw_cross_building_pipe(
        self, fr_id: int, to_id: int, color: str
    ) -> None:
        """
        Cross-building pipe routed orthogonally:
          from_node (go down) → horizontal jog at mid-height → (rise to) to_node.
        Different y-offsets for steam vs feedwater connections avoid overlap.
        """
        ax = self.ax
        x0, y0 = self._pos[fr_id]
        x1, y1 = self._pos[to_id]

        pad  = _SYM_SIZE + 0.12
        # Midway y between the two buildings with a small offset per direction
        y_mid = (y0 + y1) / 2 + (0.3 if y0 > y1 else -0.3)

        xs = [x0, x0, x1, x1]
        ys = [y0 - pad, y_mid, y_mid, y1 + pad]

        ax.plot(xs, ys, color=color, lw=_PIPE_LW * 0.9,
                linestyle=(0, (5, 2)),   # dashed — inter-system line
                solid_capstyle="round", solid_joinstyle="round", zorder=2)

        # Arrow at the horizontal segment midpoint
        mx = (x0 + x1) / 2
        dx = x1 - x0
        sign = 1 if dx >= 0 else -1
        ax.annotate(
            "", xy=(mx + sign * 0.22, y_mid), xytext=(mx, y_mid),
            arrowprops=dict(arrowstyle="-|>", color=color,
                            lw=_PIPE_LW * 0.9, mutation_scale=12),
            zorder=3,
        )

        # Label
        t_fr = self._nodes[fr_id]["type"]
        t_to = self._nodes[to_id]["type"]
        slabel = _STREAM_LABELS.get((t_fr, t_to), "PROCESS LINE")
        ax.text(
            mx, y_mid + 0.16, slabel,
            ha="center", va="bottom",
            fontsize=5.5, style="italic",
            color=self.style["stream_label"],
            zorder=4,
        )

    # ------------------------------------------------------------------
    def _draw_node(self, nid: int, node: dict, cx: float, cy: float) -> None:
        """Draw symbol, equipment tag, name label, and sizing parameters."""
        st    = self.style
        ax    = self.ax
        typ   = node["type"]
        name  = node["name"]
        props = node["properties"]

        draw_fn = SYMBOL_DRAW.get(typ, draw_unknown)
        draw_fn(ax, cx, cy, size=_SYM_SIZE,
                edge=st["sym_edge"], face=st["sym_face"])

        # ── Equipment tag bubble (top-left of symbol) ────────────────────
        tag = self._tags.get(nid, "")
        if tag:
            self._draw_tag_bubble(cx, cy, tag)

        # ── Component name (bold, just below symbol) ──────────────────────
        ax.text(
            cx, cy - _LABEL_GAP, name,
            ha="center", va="top",
            fontsize=8.5, fontweight="bold",
            color=st["label_fg"], zorder=5,
        )

        # ── Component type (italic, smaller) ──────────────────────────────
        type_str = typ.replace("_", " ").title() if typ not in ("unknown", "boundary") else ""
        if type_str:
            ax.text(
                cx, cy - _LABEL_GAP - 0.30, type_str,
                ha="center", va="top",
                fontsize=6.0, style="italic",
                color=st["param_fg"], zorder=5,
            )

        # ── Sizing parameters ─────────────────────────────────────────────
        param_defs = _PARAM_KEYS.get(typ, [])
        y_off = cy - _LABEL_GAP - 0.58
        for pkey, plabel, punit in param_defs:
            val = self._get_prop(props, pkey)
            if val is None:
                continue
            txt = f"{plabel} = {val}" + (f" {punit}" if punit else "")
            ax.text(
                cx, y_off, txt,
                ha="center", va="top",
                fontsize=5.8,
                color=st["param_fg"], zorder=5,
                fontfamily="monospace",
            )
            y_off -= 0.23

        # ── Requirements badge ────────────────────────────────────────────
        self._draw_req_badge(name, cx, cy)

    # ------------------------------------------------------------------
    def _draw_tag_bubble(self, cx: float, cy: float, tag: str) -> None:
        """Small equipment tag in the upper-left of the symbol."""
        st = self.style
        ax = self.ax
        bx = cx - _SYM_SIZE * 0.70
        by = cy + _SYM_SIZE * 0.75
        bw, bh = len(tag) * 0.09 + 0.20, 0.28
        ax.add_patch(mpatches.FancyBboxPatch(
            (bx - bw / 2, by - bh / 2), bw, bh,
            boxstyle="round,pad=0.03",
            facecolor=st["tag_bg"],
            edgecolor=st["tag_border"],
            linewidth=0.8, zorder=6,
        ))
        ax.text(
            bx, by, tag,
            ha="center", va="center",
            fontsize=5.0, fontweight="bold",
            color=st["tag_fg"], zorder=7,
        )

    # ------------------------------------------------------------------
    def _get_prop(self, props: dict, key: str) -> str | None:
        val = props.get(key)
        if val is None:
            val = props.get("design_summary", {}).get(key)
        if val is None:
            return None
        if not isinstance(val, (int, float)):
            return str(val)
        if val == 0:
            return "0"
        abs_val = abs(val)
        if abs_val >= 1000:
            return f"{val:,.0f}"
        if abs_val >= 10:
            return f"{val:.1f}"
        if abs_val >= 0.1:
            return f"{val:.3f}"
        return f"{val:.4f}"

    # ------------------------------------------------------------------
    def _draw_req_badge(self, node_name: str, cx: float, cy: float) -> None:
        st = self.style
        ax = self.ax

        has_baseline = node_name in _REQ_COMPONENT_MAP
        req_data     = self.req_info.get(node_name)

        if not has_baseline and req_data is None:
            return

        bx = cx + _SYM_SIZE * 0.82
        by = cy + _SYM_SIZE * 0.82

        if req_data and req_data.get("generated"):
            n_app = req_data.get("applicable", "?")
            n_tbd = req_data.get("tbd", 0)
            if n_tbd > 0:
                badge_edge = "#cc6600"
                badge_face = "#fff3e0" if not self.blueprint else "#3a1a00"
                btxt = f"REQ\n{n_app}+{n_tbd}TBD"
            else:
                badge_edge = st["req_gen_edge"]
                badge_face = st["req_gen_face"]
                btxt = f"REQ\n✓ {n_app}"
        else:
            badge_edge = st["req_edge"]
            badge_face = st["req_face"]
            btxt = "REQ"

        bw = 0.52
        bh = 0.34 if "\n" not in btxt else 0.46
        ax.add_patch(mpatches.FancyBboxPatch(
            (bx - bw / 2, by - bh / 2), bw, bh,
            boxstyle="round,pad=0.03",
            facecolor=badge_face, edgecolor=badge_edge,
            linewidth=1.0, zorder=6,
        ))
        ax.text(
            bx, by, btxt,
            ha="center", va="center",
            fontsize=4.8, fontweight="bold",
            color=badge_edge,
            multialignment="center",
            zorder=7,
        )

    # ------------------------------------------------------------------
    def _draw_legend(self) -> None:
        """Compact symbol legend at bottom-left."""
        from .symbols import (
            draw_pump, draw_steam_generator, draw_turbine,
            draw_valve, draw_reactor_core, draw_condenser, draw_boundary,
        )
        st = self.style
        ax = self.ax

        items = [
            (draw_reactor_core,    "Reactor Core"),
            (draw_pump,            "Pump (centrifugal)"),
            (draw_steam_generator, "Steam Generator / HX"),
            (draw_turbine,         "Turbine"),
            (draw_valve,           "Valve"),
            (draw_condenser,       "Condenser"),
            (draw_boundary,        "System Boundary"),
        ]

        all_x = [x for x, _ in self._pos.values()]
        all_y = [y for _, y in self._pos.values()]
        lx0 = min(all_x) - 0.8
        ly0 = min(all_y) - _RETURN_DY - 1.2

        # Legend box
        n_rows = math.ceil(len(items) / 3)
        leg_w  = 7.6
        leg_h  = n_rows * 0.65 + 0.9
        ax.add_patch(mpatches.FancyBboxPatch(
            (lx0 - 0.15, ly0 - leg_h + 0.15), leg_w, leg_h,
            boxstyle="square,pad=0",
            fill=False,
            edgecolor=st["fg"],
            linewidth=0.6,
            zorder=5,
        ))
        ax.text(lx0, ly0 + 0.08, "LEGEND",
                fontsize=6.5, fontweight="bold",
                color=st["fg"], va="bottom", zorder=6)

        sz  = 0.21
        col_w, row_h = 2.55, 0.62
        for i, (fn, lbl) in enumerate(items):
            col = i % 3
            row = i // 3
            lx = lx0 + col * col_w
            ly = ly0 - 0.36 - row * row_h
            fn(ax, lx + sz, ly, size=sz,
               edge=st["sym_edge"], face=st["sym_face"], lw=0.9)
            ax.text(lx + sz * 2.5, ly, lbl,
                    ha="left", va="center",
                    fontsize=5.8, color=st["fg"], zorder=6)

        # Line-type legend
        line_types = [
            (st["pipe"],     "-",          "Primary coolant"),
            (st["pipe_sec"], (0, (5, 2)), "Main steam"),
            (st["pipe_ret"], "-",          "Feedwater / condensate"),
        ]
        lly = ly0 - 0.36 - n_rows * row_h
        ax.text(lx0, lly + 0.04, "PIPE DESIGNATIONS",
                fontsize=5.8, fontweight="bold", color=st["fg"], zorder=6)
        for j, (clr, ls, desc) in enumerate(line_types):
            lly_j = lly - 0.28 - j * 0.30
            ax.plot([lx0, lx0 + 0.65], [lly_j, lly_j],
                    color=clr, lw=1.6, linestyle=ls, zorder=6)
            ax.text(lx0 + 0.75, lly_j, desc,
                    ha="left", va="center",
                    fontsize=5.5, color=st["fg"], zorder=6)

        # REQ badges
        req_lx = lx0 + leg_w - 3.0
        req_ly = ly0 - 0.22
        ax.text(req_lx, req_ly + 0.04, "REQ BADGES",
                fontsize=5.8, fontweight="bold", color=st["fg"], zorder=6)
        for badge_clr, badge_face, blbl in [
            (st["req_edge"],     st["req_face"],     "Baseline available"),
            (st["req_gen_edge"], st["req_gen_face"],  "Requirements generated"),
            ("#cc6600",          "#fff3e0" if not self.blueprint else "#3a1a00",
             "Has TBD parameters"),
        ]:
            req_ly -= 0.34
            ax.add_patch(mpatches.FancyBboxPatch(
                (req_lx, req_ly - 0.12), 0.36, 0.24,
                boxstyle="round,pad=0.02",
                facecolor=badge_face, edgecolor=badge_clr,
                linewidth=0.8, zorder=6,
            ))
            ax.text(req_lx + 0.18, req_ly,
                    "REQ", ha="center", va="center",
                    fontsize=4.5, fontweight="bold",
                    color=badge_clr, zorder=7)
            ax.text(req_lx + 0.46, req_ly, blbl,
                    ha="left", va="center",
                    fontsize=5.5, color=st["fg"], zorder=6)

    # ------------------------------------------------------------------
    def _draw_title_block(self) -> None:
        """
        Professional engineering drawing title block (bottom-right corner).

        Layout (right-justified):
        ┌──────────────────────────────────────┐
        │  PROJECT                             │
        │  nucsys-agent                         │
        ├──────────────────────────────────────┤
        │  TITLE                               │
        │  <self.title>                         │
        ├────────────┬──────────┬──────────────┤
        │ DWG NO.    │ SCALE    │ DATE         │
        │ NUCS-001   │ NTS      │ yyyy-mm-dd   │
        ├────────────┼──────────┴──────────────┤
        │ REV.       │ Standard: IEC-60617      │
        │ A          │ nucsys-agent             │
        └────────────┴──────────────────────────┘
        """
        st = self.style
        ax = self.ax

        all_x = [x for x, _ in self._pos.values()]
        all_y = [y for _, y in self._pos.values()]
        bw = 5.2
        bh = 2.8
        tx1 = max(all_x) + 1.0
        ty0 = min(all_y) - _RETURN_DY - bh - 0.4

        def hline(y_):
            ax.plot([tx1 - bw, tx1], [y_, y_],
                    color=st["fg"], lw=0.6, zorder=8)

        def vline(x_, y_bot, y_top):
            ax.plot([x_, x_], [y_bot, y_top],
                    color=st["fg"], lw=0.6, zorder=8)

        # Outer box
        ax.add_patch(mpatches.FancyBboxPatch(
            (tx1 - bw, ty0), bw, bh,
            boxstyle="square,pad=0",
            facecolor=st["title_bg"],
            edgecolor=st["fg"],
            linewidth=1.4, zorder=7,
        ))

        # Row heights (from top)
        r_proj  = ty0 + bh
        r_title = r_proj  - 0.72
        r_info  = r_title - 0.92
        r_rev   = r_info  - 0.60
        # bottom = ty0

        # ── Row 1: PROJECT ────────────────────────────────────────────────
        hline(r_title)
        ax.text(tx1 - bw + 0.12, r_proj - 0.06,
                "PROJECT", ha="left", va="top",
                fontsize=5.0, fontweight="bold", color=st["fg"], zorder=8)
        ax.text(tx1 - bw + 0.12, r_proj - 0.28,
                "nucsys-agent  •  Nuclear System Design",
                ha="left", va="top",
                fontsize=6.5, fontweight="bold", color=st["fg"], zorder=8)

        # ── Row 2: TITLE ──────────────────────────────────────────────────
        hline(r_info)
        ax.text(tx1 - bw + 0.12, r_title - 0.06,
                "DRAWING TITLE", ha="left", va="top",
                fontsize=5.0, fontweight="bold", color=st["fg"], zorder=8)
        # Wrap title at ~52 chars
        ttl = self.title
        if len(ttl) > 46:
            mid = ttl[:46].rfind(" ")
            lines_ = [ttl[:mid], ttl[mid + 1:]] if mid > 0 else [ttl[:46], ttl[46:]]
        else:
            lines_ = [ttl]
        for li, tline in enumerate(lines_):
            ax.text(tx1 - bw + 0.12, r_title - 0.28 - li * 0.24,
                    tline, ha="left", va="top",
                    fontsize=6.8, fontweight="bold", color=st["fg"], zorder=8)
        ax.text(tx1 - bw + 0.12, r_title - 0.28 - len(lines_) * 0.24,
                "Single-Line Diagram  (IEC-60617 / IEEE-315)",
                ha="left", va="top", fontsize=5.5, color=st["fg"], zorder=8)

        # ── Row 3: DWG NO. / SCALE / DATE ────────────────────────────────
        hline(r_rev)
        col1 = tx1 - bw + bw * 0.36
        col2 = tx1 - bw + bw * 0.64
        vline(col1, r_rev, r_info)
        vline(col2, r_rev, r_info)
        for label, val, xc in [
            ("DWG NO.",  "NUCS-001",            tx1 - bw + (col1 - tx1 + bw) / 2),
            ("SCALE",    "NTS",                  (col1 + col2) / 2),
            ("DATE",     date.today().isoformat(), (col2 + tx1) / 2),
        ]:
            ax.text(xc, r_info - 0.05, label,
                    ha="center", va="top",
                    fontsize=4.8, fontweight="bold", color=st["fg"], zorder=8)
            ax.text(xc, r_info - 0.24, val,
                    ha="center", va="top",
                    fontsize=6.0, color=st["fg"], zorder=8,
                    fontfamily="monospace")

        # ── Row 4: REV / STANDARD ─────────────────────────────────────────
        vline(col1, ty0, r_rev)
        ax.text(tx1 - bw + (col1 - tx1 + bw) / 2, r_rev - 0.05,
                "REV.", ha="center", va="top",
                fontsize=4.8, fontweight="bold", color=st["fg"], zorder=8)
        ax.text(tx1 - bw + (col1 - tx1 + bw) / 2, r_rev - 0.26,
                "A", ha="center", va="top",
                fontsize=8.0, fontweight="bold", color=st["fg"], zorder=8)
        ax.text(col1 + 0.12, r_rev - 0.05,
                "Standard:   IEC-60617 / IEEE-315",
                ha="left", va="top",
                fontsize=5.3, color=st["fg"], zorder=8,
                fontfamily="monospace")
        ax.text(col1 + 0.12, r_rev - 0.26,
                "Generated:  nucsys-agent",
                ha="left", va="top",
                fontsize=5.3, color=st["fg"], zorder=8,
                fontfamily="monospace")

    # ------------------------------------------------------------------
    def _draw_drawing_border(self) -> None:
        """
        Engineering drawing border: thick outer frame + thin inner frame
        (standard A-size border convention).
        """
        st = self.style
        ax = self.ax
        xl, xr = ax.get_xlim()
        yb, yt = ax.get_ylim()
        w = xr - xl
        h = yt - yb

        outer_pad = 0.08
        inner_pad = 0.38

        for pad, lw in [(outer_pad, 2.4), (inner_pad, 0.7)]:
            ax.add_patch(mpatches.FancyBboxPatch(
                (xl + pad, yb + pad), w - 2 * pad, h - 2 * pad,
                boxstyle="square,pad=0",
                fill=False,
                edgecolor=st["border"],
                linewidth=lw,
                zorder=10,
                clip_on=False,
            ))
