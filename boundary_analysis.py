import subprocess
import sys
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]

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

def path_to_module(p):
    if not p.endswith(".lean") or not p.startswith("Mathlib/"):
        return None
    return p[:-5].replace("/", ".")

# Get commit history with file lists
log = subprocess.check_output(
    ["git", "log", "-n2000", "--pretty=format:%H|%s", "--name-only"],
    text=True, cwd="."
).strip().split("\n\n")

commits = []
for entry in log:
    lines = entry.split("\n")
    if not lines or "|" not in lines[0]:
        continue
    sha, subj = lines[0].split("|", 1)
    files = [path_to_module(l) for l in lines[1:] if l]
    files = [m for m in files if m and m in g]
    if files:
        commits.append((sha, files))

print(f"using {len(commits)} commits with mathlib edits\n")

# ===== CRITERION 2: Co-edit cohesion =====
# For each pair of namespaces, count co-edits (commits touching both).
# A "good" boundary between A and B means LOW co-edit frequency.

print("=" * 76)
print("CO-EDIT MATRIX (top-level namespaces, last 2000 commits)")
print("=" * 76)
print("Reads as: if package X is edited, what fraction of those commits")
print("ALSO edit package Y? High value = bad boundary (X and Y are coupled).")
print()

ns_commits = defaultdict(set)  # ns -> set of commit indices
for i, (_, mods) in enumerate(commits):
    for m in mods:
        ns_commits[ns2(m)].add(i)

interesting = sorted(ns_commits.items(), key=lambda p: -len(p[1]))[:14]
names = [n for n, _ in interesting]

print(f"{'package':<28} {'#commits':>8}  " + "  ".join(f"{n.split('.')[-1][:5]:>5}" for n in names))
for n, cs in interesting:
    row = f"{n:<28} {len(cs):>8}  "
    for n2 in names:
        if n2 == n:
            row += f"{'-':>5}  "
        else:
            shared = len(cs & ns_commits[n2])
            pct = 100 * shared / len(cs) if cs else 0
            row += f"{pct:>4.0f}%  "
    print(row)

# Print which pairs are MOST coupled (co-edit) — these are candidates for merging
print()
print("Most coupled pairs (high co-edit % suggests they belong together):")
pairs = []
for i, n1 in enumerate(names):
    for n2 in names[i+1:]:
        c1 = ns_commits[n1]
        c2 = ns_commits[n2]
        if not c1 or not c2:
            continue
        # symmetric: jaccard
        j = len(c1 & c2) / len(c1 | c2)
        pairs.append((j, n1, n2, len(c1 & c2)))
pairs.sort(reverse=True)
for j, n1, n2, k in pairs[:12]:
    print(f"  jaccard={j:.2f}  ({k:>3} co-edits)  {n1}  ↔  {n2}")

# ===== CRITERION 3: Topological cut sizes =====
print()
print("=" * 76)
print("CROSS-BOUNDARY EDGE COUNT under existing namespace partition")
print("=" * 76)

cross = defaultdict(int)
intra = defaultdict(int)
for u, v in g.edges():
    nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
    if nu == nv:
        intra[nu] += 1
    else:
        cross[(nu, nv)] += 1

total_edges = g.number_of_edges()
total_cross = sum(cross.values())
print(f"  total edges: {total_edges}")
print(f"  cross-boundary: {total_cross} ({100*total_cross/total_edges:.1f}%)")
print(f"  intra-boundary: {sum(intra.values())} ({100*sum(intra.values())/total_edges:.1f}%)")
print()
print("  Top 10 inter-package edge flows (importer → importee):")
for (nu, nv), c in sorted(cross.items(), key=lambda p: -p[1])[:10]:
    if nu == "Mathlib" or nv == "Mathlib":  # skip the umbrella
        continue
    print(f"    {c:>5}  {nu}  →  {nv}")

# ===== CRITERION 1 PROXY: Federation blast radius =====
# Under namespace federation: a commit invalidates a downstream package P iff
# the commit edited a module in some package P' that P transitively imports.
print()
print("=" * 76)
print("FEDERATED BLAST RADIUS (namespace boundaries, no API-hashing)")
print("=" * 76)
print("If we federated at namespace level, how many DOWNSTREAM PACKAGES")
print("does each commit invalidate? (lower = better federation)")
print()

# Build namespace-level DAG: edge ns_a -> ns_b if any module in ns_a imports ns_b
ns_g = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = ns2(g.nodes[u]['drv_name']), ns2(g.nodes[v]['drv_name'])
    if nu != nv:
        ns_g.add_edge(nu, nv)

