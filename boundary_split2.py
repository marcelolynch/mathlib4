"""
Diagnose namespace cycles, then re-run analysis on cycle-free partitions
by collapsing strongly connected components at the package level.
"""
import subprocess
import sys
from collections import defaultdict, Counter
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

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Build namespace-level digraph and find SCCs
ns_g = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
    if nu != nv:
        ns_g.add_edge(nu, nv)

print(f"namespace graph: {ns_g.number_of_nodes()} nodes, {ns_g.number_of_edges()} edges")

sccs = list(networkx.strongly_connected_components(ns_g))
sccs.sort(key=lambda s: -len(s))
nontriv = [s for s in sccs if len(s) > 1]
print(f"strongly-connected components: {len(sccs)} total, {len(nontriv)} non-trivial")
for i, s in enumerate(nontriv):
    print(f"  SCC #{i}: {len(s)} namespaces")
    for n in sorted(s):
        # count out-of-SCC outgoing edges (would-be-cross-package)
        within = sum(1 for _, v in ns_g.out_edges(n) if v in s)
        out = sum(1 for _, v in ns_g.out_edges(n) if v not in s)
        print(f"    {n} (out: {within} within, {out} outside SCC)")

# Specific cycle examples (for the biggest SCC)
if nontriv:
    biggest = nontriv[0]
    print(f"\nExample cycle edges within biggest SCC ({len(biggest)} namespaces):")
    sub = ns_g.subgraph(biggest)
    cycles = list(networkx.simple_cycles(sub))[:5]
    for c in cycles:
        print(f"  cycle: {' → '.join(c + [c[0]])}")

# Count specific cycle-creating edges per ns pair
print("\nMost frequent 'wrong-way' edges (importer in expected-downstream → importee in expected-upstream):")
# Heuristic: foundation = expected-upstream of everything else.
FOUNDATIONS = {"Mathlib.Init", "Mathlib.Logic", "Mathlib.Util", "Mathlib.Lean",
               "Mathlib.Tactic", "Mathlib.Order", "Mathlib.Data", "Mathlib.SetTheory",
               "Mathlib.Control", "Mathlib.Combinatorics"}
ALGEBRA = {"Mathlib.Algebra", "Mathlib.RingTheory", "Mathlib.LinearAlgebra",
           "Mathlib.GroupTheory", "Mathlib.FieldTheory", "Mathlib.CategoryTheory"}
ANALYSIS = {"Mathlib.Analysis", "Mathlib.Topology", "Mathlib.MeasureTheory"}

def layer(name):
    n = ns2(name)
    if n in FOUNDATIONS: return 0
    if n in ALGEBRA: return 1
    if n in ANALYSIS: return 2
    return 3

wrong_edges = Counter()
for u, v in g.edges():
    lu, lv = layer(g.nodes[u]['drv_name']), layer(g.nodes[v]['drv_name'])
    if lu < lv:  # importer is in upstream layer, importee in downstream layer = wrong way
        nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
        wrong_edges[(nu, nv)] += 1
print(f"  total wrong-direction edges: {sum(wrong_edges.values())}")
for (nu, nv), c in wrong_edges.most_common(15):
    print(f"    {c:>4}  {nu:<30} → {nv}")

# Now re-run the analysis but use the SCC condensation as the package partition
# (collapses cycles into single packages)
print("\n=========================================================================")
print("RE-RUN WITH CYCLE-FREE PARTITIONS (collapse SCCs into single packages)")
print("=========================================================================")

# Convert SCC sets to a partition function
ns_to_scc = {}
for i, s in enumerate(sccs):
    label = f"SCC{i}({sorted(s)[0].split('.')[-1]}-{len(s)}ns)" if len(s) > 1 else sorted(s)[0]
    for n in s:
        ns_to_scc[n] = label

def partition_scc(name):
    return ns_to_scc.get(ns2(name), ns2(name))

# Try "merge non-trivial SCCs into FOUNDATION-extended" simpler partition
# Logic: anything that participates in a cycle with a foundation namespace gets merged into FOUNDATION
foundation_extended = set(FOUNDATIONS)
for s in nontriv:
    if any(n in FOUNDATIONS for n in s):
        foundation_extended |= s

def partition_p4_fixed(name):
    n = ns2(name)
    if n in foundation_extended: return "foundations+"
    if n in ALGEBRA: return "algebra"
    if n in ANALYSIS: return "analysis"
    return "leaves"

def partition_p3_fixed(name):
    n = ns2(name)
    if n in foundation_extended or n in ALGEBRA: return "core"
    if n in ANALYSIS: return "analysis"
    return "leaves"

