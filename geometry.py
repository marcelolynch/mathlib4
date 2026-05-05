"""
Compute Gromov hyperbolicity δ and Ollivier-Ricci-proxy curvature κ
on mathlib's file-level dependency graph. Compare to the paper's
declaration-level numbers (δ≤1.5, κ≈+0.022).

Also run Louvain community detection and compare resulting clusters
to the existing namespace partition.
"""
import sys
import random
from collections import Counter, defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import numpy as np
import statistics

random.seed(42)
np.random.seed(42)

with open("mathlib-clean.log") as f:
    g_di = lakeprof.parse(f)

# Geometry analyses use the UNDIRECTED simple graph (paper convention)
g = g_di.to_undirected()
# Drop self-loops if any
g.remove_edges_from(networkx.selfloop_edges(g))
print(f"undirected file-level graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")

degrees = dict(g.degree())
mean_deg = sum(degrees.values()) / len(degrees)
print(f"mean degree: {mean_deg:.1f}")

# Top-1% prune (paper convention)
top_1pct_count = max(1, len(degrees) // 100)
high_deg_nodes = sorted(degrees, key=lambda n: -degrees[n])[:top_1pct_count]
print(f"\npruning top {top_1pct_count} highest-degree nodes (paper convention)")
for n in high_deg_nodes[:5]:
    print(f"  prune: {n} (degree {degrees[n]})")

g_pruned = g.copy()
g_pruned.remove_nodes_from(high_deg_nodes)
# Keep largest connected component after pruning
components = list(networkx.connected_components(g_pruned))
components.sort(key=len, reverse=True)
g_pruned = g_pruned.subgraph(components[0]).copy()
print(f"after prune + LCC: {g_pruned.number_of_nodes()} nodes, {g_pruned.number_of_edges()} edges")

# ---------- Gromov hyperbolicity δ via random quadruples ----------
print("\n=== Gromov δ (sampled) ===")

def sample_delta(graph, n_quads=2000, dist_cache_size=50):
    """Sample random quadruples; for each compute δ = (S_max - S_mid)/2."""
    nodes = list(graph.nodes)
    deltas = []
    # Cache shortest paths from sampled sources
    cached = {}
    def dist(u, v):
        if u not in cached:
            cached[u] = dict(networkx.single_source_shortest_path_length(graph, u))
        return cached[u].get(v, float("inf"))

    attempts = 0
    while len(deltas) < n_quads and attempts < n_quads * 5:
        attempts += 1
        x, y, z, w = random.sample(nodes, 4)
        d_xy, d_zw = dist(x, y), dist(z, w)
        d_xz, d_yw = dist(x, z), dist(y, w)
        d_xw, d_yz = dist(x, w), dist(y, z)
        if any(d == float("inf") for d in [d_xy, d_zw, d_xz, d_yw, d_xw, d_yz]):
            continue
        sums = sorted([d_xy + d_zw, d_xz + d_yw, d_xw + d_yz])
        delta = (sums[2] - sums[1]) / 2
        deltas.append(delta)
    return deltas

# Run on full and pruned graphs
print(f"sampling on full undirected graph...")
deltas_full = sample_delta(g, n_quads=1500)
print(f"  n_quads sampled: {len(deltas_full)}")
print(f"  max δ:    {max(deltas_full):.2f}")
print(f"  mean δ:   {statistics.mean(deltas_full):.3f}")
print(f"  median δ: {statistics.median(deltas_full):.3f}")
print(f"  p99 δ:    {sorted(deltas_full)[int(0.99*len(deltas_full))]:.2f}")

print(f"\nsampling on pruned graph...")
deltas_pruned = sample_delta(g_pruned, n_quads=1500)
print(f"  max δ:    {max(deltas_pruned):.2f}")
print(f"  mean δ:   {statistics.mean(deltas_pruned):.3f}")
print(f"  median δ: {statistics.median(deltas_pruned):.3f}")

print(f"\npaper's declaration-level (619k nodes, 12.5M edges): max δ = 1.50 full, 1.00 pruned")
print(f"file-level (8.2k nodes, 33.7k edges):                max δ = {max(deltas_full):.2f} full, {max(deltas_pruned):.2f} pruned")

# ---------- Jaccard-overlap curvature κ proxy ----------
print("\n=== Local curvature κ (Jaccard-overlap proxy on sampled edges) ===")

def jaccard_kappa(graph, n_edges=5000):
    """For each sampled edge (u,v), κ̂ = |N(u)∩N(v)|/|N(u)∪N(v)| - 1/(|N(u)|+|N(v)|)"""
    edges = list(graph.edges())
    sample = random.sample(edges, min(n_edges, len(edges)))
    kappas = []
    for u, v in sample:
        Nu = set(graph.neighbors(u))
        Nv = set(graph.neighbors(v))
        inter = len(Nu & Nv)
        union = len(Nu | Nv)
        if union == 0:
            continue
        kappa = inter / union - 1 / (len(Nu) + len(Nv))
        kappas.append(kappa)
    return kappas

kappas_full = jaccard_kappa(g, n_edges=5000)
kappas_pruned = jaccard_kappa(g_pruned, n_edges=5000)

print(f"full graph:    mean κ = {statistics.mean(kappas_full):+.4f}  median = {statistics.median(kappas_full):+.4f}  n = {len(kappas_full)}")
print(f"pruned graph:  mean κ = {statistics.mean(kappas_pruned):+.4f}  median = {statistics.median(kappas_pruned):+.4f}  n = {len(kappas_pruned)}")
print(f"\npaper's decl-level: mean κ = +0.022 (positive)")
print(f"file-level:         mean κ = {statistics.mean(kappas_pruned):+.4f}")

# Save for later
import json
with open("geometry_baseline.json", "w") as f:
    json.dump({
        "delta_full_max": max(deltas_full),
        "delta_pruned_max": max(deltas_pruned),
        "delta_full_mean": statistics.mean(deltas_full),
        "kappa_full_mean": statistics.mean(kappas_full),
        "kappa_pruned_mean": statistics.mean(kappas_pruned),
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
    }, f)

# ---------- Null model: configuration model with same degree sequence ----------
print("\n=== Null model: configuration model (same degrees, edges rewired) ===")
deg_seq = [d for _, d in g.degree()]
g_cfg = networkx.configuration_model(deg_seq, seed=42)
g_cfg = networkx.Graph(g_cfg)  # collapse multi-edges
g_cfg.remove_edges_from(networkx.selfloop_edges(g_cfg))
# Prune top 1% and take LCC
deg_cfg = dict(g_cfg.degree())
high_cfg = sorted(deg_cfg, key=lambda n: -deg_cfg[n])[:top_1pct_count]
g_cfg.remove_nodes_from(high_cfg)
comps_cfg = list(networkx.connected_components(g_cfg))
comps_cfg.sort(key=len, reverse=True)
g_cfg = g_cfg.subgraph(comps_cfg[0]).copy()
print(f"config model after prune + LCC: {g_cfg.number_of_nodes()} nodes, {g_cfg.number_of_edges()} edges")

deltas_cfg = sample_delta(g_cfg, n_quads=1500)
kappas_cfg = jaccard_kappa(g_cfg, n_edges=5000)
print(f"config model:  max δ = {max(deltas_cfg):.2f},  mean κ = {statistics.mean(kappas_cfg):+.4f}")

print("\n--- Summary table ---")
print(f"{'graph':<28} {'nodes':>7} {'max δ':>8} {'mean κ':>10}")
print(f"{'mathlib (file-level), full':<28} {g.number_of_nodes():>7} {max(deltas_full):>8.2f} {statistics.mean(kappas_full):>+10.4f}")
print(f"{'mathlib (file-level), pruned':<28} {g_pruned.number_of_nodes():>7} {max(deltas_pruned):>8.2f} {statistics.mean(kappas_pruned):>+10.4f}")
print(f"{'configuration-model null':<28} {g_cfg.number_of_nodes():>7} {max(deltas_cfg):>8.2f} {statistics.mean(kappas_cfg):>+10.4f}")
print(f"{'paper (decl-level)':<28} {613348:>7} {1.50:>8.2f} {0.0220:>+10.4f}")

# ---------- Per-namespace localization ----------
print("\n=== Per-namespace mean κ (where is local density highest?) ===")

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

ns_kappas = defaultdict(list)
for u, v in random.sample(list(g.edges()), 8000):
    if u not in g_pruned or v not in g_pruned:
        continue
    Nu = set(g_pruned.neighbors(u))
    Nv = set(g_pruned.neighbors(v))
    inter = len(Nu & Nv)
    union = len(Nu | Nv)
    if union == 0: continue
    kappa = inter/union - 1/(len(Nu)+len(Nv))
    nu, nv = ns2(g_di.nodes[u].get("drv_name", u)), ns2(g_di.nodes[v].get("drv_name", v))
    if nu == nv:
        ns_kappas[nu].append(kappa)

print(f"  {'namespace':<32} {'n_edges':>7} {'mean κ':>10}")
for ns_, kvs in sorted(ns_kappas.items(), key=lambda p: -statistics.mean(p[1]) if len(p[1])>20 else 99):
    if len(kvs) < 20: continue
    print(f"  {ns_:<32} {len(kvs):>7} {statistics.mean(kvs):>+10.4f}")
