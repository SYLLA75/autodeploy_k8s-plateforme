#!/usr/bin/env python3
# ==============================================================================
#  apps/garde_sonde.py — une photo de la plateforme, prise sur le master
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Il lit, en une fois, tout ce que la garde (garde.py, sur vms0) doit savoir
#  pour juger une minute : Prometheus (file, CPU, mémoire, nœuds, disques,
#  redémarrages), Locust, les nœuds, les pods de train-ticket, les objets de
#  Chaos Mesh, l'état des pannes, le leader MySQL, la passerelle de collecte,
#  le réglage des 140 ms. Il imprime UN SEUL objet JSON sur sa sortie, et rien
#  d'autre (les avertissements vont sur la sortie d'erreur).
#
#  POURQUOI SUR LE MASTER, EN UN SEUL APPEL
#
#  kubectl ne tourne que sur le master. La garde ouvre donc UNE connexion ssh
#  par minute, qui lance ce script, au lieu de vingt connexions : des centaines
#  de connexions ont peut-être bloqué l'accès ssh du site en septembre (N8).
#
#  CE QU'IL NE FAIT JAMAIS
#
#  Aucun geste. Il ne lance que des lectures : « kubectl get », la lecture de
#  fichiers, « consommateur.sh verifier » et « donnees.sh etat --brut » (deux
#  lectures, sans journal). Une seule écriture : l'heure UTC dans
#  ~/garde.battement, pour qu'une vérification extérieure (K1.6c) sache que la
#  garde passe encore.
#
#  CHAQUE MESURE EST INDÉPENDANTE
#
#  Une mesure qui échoue ou qui pend rend {"erreur": "..."} pour ELLE SEULE.
#  Chaque commande a son propre plafond (kubectl --request-timeout=20s, et un
#  plafond du processus), et la sonde entière tient en 45 s au pire : les
#  lectures partent en parallèle (un petit groupe de fils), et aucune ne peut
#  dépasser l'échéance commune. Un processus qui pend est tué avec tout son
#  groupe (un script et ses kubectl).
#
#  LE RETRAIT DE LA FILE
#
#  Prometheus n'a pas le compteur des messages retirés pour UNE file
#  (rabbitmq_queue_messages_delivered_ack_total n'existe pas ici, R2). On le
#  déduit : sur les 2 mêmes minutes, ce qui est sorti de la file = ce qui y est
#  entré − ce dont le tas a grossi. Avec le tas = prêts + non acquittés :
#      retrait = rate(dépôt[2m]) − (delta(prêts[2m]) + delta(non acquittés[2m])) / 120
#  Exemple : 3,3 msg/s déposés, tas passé de 0 à 24 en 2 min → 3,3 − 0,2 = 3,1.
#
#  Usage (sur le master ; lu en entier avant de s'exécuter, comme tout Python) :
#      python3 ~/autodeploy/apps/garde_sonde.py [--commandes] | python3 -m json.tool
#      --commandes   lit aussi le nombre de commandes en table (donnees.sh etat --brut,
#                    environ 5 s, un kubectl exec dans MySQL) ; garde.py le demande
#                    une minute sur dix
#      --racine <d>  le dépôt déployé (défaut : le dossier au-dessus de apps/)
#  Variable reconnue :
#      GARDE_KUBECTL  (défaut: kubectl)  le kubectl à lancer (essais : un faux kubectl)
# ==============================================================================
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

# ------------------------------------------------------------------------------
# Réglages (les noms viennent des scripts du dépôt)
# ------------------------------------------------------------------------------
ECHEANCE_S = 36          # toute lecture est finie (ou abandonnée) avant 36 s ; sortie avant 38 s,
                         # ce qui laisse 12 s à ssh et au démarrage de python sous le plafond de
                         # 50 s de garde.py (ConnectTimeout=15 n'est atteint que si l'hôte est muet)
PLAFOND_KUBECTL_S = 25   # kubectl a --request-timeout=20s ; 5 s de marge pour son démarrage
PLAFOND_VERIFIER_S = 40  # consommateur.sh verifier : plusieurs kubectl à la suite
PLAFOND_DONNEES_S = 35   # donnees.sh etat --brut : 4 requêtes SQL par kubectl exec
FILS = 10                # lectures en parallèle (une vingtaine en tout)

