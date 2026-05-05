"""Phase 7 — module-system delta: how much headroom remains for `private import`?"""
import sys
from collections import Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

# Overall edge composition
total = g.number_of_edges()
counts = Counter()
for _, _, d in g.edges(data=True):
    if d.get("isMeta"):
        counts["meta"] += 1
    elif d.get("isExported", True):  # default-true if absent
        counts["public (isExported)"] += 1
    else:
        counts["private (not exported)"] += 1
    if d.get("importAll"):
        counts["importAll (subset)"] += 1

print(f"Total import edges: {total}")
for k, v in counts.most_common():
    print(f"  {k:<28} {v:>6}  {100*v/total:>5.1f}%")

# Edges on the standard critical path: how many are public?
crit_path = list(reversed(networkx.dag_longest_path(g, weight="time")))
print(f"\nStandard critical path: {len(crit_path)} nodes")
cp_edges = []
for u, v in zip(crit_path[:-1], crit_path[1:]):
    if g.has_edge(u, v):
        cp_edges.append((u, v, g[u][v]))
    elif g.has_edge(v, u):
        cp_edges.append((v, u, g[v][u]))
print(f"Edges along standard CP: {len(cp_edges)}")
cp_pub = sum(1 for _, _, d in cp_edges if d.get("isExported", True) and not d.get("isMeta"))
cp_priv = sum(1 for _, _, d in cp_edges if not d.get("isExported", True))
cp_meta = sum(1 for _, _, d in cp_edges if d.get("isMeta"))
print(f"  public:  {cp_pub} ({100*cp_pub/max(1,len(cp_edges)):.0f}%)")
print(f"  private: {cp_priv}")
print(f"  meta:    {cp_meta}")

# What-if: all imports become private/private-aware (set isExported=False)
print("\n--- What-if: every import becomes `private import` ---")
g_priv = g.copy()
for u, v, d in g_priv.edges(data=True):
    d["isExported"] = False

# Re-run rebuild-aware CP logic (mirror lakeprof.report)
def rebuild_cp(g_):
    cats = ["public", "private", "meta"]
    dist = {c: {v: g_.nodes[v]["time"] for v in g_} for c in cats}
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
        if dist["meta"][v] < dist["public"][v]:
            pass  # meta starts at public for new nodes (lakeprof handles this differently)
    return max(dist["private"].values())

current_rebuild = rebuild_cp(g)
maximal_private = rebuild_cp(g_priv)
print(f"current rebuild CP:                     {current_rebuild:.1f}s")
print(f"maximal-private rebuild CP (lower bnd): {maximal_private:.1f}s")
print(f"headroom from full private adoption:    {current_rebuild - maximal_private:+.1f}s "
      f"({100*(current_rebuild - maximal_private)/current_rebuild:+.1f}%)")

# Count: of the modules on the standard CP, how many INCOMING public imports
# come from non-CP nodes? Those are conversion candidates that, if made private,
# would shrink rebuild blast radii for changes to non-CP modules without affecting
# the standard CP.
print("\n--- Per-CP-module: incoming public imports from non-CP modules ---")
cp_set = set(crit_path)
print(f"{'rank':>4} {'#cand':>6} {'time':>6}  module")
candidates_total = 0
for i, m in enumerate(crit_path[:30], 1):
    incoming_pub = 0
    for u, v, d in g.in_edges(m, data=True):
        if u not in cp_set and d.get("isExported", True) and not d.get("isMeta"):
            incoming_pub += 1
    candidates_total += incoming_pub
    if incoming_pub > 0:
        print(f"{i:>4} {incoming_pub:>6} {g.nodes[m]['time']:>5.1f}s  {m}")
print(f"\ntotal conversion candidates among top-30 CP modules: {candidates_total}")
