"""
Extended Louvain analysis: cycle structure, per-cluster CP, resolution sweep,
edge crossing on critical path, blast radius under Louvain federation.
"""
import sys
import json
import random
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import statistics
import subprocess
from networkx.algorithms.community import louvain_communities, modularity

random.seed(42)

with open("mathlib-clean.log") as f:
    g_di = lakeprof.parse(f)
for u, v, data in g_di.edges(data=True):
    data["time"] = g_di.nodes[u]["time"]
g = g_di.to_undirected()
g.remove_edges_from(networkx.selfloop_edges(g))
total_work = sum(d["time"] for _, d in g_di.nodes(data=True))
full_cp = networkx.dag_longest_path_length(g_di, weight="time")

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Run Louvain at default resolution for primary analysis
print("Louvain @ resolution=1.0...")
communities = louvain_communities(g, seed=42, resolution=1.0)
communities.sort(key=len, reverse=True)
node_to_comm = {}
for i, c in enumerate(communities):
    for u in c:
        node_to_comm[u] = i

# Each community gets a label: dominant namespace + index
def comm_label(idx):
    c = communities[idx]
    ns_count = Counter(ns2(g_di.nodes[u]['drv_name']) for u in c)
    dom = ns_count.most_common(1)[0][0].replace("Mathlib.", "")
    return f"L{idx+1}-{dom}({len(c)})"

print(f"\n{len(communities)} communities, modularity = {modularity(g, communities):.4f}")

# ---- 1. Cycle structure at the Louvain-package level ----
print("\n=== Q1: Does the Louvain partition form a DAG at the package level? ===")
pkg_g = networkx.DiGraph()
for u, v in g_di.edges():  # use DIRECTED edges (importer→importee)
    pu, pv = node_to_comm[u], node_to_comm[v]
    if pu != pv:
        pkg_g.add_edge(pu, pv)

is_dag = networkx.is_directed_acyclic_graph(pkg_g)
print(f"package graph: {pkg_g.number_of_nodes()} nodes, {pkg_g.number_of_edges()} edges")
print(f"is DAG: {is_dag}")
if not is_dag:
    sccs = list(networkx.strongly_connected_components(pkg_g))
    nontriv = [s for s in sccs if len(s) > 1]
    print(f"SCCs: {len(sccs)} total, {len(nontriv)} non-trivial; biggest: {max((len(s) for s in nontriv), default=1)}")
    if nontriv:
        biggest_scc = nontriv[0]
        print(f"\nBiggest SCC contains these communities:")
        for c_idx in biggest_scc:
            print(f"  {comm_label(c_idx)}")
        # what are the cycle-creating edges? for each pair in the SCC, edges in both directions
        bidir_count = 0
        bidir_pairs = []
        sub = pkg_g.subgraph(biggest_scc)
        for pu, pv in sub.edges():
            if sub.has_edge(pv, pu):
                bidir_count += 1
        bidir_pairs_dedup = set()
        for pu, pv in sub.edges():
            if sub.has_edge(pv, pu) and (pv, pu) not in bidir_pairs_dedup:
                bidir_pairs_dedup.add((pu, pv))
        print(f"\nbidirectional package pairs in SCC: {len(bidir_pairs_dedup)}")
        # count edges per direction
        edge_count = Counter()
        for u, v in g_di.edges():
            pu, pv = node_to_comm[u], node_to_comm[v]
            if pu != pv:
                edge_count[(pu, pv)] += 1
        for pu, pv in list(bidir_pairs_dedup)[:8]:
            c_pu_pv = edge_count[(pu, pv)]
            c_pv_pu = edge_count[(pv, pu)]
            print(f"  {comm_label(pu)} ⇄ {comm_label(pv)}:  "
                  f"{c_pu_pv} → / {c_pv_pu} ←  (smaller dir = {min(c_pu_pv, c_pv_pu)})")

# ---- 2. Per-community internal CP ----
print("\n=== Q2: Per-Louvain-community internal critical path ===")
print(f"{'community':<32} {'mods':>5} {'work':>7} {'CP':>6}")
comm_cps = []
for i, c in enumerate(communities):
    sub = g_di.subgraph(c).copy()
    for u, v, data in sub.edges(data=True):
        data["time"] = sub.nodes[u]["time"]
    work = sum(g_di.nodes[u]['time'] for u in c)
    cp = networkx.dag_longest_path_length(sub, weight="time") if sub.nodes else 0
    comm_cps.append((i, len(c), work, cp))
    if i < 15:
        print(f"  {comm_label(i):<30} {len(c):>5} {work:>5.0f}s {cp:>5.0f}s")

