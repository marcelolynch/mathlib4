"""
Find the specific MODULES (not namespaces) that most contribute to namespace cycles.
These are files whose imports cross the layered structure, weaving the SCC together.
"""
import sys
from collections import Counter, defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Use the natural layering: more-foundational namespaces first
LAYER_ORDER = [
    "Mathlib.Init", "Mathlib.Logic", "Mathlib.Util", "Mathlib.Lean",
    "Mathlib.Tactic", "Mathlib.Control", "Mathlib.Order", "Mathlib.SetTheory",
    "Mathlib.Data",
    "Mathlib.Combinatorics", "Mathlib.Algebra", "Mathlib.CategoryTheory",
    "Mathlib.GroupTheory", "Mathlib.RingTheory", "Mathlib.LinearAlgebra",
    "Mathlib.FieldTheory",
    "Mathlib.Topology", "Mathlib.Analysis", "Mathlib.MeasureTheory",
    "Mathlib.Geometry",
    "Mathlib.NumberTheory", "Mathlib.AlgebraicGeometry", "Mathlib.AlgebraicTopology",
    "Mathlib.Probability", "Mathlib.RepresentationTheory", "Mathlib.Dynamics",
    "Mathlib.Computability", "Mathlib.ModelTheory", "Mathlib.Condensed",
    "Mathlib.InformationTheory", "Mathlib.Testing", "Mathlib.Deprecated",
    "Mathlib",
]
LAYER = {n: i for i, n in enumerate(LAYER_ORDER)}
def layer(modname):
    n = ns2(modname)
    return LAYER.get(n, 99)

# For each module, count outgoing wrong-direction imports
# (imports of modules in a "more downstream" namespace per the layering above)
wrong_out = Counter()
wrong_total = 0
for u, v in g.edges():
    lu, lv = layer(g.nodes[u]['drv_name']), layer(g.nodes[v]['drv_name'])
    if lu < lv:  # importer is in upstream layer, importee in downstream layer
        wrong_out[u] += 1
        wrong_total += 1

print(f"total wrong-direction edges: {wrong_total} (under proposed layering)")
print(f"distinct importer modules: {len(wrong_out)}")
print()
print(f"Modules importing the most 'downstream' (= cycle-making):\n")
print(f"  {'wrong':>5} {'time':>5}  {'edits':>5}  module → namespaces")

# Get edit count for each module from git
import subprocess
log = subprocess.check_output(
    ["git", "log", "-n2000", "--pretty=format:%H", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

edits = Counter()
for entry in log:
    lines = entry.split("\n")
    if len(lines) < 2:
        continue
    for l in lines[1:]:
        m = path_to_module(l)
        if m and m in g:
            edits[m] += 1

# For each top wrong importer, print also which namespaces they reach into
for u, c in wrong_out.most_common(20):
    targets = Counter()
    for v in g.successors(u):
        if layer(g.nodes[v]['drv_name']) > layer(g.nodes[u]['drv_name']):
            targets[ns2(g.nodes[v]['drv_name'])] += 1
    target_str = ", ".join(f"{ns}({n})" for ns, n in targets.most_common(4))
    print(f"  {c:>4}  {g.nodes[u]['time']:>4.1f}s  {edits.get(u,0):>4}  {u}")
    print(f"          → {target_str}")

# Per source-namespace: how many modules contribute wrong-direction edges
print(f"\n\nPer-namespace 'cycle-making' module count (importers of downstream namespaces):")
ns_offenders = defaultdict(set)
for u in wrong_out:
    ns_offenders[ns2(g.nodes[u]['drv_name'])].add(u)
print(f"  {'namespace':<32}  {'modules':>7}  {'edges':>5}  {'%-of-modules':>12}")
total_per_ns = defaultdict(int)
for u in g.nodes:
    total_per_ns[ns2(g.nodes[u]['drv_name'])] += 1
for ns, mods in sorted(ns_offenders.items(), key=lambda p: -sum(wrong_out[m] for m in p[1])):
    edges_from_ns = sum(wrong_out[m] for m in mods)
    print(f"  {ns:<32}  {len(mods):>7}  {edges_from_ns:>5}  "
          f"{100*len(mods)/total_per_ns[ns]:>11.0f}%")

# What if we removed the top-K cycle-making modules from the graph entirely?
# Does the namespace SCC shrink?
print(f"\n\nWhat-if: surgical removal of top-K wrong-direction importers")
print(f"(simulates 'refactor these K files to no longer cross layers')")
print(f"\n  {'K':>4}  {'edges left':>11}  {'biggest SCC':>11}")

ranked = [m for m, _ in wrong_out.most_common()]
for K in [0, 5, 10, 25, 50, 100, 200, 500]:
    skip = set(ranked[:K])
    ns_g_pruned = networkx.DiGraph()
    skipped_edges = 0
    for u, v in g.edges():
        if u in skip:
            skipped_edges += 1
            continue
        nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
        if nu != nv:
            ns_g_pruned.add_edge(nu, nv)
    sccs = list(networkx.strongly_connected_components(ns_g_pruned))
    biggest = max((len(s) for s in sccs if len(s) > 1), default=1)
    print(f"  {K:>4}  {ns_g_pruned.number_of_edges():>11}  {biggest:>11}")
