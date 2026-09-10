import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes

d = Path("donnees/2026-09-09_1500-1504")
msg = []
for f in sorted(d.glob("*traces_*.json")):
    msg += [n for n in lire_notes(f) if n.systeme_file and n.nom_file]

dep = [n for n in msg if n.operation_file == "send"]
ret = [n for n in msg if n.operation_file == "process"]

print("%-16s %10s %10s %10s %10s" % ("file", "dépôts", "retraits", "retraits", "écart"))
print("%-16s %10s %10s %10s %10s" % ("", "(notes)", "(notes)", "(messages)", ""))
print("-"*60)
for f in sorted({n.nom_file for n in msg}):
    d_n = sum(1 for n in dep if n.nom_file == f)
    r_n = sum(1 for n in ret if n.nom_file == f)
    # un message = une paire (trace, numero de livraison)
    r_m = len({(n.trace_id, n.attributs.get("messaging.rabbitmq.message.delivery_tag"))
               for n in ret if n.nom_file == f})
    print("%-16s %10d %10d %10d %10d" % (f, d_n, r_n, r_m, d_n - r_m))
print()
print("La colonne « écart » est la grandeur centrale : ce qui entre moins ce qui sort.")
print("Comptée sur les notes, elle vaudrait %d et %d — donc négative, donc fausse."
      % (54-106, 39-78))