# ---- 3. Edge-crossing analysis: how many CP edges cross Louvain boundaries? ----
print("\n=== Q3: How many critical-path edges cross Louvain boundaries? ===")
crit_path = list(reversed(networkx.dag_longest_path(g_di, weight="time")))
ns_crossings = 0
louvain_crossings = 0
for u, v in zip(crit_path[:-1], crit_path[1:]):
    if ns2(g_di.nodes[u]['drv_name']) != ns2(g_di.nodes[v]['drv_name']):
        ns_crossings += 1
    if node_to_comm[u] != node_to_comm[v]:
        louvain_crossings += 1
print(f"CP has {len(crit_path)-1} edges total")
print(f"  cross namespace boundaries: {ns_crossings} ({100*ns_crossings/(len(crit_path)-1):.0f}%)")
print(f"  cross Louvain boundaries:   {louvain_crossings} ({100*louvain_crossings/(len(crit_path)-1):.0f}%)")
print(f"  → {'Louvain' if louvain_crossings < ns_crossings else 'namespace'} partition has fewer CP-crossings")

# ---- 4. Per-commit blast under Louvain federation (no API hashing, content-hash) ----
print("\n=== Q4: Per-commit cross-package blast under Louvain federation ===")
log = subprocess.check_output(
    ["git", "log", "-n2000", "--pretty=format:%H|%s", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

commits = []
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]: continue
    files = [path_to_module(l) for l in lines[1:] if l]
    files = [m for m in files if m and m in g_di]
    if files:
        commits.append(files)

if is_dag:
    deps = {p: networkx.ancestors(pkg_g, p) for p in pkg_g.nodes}
else:
    # Use SCC condensation for ancestor calculation
    cond = networkx.condensation(pkg_g)
    scc_of = cond.graph['mapping']  # node -> scc_index
    deps_cond = {s: networkx.ancestors(cond, s) for s in cond.nodes}
    # for each pkg, ancestors in pkg_g = members of its SCC + all members of ancestor SCCs
    scc_members = defaultdict(set)
    for p, s in scc_of.items():
        scc_members[s].add(p)
    deps = {}
    for p in pkg_g.nodes:
        s = scc_of[p]
        ancestors = set()
        for sa in deps_cond.get(s, set()):
            ancestors |= scc_members[sa]
        # within own SCC, all members are mutual ancestors
        ancestors |= scc_members[s] - {p}
        deps[p] = ancestors

# Modules per Louvain community
pkg_modules = defaultdict(list)
for u, p in node_to_comm.items():
    pkg_modules[p].append(u)

louv_blast_pkgs, louv_blast_mods, ns_blast_pkgs = [], [], []
# For comparison, also compute namespace-package blast
ns_pkg_g = networkx.DiGraph()
ns_of = {u: ns2(g_di.nodes[u]['drv_name']) for u in g_di.nodes}
for u, v in g_di.edges():
    if ns_of[u] != ns_of[v]:
        ns_pkg_g.add_edge(ns_of[u], ns_of[v])
# Ancestors via SCC condensation for namespace graph too (since it has cycles)
ns_cond = networkx.condensation(ns_pkg_g)
ns_scc_of = ns_cond.graph['mapping']
ns_scc_members = defaultdict(set)
for p, s in ns_scc_of.items():
    ns_scc_members[s].add(p)
ns_deps = {}
for p in ns_pkg_g.nodes:
    s = ns_scc_of[p]
    ancestors = set()
    for sa in networkx.ancestors(ns_cond, s):
        ancestors |= ns_scc_members[sa]
    ancestors |= ns_scc_members[s] - {p}
    ns_deps[p] = ancestors

for mods in commits:
    edited_louv = {node_to_comm[m] for m in mods}
    invalidated = set(edited_louv)
    for p in edited_louv:
        invalidated |= deps.get(p, set())
    louv_blast_pkgs.append(len(invalidated))

    edited_ns = {ns_of[m] for m in mods}
    inv_ns = set(edited_ns)
    for n in edited_ns:
        inv_ns |= ns_deps.get(n, set())
    ns_blast_pkgs.append(len(inv_ns))

louv_blast_pkgs.sort()
ns_blast_pkgs.sort()
n = len(louv_blast_pkgs)
def q(arr, p): return arr[int(p * n)] if int(p*n) < n else arr[-1]
print(f"\n{'partition':<32} {'p25':>5} {'p50':>5} {'p75':>5} {'p90':>5}    of N pkgs")
print(f"{'Louvain (15 pkgs)':<32} {q(louv_blast_pkgs,.25):>5} {q(louv_blast_pkgs,.5):>5} "
      f"{q(louv_blast_pkgs,.75):>5} {q(louv_blast_pkgs,.9):>5}    of {len(communities)}")
print(f"{'namespaces (34 pkgs)':<32} {q(ns_blast_pkgs,.25):>5} {q(ns_blast_pkgs,.5):>5} "
      f"{q(ns_blast_pkgs,.75):>5} {q(ns_blast_pkgs,.9):>5}    of {len(ns_pkg_g.nodes)}")

# Module-level under Louvain federation
print(f"\nUnder Louvain federation (each pkg edit = all of pkg + downstream pkgs invalidated):")
mod_blasts = []
for mods in commits:
    invalidated_pkgs = set()
    for m in mods:
        invalidated_pkgs.add(node_to_comm[m])
        invalidated_pkgs |= deps.get(node_to_comm[m], set())
    cnt = sum(len(pkg_modules[p]) for p in invalidated_pkgs)
    mod_blasts.append(cnt)

mod_blasts.sort()
print(f"  median modules invalidated: {q(mod_blasts,.5)} of {len(g.nodes)} ({100*q(mod_blasts,.5)/len(g.nodes):.0f}%)")
print(f"  p25/p50/p75/p90: {q(mod_blasts,.25)} / {q(mod_blasts,.5)} / {q(mod_blasts,.75)} / {q(mod_blasts,.9)}")
print(f"  for reference, file-level cache (from earlier): 14 / 507 / 2604 / 6460")

# ---- 5. Resolution sweep ----
print("\n=== Q5: Resolution sweep (different community granularities) ===")
print(f"{'γ':>5}  {'#comms':>6}  {'modularity':>10}  {'sizes (top 5)':>30}")
resolutions = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
sweep_results = {}
for gamma in resolutions:
    comms_gamma = louvain_communities(g, seed=42, resolution=gamma)
    comms_gamma.sort(key=len, reverse=True)
    q = modularity(g, comms_gamma)
    sweep_results[gamma] = {"n": len(comms_gamma), "q": q, "sizes": [len(c) for c in comms_gamma[:5]]}
    print(f"  {gamma:>4}  {len(comms_gamma):>6}  {q:>10.4f}  {[len(c) for c in comms_gamma[:5]]}")

# Save data for plotting
out = {
    "louvain_modularity": modularity(g, communities),
    "namespace_modularity": modularity(g, [{u for u in g.nodes if ns_of[u] == n} for n in set(ns_of.values())]),
    "n_communities": len(communities),
    "n_namespaces": len(set(ns_of.values())),
    "comm_sizes": [len(c) for c in communities],
    "comm_cps": [{"label": comm_label(i), "size": len(c), "work": sum(g_di.nodes[u]['time'] for u in c),
                  "cp": comm_cps[i][3]} for i, c in enumerate(communities)],
    "is_dag": is_dag,
    "cp_crossings": {"namespace": ns_crossings, "louvain": louvain_crossings, "total": len(crit_path)-1},
    "blast_louvain_pkgs": louv_blast_pkgs,
    "blast_ns_pkgs": ns_blast_pkgs,
    "blast_louvain_mods": mod_blasts,
    "resolution_sweep": sweep_results,
}
with open("louvain_data.json", "w") as f:
    json.dump(out, f, indent=2)
print("\nsaved data to louvain_data.json")

# Save the partition itself
with open("louvain_partition.json", "w") as f:
    json.dump({
        "communities": [list(c) for c in communities],
        "node_to_comm": node_to_comm,
        "labels": [comm_label(i) for i in range(len(communities))]
    }, f)
print("saved partition to louvain_partition.json")
