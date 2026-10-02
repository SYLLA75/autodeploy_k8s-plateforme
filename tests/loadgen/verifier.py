"""
Lit ce qu'une course de Locust a laissé (statistiques CSV, journal du faux
serveur) et rend un verdict : code 0 si le cas passe, 1 sinon.

Appelé par test_locust.sh, un sous-cas par commande :
  nominal   <dossier_nouveau> <dossier_original>
  nouveau   <dossier> <delai_reponse> <duree> <chemin_fige>[,<chemin_fige>]
  original  <dossier> <duree>
  silence   <dossier> <delai_reponse> <duree> <motif_erreur>
  delais    <journal_envois> <connexion> <reponse>
  corps     <dossier> <delai_reponse> <duree> <chemin_fige>
  refus     <dossier> <delai_reponse> <duree>
  priorite  <dossier_locustfile> <port>        (à lancer avec le python de Locust)
"""
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

# Le nom porté dans les statistiques par chaque chemin du faux serveur.
NOMS = {
    "/api/v1/verifycode/generate": "00 code de vérification",
    "/api/v1/users/login": "01 connexion",
    "/api/v1/foodservice/orders": "40 commander un repas",
}

ECHECS = []


def verifier(condition, message):
    print(("    ok      " if condition else "    ÉCHEC   ") + message)
    if not condition:
        ECHECS.append(message)


def lire_csv(chemin):
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stats(dossier):
    return {l["Name"]: l for l in lire_csv(f"{dossier}/r_stats.csv") if l["Name"] != "Aggregated"}


def echecs(dossier):
    return lire_csv(f"{dossier}/r_failures.csv")


def exceptions(dossier):
    return lire_csv(f"{dossier}/r_exceptions.csv")


def journal(chemin):
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def total_echecs(s):
    return sum(int(l["Failure Count"]) for l in s.values())


def max_reponse(s):
    return max((float(l["Max Response Time"]) for l in s.values()), default=0.0)


# --------------------------------------------------------------------- (a)
# Le tirage des parcours (poids 6:2:1:1) est comparé PAR PARCOURS, avec un test
# du khi-deux d'homogénéité. Un parcours se retrouve dans les statistiques :
#   repas    = « 40 commander un repas »       (1 requête)
#   réserver = « 20 mes contacts »             (chercher, contacts, réserver)
#   chercher = « 10 chercher un train » − réserver
#   courriel = « 60 déclencher un courriel »
# Pourquoi : la part d'une REQUÊTE n'est pas un tirage simple (un parcours
# « réserver » compte 3 requêtes), et un écart fixe de 6 points n'a pas le même
# sens à 300 ou à 3 000 parcours : sur une machine chargée, la course en fait
# moins et l'écart dépassait 6 points par hasard (2 fois sur 9). Le khi-deux est
# calibré par les comptes eux-mêmes : si les deux fichiers tirent avec les mêmes
# poids, il ne se trompe qu'une fois sur 1 000 (seuil 0,001), quelle que soit
# la longueur de la course. Il n'affaiblit rien : à 1 000 parcours par course
# (le minimum exigé ; 3 000 environ sur 24 s), un poids changé qui déplace de
# 10 points la part d'un parcours donne un khi-deux d'environ 20 (> 16,3).
SEUIL_KHI2 = 0.001
PARCOURS_MIN = 1000


def parcours(s):
    """Le nombre de parcours de chaque sorte, lu dans les statistiques."""
    n = {nom: int(l["Request Count"]) for nom, l in s.items()}
    reserver = n.get("20 mes contacts", 0)
    return {"repas": n.get("40 commander un repas", 0), "réserver": reserver,
            "chercher": n.get("10 chercher un train", 0) - reserver,
            "courriel": n.get("60 déclencher un courriel", 0)}


