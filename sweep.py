import sys
sys.path.insert(0, "/Users/chelo/lakeprof")
import lakeprof

with open("mathlib-clean.log") as f:
    g = lakeprof.parse(f)

for nproc in [16, 32, 48, 64, 72, 80, 88, 96, 104, 112, 120, 128, 144, 160, 192, 256]:
    gs = lakeprof.simulate(g, max_nproc=nproc)
    t = max(d["stop"] for _, d in gs.nodes(data=True))
    print(f"{nproc:4d}  {t:8.1f}s")
