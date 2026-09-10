"""Quelles étiquettes porte chaque compteur, et comment rapprocher traces et compteurs ?"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes, lire_releves

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"

# --- côté traces
notes = []
for f in sorted(D.glob("*traces_*.json"))[:4]:
    notes += lire_notes(f)
n = next(x for x in notes if x.pod_uid)
print("CÔTÉ TRACES — comment une note désigne son émetteur")
print(f"  service   : {n.service}")
print(f"  pod_uid   : {n.pod_uid}")
print(f"  machine   : {n.machine}")
print(f"  namespace : {n.namespace}")

# --- côté compteurs
etiq = collections.defaultdict(set)
exemple = {}
for f in sorted(D.glob("*metrics_*.json"))[:3]:
    for r in lire_releves(f):
        etiq[r.nom] |= set(r.etiquettes)
        exemple.setdefault(r.nom, r.etiquettes)

print(f"\nCÔTÉ COMPTEURS — {len(etiq)} noms")
for nom in sorted(etiq):
    print(f"\n  {nom}")
    print(f"    étiquettes : {', '.join(sorted(etiq[nom]))}")
    ex = {k: v for k, v in exemple[nom].items()
          if k in ("pod", "namespace", "node", "instance", "queue", "container",
                   "uid", "created_by_name", "host_ip", "pod_ip")}
    if ex:
        print(f"    exemple    : {ex}")
