"""
Train a 16-dim Poincaré-ball embedding of mathlib's file-level graph
using contrastive loss with random non-edge negatives.

Then analyze:
  - Hyperbolic distance to namespace centroids (per-module "namespace fit")
  - Hyperbolic clusters (k-means in embedding space) vs Louvain
  - Modules whose embedding is farthest from their own namespace
"""
import sys
import time
import math
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
print(f"nodes: {N}, edges: {g.number_of_edges()}")

# Edge list as integer pairs
edges = np.array([(node_to_idx[u], node_to_idx[v]) for u, v in g.edges()], dtype=np.int64)
print(f"edge tensor: {edges.shape}")

# ---------- Poincaré ball ops ----------
EPS = 1e-7
def poincare_dist(x, y):
    """x, y: (B, D) tensors in open unit ball."""
    diff = x - y
    diff_sq = (diff * diff).sum(dim=-1)
    norm_x = (x * x).sum(dim=-1).clamp(max=1 - EPS)
    norm_y = (y * y).sum(dim=-1).clamp(max=1 - EPS)
    arg = 1 + 2 * diff_sq / ((1 - norm_x) * (1 - norm_y) + EPS)
    return torch.acosh(arg.clamp(min=1 + EPS))

class PoincareEmbedding(torch.nn.Module):
    def __init__(self, n, d):
        super().__init__()
        # Init near origin
        self.emb = torch.nn.Parameter(torch.randn(n, d) * 0.001)

    def forward(self, idx):
        e = self.emb[idx]
        # Project into ball if any drifted out
        norm = e.norm(dim=-1, keepdim=True)
        max_norm = 1 - EPS
        e = torch.where(norm >= max_norm, e * max_norm / (norm + EPS), e)
        return e

D = 16
NEG_PER_POS = 5
BATCH_SIZE = 2048
EPOCHS = 5
LR = 0.05  # lower than paper since we're using plain Adam, not Riemannian

model = PoincareEmbedding(N, D)
opt = torch.optim.Adam(model.parameters(), lr=LR)

print(f"\ntraining: D={D}, neg={NEG_PER_POS}, batch={BATCH_SIZE}, epochs={EPOCHS}, lr={LR}")
edge_tensor = torch.from_numpy(edges)

t0 = time.time()
for epoch in range(EPOCHS):
    perm = torch.randperm(len(edge_tensor))
    epoch_loss = 0.0
    n_batches = 0
    for start in range(0, len(edge_tensor), BATCH_SIZE):
        batch = edge_tensor[perm[start:start + BATCH_SIZE]]
        u, v = batch[:, 0], batch[:, 1]
        # negative samples
        neg = torch.randint(0, N, (len(batch), NEG_PER_POS))
        u_emb = model(u)
        v_emb = model(v)
        neg_emb = model(neg.flatten()).view(-1, NEG_PER_POS, D)

        d_pos = poincare_dist(u_emb, v_emb)
        d_neg = poincare_dist(u_emb.unsqueeze(1).expand(-1, NEG_PER_POS, -1).reshape(-1, D),
                              neg_emb.reshape(-1, D)).view(-1, NEG_PER_POS)

        # Contrastive: -log(exp(-d_pos) / (exp(-d_pos) + sum exp(-d_neg)))
        loss = -torch.log_softmax(
            torch.cat([-d_pos.unsqueeze(1), -d_neg], dim=1), dim=1
        )[:, 0].mean()

        opt.zero_grad()
        loss.backward()
        opt.step()

        # Project embeddings into ball after step
        with torch.no_grad():
            norms = model.emb.norm(dim=-1, keepdim=True)
            mask = norms >= 1 - EPS
            model.emb[mask.squeeze()] *= (1 - EPS) / norms[mask.squeeze()]

        epoch_loss += loss.item()
        n_batches += 1
    print(f"  epoch {epoch+1}/{EPOCHS}: loss = {epoch_loss/n_batches:.4f}  ({time.time()-t0:.1f}s)")