print(f"\nFoundation-extended (merging cycle participants): {sorted(foundation_extended)}")

PARTITIONS = [
    ("monolithic", lambda n: "ALL"),
    ("P_SCC (collapse all cycles)", partition_scc),
    ("P4_fixed (4 packages, foundation absorbs cycles)", partition_p4_fixed),
    ("P3_fixed (3 packages, core absorbs cycles)", partition_p3_fixed),
]

results = {}
for label, fn in PARTITIONS:
    pkg_of = {u: fn(g.nodes[u]['drv_name']) for u in g.nodes}
    pkgs = set(pkg_of.values())

    pkg_modules = defaultdict(list)
    for u, p in pkg_of.items():
        pkg_modules[p].append(u)

    pkg_work = {p: sum(g.nodes[u]['time'] for u in mods)
                for p, mods in pkg_modules.items()}

    pkg_cp = {}
    for p, mods in pkg_modules.items():
        sub = g.subgraph(mods).copy()
        for uu, vv, data in sub.edges(data=True):
            data['time'] = sub.nodes[uu]['time']
        pkg_cp[p] = networkx.dag_longest_path_length(sub, weight='time') if sub.nodes else 0

    pkg_g = networkx.DiGraph()
    for p in pkgs:
        pkg_g.add_node(p)
    for u, v in g.edges():
        if pkg_of[u] != pkg_of[v]:
            pkg_g.add_edge(pkg_of[u], pkg_of[v])

    if not networkx.is_directed_acyclic_graph(pkg_g):
        print(f"\n  ===== {label} =====  STILL CYCLIC")
        cycle_count = sum(1 for _ in networkx.simple_cycles(pkg_g))
        print(f"  package-level cycles: {cycle_count}")
        continue

    pkg_g_w = pkg_g.copy()
    for pu, pv in pkg_g_w.edges():
        pkg_g_w[pu][pv]['w'] = pkg_cp[pu]
    if pkg_g_w.edges:
        long_path = networkx.dag_longest_path(pkg_g_w, weight='w')
        pipeline_wc = sum(pkg_cp[p] for p in long_path)
    else:
        pipeline_wc = max(pkg_cp.values())
        long_path = [max(pkg_cp, key=pkg_cp.get)]

    bottleneck_cp = max(pkg_cp.values())
    bottleneck_pkg = max(pkg_cp, key=pkg_cp.get)

    n_cross = sum(1 for u, v in g.edges() if pkg_of[u] != pkg_of[v])

    print(f"\n  ===== {label} =====")
    print(f"  packages:                 {len(pkgs)}")
    print(f"  cross-package edges:      {n_cross} ({100*n_cross/g.number_of_edges():.1f}% of total)")

    if len(pkgs) <= 10:
        print(f"  per-package breakdown:")
        for p in sorted(pkgs, key=lambda p: -pkg_cp[p]):
            print(f"    {p:<28} {len(pkg_modules[p]):>5} mods, {pkg_work[p]:>6.0f}s work, {pkg_cp[p]:>5.0f}s CP")
    else:
        top = sorted(pkgs, key=lambda p: -pkg_cp[p])[:10]
        print(f"  top 10 packages by internal CP:")
        for p in top:
            print(f"    {p:<32} {len(pkg_modules[p]):>5} mods, {pkg_cp[p]:>5.0f}s CP")

    print(f"  scenarios:")
    print(f"    monolithic baseline:                          {full_cp:>6.0f}s")
    print(f"    strict-pipeline (full each pkg as barrier):   {pipeline_wc:>6.0f}s ({100*(pipeline_wc-full_cp)/full_cp:+.0f}%)")
    print(f"      chain: {' → '.join(long_path[:5])}{'...' if len(long_path)>5 else ''}")
    print(f"    bottleneck pkg only (rest cached):            {bottleneck_cp:>6.0f}s ({100*(bottleneck_cp-full_cp)/full_cp:+.0f}%)")
    print(f"      bottleneck = {bottleneck_pkg}")

    results[label] = {
        "pkg_of": pkg_of, "pkg_g": pkg_g, "pkgs": pkgs,
        "pkg_cp": pkg_cp, "pkg_modules": pkg_modules
    }

# Incremental cross-package blast for cycle-free partitions
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
print(f"({len(commits)} commits sampled)\n")
print(f"{'partition':<48} {'p25':>5} {'p50':>5} {'p75':>5} {'p90':>5}   pkgs")

for label, r in results.items():
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
          f"{blasts[9*len(blasts)//10]:>5}   of {n_pkgs}")

print(f"\nfor reference, file-level cache (today): p25=14, p50=507, p75=2604, p90=6460 modules")
