#!/usr/bin/env python3
"""
Faux kubectl pour les essais de la garde : il rejoue les sorties RÉELLES du
master (donnees/modele.json, relevées le 1/10 au soir) en y changeant ce que
le cas demande (FAUX_SCENARIO, un fichier JSON). Il note chaque appel dans
FAUX_LOG_KUBECTL. Il ne joint rien : aucun réseau, aucun cluster.

Le scénario (toutes les clés sont facultatives ; défaut = plateforme saine en
campagne, Locust à 25 voyageurs) :
  pend            true : chaque appel pend (le processus EST un sommeil)
  tout_erreur     true : chaque appel rend « Error from server » et le code 1
  prom            { nom : nombre | "erreur" | "vide" | "pend" | [ [étiquettes, valeur], … ] }
                  noms : ceux de garde_sonde.py (depot, tas_pret, …)
  locust          "absent" | "erreur" | { voyageurs, etat, req_s, echecs_pct: {nom: %},
                  recherche_ms, reservation_echec (0..1), bloque: [nom, …],
                  req_s_10s (la moyenne de 10 s de Locust seule, les totaux suivent req_s) }
  noeuds          { nom : { statut, ip } }      (changements sur le modèle)
  pods            { préfixe : { pret, redemarrages, phase } }
  chaos           [ { kind, name, namespace, creation, duration } ]   (en plus du réglage)
  sans_140        [ réplique, … ]  : répliques sans le retard de base
  restes          [ source, … ]    : retard encore posé par un objet disparu (sur une réplique)
  passerelle      "1/1"
  leader          "tsdb-mysql-0" | null
"""
import json
import os
import sys
import time
import urllib.parse

ICI = os.path.dirname(os.path.abspath(__file__))
MODELE = json.load(open(os.path.join(ICI, "donnees", "modele.json"), encoding="utf-8"))
args = sys.argv[1:]
try:
    with open(os.environ["FAUX_SCENARIO"], encoding="utf-8") as f:
        SC = json.load(f)
except (KeyError, OSError, ValueError):
    SC = {}

if os.environ.get("FAUX_LOG_KUBECTL"):
    with open(os.environ["FAUX_LOG_KUBECTL"], "a", encoding="utf-8") as f:
        f.write(" ".join(args) + "\n")

if SC.get("pend"):
    os.execvp("sleep", ["sleep", "100000"])
if SC.get("tout_erreur"):
    print("Error from server (InternalError): faux serveur en panne", file=sys.stderr)
    sys.exit(1)

T0 = float(os.environ.get("FAUX_T0", "0") or 0)
# L'horloge de la garde (GARDE_MAINTENANT, passée par le faux ssh et la sonde) :
# les totaux de Locust avancent au rythme des minutes factices.
if os.environ.get("GARDE_MAINTENANT"):
    from datetime import datetime, timezone
    MAINTENANT = datetime.strptime(os.environ["GARDE_MAINTENANT"], "%Y-%m-%dT%H:%M:%SZ") \
        .replace(tzinfo=timezone.utc).timestamp()
else:
    MAINTENANT = time.time()
ECHEANCE = "2026-10-01T12:00:00Z"
REPLIQUES = ["ts-delivery-service-79c46f4f45-44v2p", "ts-delivery-service-79c46f4f45-mmndx",
             "ts-delivery-service-79c46f4f45-r5pwb"]


def sortir(texte, code=0, err=""):
    sys.stdout.write(texte)
    if err:
        sys.stderr.write(err)
    sys.exit(code)


# ------------------------------------------------------------------ Prometheus
SAIN = {"depot": 3.3, "tas_pret": 0, "tas_non_acquitte": 0, "retrait": 3.3, "consommateurs": 3,
        "cpu_commandes": 0.40, "reseau_commandes": 4.4e6, "taille_prometheus": 7.7e9,
        "historique_prometheus": 5.8 * 86400}