emb = model.emb.detach().numpy()
norms = np.linalg.norm(emb, axis=1)
print(f"\nfinal embedding: shape {emb.shape}, mean norm = {norms.mean():.3f}, max norm = {norms.max():.3f}")

# ---------- Analysis ----------
def ns2(name):
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "Mathlib":
        return f"Mathlib.{parts[1]}"
    return parts[0]

# Namespace centroids in hyperbolic space (proxy: Euclidean mean, OK near origin)
ns_to_indices = defaultdict(list)
for u in nodes:
    ns_to_indices[ns2(g_di.nodes[u].get("drv_name", u))].append(node_to_idx[u])

ns_centroids = {n: emb[idxs].mean(axis=0) for n, idxs in ns_to_indices.items() if len(idxs) >= 5}

def hyp_dist_np(x, y):
    """numpy version of Poincaré distance"""
    diff_sq = ((x - y) ** 2).sum(axis=-1)
    nx = min((x * x).sum(), 1 - EPS)
    ny = ((y * y).sum(axis=-1) if y.ndim > 1 else min((y * y).sum(), 1 - EPS))
    if y.ndim > 1:
        ny = np.minimum(ny, 1 - EPS)
    return np.arccosh(np.clip(1 + 2 * diff_sq / ((1 - nx) * (1 - ny) + EPS), 1 + EPS, None))

# Compute distance from each module to centroid of its declared namespace
print("\n=== Modules farthest from their namespace centroid (potential misnomers) ===")
print("(only namespaces with ≥10 modules)")
ns_to_dists = defaultdict(list)
for u, idx in node_to_idx.items():
    ns = ns2(g_di.nodes[u].get("drv_name", u))
    if ns not in ns_centroids:
        continue
    d = hyp_dist_np(emb[idx], ns_centroids[ns])
    ns_to_dists[ns].append((d, u))

# For each namespace, mean distance + worst offenders
print(f"\n{'namespace':<32} {'n':>4} {'mean d':>8} {'worst-fitting modules':<60}")
for ns, dists in sorted(ns_to_dists.items(), key=lambda p: -np.mean([d for d,_ in p[1]]) if len(p[1])>10 else -1)[:15]:
    if len(dists) < 10: continue
    mean_d = np.mean([d for d, _ in dists])
    worst = sorted(dists, reverse=True)[:2]
    worst_str = "; ".join(f"{u}({d:.2f})" for d, u in worst)
    print(f"{ns:<32} {len(dists):>4} {mean_d:>8.3f}  {worst_str[:60]}")

# Per-module: which namespace centroid is each closest to? Is it their own?
mismatch_count = 0
mismatch_per_ns = Counter()
for u, idx in node_to_idx.items():
    own_ns = ns2(g_di.nodes[u].get("drv_name", u))
    if own_ns not in ns_centroids: continue
    best_ns, best_d = None, float("inf")
    for ns, c in ns_centroids.items():
        d = hyp_dist_np(emb[idx], c)
        if d < best_d:
            best_d = d; best_ns = ns
    if best_ns != own_ns:
        mismatch_count += 1
        mismatch_per_ns[own_ns] += 1

print(f"\n=== Embedding-vs-namespace mismatch ===")
print(f"Modules whose closest hyperbolic centroid is NOT their declared namespace: {mismatch_count} / {sum(len(v) for v in ns_to_indices.values())}")
print(f"\nTop 10 namespaces with most embedding mismatches:")
for ns, count in mismatch_per_ns.most_common(10):
    total = len(ns_to_indices[ns])
    print(f"  {ns:<32} {count:>4}/{total:>4}  ({100*count/total:.0f}%)")

# Save embedding
np.save("poincare_emb.npy", emb)
with open("poincare_nodes.txt", "w") as f:
    for n in nodes:
        f.write(g_di.nodes[n].get("drv_name", n) + "\n")
print(f"\nembedding saved to poincare_emb.npy ({emb.shape}, {emb.nbytes:,} bytes)")
