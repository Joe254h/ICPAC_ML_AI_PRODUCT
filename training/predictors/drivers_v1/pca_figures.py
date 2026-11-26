#!/usr/bin/env python3
"""Manuscript figures and tables for the grouped PCA (ICPAC_WEEK2_DRIVERS_245_V1).

    python pca_figures.py            # reads groups/<G>/..., writes figures/pca/

For every group it writes, as 300 dpi PNG and vector PDF:
  <G>_scree.*     eigenvalues with North et al. (1982) sampling error bars, the Kaiser line and
                  the broken-stick expectation (left); cumulative explained variance with the
                  80/90/95 % marks and the selected count (right). Two panels, one axis each.
  <G>_loadings.*  loadings of the selected components (diverging scale, symmetric about 0)
  <G>_seasonal.*  case-level groups only: monthly mean of the leading 3 component scores
and one table for the paper: selection_criteria.csv and selection_criteria.tex.
Spatial maps of component scores need the projected features; they come with the
feature-table step.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers_pca as dp  # noqa: E402
import numpy as np  # noqa: E402

GROUPS = dp.EXP / "groups"
OUT = dp.EXP / "figures" / "pca"
NAMES = {
    "G1": "G1 Atmospheric state and dynamics",
    "G2": "G2 Moisture transport and budgets",
    "G3": "G3 Rainfall and ensemble statistics",
    "G4": "G4 Antecedent rainfall and land surface",
    "G5": "G5 Ocean and climate indices",
    "G6": "G6 Regional circulation mechanisms",
    "G910": "G9+10 Cloud microphysics and surface",
}
N_STAR = 500
SELECTED = "#2a6fb0"  # one hue for selected components
OTHER = "#c4cad3"  # recessive gray for the rest
INK = "#1f2328"
QUIET = "#59636e"
GRID = "#e6e8eb"


def criteria(e, ratio):
    p = len(e)
    stick = np.array([sum(1 / k for k in range(i, p + 1)) / p for i in range(1, p + 1)])
    err = e * np.sqrt(2 / N_STAR)
    sep = (e[:-1] - e[1:]) > err[:-1]
    north = int(np.argmin(sep)) if not sep.all() else p
    cum = np.cumsum(ratio)
    return {
        "kaiser": int((e > 1).sum()),
        "broken_stick": int(np.argmax(ratio < stick)) if (ratio < stick).any() else p,
        "north": north,
        "v80": int(np.searchsorted(cum, 0.8) + 1),
        "v90": int(np.searchsorted(cum, 0.9) + 1),
        "v95": int(np.searchsorted(cum, 0.95) + 1),
        "stick": stick,
        "err": err,
        "cum": cum,
    }


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(QUIET)
    ax.tick_params(colors=QUIET, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def scree(g, e, ratio, nsel, c, plt):
    show = min(len(e), 30)
    k = np.arange(1, show + 1)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.4), constrained_layout=True)
    colors = [SELECTED if i < nsel else OTHER for i in range(show)]
    a1.bar(k, e[:show], color=colors, width=0.7)
    a1.errorbar(
        k, e[:show], yerr=c["err"][:show], fmt="none", ecolor=INK, elinewidth=0.8, capsize=2
    )
    a1.plot(k, c["stick"][:show] * e.sum(), color=QUIET, linestyle="--", linewidth=1.2)
    a1.axhline(1.0, color=QUIET, linewidth=0.8, linestyle=":")
    a1.text(2.2, c["stick"][1] * e.sum(), "broken stick", color=QUIET, fontsize=7.5, va="bottom")
    a1.text(show * 0.55, 1.0, "Kaiser (λ = 1)", color=QUIET, fontsize=7.5, va="bottom")
    a1.set_xlabel("Component", fontsize=8.5, color=INK)
    a1.set_ylabel("Eigenvalue (correlation PCA)", fontsize=8.5, color=INK)
    a1.set_title(f"Eigenvalues ± North error (N* = {N_STAR})", fontsize=9, color=INK, loc="left")
    style(a1)
    a2.plot(k, c["cum"][:show] * 100, color=SELECTED, linewidth=2, marker="o", markersize=3)
    for t in (80, 90, 95):
        a2.axhline(t, color=GRID, linewidth=0.9)
        a2.text(show, t, f"{t}% ", color=QUIET, fontsize=7.5, va="bottom", ha="right")
    a2.axvline(nsel, color=INK, linewidth=0.9, linestyle="--")
    a2.text(nsel + 0.3, 8, f"selected: {nsel} ({c['cum'][nsel - 1]:.1%})", color=INK, fontsize=8)
    a2.set_ylim(0, 102)
    a2.set_xlabel("Number of components", fontsize=8.5, color=INK)
    a2.set_ylabel("Cumulative variance explained (%)", fontsize=8.5, color=INK)
    a2.set_title("Cumulative variance", fontsize=9, color=INK, loc="left")
    style(a2)
    fig.suptitle(NAMES[g], fontsize=10.5, color=INK, x=0.01, ha="left", fontweight="bold")
    return fig


def loadings(g, comps, names, nsel, plt):
    L = comps[:nsel].T  # features x selected PCs
    h = max(3.0, 0.16 * len(names) + 1.2)
    fig, ax = plt.subplots(figsize=(1.2 + 0.42 * nsel + 2.2, h), constrained_layout=True)
    lim = float(np.abs(L).max())
    im = ax.imshow(L, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_yticks(range(len(names)), names, fontsize=6.5, color=INK)
    ax.set_xticks(
        range(nsel), [f"PC{i + 1}" for i in range(nsel)], fontsize=7, color=INK, rotation=90
    )
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cb.set_label("Loading", fontsize=8, color=INK)
    cb.ax.tick_params(labelsize=7, colors=QUIET)
    ax.set_title(
        f"{NAMES[g]}: loadings of the {nsel} selected components", fontsize=9, color=INK, loc="left"
    )
    return fig


def seasonal(g, plt):
    """Small multiples: one panel per leading component, mean and +-1 sd band by start month."""
    path = GROUPS / g / "case_pcs.csv"
    if not path.is_file():
        return None
    rows = list(csv.DictReader(path.open()))
    cols = [c for c in rows[0] if c.startswith(f"{g}_PC")][:3]
    month = np.array([int(r["mmdd"][:2]) for r in rows])
    fig, axes = plt.subplots(
        1, len(cols), figsize=(3.2 * len(cols), 2.8), sharey=True, constrained_layout=True
    )
    for ax, col in zip(np.atleast_1d(axes), cols):
        v = np.array([float(r[col]) for r in rows])
        m = np.array([v[month == k].mean() for k in range(1, 13)])
        s = np.array([v[month == k].std() for k in range(1, 13)])
        x = np.arange(1, 13)
        ax.fill_between(x, m - s, m + s, color=SELECTED, alpha=0.15, linewidth=0)
        ax.plot(x, m, color=SELECTED, linewidth=2, marker="o", markersize=3)
        ax.axhline(0, color=QUIET, linewidth=0.8)
        ax.set_xticks(x, list("JFMAMJJASOND"), fontsize=8)
        ax.set_title(col.replace(f"{g}_", ""), fontsize=9, color=INK, loc="left")
        style(ax)
    np.atleast_1d(axes)[0].set_ylabel("Score (band = ±1 sd across years)", fontsize=8, color=INK)
    fig.suptitle(
        f"{NAMES[g]}: leading components by start month", fontsize=10, color=INK, x=0.01, ha="left"
    )
    return fig


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.dpi": 100})
    OUT.mkdir(parents=True, exist_ok=True)
    table = []
    for g in NAMES:
        f = GROUPS / g / f"{g}_PCA_2005_2021.npz"
        if not f.is_file():
            print(f"skip {g}: {f} not found")
            continue
        with np.load(f, allow_pickle=False) as z:
            e, ratio = z["eigenvalues"], z["explained_variance_ratio"]
            comps, names, nsel = (
                z["components"],
                [str(x) for x in z["feature_names"]],
                int(z["n_selected"]),
            )
            dropped = (
                [str(x) for x in z["dropped_features"]] if "dropped_features" in z.files else []
            )
        c = criteria(e, ratio)
        figs = {
            "scree": scree(g, e, ratio, nsel, c, plt),
            "loadings": loadings(g, comps, names, nsel, plt),
        }
        if g in ("G5", "G6"):
            figs["seasonal"] = seasonal(g, plt)
        for kind, fig in figs.items():
            if fig is None:
                continue
            for ext in ("png", "pdf"):
                fig.savefig(OUT / f"{g}_{kind}.{ext}", dpi=300)
            plt.close(fig)
        table.append({
            "group": NAMES[g], "variables": len(names), "dropped": len(dropped),
            "top5_percent": " ".join(f"{100 * r:.1f}" for r in ratio[:5]),
            "kaiser": c["kaiser"], "broken_stick": c["broken_stick"], f"north_N{N_STAR}": c["north"],
            "v80": c["v80"], "v90": c["v90"], "v95": c["v95"], "selected": nsel,
            "variance_selected": f"{100 * c['cum'][nsel - 1]:.1f}",
        })  # fmt: skip
        print(f"{g}: figures written")
    with open(OUT / "selection_criteria.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    with open(OUT / "selection_criteria.tex", "w") as fh:
        fh.write("\\begin{tabular}{lrrrrrrrrr}\n\\hline\n")
        fh.write(
            f"Group & Vars & Kaiser & Broken stick & North ($N^*={N_STAR}$) & 80\\% & 90\\% & 95\\% & Selected & Var.\\,(\\%)\\\\\n\\hline\n"
        )
        for r in table:
            fh.write(f"{r['group']} & {r['variables']} & {r['kaiser']} & {r['broken_stick']} & "
                     f"{r[f'north_N{N_STAR}']} & {r['v80']} & {r['v90']} & {r['v95']} & "
                     f"{r['selected']} & {r['variance_selected']}\\\\\n")  # fmt: skip
        fh.write("\\hline\n\\end{tabular}\n")
    print(f"PASS: figures and selection_criteria.csv/.tex in {OUT}")


if __name__ == "__main__":
    main()