def khi2_homogeneite(a, b):
    """Khi-deux d'homogénéité de deux comptes (mêmes clés) ; rend (khi2, ddl, p)."""
    cles = [k for k in a if a[k] + b[k] > 0]
    na, nb = sum(a[k] for k in cles), sum(b[k] for k in cles)
    khi2 = 0.0
    for k in cles:
        t = a[k] + b[k]
        for o, n in ((a[k], na), (b[k], nb)):
            e = n * t / (na + nb)
            khi2 += (o - e) ** 2 / e
    ddl = len(cles) - 1
    if ddl != 3:
        return khi2, ddl, None
    # Survie de la loi du khi-deux à 3 degrés de liberté (forme exacte).
    p = math.erfc(math.sqrt(khi2 / 2)) + math.sqrt(2 * khi2 / math.pi) * math.exp(-khi2 / 2)
    return khi2, ddl, p


def nominal(d_nouveau, d_original):
    resume = {}
    for etiquette, d in (("nouveau", d_nouveau), ("original", d_original)):
        s, j = stats(d), journal(f"{d}/journal")
        total = sum(int(l["Request Count"]) for l in s.values())
        parts = {n: int(l["Request Count"]) / total for n, l in s.items()} if total else {}
        requetes = {(r["methode"], r["chemin"], tuple(r["cles"])) for r in j}
        par_voyageur = defaultdict(list)
        for r in j:
            par_voyageur[r["voyageur"]].append(r)
        resume[etiquette] = dict(s=s, total=total, parts=parts, requetes=requetes,
                                 voyageurs=par_voyageur)
        print(f"    {etiquette:9s} {total} requêtes, {total_echecs(s)} échecs, "
              f"{len(par_voyageur)} voyageurs")
        verifier(total > 200, f"{etiquette} : assez de requêtes pour comparer ({total})")
        verifier(total_echecs(s) == 0, f"{etiquette} : aucun échec")
        verifier(not exceptions(d), f"{etiquette} : aucune exception dans un parcours")
        debuts_ok = all(
            [(r["methode"], r["chemin"]) for r in rs[:2]]
            == [("GET", "/api/v1/verifycode/generate"), ("POST", "/api/v1/users/login")]
            and all(r["auth"] == "Bearer jeton" for r in rs[2:])
            for rs in par_voyageur.values())
        verifier(debuts_ok, f"{etiquette} : chaque voyageur commence par code + connexion, "
                            "puis tout porte le jeton")
    n, o = resume["nouveau"], resume["original"]
    verifier(set(n["s"]) == set(o["s"]), "mêmes noms dans les statistiques")
    verifier(n["requetes"] == o["requetes"],
             f"mêmes requêtes (méthode, chemin, champs du corps) : {len(n['requetes'])} sortes")
    print("    %-28s %9s %9s" % ("part des requêtes", "nouveau", "original"))
    for nom in sorted(set(n["parts"]) | set(o["parts"])):
        a, b = n["parts"].get(nom, 0), o["parts"].get(nom, 0)
        print("    %-28s %8.1f%% %8.1f%%" % (nom, 100 * a, 100 * b))
        verifier(abs(a - b) < 0.06, f"proportion de « {nom} » comparable (écart < 6 points)")
    # Par parcours : le test qui juge le tirage (voir plus haut).
    pn, po = parcours(n["s"]), parcours(o["s"])
    print("    %-28s %9s %9s" % ("parcours tirés", "nouveau", "original"))
    for k in pn:
        print("    %-28s %9d %9d" % (k, pn[k], po[k]))
    for etiquette, r in (("nouveau", n), ("original", o)):
        c = {nom: int(l["Request Count"]) for nom, l in r["s"].items()}
        ecart = abs(c.get("20 mes contacts", 0) - c.get("30 réserver un billet", 0))
        verifier(ecart <= len(r["voyageurs"]),
                 f"{etiquette} : chaque « réserver » fait contacts puis réservation (écart {ecart}, "
                 f"au plus un parcours coupé par voyageur)")
        k = sum(parcours(r["s"]).values())
        verifier(k >= PARCOURS_MIN, f"{etiquette} : assez de parcours pour juger le tirage ({k} ≥ {PARCOURS_MIN})")
    khi2, ddl, p = khi2_homogeneite(pn, po)
    verifier(p is not None and p >= SEUIL_KHI2,
             f"même tirage des parcours : khi-deux {khi2:.2f} à {ddl} ddl, p = "
             + (f"{p:.3g}" if p is not None else "?") + f" ≥ {SEUIL_KHI2}")
    rapport = n["total"] / o["total"] if o["total"] else 0
    verifier(0.8 < rapport < 1.25, f"même rythme : rapport des totaux {rapport:.2f}")


