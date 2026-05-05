"""
Louvain community detection on the file-level dependency graph.
Compare resulting clusters to the existing namespace partition.
"""
import sys
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import statistics

with open("mathlib-clean.log") as f:
    g_di = lakeprof.parse(f)

g = g_di.to_undirected()
g.remove_edges_from(networkx.selfloop_edges(g))

# Use the "louvain_communities" function (networkx >= 2.7)
print(f"running Louvain on {g.number_of_nodes()} nodes, {g.number_of_edges()} edges...")
import random
random.seed(42)

try:
    from networkx.algorithms.community import louvain_communities
    communities = louvain_communities(g, seed=42, resolution=1.0)
except ImportError:
    print("louvain_communities not available; falling back to greedy modularity")
    from networkx.algorithms.community import greedy_modularity_communities
    communities = list(greedy_modularity_communities(g))

communities.sort(key=len, reverse=True)
print(f"\nfound {len(communities)} communities; sizes (top 20): "
      f"{[len(c) for c in communities[:20]]}")

# How well does Louvain partition match the namespace partition?
# For each Louvain community, what fraction of its nodes are in its dominant namespace?
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

print("\n=== Top 20 Louvain communities: dominant namespace + purity ===")
print(f"{'#':>3} {'size':>5} {'pure':>5}  {'dominant ns':<32}  most-common-after")
for i, c in enumerate(communities[:20]):
    ns_count = Counter()
    for u in c:
        n = ns2(g_di.nodes[u].get("drv_name", u))
        ns_count[n] += 1
    dominant = ns_count.most_common(3)
    purity = dominant[0][1] / len(c) * 100
    second = f"{dominant[1][0]}={dominant[1][1]}" if len(dominant) > 1 else "—"
    third = f"{dominant[2][0]}={dominant[2][1]}" if len(dominant) > 2 else ""
    print(f"{i+1:>3} {len(c):>5} {purity:>4.0f}%  {dominant[0][0]:<32}  {second} {third}")

# How spread is each namespace across Louvain communities?
print("\n=== Namespace spread across Louvain communities ===")
print("(For each top namespace, in how many communities do its modules appear?)")
ns_to_comms = defaultdict(set)
node_to_comm = {}
for i, c in enumerate(communities):
    for u in c:
        node_to_comm[u] = i
        n = ns2(g_di.nodes[u].get("drv_name", u))
        ns_to_comms[n].add(i)

ns_sizes = Counter()
for u in g.nodes:
    ns_sizes[ns2(g_di.nodes[u].get("drv_name", u))] += 1

print(f"{'namespace':<32} {'mods':>5} {'comms':>6} {'biggest comm share':>20}")
for ns_name, n_mods in ns_sizes.most_common(20):
    comms_with = ns_to_comms[ns_name]
    # What's the biggest community for this namespace?
    comm_sizes_for_ns = Counter()
    for u in g.nodes:
        if ns2(g_di.nodes[u].get("drv_name", u)) == ns_name:
            if u in node_to_comm:
                comm_sizes_for_ns[node_to_comm[u]] += 1
    biggest_share = comm_sizes_for_ns.most_common(1)[0][1] / n_mods * 100 if comm_sizes_for_ns else 0
    print(f"{ns_name:<32} {n_mods:>5} {len(comms_with):>6} {biggest_share:>19.0f}%")

# Modularity of namespace partition vs Louvain
from networkx.algorithms.community import modularity
namespace_partition = defaultdict(set)
for u in g.nodes:
    namespace_partition[ns2(g_di.nodes[u].get("drv_name", u))].add(u)
namespace_partition = list(namespace_partition.values())

q_louvain = modularity(g, communities)
q_namespace = modularity(g, namespace_partition)

print(f"\n=== Modularity comparison (higher = better cluster fit) ===")
print(f"Louvain partition:    {q_louvain:.4f}  ({len(communities)} clusters)")
print(f"Namespace partition:  {q_namespace:.4f}  ({len(namespace_partition)} clusters)")
print(f"\n→ {'Louvain is better' if q_louvain > q_namespace else 'Namespaces are better'}: {abs(q_louvain - q_namespace):.4f} delta")