NS_APP = "train-ticket"
REGLAGE = "consommateur-temps-de-service"   # l'objet du réglage de base (consommateur.sh)
PASSERELLE = "otel-gateway-opentelemetry-collector"   # collecte.sh, GATEWAY
NS_OBS = "observability"
LEADER_SVC = "tsdb-mysql-leader"            # panne.sh, PANNE_BASE_SVC_LEADER
FILE = "food_delivery"
PROM = "/api/v1/namespaces/observability/services/prom-prometheus-server:80/proxy/api/v1/query?query="
LOCUST = "/api/v1/namespaces/loadgen/services/locust:8089/proxy/stats/requests"
KUBECTL = os.environ.get("GARDE_KUBECTL", "kubectl")

# Les requêtes Prometheus. « somme » : une seule valeur attendue (une réponse
# vide est une erreur) ; « series » : une valeur par pod ou par nœud.
F = f'queue="{FILE}"'
REQUETES = {
    "depot": ("somme", f"sum(rate(rabbitmq_queue_messages_published_total{{{F}}}[2m]))"),
    "tas_pret": ("somme", f"sum(rabbitmq_queue_messages_ready{{{F}}})"),
    "tas_non_acquitte": ("somme", f"sum(rabbitmq_queue_messages_unacked{{{F}}})"),
    "retrait": ("somme", f"sum(rate(rabbitmq_queue_messages_published_total{{{F}}}[2m]))"
                         f" - (sum(delta(rabbitmq_queue_messages_ready{{{F}}}[2m]))"
                         f" + sum(delta(rabbitmq_queue_messages_unacked{{{F}}}[2m]))) / 120"),
    "consommateurs": ("somme", f"sum(rabbitmq_queue_consumers{{{F}}})"),
    "cpu_commandes": ("somme", 'sum(rate(container_cpu_usage_seconds_total{namespace="train-ticket",'
                               'pod=~"ts-order-service-.*",container!=""}[2m]))'),
    "reseau_commandes": ("somme", 'sum(rate(container_network_receive_bytes_total{namespace="train-ticket",'
                                  'pod=~"ts-order-service-.*"}[2m]))'),
    "memoire_pods": ("series", 'sum by (namespace, pod) (container_memory_working_set_bytes{'
                               'namespace=~"observability|train-ticket",'
                               'pod=~"jaeger.*|tsdb-mysql-0|ts-order-service-.*",container!=""})'),
    "noeuds_prets": ("series", 'kube_node_status_condition{condition="Ready",status="true"}'),
    "disque_utilise_pct": ("series", '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"}'
                                     ' / node_filesystem_size_bytes{mountpoint="/"})'),
    "memoire_noeuds": ("series", "node_memory_MemAvailable_bytes"),
    "redemarrages": ("series", 'sum by (namespace, pod) (kube_pod_container_status_restarts_total{'
                               'namespace=~"train-ticket|loadgen|observability"})'),
    "pods_cles_prets": ("series", 'kube_pod_status_ready{namespace="train-ticket",condition="true",'
                                  'pod=~"ts-(order|travel|seat|preserve|security)-service-.*"}'),
    "taille_prometheus": ("somme", "sum(prometheus_tsdb_storage_blocks_bytes)"),
    # Au plafond de taille (O10), Prometheus efface les plus vieux blocs : ce qui
    # compte est la durée qu'il garde encore, en secondes.
    "historique_prometheus": ("somme", "time() - min(prometheus_tsdb_lowest_timestamp_seconds)"),
}

T0 = time.monotonic()
ECHEANCE = T0 + ECHEANCE_S


def avertir(texte):
    print(f"garde_sonde : {texte}", file=sys.stderr)


