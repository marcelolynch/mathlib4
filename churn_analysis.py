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

total_work = sum(d["time"] for _, d in g.nodes(data=True))

# For change to module m, modules needing rebuild = ancestors of m
# (importers transitively).
N_COMMITS = 1000
log = subprocess.check_output(
    ["git", "log", f"-n{N_COMMITS}", "--pretty=format:%H|%s",
     "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

def path_to_module(p):
    if not p.endswith(".lean"):
        return None
    if not (p.startswith("Mathlib/") or p == "Mathlib.lean"):
        return None
    return p[:-5].replace("/", ".")

commits = []
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]:
        continue
    sha, subject = lines[0].split("|", 1)
    files = [path_to_module(l) for l in lines[1:] if l]
    files = [m for m in files if m is not None and m in g]
    if files:
        commits.append((sha, subject, files))

print(f"analyzed last {len(commits)} commits with ≥1 mathlib module change\n")

# Cache descendants for speed
def blast(mods):
    affected = set()
    for m in mods:
        affected.add(m)
        affected |= networkx.ancestors(g, m)
    return affected

# Per-commit blast radius
rows = []
for sha, subj, mods in commits:
    aff = blast(mods)
    aff_work = sum(g.nodes[u]["time"] for u in aff)
    sub = g.subgraph(aff).copy()
    for u, v, data in sub.edges(data=True):
        data["time"] = sub.nodes[u]["time"]
    aff_floor = networkx.dag_longest_path_length(sub, weight="time") if sub.nodes else 0
    rows.append((sha[:8], len(mods), len(aff), aff_work, aff_floor, subj[:60]))

# Distribution
print("Distribution of cache-invalidation blast radius:")
print(f"  {'pct touched modules':>22}  {'pct invalidated':>17}  {'pct rebuild work':>18}  {'pct CP':>9}")
def pct(rows_, key):
    vals = sorted(r[key] for r in rows_)
    return [vals[int(len(vals) * q) - 1] for q in [0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0]]
quantile_labels = ["p25", "p50", "p75", "p90", "p95", "p99", "max"]

t_modules    = pct(rows, 1)
t_aff        = pct(rows, 2)
t_aff_work   = pct(rows, 3)
t_aff_floor  = pct(rows, 4)

print(f"  {'quantile':>10}  {'edited mods':>11}  {'invalidated':>11}  "
      f"{'rebuild work':>13}  {'rebuild CP':>11}  {'CP % of full':>13}")
full_cp = networkx.dag_longest_path_length(g, weight="time")
for i, q in enumerate(quantile_labels):
    print(f"  {q:>10}  {t_modules[i]:>11}  {t_aff[i]:>11}  "
          f"{t_aff_work[i]:>11.0f}s  {t_aff_floor[i]:>9.0f}s  "
          f"{100*t_aff_floor[i]/full_cp:>11.1f}%")

# Where does churn land by namespace?
print()
print("Namespace edit frequency (top 20 by # commits touching it):")
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

ns_commits = defaultdict(int)
ns_edits = defaultdict(int)
for _, _, mods in commits:
    namespaces_touched = set()
    for m in mods:
        ns_edits[ns2(m)] += 1
        namespaces_touched.add(ns2(m))
    for n in namespaces_touched:
        ns_commits[n] += 1

# Avg blast radius per edited module per namespace (how "deep in the graph" is each ns?)
print(f"  {'namespace':<32}  {'commits':>7}  {'edits':>6}  "
      f"{'avg dependents':>14}  {'%-of-graph rebuilt':>19}")
for n, c in sorted(ns_commits.items(), key=lambda p: -p[1])[:20]:
    # Pick representative modules edited in this ns to compute avg dep blast
    edited_mods_in_ns = [m for m in g.nodes if ns2(g.nodes[m]['drv_name']) == n
                         and g.nodes[m].get('kind') is None]
    if not edited_mods_in_ns:
        continue
    sample = edited_mods_in_ns[:50]
    avgs = [len(networkx.ancestors(g, m)) for m in sample]
    avg_blast = sum(avgs) / len(avgs) if avgs else 0
    pct_graph = 100 * avg_blast / len(g.nodes)
    print(f"  {n:<32}  {c:>7}  {ns_edits[n]:>6}  {avg_blast:>11.0f}  {pct_graph:>17.1f}%")

# Worst-blast commits (the cache-busters)
print()
print("Top 10 cache-busting commits (largest CP impact):")
worst = sorted(rows, key=lambda r: -r[4])[:10]
for sha, ne, na, aw, af, subj in worst:
    print(f"  {sha}  edited {ne:>3} → invalidated {na:>4}  "
          f"rebuild CP {af:>5.0f}s ({100*af/full_cp:>4.1f}% of full)  {subj}")