SERIES = {
    "memoire_pods": [[{"namespace": "observability", "pod": "jaeger-7d9f8c-abcde"}, 1.14e9],
                     [{"namespace": "train-ticket", "pod": "tsdb-mysql-0"}, 8.3e8],
                     [{"namespace": "train-ticket", "pod": "ts-order-service-5c7d8-xyz12"}, 5.5e8]],
    "noeuds_prets": [[{"node": n}, 1] for n in ("master", "workers0", "workers1", "workers2",
                                                 "workers3", "workers4", "workers5", "workers6")],
    "disque_utilise_pct": [[{"node": n}, 33.0] for n in ("master", "workers0", "workers1", "workers2",
                                                         "workers3", "workers4", "workers5", "workers6")],
    "memoire_noeuds": [[{"node": n}, 2.5 * 2**30] for n in ("master", "workers0", "workers1", "workers2",
                                                            "workers3", "workers4", "workers5", "workers6")],
    "redemarrages": [[{"namespace": "train-ticket", "pod": "ts-auth-service-d57b979b6-6rhnt"}, 63],
                     [{"namespace": "observability", "pod": "otel-agent-opentelemetry-collector-agent-hkcnm"}, 162],
                     [{"namespace": "observability", "pod": "otel-gateway-opentelemetry-collector-6b8-k2"}, 0],
                     [{"namespace": "observability", "pod": "jaeger-7d9f8c-abcde"}, 27],
                     [{"namespace": "loadgen", "pod": "locust-6f7b-q8x"}, 0]],
    "pods_cles_prets": [[{"pod": f"ts-{s}-service-1-a"}, 1] for s in ("order", "travel", "seat", "preserve", "security")],
}


def nom_requete(q):
    if "delta(" in q:
        return "retrait"
    for cle, nom in (("messages_published_total", "depot"), ("messages_ready", "tas_pret"),
                     ("messages_unacked", "tas_non_acquitte"), ("queue_consumers", "consommateurs"),
                     ("container_cpu_usage", "cpu_commandes"), ("network_receive", "reseau_commandes"),
                     ("memory_working_set", "memoire_pods"), ("kube_node_status_condition", "noeuds_prets"),
                     ("filesystem_avail", "disque_utilise_pct"), ("MemAvailable", "memoire_noeuds"),
                     ("restarts_total", "redemarrages"), ("kube_pod_status_ready", "pods_cles_prets"),
                     ("tsdb_storage_blocks", "taille_prometheus"),
                     ("tsdb_lowest_timestamp", "historique_prometheus")):
        if cle in q:
            return nom
    return None


def prometheus(chemin):
    q = urllib.parse.unquote(chemin.split("query=", 1)[1])
    nom = nom_requete(q)
    if nom is None or q.count("(") != q.count(")"):
        sortir("", 1, MODELE["prom_erreur_err"])
    v = (SC.get("prom") or {}).get(nom, SAIN.get(nom, SERIES.get(nom)))
    if v == "erreur":
        sortir("", 1, MODELE["prom_erreur_err"])
    if v == "pend":
        os.execvp("sleep", ["sleep", "100000"])
    if v == "illisible":
        sortir("<html>proxy</html>")
    t = round(time.time(), 3)
    if v == "vide":
        res = []
    elif isinstance(v, list):
        res = [{"metric": dict(e, __name__="x", job="kubernetes-service-endpoints"), "value": [t, str(x)]}
               for e, x in v]
    else:
        res = [{"metric": {}, "value": [t, str(v)]}]
    sortir(json.dumps({"status": "success", "data": {"resultType": "vector", "result": res}}))


# ------------------------------------------------------------------ Locust
PARTS = {"00 code de vérification": 0.03, "01 connexion": 0.03, "10 chercher un train": 0.20,
         "20 mes contacts": 0.15, "30 réserver un billet": 0.15, "40 commander un repas": 0.37,
         "60 déclencher un courriel": 0.07}


def locust():
    lo = SC.get("locust", {})
    if lo == "absent":
        sortir("", 1, MODELE["locust_absent_err"])
    if lo == "erreur":
        sortir("", 1, "Error from server (InternalError): an error on the server (\"\") has prevented the request\n")
    modele = MODELE["locust_stats"]
    voyageurs, req_s = lo.get("voyageurs", 25), lo.get("req_s", 7.5)
    ecoule = max(1.0, MAINTENANT - T0) if T0 else 600.0
    stats, total_n, total_e = [], 0, 0
    for s in modele["stats"]:
        if s["name"] == "Aggregated":
            continue
        s = dict(s)
        nom = s["name"]
        r = req_s * PARTS.get(nom, 0.0)
        echec = (lo.get("echecs_pct") or {}).get(nom, 0.0) / 100.0
        if nom == "30 réserver un billet":
            echec = lo.get("reservation_echec", echec)
        # « bloque » : ce parcours n'avance plus depuis la minute précédente
        # (des voyageurs coincés : ni réussite, ni échec).
        n = int(r * (ecoule - (60 if nom in lo.get("bloque", []) else 0))) + 50
        s.update(num_requests=n, num_failures=int(n * echec), current_rps=round(r, 2),
                 current_fail_per_sec=round(r * echec, 2), total_rps=round(r, 2))
        if nom == "10 chercher un train" and "recherche_ms" in lo:
            s.update(avg_response_time=float(lo["recherche_ms"]), median_response_time=lo["recherche_ms"])
        stats.append(s)
        total_n += n
        total_e += s["num_failures"]
    agg = dict(next(s for s in modele["stats"] if s["name"] == "Aggregated"))
    rps_10s = lo.get("req_s_10s", req_s)
    agg.update(num_requests=total_n, num_failures=total_e, current_rps=rps_10s)
    stats.append(agg)
    sortir(json.dumps(dict(modele, stats=stats, state=lo.get("etat", "running"), user_count=voyageurs,
                           total_rps=rps_10s, fail_ratio=total_e / total_n if total_n else 0.0)))


