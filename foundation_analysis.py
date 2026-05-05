import sys
from collections import defaultdict
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)

for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

total_work = sum(d["time"] for _, d in g.nodes(data=True))
full_floor = networkx.dag_longest_path_length(g, weight="time")
print(f"baseline: total work {total_work:.0f}s, ∞-core floor {full_floor:.0f}s\n")

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

def ns1(name):
    return name.split(".")[0]

def analyze(label, foundation_predicate):
    print("=" * 72)
    print(f"FOUNDATION: {label}")
    print("=" * 72)

    foundation = {u for u in g.nodes if foundation_predicate(g.nodes[u]["drv_name"])}
    downstream = set(g.nodes) - foundation

    f_work = sum(g.nodes[u]["time"] for u in foundation)
    d_work = sum(g.nodes[u]["time"] for u in downstream)

    g_f = g.subgraph(foundation).copy()
    for u, v, data in g_f.edges(data=True):
        data["time"] = g_f.nodes[u]["time"]
    f_floor = networkx.dag_longest_path_length(g_f, weight="time") if g_f.nodes else 0

    g_post = g.copy()
    for u in foundation:
        g_post.nodes[u]["time"] = 0
    for u, v, data in g_post.edges(data=True):
        data["time"] = g_post.nodes[u]["time"]
    d_floor = networkx.dag_longest_path_length(g_post, weight="time")

    print(f"  foundation:   {len(foundation):>5} modules, {f_work:>6.0f}s work, "
          f"{f_floor:>5.0f}s floor (∞ cores)")
    print(f"  downstream:   {len(downstream):>5} modules, {d_work:>6.0f}s work, "
          f"{d_floor:>5.0f}s floor (with foundation cached)")
    print(f"  total floor (sequential phases): {f_floor + d_floor:.0f}s "
          f"(vs {full_floor:.0f}s monolithic) "
          f"= {100*(full_floor - f_floor - d_floor)/full_floor:+.1f}%")

    print()
    print("  Per-downstream-namespace, if each namespace shards to its own worker")
    print("  (foundation already cached; only intra-namespace + foundation deps count):")
    print(f"    {'namespace':<30}  {'modules':>7}  {'work':>8}  {'CP':>7}  {'1-worker':>9}")

    by_ns = defaultdict(list)
    for u in downstream:
        by_ns[ns2(g.nodes[u]["drv_name"])].append(u)

    rows = []
    for n, nodes in by_ns.items():
        if len(nodes) < 5:
            continue
        sub = g_post.subgraph(set(nodes) | foundation).copy()
        for uu, vv, data in sub.edges(data=True):
            data["time"] = sub.nodes[uu]["time"]
        cp = networkx.dag_longest_path_length(sub, weight="time")
        work = sum(g.nodes[u]["time"] for u in nodes)
        rows.append((n, len(nodes), work, cp))
    rows.sort(key=lambda r: -r[2])
    for n, cnt, work, cp in rows[:12]:
        print(f"    {n:<30}  {cnt:>7}  {work:>6.0f}s  {cp:>5.0f}s  {work/cp:>7.1f}x")
    print()

    # If you ran every downstream namespace on its own machine in parallel:
    if rows:
        max_ns_cp = max(r[3] for r in rows)
        print(f"  Best-case wall-clock if each downstream namespace runs on its own")
        print(f"  unbounded-CPU machine in parallel:")
        print(f"    foundation phase:  {f_floor:.0f}s")
        print(f"    downstream phase:  {max_ns_cp:.0f}s (max across {len(rows)} namespaces)")
        print(f"    total:             {f_floor + max_ns_cp:.0f}s "
              f"(vs {full_floor:.0f}s monolithic) "
              f"= {100*(full_floor - f_floor - max_ns_cp)/full_floor:+.1f}%")
    print()

# Cut A: minimal foundation (the layer everyone depends on)
A = {"Mathlib.Init", "Mathlib.Logic", "Mathlib.Tactic", "Mathlib.Util",
     "Mathlib.Lean", "Mathlib.Order", "Mathlib.Data", "Mathlib.Algebra",
     "Mathlib.CategoryTheory", "Mathlib.Topology", "Mathlib.Combinatorics"}
analyze("CUT A — minimal: Init+Logic+Tactic+Util+Lean+Order+Data+Algebra+CategoryTheory+Topology+Combinatorics",
        lambda name: ns2(name) in A or ns1(name) != "Mathlib")

# Cut B: A + linear/ring/group/field algebra
B = A | {"Mathlib.LinearAlgebra", "Mathlib.RingTheory", "Mathlib.GroupTheory",
         "Mathlib.FieldTheory", "Mathlib.SetTheory"}
analyze("CUT B — A + LinearAlgebra+RingTheory+GroupTheory+FieldTheory+SetTheory",
        lambda name: ns2(name) in B or ns1(name) != "Mathlib")

# Cut C: B + Analysis (all the way through to the heavy normed/calculus stack)
C = B | {"Mathlib.Analysis", "Mathlib.MeasureTheory"}
analyze("CUT C — B + Analysis + MeasureTheory",
        lambda name: ns2(name) in C or ns1(name) != "Mathlib")
