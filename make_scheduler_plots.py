"""Generate figures for the scheduler-headroom blog post.

Saves SVGs to /Users/chelo/lakeprof-experiments/reports/figs-scheduler/.

Run from /Users/chelo/mathlib4-lakeprof.

If RUNNER=1 in the environment, sources data from runner-clean.graph.json +
runner_cache_hit_sweep.json (recorded on the Xeon Gold 6248R pr runner) and
writes to figs-scheduler-runner/ instead. Otherwise uses the local
Apple-Silicon trace.
"""
import json
import os
import sys

sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

sys.path.insert(0, ".")
from scheduler_sim import simulate, wall_clock, load_graph_json

RUNNER = os.environ.get("RUNNER") == "1"
OUT = ("/Users/chelo/lakeprof-experiments/reports/figs-scheduler-runner"
       if RUNNER else
       "/Users/chelo/lakeprof-experiments/reports/figs-scheduler")
SUBTITLE = ("runner trace — Xeon Gold 6248R, 12 cores, KVM"
            if RUNNER else
            "local 18-core Apple-Silicon trace")
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "savefig.bbox": "tight",
    "savefig.dpi": 100,
    "figure.dpi": 100,
})

PALETTE = {
    "fifo":   "#4477AA",
    "hlfet":  "#228833",
    "lpt":    "#CCBB44",
    "random": "#AA3377",
    "lb":     "#BB5566",
    "cp":     "#88CCEE",
    "cp-bound":   "#CCBB44",
    "work-bound": "#228833",
}

# --------------------------------------------------------------------------- #
# Load data
# --------------------------------------------------------------------------- #

if RUNNER:
    g = load_graph_json("runner-clean.graph.json")
else:
    with open("mathlib-clean.log") as f:
        g = lakeprof.parse(f)
for u, _, d in g.edges(data=True):
    d["time"] = g.nodes[u]["time"]
total_work = sum(d["time"] for _, d in g.nodes(data=True))
cp_path = networkx.dag_longest_path(g, weight="time")
cp_clean = sum(g.nodes[u]["time"] for u in cp_path)

P = 12
LB_clean = max(cp_clean, total_work / P)

# Run all four policies (cheap)
walls = {}
for pol in ("fifo", "hlfet", "lpt", "random"):
    gs, _ = simulate(g, P, priority=pol)
    walls[pol] = wall_clock(gs)
print(f"clean-build wall-clocks: {walls}")
print(f"  total_work={total_work:.0f}s, CP={cp_clean:.0f}s, LB={LB_clean:.1f}s")

sweep_path = "runner_cache_hit_sweep.json" if RUNNER else "scheduler_cache_hit_sweep.json"
with open(sweep_path) as f:
    sweep = json.load(f)
rows = sweep["rows"]
print(f"sweep rows: {len(rows)}")


# --------------------------------------------------------------------------- #
# fig1 — clean-build per-policy wall-clock at p=12 vs LB
# --------------------------------------------------------------------------- #

fig, ax = plt.subplots(figsize=(7.5, 4.0))
order = ["fifo", "hlfet", "lpt", "random"]
xs = np.arange(len(order))
ys = [walls[p] for p in order]
bars = ax.bar(xs, ys, color=[PALETTE[p] for p in order], width=0.62, zorder=3)
ax.axhline(LB_clean, color=PALETTE["lb"], lw=1.6, ls="--", zorder=2,
           label=f"makespan lower bound = max(CP, work/p) = {LB_clean:.0f} s")
ax.axhline(cp_clean, color=PALETTE["cp"], lw=1.6, ls=":", zorder=2,
           label=f"critical-path floor = {cp_clean:.0f} s")
ax.set_xticks(xs)
ax.set_xticklabels([p.upper() if p == "fifo" else p for p in order])
ax.set_ylabel("simulated wall-clock at p=12 (s)")
ax.set_title(f"Clean-build wall-clock: any oracle scheduler is at or above the dashed line\n({SUBTITLE})", fontsize=11)
for x, y, p in zip(xs, ys, order):
    over = (y - LB_clean) / y * 100
    ax.annotate(f"{y:.0f}s\n+{over:.2f}% over LB",
                (x, y), textcoords="offset points", xytext=(0, 6),
                ha="center", va="bottom", fontsize=10)
ax.set_ylim(LB_clean - 30, max(ys) * 1.06)
ax.legend(loc="upper right", framealpha=0.95)
plt.savefig(f"{OUT}/01-policies-cleanbuild.svg")
plt.close(fig)


# --------------------------------------------------------------------------- #
# fig2 — CDF of gap-over-LB across 184 commits, FIFO and HLFET
# --------------------------------------------------------------------------- #

fig, ax = plt.subplots(figsize=(7.5, 4.0))
fifo_gaps = sorted(r["fifo_gap"] for r in rows)
hl_gaps   = sorted(r["hlfet_gap"] for r in rows)
n = len(rows)
yy = np.arange(1, n + 1) / n
ax.plot([g * 100 for g in fifo_gaps], yy, color=PALETTE["fifo"], lw=2,
        label=f"FIFO  (mean {sum(fifo_gaps)/n*100:.2f}%)")
