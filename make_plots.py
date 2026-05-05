"""Generate all figures for the blogpost. Saves SVGs to figs/."""
import sys
import subprocess
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "savefig.bbox": "tight",
    "savefig.dpi": 100,
    "figure.dpi": 100,
})

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]
total_work = sum(d["time"] for _, d in g.nodes(data=True))
full_cp = networkx.dag_longest_path_length(g, weight="time")

# ---------------- 1. Speedup curve ----------------
fig, ax = plt.subplots(figsize=(8, 4.5))
nprocs = [1, 2, 4, 8, 16, 32, 48, 64, 72, 80, 88, 96, 104, 112, 120, 128, 144, 160, 192, 256]
times = []
for n in nprocs:
    gs = lakeprof.simulate(g, max_nproc=n)
    times.append(max(d["stop"] for _, d in gs.nodes(data=True)))

ax.plot(nprocs, times, "o-", color="#2E86AB", linewidth=2, markersize=6, label="simulated")
ax.axhline(y=full_cp, color="#E63946", linestyle="--", linewidth=1.5,
           label=f"critical-path floor = {full_cp:.0f}s")
ax.scatter([18], [1966], color="#06A77D", s=100, zorder=10,
           label="actual 18-core: 1966s")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlabel("cores")
ax.set_ylabel("wall-clock (s, log)")
ax.set_title("Simulated wall-clock vs core count")
ax.set_xticks([1, 2, 4, 8, 16, 32, 64, 128, 256])
ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
ax.legend(loc="upper right")
plt.savefig("figs/01-speedup-curve.svg")
plt.close()
print("1. speedup-curve")

# ---------------- 2. Parallelism profile over time ----------------
gs = lakeprof.simulate(g, max_nproc=None)
events = []
for _, d in gs.nodes(data=True):
    events.append((d["start"], +1))
    events.append((d["stop"], -1))
events.sort()

ts, ns_, running = [0.0], [0], 0
for t, delta in events:
    ts.append(t)
    ns_.append(running)
    running += delta
    ts.append(t)
    ns_.append(running)

fig, ax = plt.subplots(figsize=(10, 4))
ax.fill_between(ts, ns_, step="post", alpha=0.55, color="#2E86AB")
ax.axhline(32, color="#E63946", linestyle="--", linewidth=1.2, alpha=0.8,
           label="32 concurrent jobs")
ax.set_xlabel("time (s, simulated under ∞ cores)")
ax.set_ylabel("concurrent build tasks")
ax.set_title("Parallelism profile: how wide is mathlib's build at each moment?")
ax.set_xlim(0, full_cp)
ax.set_ylim(0, 250)
ax.legend(loc="upper right")
plt.savefig("figs/02-parallelism-profile.svg")
plt.close()
print("2. parallelism-profile")

# ---------------- 3. Per-namespace work bar chart ----------------
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

ns_work = defaultdict(float)
for u, d in g.nodes(data=True):
    ns_work[ns2(d["drv_name"])] += d["time"]

top = sorted(ns_work.items(), key=lambda p: -p[1])[:15]
labels = [n.replace("Mathlib.", "") for n, _ in top]
vals = [v for _, v in top]

fig, ax = plt.subplots(figsize=(8, 5.5))
bars = ax.barh(range(len(labels)), vals, color="#2E86AB")
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels)
ax.invert_yaxis()
ax.set_xlabel("total compilation work (CPU-seconds)")
ax.set_title(f"Where mathlib's {total_work:.0f}s of work lives (top 15 namespaces)")
for i, v in enumerate(vals):
    ax.text(v + 50, i, f"{v:.0f}s", va="center", fontsize=9)
plt.savefig("figs/03-per-namespace-work.svg")
plt.close()
print("3. per-namespace-work")

# ---------------- 4. Bottleneck what-if ----------------
crit_path = list(reversed(networkx.dag_longest_path(g, weight="time")))
cp_sorted = sorted(crit_path, key=lambda u: -g.nodes[u]["time"])

K_vals = list(range(0, 51))
floors = []
for K in K_vals:
    g2 = g.copy()
    for u in cp_sorted[:K]:
        g2.nodes[u]["time"] = 0
    for u, v, data in g2.edges(data=True):
        data["time"] = g2.nodes[u]["time"]
    floors.append(networkx.dag_longest_path_length(g2, weight="time"))

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(K_vals, floors, "o-", color="#E63946", linewidth=2, markersize=4)
ax.axhline(full_cp, color="#999", linestyle=":", linewidth=1)
ax.annotate("plateau: alternative chain takes over",
            xy=(10, 665), xytext=(20, 700),
            arrowprops=dict(arrowstyle="->", color="#444"), fontsize=9)
ax.set_xlabel("K (top-K critical-path modules zeroed)")
ax.set_ylabel("new critical-path floor (s)")
ax.set_title("Diminishing returns from splitting top-CP modules")
plt.savefig("figs/04-bottleneck-whatif.svg")
plt.close()
print("4. bottleneck-whatif")