# --------------------------------------------------------------------- (b)
def nouveau(d, delai, duree, figes):
    delai, duree = float(delai), float(duree)
    figes = figes.split(",")
    s, e, j = stats(d), echecs(d), journal(f"{d}/journal")
    for chemin in figes:
        nom = NOMS[chemin]
        lignes = [l for l in e if l["Name"] == nom and "ReadTimeout" in l["Error"]]
        nb = sum(int(l["Occurrences"]) for l in lignes)
        verifier(nb > 0, f"échec compté sous « {nom} » (ReadTimeout) : {nb}")
        if lignes:
            print("            " + lignes[0]["Error"][:110])
    autres = [l for l in e if not any(l["Name"] == NOMS[c] for c in figes)]
    verifier(not autres, f"aucun autre motif d'échec ({len(autres)})")
    verifier(not exceptions(d), "aucune exception : les parcours absorbent l'expiration")
    m = max_reponse(s)
    verifier(m <= (delai + 1) * 1000,
             f"aucune requête n'a attendu plus que le délai : max {m:.0f} ms ≤ {(delai + 1) * 1000:.0f}")
    # Le voyageur continue : des requêtes NON figées arrivent jusqu'à la fin.
    debut = min((r["t"] for r in j), default=0)
    fin_tiers = debut + duree * 2 / 3
    par_voyageur = defaultdict(list)
    for r in j:
        par_voyageur[r["voyageur"]].append(r)
    tardives = {v: sum(1 for r in rs if r["t"] >= fin_tiers)
                for v, rs in par_voyageur.items()}
    print(f"    requêtes reçues dans le dernier tiers, par voyageur : {tardives}")
    verifier(tardives and all(n > 0 for n in tardives.values()),
             "chaque voyageur envoie encore des requêtes à la fin")
    servies = sum(1 for r in j if r["t"] >= fin_tiers and not r["fige"])
    verifier(servies > 0, f"les autres parcours avancent encore à la fin : {servies} requêtes servies")
    # Le plus long silence d'un voyageur : au plus le délai, plus une marge
    # pour le rythme (0,5 s) et l'ordonnancement.
    ecarts = {v: max((b["t"] - a["t"] for a, b in zip(rs, rs[1:])), default=0)
              for v, rs in par_voyageur.items()}
    print("    plus long silence par voyageur (s) : "
          + str({v: round(e, 2) for v, e in ecarts.items()}))
    verifier(all(e <= delai + 1.5 for e in ecarts.values()),
             f"aucun voyageur muet plus de {delai + 1.5:.1f} s")
    verifier(sum(int(l["Request Count"]) for l in s.values()) > 3 * len(par_voyageur),
             "le nombre de requêtes croît")
    if "/api/v1/users/login" in figes:
        tentatives = sum(1 for r in j if r["chemin"] == "/api/v1/users/login")
        borne = len(par_voyageur) * (duree / delai + 3)
        verifier(0 < tentatives <= borne,
                 f"reconnexions bornées par le délai, pas de boucle folle : {tentatives} ≤ {borne:.0f}")


# --------------------------------------------------------------------- (c)
def original(d, duree):
    duree = float(duree)
    s, j = stats(d), journal(f"{d}/journal")
    par_voyageur = defaultdict(list)
    for r in j:
        par_voyageur[r["voyageur"]].append(r)
    figes = {v: [r for r in rs if r["fige"]] for v, rs in par_voyageur.items()}
    verifier(par_voyageur and all(len(figes[v]) == 1 and rs[-1]["fige"]
                                  for v, rs in par_voyageur.items()),
             f"chaque voyageur ({len(par_voyageur)}) est resté sur sa première commande de repas, "
             "sans plus rien envoyer")
    debut = min((r["t"] for r in j), default=0)
    derniere = max((r["t"] for r in j), default=0) - debut
    verifier(derniere < duree / 2,
             f"plus aucune requête après {derniere:.1f} s, sur {duree:.0f} s de course")
    repas = s.get(NOMS["/api/v1/foodservice/orders"])
    verifier(repas is None or int(repas["Failure Count"]) == 0,
             "et Locust ne compte aucun échec : le défaut est invisible")


