"""
Try multiple boundary partitions of mathlib4 and measure their effect on
(a) clean-build wall-clock under strict package pipelining
(b) wall-clock with upstream packages pre-cached
(c) per-commit cross-package blast distribution
"""
import subprocess
import sys
from collections import defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import statistics

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

total_work = sum(d["time"] for _, d in g.nodes(data=True))
full_cp = networkx.dag_longest_path_length(g, weight="time")

# ----- partition definitions -----
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

FOUNDATIONS = {"Mathlib.Init", "Mathlib.Logic", "Mathlib.Util", "Mathlib.Lean",
               "Mathlib.Tactic", "Mathlib.Order", "Mathlib.Data", "Mathlib.SetTheory",
               "Mathlib.Control", "Mathlib.Combinatorics"}
ALGEBRA = {"Mathlib.Algebra", "Mathlib.RingTheory", "Mathlib.LinearAlgebra",
           "Mathlib.GroupTheory", "Mathlib.FieldTheory", "Mathlib.CategoryTheory"}
ANALYSIS = {"Mathlib.Analysis", "Mathlib.Topology", "Mathlib.MeasureTheory"}
# everything else = leaves (NumberTheory, AlgebraicGeometry, Geometry, Probability,
# AlgebraicTopology, RepresentationTheory, Dynamics, Condensed, Computability,
# ModelTheory, InformationTheory)

def partition_p2(name):
    n = ns2(name)
    return "FOUNDATION" if n in FOUNDATIONS else "EVERYTHING-ELSE"

def partition_p3(name):
    n = ns2(name)
    if n in FOUNDATIONS or n in ALGEBRA: return "CORE"
    if n in ANALYSIS: return "ANALYSIS"
    return "LEAVES"

def partition_p4(name):
    n = ns2(name)
    if n in FOUNDATIONS: return "foundations"
    if n in ALGEBRA: return "algebra"
    if n in ANALYSIS: return "analysis"
    return "leaves"

def partition_ns(name):
    return ns2(name)

PARTITIONS = [
    ("monolithic", lambda n: "ALL"),
    ("P2 (foundation / rest)", partition_p2),
    ("P3 (core / analysis / leaves)", partition_p3),
    ("P4 (foundations / algebra / analysis / leaves)", partition_p4),
    ("P_namespace (~30 top-level namespaces)", partition_ns),
]

def analyze_partition(label, fn):
    pkg_of = {u: fn(g.nodes[u]['drv_name']) for u in g.nodes}
    pkgs = set(pkg_of.values())

    # Per-package stats
    pkg_modules = defaultdict(list)
    for u, p in pkg_of.items():
        pkg_modules[p].append(u)

    pkg_work = {p: sum(g.nodes[u]['time'] for u in mods)
                for p, mods in pkg_modules.items()}

    # Per-package internal CP (induced subgraph)
    pkg_cp = {}
    for p, mods in pkg_modules.items():
        sub = g.subgraph(mods).copy()
        for uu, vv, data in sub.edges(data=True):
            data['time'] = sub.nodes[uu]['time']
        pkg_cp[p] = networkx.dag_longest_path_length(sub, weight='time') if sub.nodes else 0

    # Package-level dependency DAG
    pkg_g = networkx.DiGraph()
    for p in pkgs:
        pkg_g.add_node(p)
    cross_edges_count = defaultdict(int)
    for u, v in g.edges():
        pu, pv = pkg_of[u], pkg_of[v]
        if pu != pv:
            cross_edges_count[(pu, pv)] += 1
            pkg_g.add_edge(pu, pv)

    # Strict-pipeline wall-clock: longest path through pkg_g where each pkg
    # contributes its internal CP, and packages must finish before downstream starts.
    # Treat each package as a node with weight = internal CP.
    if not networkx.is_directed_acyclic_graph(pkg_g):
        # cycles indicate bad partition (e.g. mutual deps); skip
        print(f"  WARNING: package graph has cycles for {label}")
        return

    # Use dag_longest_path with node weights = internal CP
    # Trick: weight each edge by the source node's internal CP, then add target's CP.
    pkg_g_w = pkg_g.copy()
    for pu, pv in pkg_g_w.edges():
        pkg_g_w[pu][pv]['w'] = pkg_cp[pu]
    if pkg_g_w.edges:
        long_path = networkx.dag_longest_path(pkg_g_w, weight='w')
        pipeline_wc = sum(pkg_cp[p] for p in long_path)
    else:
        pipeline_wc = max(pkg_cp.values())
        long_path = [max(pkg_cp, key=pkg_cp.get)]

    # Pre-cached upstream: assume all but one package is pre-cached.
    # The cost is just the bottleneck package's internal CP.
    bottleneck_cp = max(pkg_cp.values())
    bottleneck_pkg = max(pkg_cp, key=pkg_cp.get)

    # Total cross-package edges
    n_cross = sum(cross_edges_count.values())

    print(f"\n  ===== {label} =====")
    print(f"  packages:                 {len(pkgs)}")
    print(f"  cross-package edges:      {n_cross} ({100*n_cross/g.number_of_edges():.1f}% of {g.number_of_edges()})")

    if len(pkgs) <= 8:
        print(f"  per-package breakdown:")
        print(f"    {'package':<24} {'mods':>5} {'work':>7} {'CP':>6}")
        for p in sorted(pkgs, key=lambda p: -pkg_cp[p]):
            print(f"    {p:<24} {len(pkg_modules[p]):>5} {pkg_work[p]:>5.0f}s {pkg_cp[p]:>4.0f}s")
    else:
        # show top 8 by CP
        top = sorted(pkgs, key=lambda p: -pkg_cp[p])[:8]
        print(f"  top 8 packages by internal CP:")
        for p in top:
            print(f"    {p:<32} {len(pkg_modules[p]):>5} mods, {pkg_work[p]:>5.0f}s work, {pkg_cp[p]:>4.0f}s CP")

    print(f"  scenarios:")
    print(f"    monolithic baseline:                    {full_cp:>6.0f}s  (CP)")
    print(f"    strict-pipeline (each pkg = barrier):   {pipeline_wc:>6.0f}s  ({100*pipeline_wc/full_cp:+.0f}% vs mono)")
    print(f"      pkg chain on critical path: {' → '.join(long_path)}")
    print(f"    bottleneck pkg only (rest cached):      {bottleneck_cp:>6.0f}s  ({100*bottleneck_cp/full_cp:+.0f}% vs mono)")
    print(f"      bottleneck = {bottleneck_pkg}")

    return {"pkg_of": pkg_of, "pkg_g": pkg_g, "pkgs": pkgs, "pkg_cp": pkg_cp,
            "pkg_modules": pkg_modules, "label": label}