ax.plot([g * 100 for g in hl_gaps], yy, color=PALETTE["hlfet"], lw=2,
        label=f"HLFET (mean {sum(hl_gaps)/n*100:.2f}%)")
ax.axvline(5, color="#888", lw=1, ls="--", zorder=1)
ax.text(5.1, 0.03, "5% decision-rule\nthreshold", fontsize=9, color="#555")
ax.set_xlabel("gap-over-LB at p=12 (%)")
ax.set_ylabel("CDF (cumulative fraction of commits)")
ax.set_title(f"Per-commit oracle-headroom ceiling across {n} commits — most are zero\n({SUBTITLE})", fontsize=11)
ax.set_xlim(-0.5, 28)
ax.set_ylim(0, 1.005)
ax.legend(loc="lower right")
plt.savefig(f"{OUT}/02-gap-cdf.svg")
plt.close(fig)


# --------------------------------------------------------------------------- #
# fig3 — scatter: HLFET gap vs blast size, colored by regime
# --------------------------------------------------------------------------- #

fig, ax = plt.subplots(figsize=(8.0, 4.5))
for regime in ("cp-bound", "work-bound"):
    sub = [r for r in rows if r["regime"] == regime]
    ax.scatter(
        [r["n_blast"] for r in sub],
        [r["hlfet_gap"] * 100 for r in sub],
        s=[max(8, np.sqrt(r["fifo_wall_s"]) * 1.4) for r in sub],
        c=PALETTE[regime], alpha=0.65, edgecolor="white", linewidth=0.4,
        label=f"{regime} (n={len(sub)})",
    )
ax.set_xscale("log")
ax.set_xlabel("blast size (modules invalidated by commit, log scale)")
ax.set_ylabel("HLFET gap-over-LB (%)")
ax.set_title(f"HLFET headroom vs blast size — outliers are CP-bound Analysis/MeasureTheory refactors\n({SUBTITLE})", fontsize=11)
ax.axhline(5, color="#888", lw=1, ls="--", zorder=0)
ax.text(1.05, 5.4, "5% threshold", fontsize=9, color="#555")
ax.legend(loc="upper left", title="dot size ∝ √(FIFO wall-clock)")
plt.savefig(f"{OUT}/03-scatter-hlfet-gap.svg")
plt.close(fig)


# --------------------------------------------------------------------------- #
# fig4 — per-commit CP vs work/p — diagonal divides regimes
# --------------------------------------------------------------------------- #

fig, ax = plt.subplots(figsize=(7.0, 5.0))
for regime in ("cp-bound", "work-bound"):
    sub = [r for r in rows if r["regime"] == regime]
    ax.scatter(
        [r["rebuild_work_s"] / P for r in sub],
        [r["rebuild_cp_s"] for r in sub],
        s=[max(8, np.sqrt(r["fifo_wall_s"]) * 1.2) for r in sub],
        c=PALETTE[regime], alpha=0.65, edgecolor="white", linewidth=0.4,
        label=f"{regime} (n={len(sub)})",
    )
mx = max(max(r["rebuild_work_s"] / P for r in rows),
         max(r["rebuild_cp_s"] for r in rows))
ax.plot([0, mx], [0, mx], color="#444", lw=1, ls="--", zorder=1,
        label="rebuild_CP = rebuild_work/p")
ax.set_xlabel("rebuild_work / p (s)")
ax.set_ylabel("rebuild_CP (s)")
ax.set_title(f"Where each commit lives — above the diagonal = CP-bound (scheduler can't help)\n({SUBTITLE})", fontsize=11)
ax.set_aspect("equal")
ax.set_xlim(0, mx * 1.05)
ax.set_ylim(0, mx * 1.05)
ax.legend(loc="upper left")
plt.savefig(f"{OUT}/04-regime-scatter.svg")
plt.close(fig)


# --------------------------------------------------------------------------- #
# fig5 — gap distribution histogram (work-bound only)
# --------------------------------------------------------------------------- #

fig, ax = plt.subplots(figsize=(7.5, 3.8))
wo = [r for r in rows if r["regime"] == "work-bound"]
fifo_wo = [r["fifo_gap"] * 100 for r in wo]
hl_wo   = [r["hlfet_gap"] * 100 for r in wo]
bins = np.arange(0, 20, 1.0)
ax.hist(fifo_wo, bins=bins, color=PALETTE["fifo"], alpha=0.65, label="FIFO", zorder=2)
ax.hist(hl_wo,   bins=bins, color=PALETTE["hlfet"], alpha=0.85, label="HLFET", zorder=3)
ax.set_xlabel("gap-over-LB (%) — work-bound commits only")
ax.set_ylabel("# commits")
ax.set_title(f"Where smarter scheduling could help: {len(wo)} work-bound commits\n({SUBTITLE})", fontsize=11)
ax.legend()
plt.savefig(f"{OUT}/05-hist-workbound.svg")
plt.close(fig)


print(f"\nfigures saved to {OUT}/")
for n in sorted(os.listdir(OUT)):
    print(f"  {n}")