# ------------------------------------------------------------------------------
# Lancer une commande, bornée, sans jamais pendre
# ------------------------------------------------------------------------------
# start_new_session : la commande a son propre groupe de processus. Si elle
# dépasse son plafond, on tue TOUT le groupe (un script bash et les kubectl
# qu'il a lancés) ; sinon un petit-fils garderait le tube ouvert et la lecture
# de sa sortie attendrait sans fin.
def lancer(cmd, plafond, env=None):
    reste = min(plafond, ECHEANCE - time.monotonic())
    if reste < 1:
        return {"erreur": "non lancée : échéance de la sonde atteinte"}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, text=True, errors="replace",
                             start_new_session=True, env=env)
    except OSError as e:
        return {"erreur": f"lancement impossible : {e}"}
    try:
        out, err = p.communicate(timeout=reste)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.communicate(timeout=2)
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return {"erreur": f"délai dépassé ({reste:.0f} s)"}
    return {"code": p.returncode, "out": out, "err": err}


def kubectl(*args):
    return lancer([KUBECTL, *args, "--request-timeout=20s"], PLAFOND_KUBECTL_S)


def echec_kubectl(r):
    """Le texte d'erreur d'un kubectl, ou None s'il a réussi."""
    if "erreur" in r:
        return r["erreur"]
    if r["code"] != 0:
        return (r["err"].strip().splitlines() or [f"code {r['code']}"])[-1][:300]
    return None


# ------------------------------------------------------------------------------
# Les lectures, une fonction par mesure ; chacune rend un dict
# ------------------------------------------------------------------------------
def prometheus(nom):
    sorte, requete = REQUETES[nom]
    r = kubectl("get", "--raw", PROM + urllib.parse.quote(requete, safe=""))
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    try:
        d = json.loads(r["out"])
        if d.get("status") != "success":
            return {"erreur": f"Prometheus : {d.get('error', d.get('status'))}"[:300]}
        res = d["data"]["result"]
    except (ValueError, KeyError, TypeError) as e:
        return {"erreur": f"réponse illisible : {e}"[:300]}
    if sorte == "somme":
        if not res:
            return {"erreur": "réponse vide (aucune série)"}
        return {"valeur": float(res[0]["value"][1])}
    garder = ("namespace", "pod", "node", "instance")
    return {"series": [{"etiquettes": {k: v for k, v in x["metric"].items() if k in garder},
                        "valeur": float(x["value"][1])} for x in res]}


def locust():
    r = kubectl("get", "--raw", LOCUST)
    e = echec_kubectl(r)
    if e:
        # Locust à 0 réplique : le service n'a plus de destination. Ce n'est
        # pas une panne de mesure, c'est un état (normal hors campagne).
        if "no endpoints available" in e:
            return {"absent": True, "detail": e}
        return {"erreur": e}
    try:
        d = json.loads(r["out"])
        parcours = {}
        for s in d["stats"]:
            parcours[s["name"]] = {
                "n": s["num_requests"], "echecs": s["num_failures"],
                "mediane_ms": s.get("median_response_time"), "moyenne_ms": s.get("avg_response_time"),
                "req_s": s.get("current_rps"), "echecs_s": s.get("current_fail_per_sec")}
        return {"absent": False, "etat": d["state"], "voyageurs": d.get("user_count"),
                "req_s": d.get("total_rps"), "taux_echec": d.get("fail_ratio"), "parcours": parcours}
    except (ValueError, KeyError, TypeError) as e:
        return {"erreur": f"réponse de Locust illisible : {e}"[:300]}


def noeuds():
    r = kubectl("get", "nodes", "-o", "wide", "--no-headers")
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    res = {}
    for ligne in r["out"].splitlines():
        c = ligne.split()
        if len(c) >= 6:
            res[c[0]] = {"pret": c[1].split(",")[0] == "Ready", "statut": c[1], "ip": c[5]}
    if not res:
        return {"erreur": "aucun nœud lu"}
    return {"noeuds": res}