# For each package, which packages depend on it (= ancestors in this DAG)?
ns_dependents = {n: networkx.ancestors(ns_g, n) for n in ns_g.nodes}

ns_blast_per_commit = []
for _, mods in commits:
    edited_ns = {ns2(m) for m in mods}
    invalidated = set(edited_ns)
    for n in edited_ns:
        invalidated |= ns_dependents.get(n, set())
    ns_blast_per_commit.append(len(invalidated))

import statistics
print(f"  median cross-package blast: {statistics.median(ns_blast_per_commit)} of {len(ns_g.nodes)} packages")
print(f"  p25 / p50 / p75 / p90:      "
      f"{sorted(ns_blast_per_commit)[len(ns_blast_per_commit)//4]} / "
      f"{statistics.median(ns_blast_per_commit):.0f} / "
      f"{sorted(ns_blast_per_commit)[3*len(ns_blast_per_commit)//4]} / "
      f"{sorted(ns_blast_per_commit)[9*len(ns_blast_per_commit)//10]}")

# What if we collapse the foundation (Algebra/Order/Data/Tactic/CategoryTheory) into one
# mega-package? Then internal-foundation edits don't cross boundaries.
print()
print("WHAT-IF: collapse {Algebra, Order, Data, Tactic, CategoryTheory, Lean,")
print("Logic, Init, Util} into one 'foundation' package; everything else stays.")
foundation = {"Mathlib.Algebra", "Mathlib.Order", "Mathlib.Data", "Mathlib.Tactic",
              "Mathlib.CategoryTheory", "Mathlib.Lean", "Mathlib.Logic",
              "Mathlib.Init", "Mathlib.Util", "Mathlib.SetTheory"}

def coarse_ns(name):
    n = ns2(name)
    return "FOUNDATION" if n in foundation else n

ns_g2 = networkx.DiGraph()
for u, v in g.edges():
    nu, nv = coarse_ns(g.nodes[u]['drv_name']), coarse_ns(g.nodes[v]['drv_name'])
    if nu != nv:
        ns_g2.add_edge(nu, nv)
deps2 = {n: networkx.ancestors(ns_g2, n) for n in ns_g2.nodes}

blast2 = []
for _, mods in commits:
    edited_ns = {coarse_ns(m) for m in mods}
    invalidated = set(edited_ns)
    for n in edited_ns:
        invalidated |= deps2.get(n, set())
    blast2.append(len(invalidated))

print(f"  median cross-package blast: {statistics.median(blast2):.0f} of {len(ns_g2.nodes)} packages")
print(f"  p25 / p50 / p75 / p90:      "
      f"{sorted(blast2)[len(blast2)//4]} / "
      f"{statistics.median(blast2):.0f} / "
      f"{sorted(blast2)[3*len(blast2)//4]} / "
      f"{sorted(blast2)[9*len(blast2)//10]}")

# Module-level federation blast (count downstream MODULES whose package was invalidated)
print()
print("Module-level rebuild count under foundation-collapsed federation,")
print("assuming WITHOUT API-hashing (pessimistic — every package edit forces")
print("rebuild of all downstream-package modules):")

mod_to_pkg = {u: coarse_ns(g.nodes[u]['drv_name']) for u in g.nodes}
pkg_to_mods = defaultdict(list)
for u, p in mod_to_pkg.items():
    pkg_to_mods[p].append(u)

blast_mods = []
for _, mods in commits:
    invalidated_pkgs = set()
    for m in mods:
        invalidated_pkgs.add(mod_to_pkg[m])
        invalidated_pkgs |= deps2.get(mod_to_pkg[m], set())
    cnt = sum(len(pkg_to_mods[p]) for p in invalidated_pkgs)
    blast_mods.append(cnt)

import statistics
total_mods = len(g.nodes)
print(f"  median: {statistics.median(blast_mods):.0f} of {total_mods} modules ({100*statistics.median(blast_mods)/total_mods:.0f}%)")
print(f"  p25/p50/p75/p90:  "
      f"{sorted(blast_mods)[len(blast_mods)//4]} / "
      f"{statistics.median(blast_mods):.0f} / "
      f"{sorted(blast_mods)[3*len(blast_mods)//4]} / "
      f"{sorted(blast_mods)[9*len(blast_mods)//10]}")

# Compare to module-level blast we already measured (without federation)
print()
print("vs. file-level cache (no federation, what we measured before):")
print(f"  p25/p50/p75/p90:  14 / 507 / 2604 / 6460 modules")
print()
print("So federation alone (without API-hashing) doesn't reduce the rebuild set.")
print("It just CHANGES THE GRANULARITY of cache transfer.")
print("The real win (API-hashing) requires distinguishing 'API change' from 'internals change'.")
