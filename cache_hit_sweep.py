#!/usr/bin/env python3
"""Cache-hit-aware scheduling-headroom sweep.

For each historical commit, computes the blast subset (modules whose
content hash would be invalidated under the file-level cache) and
measures FIFO wall-clock vs the makespan lower bound max(rebuild_CP,
rebuild_work / p) on the induced subgraph at p=12.

The lower bound holds for ANY scheduler. So `gap = (FIFO - LB) / FIFO`
is the maximum plausible win from an oracle scheduler on that commit's
build. If the distribution of gaps stays small across realistic commits,
no scheduling work is justified.

Usage (from /Users/chelo/mathlib4-lakeprof):
    python cache_hit_sweep.py                  # 200 commits, p=12
    python cache_hit_sweep.py -n 500 -p 12     # more commits
    python cache_hit_sweep.py --out sweep.json # save raw rows

Output: a percentile table to stdout and (optionally) a JSON file with
one row per commit so it can be re-aggregated downstream.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from typing import Dict, List, Optional

import networkx

sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from scheduler_sim import simulate, wall_clock, load_graph_json  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def path_to_module(p: str) -> Optional[str]:
    if not p.endswith(".lean"):
        return None
    if not (p.startswith("Mathlib/") or p == "Mathlib.lean"):
        return None
    return p[:-5].replace("/", ".")


def commits_with_changed_modules(n: int, repo: str) -> List[Dict]:
    """Walk the last n commits and yield those that touch at least one
    Mathlib module. Returns dicts with sha/subject/modules."""
    log = subprocess.check_output(
        ["git", "log", f"-n{n}", "--pretty=format:%H|%s", "--name-only"],
        text=True, cwd=repo,
    ).strip().split("\n\n")
    rows: List[Dict] = []
    for entry in log:
        lines = entry.split("\n")
        if not lines or "|" not in lines[0]:
            continue
        sha, subject = lines[0].split("|", 1)
        modules = [path_to_module(p) for p in lines[1:] if p]
        modules = [m for m in modules if m is not None]
        if modules:
            rows.append({"sha": sha, "subject": subject, "modules": modules})
    return rows


def blast_subgraph(g: networkx.DiGraph, changed: set) -> Optional[networkx.DiGraph]:
    """Modules invalidated under file-level cache = changed ∪ ancestors(changed).
    `ancestors` in lakeprof's orientation = consumers (modules that import any
    changed module, transitively)."""
    seeds = changed & set(g.nodes)
    if not seeds:
        return None
    affected = set(seeds)
    for m in seeds:
        affected |= networkx.ancestors(g, m)
    sub = g.subgraph(affected).copy()
    for u, _, d in sub.edges(data=True):
        d["time"] = sub.nodes[u]["time"]
    return sub


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--commits", type=int, default=200)
    ap.add_argument("-p", "--nproc", type=int, default=12)
    ap.add_argument("-i", "--input", default="mathlib-clean.log",
                    help="lakeprof log to parse (requires `lake query` in cwd)")
    ap.add_argument("--graph-json", default=None,
                    help="alternative input: pre-parsed graph JSON from lakeprof_capture")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=None,
                    help="optional JSON path for per-commit rows")
    ap.add_argument(
        "--also-hlfet",
        action="store_true",
        help="also simulate HLFET per commit (~2x runtime)",
    )
    ap.add_argument("--min-modules", type=int, default=1,
                    help="skip commits whose blast has < this many modules")
    args = ap.parse_args()

    src = args.graph_json or args.input
    print(f"loading {src}...", file=sys.stderr)
    t0 = time.monotonic()
    if args.graph_json:
        g = load_graph_json(args.graph_json)
    else:
        with open(args.input) as f:
            g = lakeprof.parse(f)
        for u, _, d in g.edges(data=True):
            d["time"] = g.nodes[u]["time"]
    print(f"  graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges "
          f"({time.monotonic()-t0:.1f}s)", file=sys.stderr)

    print(f"walking last {args.commits} commits in {args.repo}...", file=sys.stderr)
    commits = commits_with_changed_modules(args.commits, args.repo)
    print(f"  {len(commits)} commits touch ≥1 .lean file", file=sys.stderr)

    rows: List[Dict] = []
    skipped = 0
    t0 = time.monotonic()
    for i, c in enumerate(commits):
        if i % 25 == 0 and i > 0:
            elapsed = time.monotonic() - t0
            print(f"  [{i}/{len(commits)}] {elapsed:.0f}s elapsed, "
                  f"{len(rows)} rows", file=sys.stderr)
        sub = blast_subgraph(g, set(c["modules"]))
        if sub is None or sub.number_of_nodes() < args.min_modules:
            skipped += 1
            continue
        work = sum(sub.nodes[u]["time"] for u in sub.nodes)
        # NB: dag_longest_path_length(weight="time") sums edge weights, but
        # lakeprof sets edge["time"] = nodes[src]["time"] — that excludes the
        # final node's self-time. Sum nodes along the path instead.
        try:
            path = networkx.dag_longest_path(sub, weight="time")
            cp = sum(sub.nodes[u]["time"] for u in path)
        except Exception:
            cp = 0.0
        lb = max(cp, work / args.nproc)

        gs, _ = simulate(sub, args.nproc, priority="fifo")
        fifo_wall = wall_clock(gs)
        fifo_gap = (fifo_wall - lb) / fifo_wall if fifo_wall > 0 else 0.0

        row = {
            "sha": c["sha"],
            "subject": c["subject"][:80],
            "n_changed": len(c["modules"]),
            "n_blast": sub.number_of_nodes(),
            "rebuild_work_s": work,
            "rebuild_cp_s": cp,
            "lower_bound_s": lb,
            "fifo_wall_s": fifo_wall,
            "fifo_gap": fifo_gap,
            "regime": "cp-bound" if cp >= work / args.nproc else "work-bound",
        }
        if args.also_hlfet:
            gs, _ = simulate(sub, args.nproc, priority="hlfet")
            hl_wall = wall_clock(gs)
            row["hlfet_wall_s"] = hl_wall
            row["hlfet_gap"] = (hl_wall - lb) / hl_wall if hl_wall > 0 else 0.0
        rows.append(row)

    print(f"\n=== sweep summary  (p={args.nproc}, n_commits={len(rows)}, "
          f"skipped={skipped}) ===\n")
    if not rows:
        print("(no rows)")
        return 0

    # split by regime
    cp_rows = [r for r in rows if r["regime"] == "cp-bound"]
    wo_rows = [r for r in rows if r["regime"] == "work-bound"]
    print(f"CP-bound commits   (rebuild_CP ≥ work/p): {len(cp_rows)}  "
          f"(scheduler can change ≤0%)")
    print(f"work-bound commits (rebuild_CP < work/p): {len(wo_rows)}  "
          f"(scheduler may help; gap = FIFO over max-LB)")

    def pct_table(label, vals):
        if not vals:
            print(f"\n{label}: (none)")
            return
        vals = sorted(vals)
        n = len(vals)
        ps = {
            "min": vals[0],
            "p25": vals[n * 1 // 4],
            "p50": vals[n // 2],
            "p75": vals[n * 3 // 4],
            "p90": vals[min(n - 1, n * 90 // 100)],
            "p95": vals[min(n - 1, n * 95 // 100)],
            "p99": vals[min(n - 1, n * 99 // 100)],
            "max": vals[-1],
            "mean": sum(vals) / n,
        }
        print(f"\n{label}")
        print("  " + "  ".join(f"{k:>5}" for k in ps))
        print("  " + "  ".join(f"{v*100:5.2f}%" for v in ps.values()))

    pct_table("FIFO gap-over-LB, all commits",
              [r["fifo_gap"] for r in rows])
    pct_table("FIFO gap-over-LB, work-bound only",
              [r["fifo_gap"] for r in wo_rows])
    if args.also_hlfet:
        pct_table("HLFET gap-over-LB, all commits",
                  [r["hlfet_gap"] for r in rows])
        pct_table("HLFET gap-over-LB, work-bound only",
                  [r["hlfet_gap"] for r in wo_rows])

    # which work-bound commits had the biggest scheduler-recoverable gap?
    if wo_rows:
        wo_sorted = sorted(wo_rows, key=lambda r: -r["fifo_gap"])
        print("\ntop-10 work-bound commits by FIFO gap-over-LB:")
        print(f"  {'gap':>6}  {'FIFO':>7}  {'LB':>7}  {'CP':>6}  {'work':>7}  "
              f"{'#mod':>5}  sha7  subject")
        for r in wo_sorted[:10]:
            print(f"  {r['fifo_gap']*100:5.2f}%  "
                  f"{r['fifo_wall_s']:6.1f}s  {r['lower_bound_s']:6.1f}s  "
                  f"{r['rebuild_cp_s']:5.1f}s  {r['rebuild_work_s']:6.1f}s  "
                  f"{r['n_blast']:5d}  {r['sha'][:7]}  {r['subject'][:50]}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({
                "input": args.input,
                "nproc": args.nproc,
                "n_commits_walked": args.commits,
                "n_rows": len(rows),
                "n_skipped": skipped,
                "rows": rows,
            }, f, indent=2)
        print(f"\nrows written to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