def pods():
    r = kubectl("get", "pods", "-n", NS_APP, "--no-headers", "-o",
                "custom-columns=:metadata.name,:spec.nodeName,:status.phase,"
                ":status.containerStatuses[*].ready,:status.containerStatuses[*].restartCount,"
                ":metadata.deletionTimestamp")
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    res = []
    for ligne in r["out"].splitlines():
        c = ligne.split()
        if len(c) < 6:
            continue
        prets = c[3].split(",")
        try:
            redem = sum(int(x) for x in c[4].split(",") if x.isdigit())
        except ValueError:
            redem = None
        res.append({"nom": c[0], "noeud": c[1], "phase": c[2],
                    "pret": c[3] != "<none>" and all(x == "true" for x in prets),
                    "redemarrages": redem, "en_arret": c[5] != "<none>"})
    return {"pods": res}


def duree(spec):
    return spec.get("duration") if isinstance(spec, dict) else None


def chaos():
    r = kubectl("get", "networkchaos,stresschaos,podchaos,iochaos", "-A", "-o", "json")
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    try:
        items = json.loads(r["out"])["items"]
    except (ValueError, KeyError) as e:
        return {"erreur": f"réponse illisible : {e}"[:300]}
    objets, base = [], {"present": False}
    for it in items:
        m, st = it.get("metadata", {}), it.get("status") or {}
        conds = {c.get("type"): c.get("status") for c in st.get("conditions") or []}
        # L'objet de base (140 ms, sans durée, posé par consommateur.sh) n'est pas une panne.
        if m.get("namespace") == NS_APP and m.get("name") == REGLAGE:
            recs = (st.get("experiment") or {}).get("containerRecords") or []
            base = {"present": True, "latence": ((it.get("spec") or {}).get("delay") or {}).get("latency"),
                    "conditions": conds, "cibles": [x.get("id") for x in recs]}
            continue
        objets.append({"type": it.get("kind"), "nom": m.get("name"), "espace": m.get("namespace"),
                       "creation": m.get("creationTimestamp"), "duree": duree(it.get("spec")),
                       "phase": (st.get("experiment") or {}).get("desiredPhase"), "conditions": conds})
    return {"objets": objets, "base": base}


def podnetworkchaos():
    """Le retard RÉELLEMENT posé sur chaque pod, et par quel objet (source)."""
    r = kubectl("get", "podnetworkchaos", "-n", NS_APP, "-o", "json")
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    try:
        items = json.loads(r["out"])["items"]
    except (ValueError, KeyError) as e:
        return {"erreur": f"réponse illisible : {e}"[:300]}
    res = {}
    for it in items:
        spec = it.get("spec") or {}
        retards = [{"source": t.get("source"), "latence": (t.get("delay") or {}).get("latency")}
                   for t in spec.get("tcs") or []]
        sources = sorted({x.get("source") for cle in ("tcs", "ipsets", "iptables")
                          for x in spec.get(cle) or [] if x.get("source")})
        if retards or sources:
            res[it["metadata"]["name"]] = {"retards": retards, "sources": sources}
    return {"pods": res}


def passerelle():
    r = kubectl("get", "deploy", PASSERELLE, "-n", NS_OBS, "-o",
                "jsonpath={.spec.replicas}/{.status.readyReplicas}")
    e = echec_kubectl(r)
    if e:
        return {"erreur": e}
    voulues, _, pretes = r["out"].strip().partition("/")
    try:
        return {"voulues": int(voulues or 0), "pretes": int(pretes or 0)}
    except ValueError:
        return {"erreur": f"réponse illisible : {r['out'][:80]}"}


def leader():
    """Comme panne.sh base_leader, pour toutes les copies : le pod qui porte
    role=leader ET dont l'adresse est derrière le service du leader."""
    r1 = kubectl("get", "pods", "-n", NS_APP, "-l", "app=tsdb-mysql", "--no-headers", "-o",
                 "custom-columns=:metadata.name,:metadata.labels.role,:status.podIP")
    e = echec_kubectl(r1)
    if e:
        return {"erreur": e}
    r2 = kubectl("get", "endpoints", LEADER_SVC, "-n", NS_APP, "-o",
                 "jsonpath={.subsets[*].addresses[*].ip}")
    e = echec_kubectl(r2)
    if e:
        return {"erreur": e}
    copies = {}
    for ligne in r1["out"].splitlines():
        c = ligne.split()
        if len(c) >= 3:
            copies[c[0]] = {"role": c[1], "ip": c[2]}
    destinations = r2["out"].split()
    elus = [n for n, c in copies.items() if c["role"] == "leader" and c["ip"] in destinations]
    return {"leader": elus[0] if len(elus) == 1 else None, "copies": copies,
            "destinations": destinations}