# ----- run all partitions -----
results = {}
for label, fn in PARTITIONS:
    r = analyze_partition(label, fn)
    if r:
        results[label] = r

# ----- incremental: cross-package blast for each partition -----
# Get last 1500 commits with mathlib edits
log = subprocess.check_output(
    ["git", "log", "-n1500", "--pretty=format:%H|%s", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

commits = []
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]:
        continue
    files = [path_to_module(l) for l in lines[1:] if l]
    files = [m for m in files if m and m in g]
    if files:
        commits.append(files)

print(f"\n\n========== INCREMENTAL CROSS-PACKAGE BLAST ==========")
print(f"({len(commits)} commits sampled)")
print(f"\n{'partition':<48} {'p25':>5} {'p50':>5} {'p75':>5} {'p90':>5}  pkgs invalidated")

for label, r in results.items():
    if label == "monolithic":
        continue
    pkg_of = r["pkg_of"]
    pkg_g = r["pkg_g"]
    n_pkgs = len(r["pkgs"])
    deps = {p: networkx.ancestors(pkg_g, p) for p in pkg_g.nodes}

    blasts = []
    for mods in commits:
        edited_pkgs = {pkg_of[m] for m in mods}
        invalidated = set(edited_pkgs)
        for p in edited_pkgs:
            invalidated |= deps.get(p, set())
        blasts.append(len(invalidated))

    blasts.sort()
    print(f"{label:<48} {blasts[len(blasts)//4]:>5} "
          f"{statistics.median(blasts):>5.0f} "
          f"{blasts[3*len(blasts)//4]:>5} "
          f"{blasts[9*len(blasts)//10]:>5}    of {n_pkgs}")

# Show the same in MODULES (assuming pessimistic content-hash federation)
print(f"\n--- module-level rebuild count under federated content-hash cache: ---")
print(f"(every package edit invalidates all of its + downstream modules)")
print(f"\n{'partition':<48} {'p25':>6} {'p50':>6} {'p75':>6} {'p90':>6}  of total modules")
total_mods = len(g.nodes)

for label, r in results.items():
    if label == "monolithic":
        continue
    pkg_of = r["pkg_of"]
    pkg_g = r["pkg_g"]
    pkg_mods = r["pkg_modules"]
    deps = {p: networkx.ancestors(pkg_g, p) for p in pkg_g.nodes}

    blasts = []
    for mods in commits:
        invalidated_pkgs = set()
        for m in mods:
            invalidated_pkgs.add(pkg_of[m])
            invalidated_pkgs |= deps.get(pkg_of[m], set())
        cnt = sum(len(pkg_mods[p]) for p in invalidated_pkgs)
        blasts.append(cnt)

    blasts.sort()
    print(f"{label:<48} {blasts[len(blasts)//4]:>6} "
          f"{statistics.median(blasts):>6.0f} "
          f"{blasts[3*len(blasts)//4]:>6} "
          f"{blasts[9*len(blasts)//10]:>6}   of {total_mods}")

# Compare to file-level (no federation): from churn_analysis we already know
# p25=14, p50=507, p75=2604, p90=6460 modules
print(f"\nFile-level cache (today, no federation):       14    507   2604   6460")
print(f"\n→ Naive federation makes blast WORSE: granularity coarser, no API smarts.")
