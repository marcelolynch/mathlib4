"""Generate figures for the Louvain report. Saves SVGs to figs/louvain-*.svg."""
import json
import os
import sys
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.colors as mcolors

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

with open("louvain_data.json") as f:
    D = json.load(f)
with open("louvain_partition.json") as f:
    P = json.load(f)

with open("mathlib-clean.log") as f:
    g_di = lakeprof.parse(f)
g = g_di.to_undirected()
g.remove_edges_from(networkx.selfloop_edges(g))

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Recover communities and node_to_comm
communities = [set(c) for c in P["communities"]]
node_to_comm = P["node_to_comm"]

# ----- 1. Modularity comparison -----
fig, ax = plt.subplots(figsize=(7, 4))
labels = ["Namespaces\n(34 clusters)", "Louvain\n(15 clusters)"]
vals = [D["namespace_modularity"], D["louvain_modularity"]]
colors = ["#999", "#2E86AB"]
bars = ax.bar(labels, vals, color=colors, width=0.55)
for bar, v in zip(bars, vals):
    ax.text(bar.get_x()+bar.get_width()/2, v+0.01, f"Q = {v:.4f}",
            ha="center", fontsize=11, fontweight="bold")
ax.set_ylabel("modularity Q")
ax.set_title("Louvain finds a 22% more cohesive partition than namespaces")
ax.set_ylim(0, max(vals)*1.2)
plt.savefig("figs/louvain-01-modularity.svg")
plt.close()
print("01 modularity")

# ----- 2. Resolution sweep -----
fig, ax = plt.subplots(figsize=(8, 4.5))
sweep = D["resolution_sweep"]
gammas = sorted(float(g) for g in sweep.keys())
qs = [sweep[str(g)]["q"] for g in gammas]
ns = [sweep[str(g)]["n"] for g in gammas]

ax2 = ax.twinx()
ax.plot(gammas, qs, "o-", color="#2E86AB", linewidth=2, markersize=8, label="modularity Q")
ax2.plot(gammas, ns, "s--", color="#E63946", linewidth=2, markersize=6, alpha=0.75, label="# communities")
ax.set_xlabel("resolution parameter γ")
ax.set_ylabel("modularity Q", color="#2E86AB")
ax2.set_ylabel("# communities", color="#E63946")
ax.tick_params(axis="y", labelcolor="#2E86AB")
ax2.tick_params(axis="y", labelcolor="#E63946")
ax.set_title("Modularity vs resolution — peak at γ≈1.25")
ax.axvline(1.0, linestyle=":", color="#999", linewidth=0.8)
ax.text(1.0, max(qs)*0.55, " default γ=1.0", fontsize=9, color="#666")
ax2.grid(False)
plt.savefig("figs/louvain-02-resolution.svg")
plt.close()
print("02 resolution")

# ----- 3. Community sizes -----
fig, ax = plt.subplots(figsize=(8, 4.5))
sizes = sorted(D["comm_sizes"], reverse=True)
labels = [c["label"].replace("Mathlib.", "") for c in D["comm_cps"]]
labels_sorted = sorted(D["comm_cps"], key=lambda c: -c["size"])
bars = ax.bar(range(len(sizes)), sizes, color="#2E86AB")
ax.set_xticks(range(len(sizes)))
ax.set_xticklabels([c["label"] for c in labels_sorted], rotation=70, ha="right", fontsize=8)
ax.set_ylabel("# modules")
ax.set_title(f"Louvain community sizes (15 communities, {sum(sizes):,} modules total)")
plt.savefig("figs/louvain-03-sizes.svg")
plt.close()
print("03 sizes")

# ----- 4. Per-community CP and work -----
fig, ax = plt.subplots(figsize=(9, 5))
sorted_cps = sorted(D["comm_cps"], key=lambda c: -c["cp"])
labels = [c["label"] for c in sorted_cps]
cps = [c["cp"] for c in sorted_cps]
works = [c["work"] for c in sorted_cps]

x = np.arange(len(labels))
ax.bar(x - 0.18, works, 0.36, color="#999", label="total work (s)", alpha=0.7)
ax.bar(x + 0.18, cps, 0.36, color="#E63946", label="internal CP (s)")
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=70, ha="right", fontsize=8)
ax.set_ylabel("seconds")
ax.set_title("Per-Louvain-community: total work vs internal critical path")
ax.legend()
plt.savefig("figs/louvain-04-cps.svg")
plt.close()
print("04 cps")

# ----- 5. Cluster-namespace heatmap -----
ns_sizes = Counter()
for u in g.nodes:
    ns_sizes[ns2(g_di.nodes[u].get("drv_name", u))] += 1

top_namespaces = [n for n, _ in ns_sizes.most_common(18)]
n_comms = len(communities)

heat = np.zeros((n_comms, len(top_namespaces)))
for i, c in enumerate(communities):
    for u in c:
        n = ns2(g_di.nodes[u].get("drv_name", u))
        if n in top_namespaces:
            j = top_namespaces.index(n)
            heat[i, j] += 1

# Normalize per row (fraction of community in each namespace)
heat_norm = heat / heat.sum(axis=1, keepdims=True).clip(min=1)

fig, ax = plt.subplots(figsize=(11, 6))
comm_labels = [c["label"] for c in D["comm_cps"]]
im = ax.imshow(heat_norm, cmap="Blues", aspect="auto")
ax.set_xticks(range(len(top_namespaces)))
ax.set_xticklabels([n.replace("Mathlib.", "") for n in top_namespaces], rotation=45, ha="right", fontsize=9)
ax.set_yticks(range(n_comms))
ax.set_yticklabels(comm_labels, fontsize=8)
# Annotate cells with raw counts
for i in range(n_comms):
    for j in range(len(top_namespaces)):
        val = heat[i, j]
        if val > 0:
            color = "white" if heat_norm[i, j] > 0.4 else "#444"
            ax.text(j, i, f"{int(val)}", ha="center", va="center",
                    fontsize=7, color=color)