def script_lecture(racine, script, args, plafond):
    env = dict(os.environ, JOURNAL_OFF="1")
    r = lancer(["bash", os.path.join(racine, "apps", script), *args], plafond, env=env)
    if "erreur" in r:
        return r
    lignes = [l for l in (r["out"] + r["err"]).splitlines() if l.strip()]
    return {"code": r["code"], "lignes": lignes[-3:], "sortie": r["out"].strip()[-400:]}


def verifier(racine):
    # 0 OK, 1 manque, 3 panne en cours qui remplace le réglage ; l'ancienne
    # version répond « Usage » avec le code 2 : garde.py en fait « non vérifiable ».
    return script_lecture(racine, "consommateur.sh", ["verifier"], PLAFOND_VERIFIER_S)


def commandes(racine):
    r = script_lecture(racine, "donnees.sh", ["etat", "--brut"], PLAFOND_DONNEES_S)
    if "erreur" in r:
        return r
    ligne = r["sortie"].splitlines()[-1] if r["sortie"] else ""
    tables = dict(x.split("=", 1) for x in ligne.split() if "=" in x)
    if r["code"] != 0 or not tables.get("orders", "").isdigit():
        return {"erreur": f"illisible (code {r['code']}) : {ligne[:120]}"}
    return {"tables": {k: (int(v) if v.isdigit() else None) for k, v in tables.items()}}


# ------------------------------------------------------------------------------
# Les fichiers du master (lecture seule)
# ------------------------------------------------------------------------------
def dernieres_lignes(chemin, n):
    """Les n dernières lignes non vides et hors commentaire d'un registre."""
    with open(chemin, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 8192))
        texte = f.read().decode("utf-8", "replace")
    return [l for l in texte.splitlines() if l.strip() and not l.startswith("#")][-n:]


def fichiers(racine):
    j = os.path.join(racine, "journaux")
    res = {}
    # panne.etat : présent seulement pendant une injection (panne.sh l'écrit
    # avant de poser la panne, l'efface après le retrait). Lignes CLE='valeur'.
    try:
        with open(os.path.join(j, "panne.etat"), encoding="utf-8", errors="replace") as f:
            contenu = {}
            for l in f:
                cle, sep, val = l.rstrip("\n").partition("=")
                if sep:
                    contenu[cle] = val.strip("'")
        res["panne_etat"] = {"present": True, "contenu": contenu}
    except FileNotFoundError:
        res["panne_etat"] = {"present": False}
    except OSError as e:
        res["panne_etat"] = {"erreur": str(e)}
    # paliers.tsv : instant_demande, instant_effectif, observés, DEMANDÉS, rythme, cible, origine.
    # Une panne de charge (plus de voyageurs) y écrit aussi sa demande (origine « panne »).
    # « historique » : les 50 dernières lignes (instant_demande, demandés). garde.py y
    # cherche le palier d'AVANT le début d'une panne (seuil d'effondrement, K1.6b) :
    # pendant une panne de charge, la dernière ligne est la demande de la panne.
    try:
        l = dernieres_lignes(os.path.join(j, "paliers.tsv"), 50)
        if not l:
            res["palier"] = {"erreur": "registre vide"}
        else:
            c = l[-1].split("\t")
            res["palier"] = {"demande": c[0], "effectif": c[1] if len(c) > 1 else "",
                             "observes": c[2] if len(c) > 2 else "",
                             "demandes": int(c[3]) if len(c) > 3 and c[3].isdigit() else None,
                             "origine": c[6] if len(c) > 6 else "",
                             "historique": [[x[0], int(x[3]) if x[3].isdigit() else None]
                                            for x in (y.split("\t") for y in l) if len(x) > 3]}
    except OSError as e:
        res["palier"] = {"erreur": str(e)}
    # pannes.tsv : le dernier retrait donne l'heure de fin de la dernière panne.
    # donnees.tsv : les 3 dernières actions (une purge suivie d'un « dimensionner »
    # reste visible).
    for nom, fichier, n in (("pannes", "pannes.tsv", 2), ("purges", "donnees.tsv", 3)):
        try:
            res[nom] = {"lignes": [x.split("\t") for x in dernieres_lignes(os.path.join(j, fichier), n)]}
        except FileNotFoundError:
            res[nom] = {"lignes": []}
        except OSError as e:
            res[nom] = {"erreur": str(e)}
    return res


