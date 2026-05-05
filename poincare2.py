"""
Better Poincaré embedding with Riemannian gradient scaling.

The Poincaré ball has a non-Euclidean metric — gradients near the boundary should
be scaled by (1-|x|²)²/4 (the inverse of the conformal factor). Without this,
Euclidean Adam pushes points over the boundary.
"""
import sys
import time
from collections import defaultdict, Counter
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof
import networkx
import numpy as np
import torch

torch.manual_seed(42)
np.random.seed(42)

with open("mathlib-clean.log") as f:
    g_di = lakeprof.parse(f)
g = g_di.to_undirected()
g.remove_edges_from(networkx.selfloop_edges(g))

nodes = list(g.nodes)
node_to_idx = {n: i for i, n in enumerate(nodes)}
N = len(nodes)
edges = np.array([(node_to_idx[u], node_to_idx[v]) for u, v in g.edges()], dtype=np.int64)

EPS = 1e-7
def poincare_dist(x, y):
    diff_sq = ((x - y) ** 2).sum(dim=-1)
    nx = (x * x).sum(dim=-1).clamp(max=1 - EPS)
    ny = (y * y).sum(dim=-1).clamp(max=1 - EPS)
    arg = 1 + 2 * diff_sq / ((1 - nx) * (1 - ny) + EPS)
    return torch.acosh(arg.clamp(min=1 + EPS))

# Initialize close to origin
emb = torch.randn(N, 16) * 0.001
emb.requires_grad_(True)

D = 16
NEG = 10
BATCH = 4096
EPOCHS = 40
LR = 0.1  # Riemannian step rate

print(f"training: D={D}, neg={NEG}, batch={BATCH}, epochs={EPOCHS}, riemannian lr={LR}")
print(f"nodes: {N}, edges: {len(edges)}")

edge_t = torch.from_numpy(edges)
t0 = time.time()

for epoch in range(EPOCHS):
    perm = torch.randperm(len(edge_t))
    epoch_loss = 0.0
    n_batches = 0
    for start in range(0, len(edge_t), BATCH):
        batch = edge_t[perm[start:start + BATCH]]
        u, v = batch[:, 0], batch[:, 1]
        neg = torch.randint(0, N, (len(batch), NEG))

        u_emb = emb[u]
        v_emb = emb[v]
        neg_emb = emb[neg.flatten()].view(-1, NEG, D)

        d_pos = poincare_dist(u_emb, v_emb)  # (B,)
        u_exp = u_emb.unsqueeze(1).expand(-1, NEG, -1)
        d_neg = poincare_dist(u_exp.reshape(-1, D), neg_emb.reshape(-1, D)).view(-1, NEG)

        # Contrastive loss: pos should be small, negs should be large
        all_d = torch.cat([-d_pos.unsqueeze(1), -d_neg], dim=1)
        loss = -torch.log_softmax(all_d, dim=1)[:, 0].mean()

        if emb.grad is not None: emb.grad.zero_()
        loss.backward()

        # Riemannian gradient: scale by (1-|x|²)²/4
        with torch.no_grad():
            sq_norms = (emb * emb).sum(dim=-1, keepdim=True).clamp(max=1 - EPS)
            scale = ((1 - sq_norms) ** 2) / 4
            emb -= LR * scale * emb.grad
            # Project back into ball if any drifted out
            new_norms = emb.norm(dim=-1, keepdim=True)
            mask = (new_norms >= 1 - EPS).squeeze()
            if mask.any():
                emb[mask] *= (1 - EPS) / new_norms[mask]

        epoch_loss += loss.item()
        n_batches += 1

    if epoch % 5 == 0 or epoch == EPOCHS - 1:
        with torch.no_grad():
            mean_norm = emb.norm(dim=-1).mean().item()
            max_norm = emb.norm(dim=-1).max().item()
        print(f"  epoch {epoch+1:>2}/{EPOCHS}  loss={epoch_loss/n_batches:.4f}  "
              f"mean_norm={mean_norm:.3f}  max_norm={max_norm:.4f}  ({time.time()-t0:.1f}s)")

emb_np = emb.detach().numpy()
norms = np.linalg.norm(emb_np, axis=1)
print(f"\nfinal: mean norm = {norms.mean():.3f}, max = {norms.max():.4f}")
print(f"radius distribution: p50={np.percentile(norms,50):.3f}, p90={np.percentile(norms,90):.3f}, p99={np.percentile(norms,99):.3f}")