ax.set_title("Louvain communities × namespaces (rows: communities; cells: # modules)")
ax.grid(False)
plt.colorbar(im, ax=ax, label="row fraction")
plt.savefig("figs/louvain-05-heatmap.svg")
plt.close()
print("05 heatmap")

# ----- 6. Namespace scatter (how scattered is each namespace?) -----
ns_to_comms = defaultdict(set)
ns_biggest_share = {}
for u in g.nodes:
    n = ns2(g_di.nodes[u].get("drv_name", u))
    if u in node_to_comm:
        ns_to_comms[n].add(node_to_comm[u])

for n in ns_to_comms:
    comm_sizes_for_ns = Counter()
    for u in g.nodes:
        if ns2(g_di.nodes[u].get("drv_name", u)) == n and u in node_to_comm:
            comm_sizes_for_ns[node_to_comm[u]] += 1
    ns_biggest_share[n] = comm_sizes_for_ns.most_common(1)[0][1] / ns_sizes[n] if comm_sizes_for_ns else 0

# Plot top namespaces
top_ns = [n for n, _ in ns_sizes.most_common(20) if n in ns_biggest_share]
sizes_for_ns = [ns_sizes[n] for n in top_ns]
shares = [ns_biggest_share[n] * 100 for n in top_ns]
spreads = [len(ns_to_comms[n]) for n in top_ns]

fig, ax = plt.subplots(figsize=(9, 5.5))
colors = ["#06A77D" if s > 80 else "#F4A261" if s > 60 else "#E63946" for s in shares]
bars = ax.barh([n.replace("Mathlib.", "") for n in top_ns], shares, color=colors)
for i, (sh, sp, sz) in enumerate(zip(shares, spreads, sizes_for_ns)):
    ax.text(sh + 1, i, f"{sh:.0f}% in 1 comm  (across {sp} comms, {sz} mods)",
            va="center", fontsize=8)
ax.invert_yaxis()
ax.set_xlim(0, 130)
ax.set_xlabel("% of namespace's modules in its single biggest Louvain community")
ax.set_title("Namespace coherence: which namespaces survive as single packages?")
ax.axvline(80, linestyle=":", color="#06A77D", linewidth=0.8)
ax.text(80, len(top_ns)-0.5, "  ← 80% threshold", fontsize=9, color="#06A77D")
plt.savefig("figs/louvain-06-coherence.svg")
plt.close()
print("06 coherence")

# ----- 7. Critical-path crossings comparison -----
fig, ax = plt.subplots(figsize=(7, 3.5))
total = D["cp_crossings"]["total"]
ns_x = D["cp_crossings"]["namespace"]
louv_x = D["cp_crossings"]["louvain"]

categs = ["Namespaces (34 pkgs)", "Louvain (15 pkgs)"]
crossings = [ns_x, louv_x]
intra = [total - c for c in crossings]

ax.barh(categs, intra, color="#06A77D", label="intra-package CP edges")
ax.barh(categs, crossings, left=intra, color="#E63946", label="cross-package CP edges")
for i, (c, x) in enumerate(zip(crossings, [ns_x, louv_x])):
    pct = 100 * x / total
    ax.text(total + 1, i, f"{x} cross-edges ({pct:.0f}%)", va="center", fontsize=10)
ax.set_xlim(0, total * 1.4)
ax.set_xlabel("# critical-path edges (out of 137 total)")
ax.set_title("Louvain partition has 60% fewer CP-crossing edges than namespaces")
ax.legend(loc="lower right")
plt.savefig("figs/louvain-07-cp-crossings.svg")
plt.close()
print("07 cp-crossings")

# ----- 8. Per-cluster purity (dominant namespace fraction) -----
fig, ax = plt.subplots(figsize=(9, 5))
purities = []
labels_p = []
for i, c in enumerate(communities):
    ns_count = Counter(ns2(g_di.nodes[u].get("drv_name", u)) for u in c)
    dom_ns, dom_count = ns_count.most_common(1)[0]
    purity = dom_count / len(c) * 100
    purities.append(purity)
    labels_p.append(D["comm_cps"][i]["label"])

# Sort by purity
order = np.argsort(purities)[::-1]
labels_sorted = [labels_p[i] for i in order]
purities_sorted = [purities[i] for i in order]

bars = ax.bar(labels_sorted, purities_sorted,
              color=["#06A77D" if p > 80 else "#F4A261" if p > 50 else "#E63946" for p in purities_sorted])
for i, (lbl, p) in enumerate(zip(labels_sorted, purities_sorted)):
    ax.text(i, p + 1, f"{p:.0f}%", ha="center", fontsize=9)
ax.set_xticks(range(len(labels_sorted)))
ax.set_xticklabels(labels_sorted, rotation=70, ha="right", fontsize=8)
ax.set_ylabel("% of community in its dominant namespace")
ax.set_title("Per-community purity (high = single-namespace cluster, low = mixed)")
ax.set_ylim(0, 110)
ax.axhline(80, linestyle=":", color="#06A77D", linewidth=0.8)
plt.savefig("figs/louvain-08-purity.svg")
plt.close()
print("08 purity")

print("\nall louvain plots saved to figs/louvain-*.svg")
