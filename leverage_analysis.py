import subprocess
import sys
from collections import defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

# Collect commits + edited modules
log = subprocess.check_output(
    ["git", "log", "-n2000", "--pretty=format:%H|%s", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

edit_count = defaultdict(int)   # module -> # commits that touched it
total_commits_with_edits = 0
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]:
        continue
    files = [path_to_module(l) for l in lines[1:] if l]
    files = {m for m in files if m and m in g}
    if files:
        total_commits_with_edits += 1
        for m in files:
            edit_count[m] += 1

print(f"observed {total_commits_with_edits} mathlib-touching commits\n")

# For each edited module, blast-radius CP (= CP through {m} ∪ ancestors(m))
# This is the wall-clock rebuild cost when m is edited.
print("computing per-module blast CP for edited modules...", file=sys.stderr)
blast_cp = {}
edited_mods = sorted(edit_count.keys())
for i, m in enumerate(edited_mods):
    if i % 200 == 0:
        print(f"  {i}/{len(edited_mods)}", file=sys.stderr)
    aff = networkx.ancestors(g, m) | {m}
    sub = g.subgraph(aff).copy()
    for u, v, data in sub.edges(data=True):
        data["time"] = sub.nodes[u]["time"]
    blast_cp[m] = networkx.dag_longest_path_length(sub, weight="time")

# Per-module total rebuild cost over the window
total_cost = {m: edit_count[m] * blast_cp[m] for m in edit_count}
grand_total = sum(total_cost.values())
full_cp = networkx.dag_longest_path_length(g, weight="time")

print(f"full CP: {full_cp:.0f}s")
print(f"sum over all edits of (blast CP): {grand_total:.0f}s "
      f"= {grand_total/total_commits_with_edits:.0f}s avg per commit-edit\n")

# Top by expected rebuild cost over window
print("=" * 90)
print("TOP MODULES BY OBSERVED REBUILD COST (edits × blast CP)")
print("=" * 90)
print(f"{'rank':>4}  {'edits':>5}  {'blast CP':>9}  {'cum cost':>10}  {'%-of-total':>10}  module")
top = sorted(total_cost.items(), key=lambda p: -p[1])[:40]
running = 0
for rank, (m, cost) in enumerate(top, 1):
    running += cost
    print(f"{rank:>4}  {edit_count[m]:>5}  {blast_cp[m]:>7.0f}s  {running:>8.0f}s  "
          f"{100*running/grand_total:>9.1f}%  {m}")

# Pareto: how many modules account for 50%, 80%, 95%?
print()
sorted_costs = sorted(total_cost.values(), reverse=True)
cum = 0
pareto = {}
for i, c in enumerate(sorted_costs, 1):
    cum += c
    for thr in [50, 80, 90, 95, 99]:
        if thr not in pareto and cum/grand_total >= thr/100:
            pareto[thr] = i
print(f"Pareto: top {pareto.get(50,'?')} modules = 50%, "
      f"top {pareto.get(80,'?')} = 80%, "
      f"top {pareto.get(90,'?')} = 90%, "
      f"top {pareto.get(95,'?')} = 95%, "
      f"top {pareto.get(99,'?')} = 99% of total observed rebuild cost")
print(f"(over {len(total_cost)} edited modules out of {len(g.nodes)} total)")

# Two distinct lever profiles:
# - High edit, high CP: hot foundation files. Lever: API stability / private import.
# - Low edit, high CP: rarely edited but on critical path. Lever: split / refactor for parallelism.
# - High edit, low CP: leaf files. No problem.
print()
print("=" * 90)
print("LEVER CLASSIFICATION (top 30 by cost)")
print("=" * 90)
print(f"{'lever':<32}  {'edits':>5}  {'blast CP':>9}  module")

EDIT_HOT = 5  # threshold: edited >= this many times in window
CP_HIGH  = 100  # threshold: blast CP >= this many seconds

for m, cost in top[:30]:
    e = edit_count[m]
    b = blast_cp[m]
    if e >= EDIT_HOT and b >= CP_HIGH:
        lever = "API stability (hot+huge blast)"
    elif e >= EDIT_HOT and b < CP_HIGH:
        lever = "ignore (hot but cheap blast)"
    elif e < EDIT_HOT and b >= CP_HIGH:
        lever = "split/refactor (rare but heavy)"
    else:
        lever = "ignore"
    print(f"{lever:<32}  {e:>5}  {b:>7.0f}s  {m}")

# Per-namespace aggregate cost
print()
print("=" * 90)
print("PER-NAMESPACE INCREMENTAL COST (where the rebuild seconds actually go)")
print("=" * 90)
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

ns_cost = defaultdict(float)
ns_edits = defaultdict(int)
ns_modules = defaultdict(int)
for m, c in total_cost.items():
    n = ns2(m)
    ns_cost[n] += c
    ns_edits[n] += edit_count[m]
    ns_modules[n] += 1

print(f"  {'namespace':<32}  {'edits':>6}  {'mods edited':>11}  {'cost':>10}  {'%':>5}")
for n, c in sorted(ns_cost.items(), key=lambda p: -p[1])[:15]:
    print(f"  {n:<32}  {ns_edits[n]:>6}  {ns_modules[n]:>11}  "
          f"{c:>8.0f}s  {100*c/grand_total:>4.1f}%")
