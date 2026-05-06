#!/usr/bin/env python3
"""Extended list-scheduler for lakeprof's mathlib build graph.

Adds priority policies (FIFO / HLFET / LPT / random) on top of lakeprof's
single-policy simulator. Used by experiment 06 (scheduler simulation) to
quantify the wall-clock headroom from smarter scheduling at p=12.

Graph orientation (inherited from lakeprof.parse):
- edges go from consumer to dependency (drv imports m  => edge drv→m)
- g.successors(v)   = dependencies (modules v imports)
- g.predecessors(v) = consumers    (modules that import v)
- "scheduling-successors" of v (tasks that must run after v) are consumers,
  i.e. g.predecessors(v) in this orientation.

Run from /Users/chelo/mathlib4-lakeprof so `lake query` (used by parse) works.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import os
import random
import sys
from typing import Callable, Dict, List, Optional, Tuple, Union

import networkx

sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof  # noqa: E402  (relies on the path insert above)


# --------------------------------------------------------------------------- #
# Priority keys
# --------------------------------------------------------------------------- #

def _b_level(g: networkx.DiGraph) -> Dict[str, float]:
    """Static b-level (HLFET): self_time(v) + longest-path through scheduling-
    successors. In lakeprof's orientation, scheduling-successors = consumers
    = g.predecessors(v). Forward topological order works because lakeprof's
    topo places consumers before dependencies; hence consumers are computed
    first."""
    b: Dict[str, float] = {}
    for v in networkx.topological_sort(g):
        consumers = list(g.predecessors(v))
        if not consumers:
            b[v] = g.nodes[v]["time"]
        else:
            b[v] = g.nodes[v]["time"] + max(b[c] for c in consumers)
    return b


PriorityFn = Callable[[networkx.DiGraph, str], Tuple]


def make_priority(g: networkx.DiGraph, policy: Union[str, PriorityFn]) -> PriorityFn:
    """Return a callable (g, node) -> sortable key. Lower value = popped first
    (heapq is a min-heap)."""
    if callable(policy):
        return policy
    name = policy.lower()
    if name == "fifo":
        # recorded order = original start time. Matches lakeprof.simulate today.
        return lambda _g, v: (_g.nodes[v]["start"],)
    if name == "hlfet":
        b = _b_level(g)
        # bigger b-level → higher priority → lower key
        return lambda _g, v, _b=b: (-_b[v], _g.nodes[v]["start"])
    if name == "lpt":
        # bigger self-time → higher priority
        return lambda _g, v: (-_g.nodes[v]["time"], _g.nodes[v]["start"])
    if name == "random":
        rng = random.Random(42)
        keys = {v: rng.random() for v in g.nodes}
        return lambda _g, v, _k=keys: (_k[v], _g.nodes[v]["start"])
    raise ValueError(f"unknown priority policy: {policy!r}")


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #

def simulate(
    g: networkx.DiGraph,
    max_nproc: Optional[int],
    priority: Union[str, PriorityFn] = "fifo",
    record_decisions: bool = False,
) -> Tuple[networkx.DiGraph, List[dict]]:
    """List-schedule g under a fixed processor budget with the given policy.

    Returns (scheduled_graph, decisions). decisions is non-empty only when
    record_decisions=True; each entry is

        {
            "t": float,          # wall-clock at the decision
            "ready": [v, ...],   # all tasks ready at this moment, sorted by key
            "free_procs": int,   # processors available right now
            "picked": [v, ...],  # tasks dispatched in this scheduling round
        }

    Each scheduling round groups together all (free_procs ∩ ready) dispatches
    that happen at the same wall-clock t — i.e. one round per pop from the
    running heap, not one entry per task.
    """
    g = g.copy()
    key_fn = make_priority(g, priority)

    counter = itertools.count()  # unique third element to avoid heap comparing nodes
    outdeg = {v: d for v, d in g.out_degree() if d > 0}
    ready: list = []
    for v, d in g.out_degree():
        if d == 0:
            heapq.heappush(ready, (key_fn(g, v), next(counter), v))
    running: list = [(0.0, None)]
    decisions: List[dict] = []

    while running:
        t, u = heapq.heappop(running)
        if u is not None:
            for v in g.predecessors(u):
                outdeg[v] -= 1
                if outdeg[v] == 0:
                    heapq.heappush(ready, (key_fn(g, v), next(counter), v))

        free_procs = set(range(max_nproc or len(running) + len(ready))) \
            - {g.nodes[v]["proc"] for _, v in running if v is not None}

        if record_decisions and ready:
            ready_sorted = [v for _, _, v in sorted(ready)]
            decisions.append({
                "t": t,
                "ready": ready_sorted,
                "free_procs": len(free_procs),
                "picked": [],
            })

        for proc in sorted(free_procs)[:len(ready)]:
            _, _, v = heapq.heappop(ready)
            g.nodes[v]["proc"] = proc
            g.nodes[v]["start"] = t
            g.nodes[v]["stop"] = t + g.nodes[v]["time"]
            heapq.heappush(running, (g.nodes[v]["stop"], v))
            if record_decisions:
                decisions[-1]["picked"].append(v)

    return g, decisions


def wall_clock(g: networkx.DiGraph) -> float:
    return max(d["stop"] for _, d in g.nodes(data=True))


# --------------------------------------------------------------------------- #
# Divergence between two policies
# --------------------------------------------------------------------------- #

def divergence(
    g: networkx.DiGraph,
    policy_a: str,
    policy_b: str,
    max_nproc: int,
) -> List[dict]:
    """Run both policies, record per-decision picks, return the rounds where
    the two policies dispatched different sets of tasks. Each entry:

        {
            "t_a": ..., "t_b": ...,
            "free_a": ..., "free_b": ...,
            "ready_a": [...], "ready_b": [...],
            "picked_a": [...], "picked_b": [...],
            "diff_a_only": [...],   # picked by A, not by B at this index
            "diff_b_only": [...],
        }

    Decisions are aligned by index (not by wall-clock) because once policies
    diverge their wall-clocks drift.
    """
    _, dec_a = simulate(g, max_nproc, priority=policy_a, record_decisions=True)
    _, dec_b = simulate(g, max_nproc, priority=policy_b, record_decisions=True)
    out: List[dict] = []
    for i, (a, b) in enumerate(zip(dec_a, dec_b)):
        sa, sb = set(a["picked"]), set(b["picked"])
        if sa != sb:
            out.append({
                "i": i,
                "t_a": a["t"], "t_b": b["t"],
                "free_a": a["free_procs"], "free_b": b["free_procs"],
                "ready_a": a["ready"][:8], "ready_b": b["ready"][:8],
                "picked_a": a["picked"], "picked_b": b["picked"],
                "diff_a_only": sorted(sa - sb),
                "diff_b_only": sorted(sb - sa),
            })
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _load_graph(log_path: str) -> networkx.DiGraph:
    with open(log_path) as f:
        g = lakeprof.parse(f)
    # populate edge "time" so dag_longest_path uses real seconds
    for u, _, data in g.edges(data=True):
        data["time"] = g.nodes[u]["time"]
    return g


def load_graph_json(path: str) -> networkx.DiGraph:
    """Load a graph serialized via networkx.node_link_data.

    Used to re-do analysis off-runner against a runner-recorded trace without
    needing a same-SHA mathlib4 checkout (which `lakeprof.parse` requires for
    `lake query`). The parse step is done on the runner via
    `parse_log.py` in the lakeprof_capture workflow.
    """
    with open(path) as f:
        data = json.load(f)
    # node_link_data was emitted with `edges="edges"` for forward-compat with
    # networkx; load with the same kwarg.
    g = networkx.node_link_graph(data, edges="edges")
    # ensure edge["time"] is populated even if the producer skipped it
    for u, _, d in g.edges(data=True):
        if "time" not in d:
            d["time"] = g.nodes[u]["time"]
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="mathlib-clean.log",
                    help="lakeprof log path (parsed via lakeprof.parse, needs lake)")
    ap.add_argument("--graph-json", default=None,
                    help="alternative input: pre-parsed networkx graph JSON "
                         "from the lakeprof_capture workflow. Bypasses --input.")
    ap.add_argument("-p", "--nproc", type=int, default=12)
    ap.add_argument(
        "--policies",
        default="fifo,hlfet,lpt,random",
        help="comma-separated policy names",
    )
    ap.add_argument(
        "--divergence",
        nargs=2,
        metavar=("A", "B"),
        help="dump per-round divergence between two policies as JSON",
    )
    ap.add_argument(
        "--divergence-out",
        default="policy_divergence.json",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.graph_json:
        g = load_graph_json(args.graph_json)
        source_label = args.graph_json
    else:
        g = _load_graph(args.input)
        source_label = args.input
    cum = sum(d["time"] for _, d in g.nodes(data=True))

    # CP via node-sum along longest path. dag_longest_path_length(weight="time")
    # excludes the path's terminal node because lakeprof sets edge weight =
    # time(source); on the clean graph the discrepancy is ~0.5 s but on small
    # blast subgraphs it can be the dominant term.
    cp_path = networkx.dag_longest_path(g, weight="time")
    cp = sum(g.nodes[u]["time"] for u in cp_path)
    lb = max(cp, cum / args.nproc)  # makespan lower bound for ANY scheduler
    if not args.json:
        print(f"graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges, "
              f"total work {cum:.0f} s, CP {cp:.0f} s")
        print(f"makespan lower bound at p={args.nproc}: "
              f"max(CP, work/p) = max({cp:.0f}, {cum/args.nproc:.0f}) = {lb:.1f} s")

    rows: List[Tuple[str, float]] = []
    for policy in [p.strip() for p in args.policies.split(",") if p.strip()]:
        gs, _ = simulate(g, args.nproc, priority=policy)
        rows.append((policy, wall_clock(gs)))

    fifo_wall = next((w for p, w in rows if p == "fifo"), None)
    hlfet_wall = next((w for p, w in rows if p == "hlfet"), None)
    gap = None
    if fifo_wall and hlfet_wall:
        gap = (fifo_wall - hlfet_wall) / fifo_wall

    if args.json:
        out = {
            "nproc": args.nproc,
            "input": source_label,
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
            "total_work_s": cum,
            "critical_path_s": cp,
            "lower_bound_s": lb,
            "policies": [
                {
                    "policy": p,
                    "wall_s": w,
                    "gap_over_lb": (w - lb) / w,
                }
                for p, w in rows
            ],
            "gap_fifo_minus_hlfet_over_fifo": gap,
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"\nlist-schedule wall-clock at p={args.nproc}")
        for p, w in rows:
            over_lb = (w - lb) / w
            print(f"  {p:<8} {w:8.1f} s    util={cum / w / args.nproc:.1%}    "
                  f"gap-over-LB={over_lb:+.2%}")
        if gap is not None:
            print(f"\ngap (FIFO - HLFET) / FIFO = {gap:.2%}")
        # The "gap-over-LB" column above is the maximum win an oracle scheduler
        # could buy over that policy. It's an upper bound; the actual oracle
        # makespan may exceed LB. So a 0.10 % HLFET gap-over-LB means the
        # oracle path is hard-capped at 0.10 % wins for this graph at this p.

    if args.divergence:
        a, b = args.divergence
        diffs = divergence(g, a, b, args.nproc)
        with open(args.divergence_out, "w") as f:
            json.dump({
                "nproc": args.nproc,
                "policy_a": a,
                "policy_b": b,
                "n_decisions": "(see lengths in entries)",
                "n_diverging": len(diffs),
                "entries": diffs,
            }, f, indent=2)
        if not args.json:
            print(f"\n{len(diffs)} diverging decisions ({a} vs {b}) → {args.divergence_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
