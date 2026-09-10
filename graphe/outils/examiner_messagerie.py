import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lecture import lire_notes

notes = lire_notes("donnees/messagerie.json")
msg = [n for n in notes if n.systeme_file]
print("notes du fichier :", len(notes), " · dont messagerie :", len(msg))

print("\n=== par file et par opération ===")
c = collections.Counter((n.nom_file, n.operation_file) for n in msg)
for (f, op), k in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
    role = {"send": "DÉPÔT", "process": "RETRAIT"}.get(op, op)
    print("   file %-16s %-8s %3d notes" % (f, role, k))

print("\n=== qui dépose, qui retire ===")
c2 = collections.Counter((n.operation_file, n.service) for n in msg)
for (op, s), k in sorted(c2.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
    print("   %-8s %-26s %3d" % (op, s, k))

print("\n=== une note de dépôt, en détail ===")
d = next(n for n in msg if n.operation_file == "send")
print("   service    :", d.service)
print("   copie      :", d.pod_uid)
print("   machine    :", d.machine)
print("   nom        :", d.nom)
print("   durée      : %.2f ms" % d.duree_ms)
print("   attributs de messagerie :")
for k, v in sorted(d.attributs.items()):
    if k.startswith("messaging"): print("      %-42s %s" % (k, v))

print("\n=== la note de retrait correspondante ===")
r = next(n for n in msg if n.operation_file == "process")
print("   service    :", r.service, " · copie :", (r.pod_uid or "")[:8])
print("   parent     :", r.parent_id or "(aucun)")
print("   durée      : %.2f ms" % r.duree_ms)
