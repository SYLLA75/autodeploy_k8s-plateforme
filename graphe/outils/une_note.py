"""Montrer une vraie note, en clair."""
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"
for f in sorted(D.glob("*traces_*.json")):
    for n in lire_notes(f):
        if n.nom_file == "food_delivery" and n.operation_file == "process":
            h = lambda ns: datetime.fromtimestamp(ns/1e9, timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            print("UNE NOTE, TELLE QU'ELLE EST DANS TES DONNÉES")
            print(f"  qui a agi        : {n.service}")
            print(f"  sur quelle machine : {n.machine}")
            print(f"  ce qu'il a fait  : {n.nom}")
            print(f"  a commencé à     : {h(n.debut_ns)}")
            print(f"  a fini à         : {h(n.fin_ns)}")
            print(f"  a donc duré      : {n.duree_ms:.1f} millisecondes")
            print(f"  file concernée   : {n.nom_file}")
            sys.exit(0)