def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Verify embedding makes sense by checking edge distances vs random
def hyp_d(x, y):
    diff_sq = ((x - y) ** 2).sum()
    nx = min((x * x).sum(), 1 - EPS)
    ny = min((y * y).sum(), 1 - EPS)
    return np.arccosh(np.clip(1 + 2 * diff_sq / ((1 - nx) * (1 - ny) + EPS), 1 + EPS, None))

edge_dists = []
for u, v in edges[:2000]:
    edge_dists.append(hyp_d(emb_np[u], emb_np[v]))
random_dists = []
for _ in range(2000):
    u, v = np.random.randint(0, N, 2)
    if u != v:
        random_dists.append(hyp_d(emb_np[u], emb_np[v]))

print(f"\n=== Embedding sanity ===")
print(f"Mean hyperbolic distance: edges={np.mean(edge_dists):.3f},  random pairs={np.mean(random_dists):.3f}")
print(f"Ratio: edges are {np.mean(random_dists)/np.mean(edge_dists):.2f}× closer than random — good if >> 1")

# ---- Namespace centroid analysis ----
ns_to_indices = defaultdict(list)
for u in nodes:
    ns_to_indices[ns2(g_di.nodes[u].get("drv_name", u))].append(node_to_idx[u])

# Use Frechet-mean-like (average) for centroid; near the origin this approximates the hyperbolic mean
ns_centroids = {n: emb_np[idxs].mean(axis=0) for n, idxs in ns_to_indices.items() if len(idxs) >= 5}

# Mismatch check
mismatch_count = 0
mismatch_per_ns = Counter()
for u, idx in node_to_idx.items():
    own_ns = ns2(g_di.nodes[u].get("drv_name", u))
    if own_ns not in ns_centroids: continue
    best_ns, best_d = None, float("inf")
    for ns, c in ns_centroids.items():
        d = hyp_d(emb_np[idx], c)
        if d < best_d:
            best_d = d; best_ns = ns
    if best_ns != own_ns:
        mismatch_count += 1
        mismatch_per_ns[own_ns] += 1

total_eligible = sum(len(v) for v in ns_to_indices.values() if len(v) >= 5)
print(f"\n=== Namespace mismatch ===")
print(f"Modules whose nearest namespace centroid != declared namespace: "
      f"{mismatch_count}/{total_eligible} ({100*mismatch_count/total_eligible:.0f}%)")
print(f"\nTop 12 namespaces by mismatch rate (only those with ≥30 modules):")
for ns, count in sorted(mismatch_per_ns.items(),
                        key=lambda p: -p[1]/len(ns_to_indices[p[0]]) if len(ns_to_indices[p[0]]) >= 30 else -1)[:12]:
    total = len(ns_to_indices[ns])
    if total < 30: continue
    print(f"  {ns:<32} {count:>4}/{total:>4}  ({100*count/total:>3.0f}%)")

print(f"\nLowest-mismatch (best-fitting) namespaces:")
ns_mismatch_rates = []
for ns, idxs in ns_to_indices.items():
    if len(idxs) < 30 or ns not in ns_centroids: continue
    rate = mismatch_per_ns.get(ns, 0) / len(idxs)
    ns_mismatch_rates.append((rate, ns, len(idxs)))
for rate, ns, n in sorted(ns_mismatch_rates)[:10]:
    print(f"  {ns:<32} {n:>4}  {100*rate:>3.0f}%")

np.save("poincare_emb_v2.npy", emb_np)
print("\nsaved to poincare_emb_v2.npy")

# ---- Hyperbolic-distance-based partitioning vs Louvain ----
# K-means on Poincaré coordinates (using Euclidean approximation since centroids are near origin)
from sklearn.cluster import KMeans
print("\n=== K-means clustering (k=15, comparable to Louvain) ===")
km = KMeans(n_clusters=15, random_state=42, n_init=10)
labels = km.fit_predict(emb_np)

# Modularity of this partition
from networkx.algorithms.community import modularity
clusters_km = [[nodes[i] for i in range(N) if labels[i] == k] for k in range(15)]
clusters_km = [c for c in clusters_km if c]
q_km = modularity(g, clusters_km)
print(f"K-means-on-Poincaré modularity: {q_km:.4f}")
print(f"Louvain modularity (from earlier): 0.4753")
print(f"Namespace modularity (from earlier): 0.3903")
print(f"K-means cluster sizes: {sorted([len(c) for c in clusters_km], reverse=True)}")
