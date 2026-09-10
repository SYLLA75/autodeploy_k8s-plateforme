"""Le pont traces ↔ compteurs tient-il ? Et quelle étiquette donne VRAIMENT la machine ?"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lecture import lire_notes, lire_releves

D = Path(__file__).resolve().parent.parent / "donnees/2026-09-09_1505-1514"

uids_traces, machine_selon_trace = set(), {}
for f in sorted(D.glob("*traces_*.json")):
    for n in lire_notes(f):
        if n.pod_uid:
            uids_traces.add(n.pod_uid)
            machine_selon_trace[n.pod_uid] = n.machine

info, restarts, conteneur = [], [], collections.defaultdict(set)
for f in sorted(D.glob("*metrics_*.json")):
    for r in lire_releves(f):
        if r.nom == "kube_pod_info":
            info.append(r.etiquettes)
        elif r.nom == "kube_pod_container_status_restarts_total":
            restarts.append(r.etiquettes)
        elif r.nom.startswith("container_"):
            p = r.etiquettes.get("pod")
            if p:
                conteneur[p].add(r.etiquettes.get("kubernetes_io_hostname"))

print("1) LE PONT — les identifiants des traces se retrouvent-ils dans kube_pod_info ?")
uids_info = {e.get("uid") for e in info if e.get("uid")}
trouves = uids_traces & uids_info
print(f"   pods vus dans les traces      : {len(uids_traces)}")
print(f"   pods vus dans kube_pod_info   : {len(uids_info)}")
print(f"   RETROUVÉS                     : {len(trouves)} / {len(uids_traces)}")
manquants = uids_traces - uids_info
if manquants:
    print(f"   introuvables : {len(manquants)}")

print("\n2) L'ÉTIQUETTE « node » de kube_pod_info désigne-t-elle la machine DU POD ?")
par_uid = collections.defaultdict(set)
for e in info:
    if e.get("uid"):
        par_uid[e["uid"]].add(e.get("node"))
instables = {u: v for u, v in par_uid.items() if len(v) > 1}
print(f"   valeurs distinctes de « node » sur kube_pod_info : {len({e.get('node') for e in info})}")
print(f"   pods dont le « node » change au cours de la plage : {len(instables)}")

print("\n3) CONFRONTATION avec ce que disent les traces (k8s.node.name)")
ok = faux = absent = 0
exemples = []
for u in sorted(trouves):
    selon_info = par_uid[u]
    selon_trace = machine_selon_trace.get(u)
    if not selon_trace:
        absent += 1
    elif selon_trace in selon_info:
        ok += 1
    else:
        faux += 1
        if len(exemples) < 5:
            exemples.append((u[:8], selon_trace, sorted(x for x in selon_info if x)))
print(f"   d'accord   : {ok}")
print(f"   en DÉSACCORD : {faux}")
for u, t, i in exemples:
    print(f"      {u}…  trace dit {t}   ·   kube_pod_info dit {i}")

print("\n4) ET L'ÉTIQUETTE « kubernetes_io_hostname » des compteurs container_ ?")
nom_par_uid = {e["uid"]: e.get("pod") for e in info if e.get("uid")}
ok2 = faux2 = 0
ex2 = []
for u in sorted(trouves):
    nom = nom_par_uid.get(u)
    t = machine_selon_trace.get(u)
    h = conteneur.get(nom, set())
    if not (nom and t and h):
        continue
    if t in h: ok2 += 1
    else:
        faux2 += 1
        if len(ex2) < 5: ex2.append((nom, t, sorted(x for x in h if x)))
print(f"   d'accord     : {ok2}")
print(f"   en DÉSACCORD : {faux2}")
for nom, t, h in ex2:
    print(f"      {nom}  trace dit {t}   ·   container_ dit {h}")