def gestes_en_cours():
    """Les scripts du dépôt en train d'agir sur le master (ex. « panne.sh retirer »).
    Un minuteur « bash -c 'sleep …; panne.sh retirer' » n'en est pas un : il attend."""
    res = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if len(argv) < 2 or argv[1] == "-c":
            continue
        for i, a in enumerate(argv[:2]):
            base = os.path.basename(a)
            if base in ("panne.sh", "loadgen.sh", "donnees.sh", "consommateur.sh", "collecte.sh"):
                action = argv[i + 1] if len(argv) > i + 1 else ""
                res.append(f"{base} {action}".strip())
                break
    return sorted(res)


# ------------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--racine" in args:
        racine = args[args.index("--racine") + 1]
    avec_commandes = "--commandes" in args

    debut = datetime.now(timezone.utc)
    # La seule écriture : le battement, lu par la vérification extérieure (K1.6c).
    try:
        with open(os.path.expanduser("~/garde.battement"), "w", encoding="utf-8") as f:
            f.write(debut.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    except OSError as e:
        avertir(f"battement non écrit : {e}")

    travaux = {f"prom_{nom}": (prometheus, (nom,)) for nom in REQUETES}
    travaux.update({
        "locust": (locust, ()), "noeuds": (noeuds, ()), "pods": (pods, ()),
        "chaos": (chaos, ()), "podnetworkchaos": (podnetworkchaos, ()),
        "passerelle": (passerelle, ()), "leader": (leader, ()),
        "verifier": (verifier, (racine,)),
    })
    if avec_commandes:
        travaux["commandes"] = (commandes, (racine,))

    res = {"version": 1, "debut": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "epoch": round(debut.timestamp(), 3), "racine": racine}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=FILS)
    futurs = {pool.submit(f, *a): cle for cle, (f, a) in travaux.items()}
    # Les fichiers et les processus se lisent ici, pendant que kubectl travaille.
    try:
        res.update(fichiers(racine))
    except Exception as e:   # une erreur imprévue ne doit pas coûter tout le reste
        # garde.py lit chaque partie par son nom : l'erreur est mise dans chacune.
        erreur = {"erreur": f"fichiers du master : {type(e).__name__}: {e}"[:300]}
        for cle in ("panne_etat", "palier", "pannes", "purges"):
            res[cle] = dict(erreur)
    try:
        res["gestes_en_cours"] = gestes_en_cours()
    except Exception as e:
        res["gestes_en_cours"] = {"erreur": f"{type(e).__name__}: {e}"}

    finis, _ = concurrent.futures.wait(futurs, timeout=max(0.0, ECHEANCE + 1.5 - time.monotonic()))
    prom = {}
    for futur, cle in futurs.items():
        if futur in finis:
            try:
                valeur = futur.result()
            except Exception as e:
                valeur = {"erreur": f"{type(e).__name__}: {e}"[:300]}
        else:
            valeur = {"erreur": "délai global de la sonde dépassé"}
        if cle.startswith("prom_"):
            prom[cle[5:]] = valeur
        else:
            res[cle] = valeur
    res["prom"] = prom
    res["duree_s"] = round(time.monotonic() - T0, 2)
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    # Sans attendre les fils : ils sont tous bornés, mais la sortie est déjà partie.
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:   # même une erreur imprévue rend un JSON valide
        sys.stdout.write(json.dumps({"version": 1, "erreur": f"{type(e).__name__}: {e}"[:300]}) + "\n")
        sys.stdout.flush()
        os._exit(0)
