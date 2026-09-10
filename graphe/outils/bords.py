"""Les fenêtres des bords sont-elles amputées, et les retraits sont-ils appariés à un dépôt ?"""
import sys, collections
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"
notes = []
for f in sorted(D.glob("*traces_*.json")):
    notes += lire_notes(f)
notes = [n for n in notes if n.debut_ns]

envois = [n for n in notes if n.nom_file and n.operation_file == "send"]
vus, retraits = set(), []
for n in notes:
    if n.nom_file and n.operation_file == "process":
        c = n.cle_message
        if c in vus: continue
        vus.add(c); retraits.append(n)

u = lambda ns: datetime.fromtimestamp(ns/1e9, timezone.utc).strftime("%H:%M:%S")
print("HEURES RÉELLES DES ÉVÉNEMENTS (UTC)")
print(f"  toutes notes : {u(min(n.debut_ns for n in notes))} → {u(max(n.fin_ns for n in notes))}")
print(f"  dépôts       : {u(min(n.debut_ns for n in envois))} → {u(max(n.debut_ns for n in envois))}")
print(f"  retraits     : {u(min(n.debut_ns for n in retraits))} → {u(max(n.debut_ns for n in retraits))}")

# un retrait a-t-il son dépôt dans la plage ? (même trace)
traces_dep = collections.defaultdict(list)
for n in envois: traces_dep[n.trace_id].append(n)
orph = [n for n in retraits if n.trace_id not in traces_dep]
print(f"\nAPPARIEMENT dépôt ↔ retrait (par identifiant de trace)")
print(f"  retraits dont le dépôt est dans la plage : {len(retraits)-len(orph)} / {len(retraits)}")
print(f"  retraits orphelins                       : {len(orph)}")
for n in orph[:6]:
    print(f"      {u(n.debut_ns)}  file {n.nom_file}")

W = 60_000_000_000
print(f"\nPAR FENÊTRE DE 60 s  (grille absolue)")
print(f"  {'fenêtre':>8} │ {'dép':>4} {'ret':>4} {'écart':>6} │ orph │ secondes réellement couvertes")
print("  " + "─"*8 + "┼" + "─"*18 + "┼" + "─"*6 + "┼" + "─"*32)
dep = collections.Counter(n.debut_ns//W for n in envois)
ret = collections.Counter(n.debut_ns//W for n in retraits)
orw = collections.Counter(n.debut_ns//W for n in orph)
# couverture réelle : premier et dernier instant de N'IMPORTE quelle note dans la fenêtre
couv = collections.defaultdict(lambda: [None, None])
for n in notes:
    k = n.debut_ns//W
    a, b = couv[k]
    couv[k] = [n.debut_ns if a is None else min(a, n.debut_ns),
               n.debut_ns if b is None else max(b, n.debut_ns)]
for f in sorted(set(dep) | set(ret)):
    a, b = couv[f]
    span = (b-a)/1e9 if a else 0
    deb = (a - f*W)/1e9 if a else 0
    fin = ((f+1)*W - b)/1e9 if b else 0
    print(f"  {u(f*W):>8} │ {dep[f]:4d} {ret[f]:4d} {dep[f]-ret[f]:+6d} │ {orw[f]:4d} │ "
          f"{span:5.1f} s   (trou {deb:.0f} s au début, {fin:.0f} s à la fin)")
