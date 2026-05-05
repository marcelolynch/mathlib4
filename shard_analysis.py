import sys
from collections import defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)

for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

crit_path_nodes = list(reversed(networkx.dag_longest_path(g, weight="time")))
crit_floor = sum(g.nodes[u]["time"] for u in crit_path_nodes)
total_work = sum(d["time"] for _, d in g.nodes(data=True))
print(f"total work (1-CPU sim): {total_work:.0f}s")
print(f"critical path floor:    {crit_floor:.0f}s")
print(f"max speedup:            {total_work/crit_floor:.1f}x")
print()

print("=" * 60)
print("PARALLELISM PROFILE (infinite cores, recorded schedule)")
print("=" * 60)

gs = lakeprof.simulate(g, max_nproc=None)
events = []
for _, d in gs.nodes(data=True):
    events.append((d["start"], +1))
    events.append((d["stop"], -1))
events.sort()

makespan = max(d["stop"] for _, d in gs.nodes(data=True))
buckets_ready_cores = [0, 8, 16, 32, 48, 64, 96, 128, 192, 256, 512, 100000]
time_in_band = defaultdict(float)
prev_t = 0.0
running = 0
for t, delta in events:
    if t > prev_t and running > 0:
        for lo, hi in zip(buckets_ready_cores, buckets_ready_cores[1:]):
            if lo <= running < hi:
                time_in_band[(lo, hi)] += t - prev_t
                break
    running += delta
    prev_t = t

print(f"makespan (∞ cores):     {makespan:.0f}s")
print()
print("How long the build runs with N tasks concurrently active:")
print(f"  {'concurrent':>14}  {'wall time':>12}  {'%':>6}")
for lo, hi in zip(buckets_ready_cores, buckets_ready_cores[1:]):
    t = time_in_band[(lo, hi)]
    if t < 0.1:
        continue
    label = f"{lo}–{hi-1}" if hi < 100000 else f"{lo}+"
    print(f"  {label:>14}  {t:>10.1f}s  {100*t/makespan:>5.1f}%")

# narrow zones: when the build is bottlenecked
print()
print("Narrow stretches (< 32 concurrent tasks under ∞ cores):")
narrow_total = sum(t for (lo, _), t in time_in_band.items() if lo < 32)
print(f"  {narrow_total:.0f}s of {makespan:.0f}s = {100*narrow_total/makespan:.0f}% of wall-clock")
print("  (these are the periods when the critical path is exposed —")
print("   refactoring the modules running here would shorten the floor)")

print()
print("=" * 60)
print("BOTTLENECK WHAT-IF (zero out top-K critical-path modules)")
print("=" * 60)
print(f"{'K':>4}  {'new floor':>12}  {'gain':>10}  {'top removed':>40}")
print(f"{0:>4}  {crit_floor:>10.1f}s  {0:>8.1f}s  {'(baseline)':>40}")

cp_sorted = sorted(crit_path_nodes, key=lambda u: -g.nodes[u]["time"])
for K in [1, 3, 5, 10, 25, 50]:
    g2 = g.copy()
    removed = cp_sorted[:K]
    for u in removed:
        g2.nodes[u]["time"] = 0
    for u, v, data in g2.edges(data=True):
        data["time"] = g2.nodes[u]["time"]
    new_floor = networkx.dag_longest_path_length(g2, weight="time")
    print(f"{K:>4}  {new_floor:>10.1f}s  {crit_floor-new_floor:>8.1f}s  "
          f"{', '.join(g.nodes[u]['drv_name'].split('.')[-1] for u in removed[:3]):>40}{'…' if K>3 else ''}")

print()
print("=" * 60)
print("NAMESPACE SHARD ANALYSIS (top-2 prefix grouping)")
print("=" * 60)

def ns(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"{parts[0]}.{parts[1]}"
    return parts[0]

work_per_ns = defaultdict(float)
nodes_per_ns = defaultdict(int)
for u, d in g.nodes(data=True):
    work_per_ns[ns(d["drv_name"])] += d["time"]
    nodes_per_ns[ns(d["drv_name"])] += 1

cross_edges = defaultdict(int)
intra_edges = defaultdict(int)
for u, v in g.edges():
    nu, nv = ns(g.nodes[u]["drv_name"]), ns(g.nodes[v]["drv_name"])
    if nu == nv:
        intra_edges[nu] += 1
    else:
        cross_edges[(nu, nv)] += 1

print(f"  {'namespace':<35}  {'modules':>7}  {'work':>9}  {'%':>5}")
sorted_ns = sorted(work_per_ns.items(), key=lambda p: -p[1])
cum = 0
for name, work in sorted_ns[:20]:
    cum += work
    print(f"  {name:<35}  {nodes_per_ns[name]:>7}  {work:>7.0f}s  {100*work/total_work:>4.1f}%")
print(f"  {'(top-20 cumulative)':<35}  {'':>7}  {cum:>7.0f}s  {100*cum/total_work:>4.1f}%")

print()
print("Heaviest cross-namespace import flows (importer → importee, count):")
for (nu, nv), c in sorted(cross_edges.items(), key=lambda p: -p[1])[:15]:
    print(f"  {c:>5}  {nu:<35}  →  {nv}")