# --------------------------------------------------------------------- (d)
def silence(d, delai, duree, motif):
    delai, duree = float(delai), float(duree)
    s, e, j = stats(d), echecs(d), journal(f"{d}/journal")
    nb = sum(int(l["Occurrences"]) for l in e if motif in l["Error"])
    verifier(nb > 0, f"échecs comptés avec le motif « {motif} » : {nb}")
    if e:
        print("            " + e[0]["Name"] + " : " + e[0]["Error"][:100])
    noms = {l["Name"] for l in e}
    verifier("00 code de vérification" in noms, "l'échec porte le nom de la requête (« 00 code de vérification »)")
    verifier(not exceptions(d), "aucune exception : les parcours absorbent l'erreur")
    m = max_reponse(s)
    verifier(m <= (delai + 1) * 1000,
             f"aucune requête n'a attendu plus que le délai : max {m:.0f} ms ≤ {(delai + 1) * 1000:.0f}")
    total = sum(int(l["Request Count"]) for l in s.values())
    verifier(total >= 6, f"les voyageurs continuent d'essayer : {total} requêtes")
    acceptees = [r for r in j if r.get("evenement") == "connexion acceptee"]
    if acceptees:
        debut = acceptees[0]["t"]
        tard = sum(1 for r in acceptees if r["t"] >= debut + duree * 2 / 3)
        verifier(tard > 0, f"de nouvelles connexions arrivent dans le dernier tiers : {tard}")


# --------------------------------------------------------------------- (f)
def corps(d, delai, duree, chemin):
    """
    En-têtes reçus, corps figé : requests lève une ConnectionError sans
    requête attachée, et Locust 2.32.4 trébuche dessus (AttributeError). On
    vérifie que le voyageur SURVIT et que l'incident est COMPTÉ, en exception.
    """
    delai, duree = float(delai), float(duree)
    j, x = journal(f"{d}/journal"), exceptions(d)
    figees = sum(1 for r in j if r["chemin"] == chemin and r["fige"])
    verifier(figees > 0, f"des requêtes « {NOMS[chemin]} » ont reçu un corps figé : {figees}")
    nb = sum(int(l["Count"]) for l in x)
    verifier(nb > 0, f"chaque incident est compté (onglet Exceptions de Locust) : {nb}")
    if x:
        print("            " + x[0]["Message"][:110])
    log = open(f"{d}/locust.log", encoding="utf-8").read()
    verifier("failed with" not in log, "aucun voyageur n'est mort (« run_user … failed with »)")
    par_voyageur = defaultdict(list)
    for r in j:
        par_voyageur[r["voyageur"]].append(r)
    debut = min((r["t"] for r in j), default=0)
    fin_tiers = debut + duree * 2 / 3
    tardives = {v: sum(1 for r in rs if r["t"] >= fin_tiers) for v, rs in par_voyageur.items()}
    print(f"    requêtes reçues dans le dernier tiers, par voyageur : {tardives}")
    verifier(tardives and all(n > 0 for n in tardives.values()),
             "chaque voyageur envoie encore des requêtes à la fin")
    ecarts = {v: max((b["t"] - a["t"] for a, b in zip(rs, rs[1:])), default=0)
              for v, rs in par_voyageur.items()}
    print("    plus long silence par voyageur (s) : "
          + str({v: round(e, 2) for v, e in ecarts.items()}))
    verifier(all(e <= delai + 1.5 for e in ecarts.values()),
             f"aucun voyageur muet plus de {delai + 1.5:.1f} s")


