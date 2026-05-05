"""
Predict the rebuild impact of a PR (or any range of commits).

Usage:
  python pr_impact.py BASE_REF HEAD_REF
  python pr_impact.py HEAD~5 HEAD
"""
import subprocess
import sys
from collections import defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)
base, head = sys.argv[1], sys.argv[2]

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]
full_cp = networkx.dag_longest_path_length(g, weight="time")
total_work = sum(d["time"] for _, d in g.nodes(data=True))

# Get changed files
diff_files = subprocess.check_output(
    ["git", "diff", "--name-only", f"{base}...{head}"], text=True
).strip().split("\n")

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

changed = {path_to_module(p) for p in diff_files if p}
changed = {m for m in changed if m and m in g}
non_lean = sum(1 for p in diff_files if p and not p.endswith(".lean"))

print(f"## Build impact: `{base}…{head}`")
print()
print(f"- Changed Mathlib modules: **{len(changed)}**")
print(f"- Non-Mathlib files in diff: {non_lean} (toolchain bumps, etc. — would invalidate everything)")
if not changed:
    print()
    print("(no Mathlib modules changed; nothing to predict)")
    sys.exit(0)

# Compute blast
affected = set(changed)
for m in changed:
    affected |= networkx.ancestors(g, m)

work = sum(g.nodes[u]["time"] for u in affected)
sub = g.subgraph(affected).copy()
for u, v, data in sub.edges(data=True):
    data["time"] = sub.nodes[u]["time"]
rebuild_cp = networkx.dag_longest_path_length(sub, weight="time")

# Per-namespace breakdown
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

ns_invalidated = defaultdict(int)
for m in affected:
    ns_invalidated[ns2(m)] += 1

# Predicted wall-clock at our recorded 18-core ratio (1966s for 750s CP)
WC_RATIO = 1966 / full_cp  # ~2.6: 1 second of CP becomes ~2.6 sec wall clock on 18 cores
predicted_wall_18 = rebuild_cp * WC_RATIO

print()
print(f"### Predicted rebuild impact")
print()
print(f"| metric | value | vs. clean build |")
print(f"|---|---:|---:|")
print(f"| modules invalidated | {len(affected):,} | {100*len(affected)/len(g.nodes):.0f}% of {len(g.nodes):,} |")
print(f"| total rebuild work (1-CPU) | {work:,.0f}s | {100*work/total_work:.0f}% of {total_work:,.0f}s |")
print(f"| **rebuild critical path (∞ cores)** | **{rebuild_cp:.0f}s** | **{100*rebuild_cp/full_cp:.0f}% of {full_cp:.0f}s** |")
print(f"| predicted wall-clock (18 cores) | ~{predicted_wall_18/60:.1f} min | ~{100*predicted_wall_18/(WC_RATIO*full_cp):.0f}% of clean |")

print()
print(f"### Where invalidation lands (top 10 namespaces)")
print()
print(f"| namespace | modules invalidated |")
print(f"|---|---:|")
for n, c in sorted(ns_invalidated.items(), key=lambda p: -p[1])[:10]:
    print(f"| {n} | {c:,} |")

# Flag hot-module touches: which changed files are in the top-50 leverage list?
# (Mock the leverage list inline; in production would read from artifact.)
HOT_50 = [
    "Mathlib.SetTheory.Cardinal.Cofinality", "Mathlib.Tactic.Translate.Core",
    "Mathlib.SetTheory.Ordinal.Basic", "Mathlib.SetTheory.Ordinal.Arithmetic",
    "Mathlib.Tactic.Translate.ToDual", "Mathlib.Logic.Basic", "Mathlib.Order.Lattice",
    "Mathlib.Data.List.Basic", "Mathlib.Order.Cover", "Mathlib.SetTheory.Ordinal.Family",
    "Mathlib.Topology.Order", "Mathlib.Algebra.Group.Subgroup.Defs",
    "Mathlib.Data.NNReal.Defs", "Mathlib.Order.CompleteLattice.Basic",
    "Mathlib.Order.CompleteBooleanAlgebra", "Mathlib.Tactic.Linter.DirectoryDependency",
    "Mathlib.Tactic.Simps.Basic", "Mathlib.Order.ConditionallyCompleteLattice.Basic",
    "Mathlib.Order.OrderDual", "Mathlib.Algebra.Ring.Subring.Basic",
    "Mathlib.Order.BooleanAlgebra.Basic", "Mathlib.Order.Hom.Basic",
    "Mathlib.Order.SuccPred.Limit", "Mathlib.Order.Filter.Map",
    "Mathlib.Logic.Function.Defs", "Mathlib.Order.Defs.LinearOrder",
    "Mathlib.SetTheory.Cardinal.Basic", "Mathlib.Tactic.Push",
    "Mathlib.Order.ConditionallyCompleteLattice.Indexed", "Mathlib.Data.Set.Function",
    "Mathlib.Order.CompleteLattice.Defs", "Mathlib.Algebra.MvPolynomial.Basic",
    "Mathlib.Topology.Algebra.Module.LinearMap", "Mathlib.Topology.Connected.Clopen",
    "Mathlib.SetTheory.Cardinal.Order", "Mathlib.SetTheory.Cardinal.Arithmetic",
    "Mathlib.Algebra.Group.Hom.Defs", "Mathlib.Order.Filter.Basic",
    "Mathlib.Topology.Instances.ENNReal.Lemmas", "Mathlib.Data.ENat.Basic",
]

hot_touched = [m for m in changed if m in set(HOT_50)]
if hot_touched:
    print()
    print(f"### ⚠ Hot-list modules touched ({len(hot_touched)})")
    print()
    print("These are in the top-50 highest-leverage modules. Changes here have")
    print("disproportionate downstream impact — extra reviewer scrutiny recommended.")
    print()
    for m in hot_touched:
        print(f"  - `{m}`")
