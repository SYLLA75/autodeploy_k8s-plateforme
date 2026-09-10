"""Combien de notes sont à cheval sur une frontière de fenêtre, et est-ce que ça change le compte ?"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"
notes = []
for f in sorted(D.glob("*traces_*.json")):
    notes += lire_notes(f)
notes = [n for n in notes if n.debut_ns and n.fin_ns >= n.debut_ns]

envois   = [n for n in notes if n.nom_file and n.operation_file == "send"]
retraits = [n for n in notes if n.nom_file and n.operation_file == "process"]
# un retrait produit deux notes : on ne garde qu'une par message
vus, retraits_u = set(), []
for n in retraits:
    c = n.cle_message
    if c in vus: continue
    vus.add(c); retraits_u.append(n)

def stat(nom, v):
    if not v: print(f"  {nom:<10} —"); return
    v = sorted(v); q = lambda p: v[min(len(v)-1, int(len(v)*p))]
    print(f"  {nom:<10} n={len(v):6d}   médiane {q(.5):8.1f} ms   9e décile {q(.9):9.1f} ms   max {v[-1]:9.1f} ms")

print(f"notes lues : {len(notes)}   ·   dépôts {len(envois)}   ·   retraits (messages) {len(retraits_u)}\n")
print("COMBIEN DE TEMPS DURE UNE NOTE")
stat("toutes",   [n.duree_ns/1e6 for n in notes])
stat("dépôts",   [n.duree_ns/1e6 for n in envois])
stat("retraits", [n.duree_ns/1e6 for n in retraits_u])

for L in (10, 30, 60):
    W = L * 1_000_000_000
    ac = lambda v: sum(1 for n in v if n.debut_ns // W != n.fin_ns // W)
    print(f"\nGRILLE DE {L} s — notes à cheval sur une frontière")
    print(f"  toutes     {ac(notes):6d} / {len(notes):6d}   ({100*ac(notes)/len(notes):5.2f} %)")
    print(f"  dépôts     {ac(envois):6d} / {len(envois):6d}")
    print(f"  retraits   {ac(retraits_u):6d} / {len(retraits_u):6d}")

# l'écart par fenêtre, selon la convention retenue
W = 60_000_000_000
print("\n\nÉCART PAR FENÊTRE DE 60 s, file food_delivery")
print("  (dépôts − retraits ; devrait suivre la variation du niveau de la file)\n")
tables = {}
for conv, quand in (("début", lambda n: n.debut_ns), ("fin", lambda n: n.fin_ns)):
    d = collections.Counter(quand(n)//W for n in envois   if n.nom_file == "food_delivery")
    r = collections.Counter(quand(n)//W for n in retraits_u if n.nom_file == "food_delivery")
    tables[conv] = (d, r)
fen = sorted(set().union(*[set(d)|set(r) for d, r in tables.values()]))
print(f"  {'fenêtre':>9} │ {'par le DÉBUT':^22} │ {'par la FIN':^22}")
print(f"  {'':>9} │ {'dép':>4} {'ret':>4} {'écart':>6}      │ {'dép':>4} {'ret':>4} {'écart':>6}")
print("  " + "─"*9 + "┼" + "─"*24 + "┼" + "─"*24)
for f in fen:
    lig = f"  {f%1440//60:02d}:{f%60:02d}     │"
    for conv in ("début", "fin"):
        d, r = tables[conv]
        lig += f" {d[f]:4d} {r[f]:4d} {d[f]-r[f]:+6d}      │"
    print(lig)
