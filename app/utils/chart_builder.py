"""
Build a matplotlib bar chart matching the Lumi preliminary report design.
"""

from __future__ import annotations

import base64
import io
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import MultipleLocator  # noqa: E402


# Brand colors from Penny Roberts PDF reference
BLUE_START = "#3b82f6"
BLUE_END = "#0f172a"
AXIS = "#94a3b8"
LABEL = "#475569"
GRID = "#e2e8f0"


def build_utility_chart_png(
    annuals: list[float],
    *,
    width: float = 4.8,
    height: float = 3.55,
) -> bytes:
    """20-year bar chart: light → dark blue gradient (matches sample PDF)."""
    n = len(annuals)
    years = list(range(1, n + 1))

    fig, ax = plt.subplots(figsize=(width, height), dpi=200)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    cmap = LinearSegmentedColormap.from_list("lumi_blue", [BLUE_START, BLUE_END])
    colors = [cmap(i / max(n - 1, 1)) for i in range(n)]

    ax.bar(years, annuals, color=colors, width=0.82, edgecolor="none", zorder=3)

    ax.set_ylabel("Annual Cost ($)", fontsize=7.5, color=LABEL, labelpad=5)
    ax.tick_params(axis="y", labelsize=6.5, colors=AXIS, length=0)
    ax.tick_params(axis="x", labelsize=7, colors=LABEL, length=0)

    # Show Yr 1, 5, 10, 15, 20 like the sample
    tick_years = [y for y in (1, 5, 10, 15, 20) if y <= n]
    ax.set_xticks(tick_years)
    ax.set_xticklabels([f"Yr {y}" for y in tick_years])

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    ymax = max(annuals) if annuals else 1
    # Round y max up to a clean $2k step so ticks match the sample ($0k–$8k)
    step = 2000.0
    ymax_nice = math.ceil((ymax * 1.02) / step) * step
    if ymax_nice <= ymax:
        ymax_nice += step
    ax.set_ylim(0, ymax_nice)
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.set_xlim(0.35, n + 0.65)

    def _fmt(v: float, _pos) -> str:
        if v >= 1000:
            return f"${v / 1000:.0f}k"
        return f"${v:.0f}"

    ax.yaxis.set_major_formatter(plt.FuncFormatter(_fmt))

    fig.tight_layout(pad=0.25)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(), pad_inches=0.05)
    plt.close(fig)
    return buf.getvalue()


def utility_chart_data_uri(annuals: list[float], **kwargs) -> str:
    raw = build_utility_chart_png(annuals, **kwargs)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"