# ---------------- 5. Per-commit blast radius CDF ----------------
log = subprocess.check_output(
    ["git", "log", "-n2000", "--pretty=format:%H|%s", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

commits = []
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]: continue
    files = [path_to_module(l) for l in lines[1:] if l]
    files = [m for m in files if m and m in g]
    if files:
        commits.append(files)

# Compute blast CP per commit
blast_cps = []
for mods in commits:
    aff = set(mods)
    for m in mods:
        aff |= networkx.ancestors(g, m)
    sub = g.subgraph(aff).copy()
    for u, v, data in sub.edges(data=True):
        data["time"] = sub.nodes[u]["time"]
    blast_cps.append(networkx.dag_longest_path_length(sub, weight="time") if sub.nodes else 0)

import numpy as np
blast_pct = np.array([100*b/full_cp for b in blast_cps])
sorted_pct = np.sort(blast_pct)
cdf = np.arange(1, len(sorted_pct)+1) / len(sorted_pct) * 100

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(sorted_pct, cdf, color="#2E86AB", linewidth=2)
ax.fill_between(sorted_pct, 0, cdf, color="#2E86AB", alpha=0.15)
for q in [25, 50, 75, 90]:
    val = np.percentile(blast_pct, q)
    ax.axvline(val, color="#999", linestyle=":", linewidth=0.8)
    ax.text(val+1, q-3, f"p{q}: {val:.0f}%", fontsize=9)
ax.set_xlabel("rebuild critical path as % of full CP")
ax.set_ylabel("cumulative % of commits")
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.set_title(f"Per-commit blast radius CDF\n({len(blast_cps)} commits, content-hash invalidation)")
plt.savefig("figs/05-blast-cdf.svg")
plt.close()
print("5. blast-cdf")

# ---------------- 6. Leverage Pareto curve ----------------
edit_count = Counter()
for mods in commits:
    for m in mods:
        edit_count[m] += 1

print("  computing per-module blast CP for leverage chart...", file=sys.stderr)
total_cost_mod = {}
for i, m in enumerate(edit_count):
    if i % 500 == 0: print(f"    {i}/{len(edit_count)}", file=sys.stderr)
    aff = networkx.ancestors(g, m) | {m}
    sub = g.subgraph(aff).copy()
    for u, v, data in sub.edges(data=True):
        data["time"] = sub.nodes[u]["time"]
    cp = networkx.dag_longest_path_length(sub, weight="time")
    total_cost_mod[m] = edit_count[m] * cp

sorted_costs = sorted(total_cost_mod.values(), reverse=True)
cum = np.cumsum(sorted_costs)
pct_total = 100 * cum / cum[-1]
pct_mods = 100 * np.arange(1, len(sorted_costs)+1) / len(sorted_costs)

fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(pct_mods, pct_total, color="#2E86AB", linewidth=2)
ax.plot([0, 100], [0, 100], "--", color="#999", linewidth=0.8, label="if uniform")
for thr_pct in [50, 80, 95]:
    idx = np.searchsorted(pct_total, thr_pct)
    pct_m = pct_mods[idx]
    ax.scatter([pct_m], [thr_pct], color="#E63946", s=50, zorder=10)
    ax.annotate(f"{thr_pct}% cost ←\n{pct_m:.0f}% of mods",
                xy=(pct_m, thr_pct), xytext=(pct_m+8, thr_pct-12),
                fontsize=9)
ax.set_xlabel("% of edited modules (sorted by leverage)")
ax.set_ylabel("cumulative % of total observed rebuild cost")
ax.set_title("Leverage Pareto: where does observed rebuild cost concentrate?")
ax.set_xlim(0, 100); ax.set_ylim(0, 100)
ax.legend()
plt.savefig("figs/06-pareto.svg")
plt.close()
print("6. pareto")

# ---------------- 7. Import-edge composition ----------------
counts = {"public": 0, "private": 0, "meta": 0}
for _, _, d in g.edges(data=True):
    if d.get("isMeta"): counts["meta"] += 1
    elif d.get("isExported", True): counts["public"] += 1
    else: counts["private"] += 1

fig, ax = plt.subplots(figsize=(7, 2.5))
total = sum(counts.values())
left = 0
colors = {"public": "#E63946", "private": "#06A77D", "meta": "#F4A261"}
for k in ["public", "private", "meta"]:
    v = counts[k]
    ax.barh(0, v, left=left, color=colors[k],
            label=f"{k}: {v} ({100*v/total:.1f}%)")
    if v / total > 0.05:
        ax.text(left + v/2, 0, f"{k}\n{100*v/total:.1f}%",
                ha="center", va="center", color="white", fontweight="bold")
    left += v
ax.set_xlim(0, total)
ax.set_yticks([])
ax.set_xlabel("import edges")
ax.set_title(f"Import declaration kinds across mathlib ({total:,} edges)")
ax.legend(loc="upper right", fontsize=9)
ax.grid(False)
plt.savefig("figs/07-import-kinds.svg")
plt.close()
print("7. import-kinds")

# ---------------- 8. Namespace SCC visualization ----------------
ns_g = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
    if nu != nv:
        ns_g.add_edge(nu, nv)

sccs = list(networkx.strongly_connected_components(ns_g))
sccs.sort(key=lambda s: -len(s))

fig, ax = plt.subplots(figsize=(8, 5))
sizes = [len(s) for s in sccs]
labels = [f"SCC #1\n({len(sccs[0])} ns)" if i == 0
          else (sorted(sccs[i])[0].replace("Mathlib.", "") if len(sccs[i])==1 else f"SCC ({len(sccs[i])} ns)")
          for i in range(len(sccs))]
colors = ["#E63946"] + ["#2E86AB"] * (len(sccs)-1)
y_pos = range(len(sccs))
ax.barh(y_pos, sizes, color=colors)
ax.set_yticks(y_pos)
ax.set_yticklabels(labels, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("# namespaces in SCC")
ax.set_title("Strongly-connected components of mathlib's namespace graph")
ax.set_xscale("symlog", linthresh=2)
plt.savefig("figs/08-sccs.svg")
plt.close()
print("8. sccs")

# ---------------- 9. Critical path heights (CP module timeline) ----------------
crit_path = list(reversed(networkx.dag_longest_path(g, weight="time")))
xs = [g.nodes[u]['time'] for u in crit_path]
cum = np.cumsum(xs)

fig, ax = plt.subplots(figsize=(11, 4))
ax.bar(range(len(crit_path)), xs, color="#2E86AB", width=1.0, edgecolor="white", linewidth=0.3)
# Highlight Analysis-region
analysis_indices = [i for i, u in enumerate(crit_path) if "Analysis" in g.nodes[u]['drv_name']
                    or "Calculus" in g.nodes[u]['drv_name'] or "Manifold" in g.nodes[u]['drv_name']
                    or "Distribution" in g.nodes[u]['drv_name']]
if analysis_indices:
    ax.axvspan(analysis_indices[0]-0.5, analysis_indices[-1]+0.5, alpha=0.15,
               color="#E63946", label=f"Analysis region ({100*sum(xs[i] for i in analysis_indices)/sum(xs):.0f}% of CP)")
ax.set_xlabel("position on critical path (early → late)")
ax.set_ylabel("module compile time (s)")
ax.set_title(f"The {len(crit_path)}-module critical path: heaviest stretch is the Analysis region")
ax.legend(loc="upper left")
plt.savefig("figs/09-cp-heights.svg")
plt.close()
print("9. cp-heights")

# ---------------- 10. Maximal-private CP what-if comparison ----------------
def rebuild_cp(g_):
    dist = {c: {v: g_.nodes[v]["time"] for v in g_} for c in ["public", "private", "meta"]}
    for v in reversed(list(networkx.topological_sort(g_))):
        for (u, _, data) in g_.in_edges(v, data=True):
            if data.get("isExported"):
                pub_cat = "public" if not data.get("isMeta") else "meta"
                pub_dist = dist[pub_cat][v] + g_.nodes[u]["time"]
                if pub_dist > dist["public"][u]:
                    dist["public"][u] = pub_dist
            priv_cat = "meta" if data.get("isMeta") else "private" if data.get("importAll") else "public"
            priv_dist = dist[priv_cat][v] + g_.nodes[u]["time"]
            if priv_dist > dist["private"][u]:
                dist["private"][u] = priv_dist
            if dist["meta"][v] > dist["meta"][u]:
                dist["meta"][u] = dist["meta"][v]
    return max(dist["private"].values())

current = rebuild_cp(g)
g_priv = g.copy()
for _, _, d in g_priv.edges(data=True):
    d["isExported"] = False
maximal = rebuild_cp(g_priv)

fig, ax = plt.subplots(figsize=(8, 4))
labels_ = ["standard CP\n(what we measure)", "rebuild-aware CP\n(current `private` discipline)",
           "maximal-private CP\n(theoretical lower bound)"]
vals = [full_cp, current, maximal]
colors_ = ["#E63946", "#F4A261", "#06A77D"]
bars = ax.bar(labels_, vals, color=colors_, width=0.6)
for bar, v in zip(bars, vals):
    ax.text(bar.get_x()+bar.get_width()/2, v+10, f"{v:.0f}s",
            ha="center", fontsize=11, fontweight="bold")
ax.set_ylabel("seconds")
ax.set_title("Critical-path floor under different cache semantics")
ax.set_ylim(0, max(vals)*1.15)
plt.savefig("figs/10-private-headroom.svg")
plt.close()
print("10. private-headroom")

print("\nall figures saved to figs/")
