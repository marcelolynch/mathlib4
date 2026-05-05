"""
Locate the specific module-level edges that create the namespace SCC.
For each bidirectional namespace pair (where both A→B and B→A edges exist),
report the smaller direction (the one a feedback arc set would cut first).
Also try a 3-level namespace partition to see if cycles persist.
"""
import sys
from collections import defaultdict, Counter
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

def ns3(name):
    parts = name.split(".")
    if len(parts) >= 3 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}.{parts[2]}"
    return ns2(name)

# Build edge counts at namespace level
edge_count = Counter()
for u, v in g.edges():
    nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
    if nu != nv:
        edge_count[(nu, nv)] += 1

# Find bidirectional pairs
bidir_pairs = []
seen = set()
for (a, b), c in edge_count.items():
    if (a, b) in seen or (b, a) in seen:
        continue
    if (b, a) in edge_count:
        c_ab = edge_count[(a, b)]
        c_ba = edge_count[(b, a)]
        smaller = min(c_ab, c_ba)
        larger = max(c_ab, c_ba)
        bidir_pairs.append((smaller, larger, a, b, c_ab, c_ba))
        seen.add((a, b))
        seen.add((b, a))

bidir_pairs.sort(key=lambda r: r[0])

print(f"Bidirectional namespace pairs: {len(bidir_pairs)}")
print(f"Total edges in 'smaller' direction (feedback arc set heuristic): "
      f"{sum(p[0] for p in bidir_pairs)}")
print()
print(f"  {'cut size':>9} {'A→B':>5} {'B→A':>5}  pair")
total_to_cut = 0
for smaller, larger, a, b, c_ab, c_ba in bidir_pairs[:25]:
    total_to_cut += smaller
    direction = "A→B" if c_ab <= c_ba else "B→A"
    if c_ab <= c_ba:
        print(f"  cut {smaller:>4}  {c_ab:>5} {c_ba:>5}  {a:<28} ↔ {b}  (cut A→B)")
    else:
        print(f"  cut {smaller:>4}  {c_ab:>5} {c_ba:>5}  {a:<28} ↔ {b}  (cut B→A)")

# Total feedback edges
print(f"\nFeedback arc heuristic: cutting these {sum(p[0] for p in bidir_pairs)} edges "
      f"(of {sum(c for c in edge_count.values())} cross-namespace edges) "
      f"would yield a DAG at namespace level.")
print(f"That's {sum(p[0] for p in bidir_pairs)/sum(c for c in edge_count.values())*100:.1f}% of cross-NS edges.")

# Sample concrete module-level edges that are "back-edges":
# for each bidirectional pair, list the actual files in the smaller direction.
print("\n=== Module-level back-edges in the top 5 pairs ===")
for smaller, larger, a, b, c_ab, c_ba in bidir_pairs[:5]:
    cut_dir = (a, b) if c_ab <= c_ba else (b, a)
    print(f"\n{cut_dir[0]} → {cut_dir[1]}  ({smaller} edges):")
    examples = []
    for u, v in g.edges():
        nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
        if nu == cut_dir[0] and nv == cut_dir[1]:
            examples.append((g.nodes[u]['drv_name'], g.nodes[v]['drv_name']))
    # Group by importer module to find files that import many "wrong-way"
    importer_counts = Counter(u for u, _ in examples)
    print(f"  top importers (file → # wrong-direction imports):")
    for u, c in importer_counts.most_common(8):
        print(f"    {c:>3}  {u}")

# Try 3-level partition
print("\n\n=========================================================================")
print("3-LEVEL NAMESPACE PARTITION (Mathlib.X.Y instead of Mathlib.X)")
print("=========================================================================")

ns3_g = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = ns3(g.nodes[u]['drv_name']), ns3(g.nodes[v]['drv_name'])
    if nu != nv:
        ns3_g.add_edge(nu, nv)

print(f"3-level graph: {ns3_g.number_of_nodes()} nodes, {ns3_g.number_of_edges()} edges")

sccs3 = list(networkx.strongly_connected_components(ns3_g))
sccs3.sort(key=lambda s: -len(s))
nontriv3 = [s for s in sccs3 if len(s) > 1]
print(f"3-level SCCs: {len(sccs3)} total, {len(nontriv3)} non-trivial")
print(f"Largest non-trivial SCC sizes: {[len(s) for s in nontriv3[:10]]}")

if nontriv3:
    big = nontriv3[0]
    # how many modules are in the largest 3-level SCC?
    mods_in_big = sum(1 for u in g.nodes if ns3(g.nodes[u]['drv_name']) in big)
    print(f"\nLargest 3-level SCC contains {len(big)} 3-level packages = {mods_in_big} modules ({100*mods_in_big/len(g.nodes):.0f}%)")
    print(f"Sample members:")
    for n in sorted(big)[:15]:
        print(f"  {n}")

# Try 4-level (the full directory hierarchy)
def ns4(name):
    parts = name.split(".")
    if len(parts) >= 4 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}.{parts[2]}.{parts[3]}"
    return ns3(name)

print("\n\n4-LEVEL PARTITION:")
ns4_g = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = ns4(g.nodes[u]['drv_name']), ns4(g.nodes[v]['drv_name'])
    if nu != nv:
        ns4_g.add_edge(nu, nv)
print(f"4-level graph: {ns4_g.number_of_nodes()} nodes, {ns4_g.number_of_edges()} edges")
sccs4 = list(networkx.strongly_connected_components(ns4_g))
sccs4.sort(key=lambda s: -len(s))
nontriv4 = [s for s in sccs4 if len(s) > 1]
print(f"4-level SCCs: {len(sccs4)} total, {len(nontriv4)} non-trivial, largest sizes: {[len(s) for s in nontriv4[:10]]}")

if nontriv4 and nontriv4[0]:
    big = nontriv4[0]
    mods_in_big = sum(1 for u in g.nodes if ns4(g.nodes[u]['drv_name']) in big)
    print(f"Largest 4-level SCC: {len(big)} packages = {mods_in_big} modules ({100*mods_in_big/len(g.nodes):.0f}%)")