# --------------------------------------------------------------------- (g)
def refus(d, delai, duree):
    """
    Connexion figée et 403 pour toute requête sans jeton : le chemin
    « connexion expirée → requête sans jeton → 403 → _verifier reconnecte ».
    Au plus 4 requêtes d'authentification par parcours, 2 dans on_start.
    """
    delai, duree = float(delai), float(duree)
    e, x = echecs(d), exceptions(d)
    envois = journal(f"{d}/envois")
    auth = ("/api/v1/verifycode/generate", "/api/v1/users/login")
    par_parcours = Counter((r["voyageur"], r["parcours"]) for r in envois if r["chemin"] in auth)
    pire = max(par_parcours.values(), default=0)
    print(f"    parcours observés : {len({k for k in par_parcours})}, "
          f"au plus {pire} requêtes d'authentification dans un parcours")
    verifier(par_parcours and pire <= 4, "au plus 4 requêtes 00/01 par parcours (pas de boucle folle)")
    verifier(all(n <= 2 for (_, p), n in par_parcours.items() if p == 0),
             "au plus 2 dans on_start")
    refuses = sum(int(l["Occurrences"]) for l in e if "403" in l["Error"])
    expires = sum(int(l["Occurrences"]) for l in e
                  if l["Name"] == "01 connexion" and "ReadTimeout" in l["Error"])
    verifier(refuses > 0, f"les 403 sont comptés en échec sous le nom du parcours : {refuses}")
    verifier(expires > 0, f"les connexions expirées sont comptées en échec : {expires}")
    verifier(not x, "aucune exception")
    par_voyageur = defaultdict(list)
    for r in envois:
        par_voyageur[r["voyageur"]].append(r)
    voyageurs = len(par_voyageur)
    connexions = sum(1 for r in envois if r["chemin"] == "/api/v1/users/login")
    borne = voyageurs * (duree / delai + 2)
    verifier(0 < connexions <= borne, f"connexions bornées par le délai : {connexions} ≤ {borne:.0f}")
    derniers = {v: max(r["parcours"] for r in rs) for v, rs in par_voyageur.items()}
    print(f"    dernier parcours atteint, par voyageur : {list(derniers.values())}")
    verifier(voyageurs > 0 and all(n >= 2 for n in derniers.values()),
             "chaque voyageur enchaîne les parcours")


# --------------------------------------------------------------------- (e)
def delais(chemin, connexion, reponse):
    attendu = [float(connexion), float(reponse)]
    j = journal(chemin)
    valeurs = Counter(json.dumps(r["timeout"]) for r in j)
    print(f"    délais réellement transmis à requests : {dict(valeurs)}")
    verifier(len(j) > 0, f"des envois ont été observés ({len(j)})")
    verifier(all(r["timeout"] == attendu for r in j), f"tous les envois portent {attendu}")
    chemins = {r["chemin"] for r in j}
    verifier({"/api/v1/verifycode/generate", "/api/v1/users/login"} <= chemins,
             "y compris le code et la connexion de on_start")


def priorite(dossier, port):
    """Dans un seul processus : la valeur d'environnement, puis le délai explicite."""
    os.environ["TT_DELAI_CONNEXION"] = "1.5"
    os.environ.pop("TT_DELAI_REPONSE", None)
    sys.path.insert(0, dossier)
    from locust.env import Environment   # avant requests : gevent d'abord
    import requests
    vus = []
    envoi = requests.Session.send

    def espion(self, requete, **kw):
        vus.append(kw.get("timeout"))
        return envoi(self, requete, **kw)

    requests.Session.send = espion
    import locustfile
    locustfile.Voyageur.host = f"http://127.0.0.1:{port}"
    u = locustfile.Voyageur(Environment(user_classes=[locustfile.Voyageur]))
    chemin = "/api/v1/notifyservice/test_send_mq"
    u.client.get(chemin)
    u.client.get(chemin, timeout=7)
    u.client.post("/api/v1/foodservice/orders", json={}, timeout=(3, 4))
    print(f"    délais transmis : {vus}")
    verifier(vus[0] == (1.5, 60.0), "TT_DELAI_CONNEXION=1.5 seul → (1.5, 60.0)")
    verifier(vus[1] == 7, "un délai explicite (7) garde la priorité")
    verifier(vus[2] == (3, 4), "un délai explicite (3, 4) garde la priorité")


if __name__ == "__main__":
    cas, *args = sys.argv[1:]
    {"nominal": nominal, "nouveau": nouveau, "original": original, "silence": silence,
     "delais": delais, "priorite": priorite, "corps": corps, "refus": refus}[cas](*args)
    sys.exit(1 if ECHECS else 0)