# ------------------------------------------------------------------ nœuds, pods, chaos
def noeuds():
    lignes = []
    for l in MODELE["noeuds"].splitlines():
        c = l.split()
        ch = (SC.get("noeuds") or {}).get(c[0], {})
        c[1] = ch.get("statut", c[1])
        c[5] = ch.get("ip", c[5])
        lignes.append("   ".join(c))
    sortir("\n".join(lignes) + "\n")


def pods():
    lignes = [l.split() for l in MODELE["pods"].splitlines()]
    noeud = "workers0"
    for nom in ([f"ts-{s}-service-1-a" for s in ("order", "travel", "seat", "preserve", "security")]
                + REPLIQUES + ["tsdb-mysql-0", "tsdb-mysql-1", "tsdb-mysql-2"]):
        lignes.append([nom, noeud, "Running", "true", "0", "<none>"])
    for c in lignes:
        for prefixe, ch in (SC.get("pods") or {}).items():
            if c[0].startswith(prefixe):
                if "pret" in ch:
                    c[3] = "true" if ch["pret"] else "false"
                if "redemarrages" in ch:
                    c[4] = str(ch["redemarrages"])
                if "phase" in ch:
                    c[2] = ch["phase"]
    sortir("\n".join("   ".join(c) for c in lignes) + "\n")


def chaos():
    d = json.loads(json.dumps(MODELE["chaos"]))
    for o in SC.get("chaos", []):
        d["items"].append({"apiVersion": "chaos-mesh.org/v1alpha1", "kind": o["kind"],
                           "metadata": {"name": o["name"], "namespace": o.get("namespace", "train-ticket"),
                                        "creationTimestamp": o["creation"]},
                           "spec": {"action": "delay", "duration": o.get("duration")},
                           "status": {"conditions": [{"type": "AllInjected", "status": "True"}],
                                      "experiment": {"desiredPhase": o.get("phase", "Run")}}})
    sortir(json.dumps(d))


def podnetworkchaos():
    d = json.loads(json.dumps(MODELE["podnetworkchaos"]))
    for it in d["items"]:
        nom = it["metadata"]["name"]
        if nom in SC.get("sans_140", []):
            it["spec"] = {}
        if nom == REPLIQUES[0]:
            for s in SC.get("restes", []):
                it["spec"].setdefault("tcs", []).append(
                    {"type": "netem", "source": s, "delay": {"latency": "300ms"}})
    sortir(json.dumps(d))


# ------------------------------------------------------------------ aiguillage
texte = " ".join(args)
if "get --raw" in texte and "prom-prometheus-server" in texte:
    prometheus(args[args.index("--raw") + 1])
if "get --raw" in texte and "locust:8089" in texte:
    locust()
if args[:2] == ["get", "nodes"]:
    noeuds()
if args[:2] == ["get", "pods"] and "app=tsdb-mysql" in texte:
    leader = SC.get("leader", "tsdb-mysql-0")
    sortir("".join(f"tsdb-mysql-{i}   {'leader' if f'tsdb-mysql-{i}' == leader else 'follower'}   10.233.0.{10 + i}\n"
                   for i in range(3)))
if args[:2] == ["get", "endpoints"]:
    leader = SC.get("leader", "tsdb-mysql-0")
    sortir(f"10.233.0.{10 + int(leader[-1])}" if leader else "")
if args[:2] == ["get", "pods"]:
    pods()
if args[:2] == ["get", "networkchaos,stresschaos,podchaos,iochaos"]:
    chaos()
if args[:2] == ["get", "podnetworkchaos"]:
    podnetworkchaos()
if args[:3] == ["get", "deploy", "otel-gateway-opentelemetry-collector"]:
    sortir(SC.get("passerelle", "1/1"))
sortir("", 1, f"faux kubectl : appel inconnu : {texte}\n")
