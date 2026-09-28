"""
Le banc de pannes fabriquées du GNN, et le choix de la grille B/H/V.

    ./.venv/bin/python gnn_banc.py [--graines n] [--epoques e] [--version v1|v2|v3]
    ./.venv/bin/python gnn_banc.py --verifier [--version v1|v2|v3]

Phase E. Écrit d'après notes/GNN_SPEC.md §7 (le banc) et §3.5 (le choix), avec
la signature de l'écart 3 du journal (J 1989-1996). Importe gnn.py sans le
modifier : les modèles, les résidus et le post-traitement sont les siens.

LE TERRAIN : la VALIDATION seule (juge.validation(juge.lire(fautifs.SERIES))).
  Les modèles de l'étape 1 (le complet) sont appris sur ses normales
  d'apprentissage, graines 0 à n−1. Les fenêtres du banc sont ses normales
  jeu == « test » ; jamais « hors » (le vrai test), jamais C, D ni leurs essais.
  La file pleine vient de ses pannes « lenteur » d'apprentissage, les pressions du
  leurre de ses pannes « hote » d'apprentissage.

LE GÉNÉRATEUR : fabriquer(donnees, cas, X, d, Y), sur une copie profonde (le
  générateur lit les noms : ce n'est pas le modèle). Unités en ms.
  Signature M (machine X, retard d) :
    - la réplique ts-delivery-service-* de X : process_time_p50/95/99 += 5d ; ses
      flèches queries sortantes : latency_p50/95/99 += d ; sa flèche consumes :
      rate = min(rate, 1000 / (process_time_p50 d'avant + 6d)) ;
    - les autres pods de X sources de queries : ces flèches latency_* += d, et
      leurs process_time_* et request_time_* += d (borne basse) ;
    - le ricochet : les flèches calls qui entrent chez ces pods, latency_* += d,
      et leurs sources process_time_*, request_time_* += d ;
    - inchangés : les calls qui sortent de X, les nombres de la machine X, les
      appelants de la base hors de X ;
    - la file food_delivery pleine : sa ligne copiée de la i-ème fenêtre de panne
      lenteur d'apprentissage, i = rang de la fenêtre du banc modulo leur nombre.
  Les cas : M → host:X ; R (la réplique seule, file pleine) → la réplique ; M+Y
  (M, et cpu/memory/io_pressure de Y aux médianes de la machine fautive des
  pannes hote) → host:X ; Y (Y seul, file inchangée) → host:Y.
  X ∈ {workers0, workers2, workers5} ; Y = workers1 ; d ∈ {75, 150, 300}, et 400
  à part, hors critère.
  Les familles (J 1308-1310) : « entrant dans T », T chaque instance cible de
  flèches calls ou queries venant d'au moins 3 pods distincts (toutes ses flèches
  entrantes += d, ses sources process_time et request_time += d, +5d pour une
  réplique, file pleine si une réplique est parmi elles) → T ; « sortant de T »,
  T chaque réplique (ses flèches sortantes += d, process_time += 5d, file pleine)
  → T. La famille « entrant » contient la base : le journal l'autorise (J 1308).

LA MESURE : pour chaque (famille, cas, cible, d, graine) et chaque combinaison
  des 30 de la grille : le nombre de fenêtres où la réponse attendue est au rang
  1 (juge.rang, égalités contre le GNN), et la réponse la plus souvent première.

LE CHOIX (écart E-3, §13 de la spécification, qui remplace le critère 3 du §3.5) :
  parmi les combinaisons dont G_val tient pour chaque graine, le plus grand
  min(F_C, F_D, F_R), chaque famille en part des cas au rang 1, médiane des graines
  (F_C : « entrant dans tsdb-mysql-0 » ; F_D : M et M+Y ; F_R : R et « sortant »,
  d ∈ 75, 150, 300) ; à 0,05 près, le plus grand top-1 de validation ; puis la plus
  simple. Y, « entrant » ts-order-service et 400 ms sont écrits à titre
  d'information. Si le min du choix est sous 0,5, la sortie le dit : la version ne
  peut pas être figée (§13, arrêt).

L'ANCIEN CHOIX (§3.5), écrit à côté pour comparaison, dans l'ordre :
  1. admissible si G_val tient pour chaque graine : instance:tsdb-mysql-0 n'est
     première dans une majorité stricte des fenêtres d'aucune des injections de
     test des causes connues de la validation (première ou ex aequo en tête :
     gnn.base_en_tete ; decision_c.premier compterait l'égalité pour la méthode),
     par_injection, majorite) ;
  2. et, pour chaque dimension non minimale, le top-1 de la validation (sans
     alarme, par fenêtre, causes apprises, médiane des graines) au moins égal à
     celui de la même combinaison ramenée au plus simple sur cette dimension ;
  3. parmi les admissibles, le plus grand nombre de cas du banc au rang 1
     (médiane des graines ; d = 400 hors critère) ;
  4. à égalité, la plus simple (V0 < V1, puis H0 < H1 < H2, puis B1 < … < B5) ;
     aucune admissible : B1/H0/V0.

Options :
  --verifier             les contrôles du banc (T5 de la spécification, et ceux de la
                         notation, du parallélisme et du choix), sur un petit jeu
                         et 2 époques
  --version <v>          la version de l'étape 1 (gnn.VERSIONS, §11 : chacune fixe
                         SON choix B/H/V) ; v1 par défaut
  --graines <n>          graines 0 à n−1 (défaut 5)
  --epoques <e>          époques d'apprentissage (défaut 150)
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --help                 ce texte

Écrit <campagnes>/gnn-banc-validation.txt (v1 ; gnn-banc-validation-v2.txt…
pour les autres versions). Code de sortie 0 ; 1 si une campagne
est refusée ou un contrôle échoue ; 2 sur un mauvais argument.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import multiprocessing
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import decision_c as dc
import fautifs as fautifs_module
import gel
import gnn
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
SORTIE = "gnn-banc-validation.txt"
FILE = juge.FILE                                   # food_delivery
REPLIQUE = "ts-delivery-service-"
XS = ("workers0", "workers2", "workers5")          # les machines de travail qui portent une réplique
# Le leurre : la règle de couples_d.py donne les couples workers2:workers1 et
# workers5:workers1 (journal, écart 4) ; lu dans le code et le journal, pas dans D.
Y_LEURRE = "workers1"
RETARDS = (75, 150, 300)
HORS_CRITERE = 400                                 # J 2004 : donné à part (la grille est écrite, J 1586)
SOURCES_MIN = 3                                    # « entrant dans T » : au moins 3 pods sources distincts
PRESSIONS = ("cpu_pressure", "memory_pressure", "io_pressure")
LATENCES = ("latency_p50", "latency_p95", "latency_p99")
TRAITEMENT = ("process_time_p50", "process_time_p95", "process_time_p99")
REQUETE = ("request_time_p50", "request_time_p95", "request_time_p99")
CAS = ("M", "R", "M+Y", "Y", "entrant", "sortant")
FAMILLE = {"M": "machine", "R": "machine", "M+Y": "machine", "Y": "machine",
           "entrant": "entrant dans T", "sortant": "sortant de T"}
MINIMAUX = {"bout": gnn.BOUTS[0], "remontee": gnn.REMONTEES[0], "explication": gnn.EXPLICATIONS[0]}
DIMENSIONS = (("explication", "V"), ("remontee", "H"), ("bout", "B"))
# L'écart E-3 (§13) : les trois familles du critère, les chiffres donnés à titre
# d'information, la tolérance sur min(F_C, F_D, F_R).
FAMILLES_E3 = ("F_C", "F_D", "F_R")
COLONNES_E3 = FAMILLES_E3 + ("Y", "ent. order", "400 F_C", "400 F_D", "400 F_R")
TOLERANCE_E3 = 0.05
LOT_TACHE = 40                                     # fenêtres par tâche du parallélisme


# ------------------------------------------------------------------------------
# Le générateur
# ------------------------------------------------------------------------------
def _col(bloc: dict, nom: str) -> int:
    return bloc["columns"].index(nom)


def _plus(ligne: list, j: int, v: float) -> None:
    """Ajoute v à une cellule ; une valeur absente (None) le reste."""
    if ligne[j] is not None:
        ligne[j] = ligne[j] + v


def _ajouter(bloc: dict, i: int, colonnes, v: float) -> None:
    for c in colonnes:
        _plus(bloc["X"][i], _col(bloc, c), v)


def repliques(donnees: dict, machine: str | None = None) -> list[int]:
    """Les lignes des répliques du consommateur (toutes, ou celles de la machine)."""
    inst = donnees["nodes"]["instance"]
    return [i for i, (n, h) in enumerate(zip(inst["names"], inst["hosts"]))
            if n.startswith(REPLIQUE) and (machine is None or h == machine)]


def _sources(donnees: dict, cible: int) -> set[int]:
    """Les pods sources distincts des flèches calls et queries qui entrent en `cible`."""
    out = set()
    for rel in gnn.APPELS:
        e = donnees["edges"][rel]
        out |= {s for s, t in zip(e["source"], e["target"]) if t == cible and s != cible}
    return out


def cibles_entrant(donnees: dict) -> list[int]:
    """Les instances cibles de flèches calls ou queries venant d'au moins 3 pods distincts."""
    n = len(donnees["nodes"]["instance"]["names"])
    return [i for i in range(n) if len(_sources(donnees, i)) >= SOURCES_MIN]


def _remplir_file(d2: dict, file: list | None) -> None:
    if file is None:
        raise ValueError("ce cas rend la file pleine : il faut la ligne `file`")
    q = d2["nodes"]["queue"]
    i = q["names"].index(FILE)
    if len(file) != len(q["columns"]):
        raise ValueError("la ligne de file n'a pas les colonnes du gel")
    q["X"][i] = list(file)


def _replique_lente(d2: dict, i: int, d: float) -> None:
    """La part de la réplique dans la signature M : +5d, ses queries +d, sa capacité."""
    inst = d2["nodes"]["instance"]
    avant = inst["X"][i][_col(inst, "process_time_p50")]
    _ajouter(inst, i, TRAITEMENT, 5 * d)
    q = d2["edges"]["queries"]
    for j, s in enumerate(q["source"]):
        if s == i:
            _ajouter(q, j, LATENCES, d)
    c = d2["edges"]["consumes"]
    r = _col(c, "rate")
    for j, t in enumerate(c["target"]):
        if t == i and avant is not None and c["X"][j][r] is not None:
            c["X"][j][r] = min(c["X"][j][r], 1000.0 / (avant + 6 * d))


def _machine_lente(d2: dict, X: str, d: float) -> None:
    """La signature M hors file : la réplique de X, les autres pods de X qui
    interrogent la base, et le ricochet sur les flèches calls qui entrent chez eux."""
    inst = d2["nodes"]["instance"]
    reps = repliques(d2, X)
    if not reps:
        raise ValueError(f"aucune réplique sur {X} dans cette fenêtre")
    for i in reps:
        _replique_lente(d2, i, d)
    q = d2["edges"]["queries"]
    autres = {s for s in q["source"] if inst["hosts"][s] == X and s not in reps}
    for j, s in enumerate(q["source"]):
        if s in autres:
            _ajouter(q, j, LATENCES, d)
    calls = d2["edges"]["calls"]
    ricochet = set()
    for j, (s, t) in enumerate(zip(calls["source"], calls["target"])):
        if t in autres:
            _ajouter(calls, j, LATENCES, d)
            ricochet.add(s)
    # Chaque pod ralenti une fois (+d), qu'il interroge la base, appelle un pod ralenti, ou les deux ;
    # la réplique garde ses +5d.
    for i in sorted((autres | ricochet) - set(reps)):
        _ajouter(inst, i, TRAITEMENT + REQUETE, d)


def _leurre(d2: dict, Y: str, pressions: dict) -> None:
    h = d2["nodes"]["host"]
    i = h["names"].index(Y)
    for c in PRESSIONS:
        h["X"][i][_col(h, c)] = pressions[c]


def fabriquer(donnees: dict, cas: str, X: str | None, d: float, Y: str | None = None,
              file: list | None = None, pressions: dict | None = None) -> dict:
    """
    Une panne fabriquée, sur une COPIE PROFONDE de `donnees` (jamais modifié).
      cas « M », « R », « M+Y » : X est la machine ; « Y » : X et d ignorés ;
      cas « entrant », « sortant » : X est le NOM du pod T.
    `file` : la ligne food_delivery d'une fenêtre de panne lenteur (file pleine) ;
    `pressions` : {cpu_pressure, memory_pressure, io_pressure} pour Y.
    """
    if cas not in CAS:
        raise ValueError(f"cas inconnu : {cas}")
    d2 = copy.deepcopy(donnees)
    inst = d2["nodes"]["instance"]
    if cas in ("M", "M+Y"):
        _machine_lente(d2, X, d)
        _remplir_file(d2, file)
    if cas == "R":
        reps = repliques(d2, X)
        if not reps:
            raise ValueError(f"aucune réplique sur {X} dans cette fenêtre")
        for i in reps:
            _replique_lente(d2, i, d)
        _remplir_file(d2, file)
    if cas in ("M+Y", "Y"):
        if Y is None or pressions is None:
            raise ValueError("le leurre demande Y et les pressions")
        _leurre(d2, Y, pressions)
    if cas == "entrant":
        t = inst["names"].index(X)
        for rel in gnn.APPELS:
            e = d2["edges"][rel]
            for j, cible in enumerate(e["target"]):
                if cible == t and e["source"][j] != t:
                    _ajouter(e, j, LATENCES, d)
        sources = _sources(d2, t)
        reps = set(repliques(d2))
        for s in sorted(sources):
            _ajouter(inst, s, TRAITEMENT + REQUETE, (5 if s in reps else 1) * d)
        if sources & reps:
            _remplir_file(d2, file)
    if cas == "sortant":
        t = inst["names"].index(X)
        if not inst["names"][t].startswith(REPLIQUE):
            raise ValueError("« sortant de T » : T est une réplique")
        for rel in gnn.APPELS:
            e = d2["edges"][rel]
            for j, s in enumerate(e["source"]):
                if s == t:
                    _ajouter(e, j, LATENCES, d)
        _ajouter(inst, t, TRAITEMENT, 5 * d)
        _remplir_file(d2, file)
    return d2


def attendue(donnees: dict, cas: str, X: str | None, Y: str | None = None) -> list[str]:
    """La réponse attendue, en clés du juge (fautifs.py l.16-19 : le fautif de hote est la machine)."""
    inst = donnees["nodes"]["instance"]
    if cas in ("M", "M+Y"):
        return [juge._cle("host", X)]
    if cas == "R":
        return [juge._cle("instance", inst["names"][i]) for i in repliques(donnees, X)]
    if cas == "Y":
        return [juge._cle("host", Y)]
    return [juge._cle("instance", X)]


def cas_du_banc(donnees: dict, retards=RETARDS + (HORS_CRITERE,)) -> list[tuple]:
    """Les (cas, cible, d, groupe) d'une fenêtre du banc ; groupe = (famille, cas, étiquette de la cible, d)."""
    inst = donnees["nodes"]["instance"]
    out = [("Y", None, 0, (FAMILLE["Y"], "Y", Y_LEURRE, 0))]
    for d in retards:
        for X in XS:
            if repliques(donnees, X):
                for cas in ("M", "R", "M+Y"):
                    out.append((cas, X, d, (FAMILLE[cas], cas, X, d)))
        for t in cibles_entrant(donnees):
            nom = inst["names"][t]
            out.append(("entrant", nom, d, (FAMILLE["entrant"], "entrant", tn.identite("instance", nom), d)))
        for t in repliques(donnees):
            nom = inst["names"][t]
            out.append(("sortant", nom, d, (FAMILLE["sortant"], "sortant", f"réplique de {inst['hosts'][t]}", d)))
    return out


# ------------------------------------------------------------------------------
# La notation de la grille
# ------------------------------------------------------------------------------
def scores_grille(sortie: gnn.Sortie, calage: gnn.Calage) -> dict[str, np.ndarray]:
    """ŝ' de chaque nœud pour les 30 combinaisons, dans l'ordre de sortie.cles() ; les
    mêmes opérations que gnn.noter_noeuds, les étapes communes calculées une fois."""
    deps = gnn.VARIANTES[calage.variante]["deps"]
    _, r, _, eps = gnn.ecarts(sortie, calage)
    out = {}
    for b in gnn.BOUTS:
        e = gnn.bout(b, sortie, eps, calage.kappa)
        s = gnn.normaliser(sortie, r, e, calage.tau(b))
        for h in gnn.REMONTEES:
            sh = gnn.remontee(h, s, sortie, gnn.APPELS)
            for v in gnn.EXPLICATIONS:
                out[gnn.nom_choix({"bout": b, "remontee": h, "explication": v})] = \
                    gnn.explication(v, sh, sortie, deps)[0]
    return out


NOMS = [gnn.nom_choix(c) for c in gnn.grille()]


def noter_fenetre(modele, calage, donnees: dict, attendue_: list[str], base: list[str]) -> tuple[list, list, list]:
    """Pour chaque combinaison (ordre NOMS) : le rang de la réponse attendue (0 sans
    réponse attendue), la base est-elle première (gnn.base_en_tete : en tête, égalités contre le GNN), qui
    est premier."""
    sortie = gnn.residus(modele, donnees)
    grille = scores_grille(sortie, calage)
    cles = sortie.cles()
    tous = juge.noeuds(donnees)
    rangs, base1, premiers = [], [], []
    for nom in NOMS:
        sp = grille[nom]
        scores = {c: float(x) for c, x in zip(cles, sp)}
        rangs.append(juge.rang(attendue_, scores, tous) if attendue_ else 0)
        base1.append(gnn.base_en_tete(scores, base, tous))
        premiers.append(cles[int(np.argmax(sp))])
    return rangs, base1, premiers


# Le parallélisme : l'état (fenêtres, modèles, calages) est envoyé une fois à chaque
# processus ; une tâche porte une graine et une liste d'éléments.
_ETAT: dict = {}


def _init_processus(brut: bytes) -> None:
    global _ETAT
    gnn._un_fil()
    _ETAT = gnn._des_octets(brut)
    gnn.charger_echelle(_ETAT["fige"])
    _ETAT["charges"] = {g: gnn.charger(sd, _ETAT["dims"], "complet", _ETAT["version"])
                        for g, (sd, _) in _ETAT["modeles"].items()}


def _fenetre(etat: dict, element: tuple) -> tuple[dict, list[str]]:
    """(données à noter, réponse attendue) d'un élément : ("banc", i, cas, cible, d) ou ("val", j)."""
    if element[0] == "val":
        j = element[1]
        return etat["val"][j], list(etat["val_fautifs"][j])
    _, i, cas, cible, d = element
    base = etat["banc"][i]
    files = etat["files"]
    donnees = fabriquer(base, cas, cible, d, Y_LEURRE, file=files[i % len(files)], pressions=etat["pressions"])
    return donnees, attendue(base, cas, cible, Y_LEURRE)


def _tache(t: tuple) -> tuple[list, float]:
    graine, elements = t
    debut = time.perf_counter()
    modele, calage = _ETAT["charges"][graine], _ETAT["modeles"][graine][1]
    out = []
    for el in elements:
        donnees, att = _fenetre(_ETAT, el)
        out.append(noter_fenetre(modele, calage, donnees, att, _ETAT["base"]))
        gnn._GRAPHES.clear()                     # les fenêtres fabriquées ne servent qu'une fois
    return out, time.perf_counter() - debut


def noter_tout(etapes: dict, fige: dict, banc: list[dict], val: list[dict], files: list, pressions: dict,
               elements: list[tuple]) -> tuple[dict, float, float]:
    """({graine : [résultat de chaque élément]}, durée réelle, temps de calcul cumulé)."""
    for e1 in etapes.values():
        for b in gnn.BOUTS:
            e1.calage.tau(b)                     # calculé ici une fois, envoyé tel quel
    versions = {e1.version for e1 in etapes.values()}
    if len(versions) != 1:
        raise ValueError(f"une seule version de l'étape 1 par notation : {sorted(versions)}")
    etat = {"fige": fige, "dims": gnn.dimensions(fige), "base": dc.cles_base(fige), "version": versions.pop(),
            "banc": [f["donnees"] for f in banc], "val": [f["donnees"] for f in val],
            "val_fautifs": [f["fautifs"] for f in val], "files": files, "pressions": pressions,
            "modeles": {g: ({k: v for k, v in e1.modele.state_dict().items()}, e1.calage) for g, e1 in etapes.items()}}
    taches = [(g, elements[i:i + LOT_TACHE]) for g in sorted(etapes) for i in range(0, len(elements), LOT_TACHE)]
    debut = time.perf_counter()
    with ProcessPoolExecutor(max_workers=min(gnn.PROCESSUS, len(taches)),
                             mp_context=multiprocessing.get_context("spawn"),
                             initializer=_init_processus, initargs=(gnn._en_octets(etat),)) as ex:
        resultats = list(ex.map(_tache, taches))
    out = {g: [] for g in etapes}
    cumul = 0.0
    for (g, _), (res, duree) in zip(taches, resultats):
        out[g] += res
        cumul += duree
    return out, time.perf_counter() - debut, cumul


# ------------------------------------------------------------------------------
# Les mesures et le choix
# ------------------------------------------------------------------------------
def _med(valeurs) -> float:
    return statistics.median(valeurs)


def _case(valeurs: list, total: int | None = None) -> str:
    texte = f"{_med(valeurs):g}" + (f"/{total}" if total is not None else "")
    if min(valeurs) != max(valeurs):
        texte += f" [{min(valeurs):g}–{max(valeurs):g}]"
    return texte


def gval(val: list[dict], res: list, k: int, base_seule=None) -> list[tuple[str, int]]:
    """Les injections de test des causes connues où la base est première dans une
    majorité stricte des fenêtres (decision_c.garde, sur la validation)."""
    place = {f["id"]: j for j, f in enumerate(val)}
    test = [f for f in val if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    injections = {c: v for c, v in dc.par_injection(test).items() if not v[0]["jamais_vue"]}
    return [c for c, v in sorted(injections.items())
            if dc.majorite(sum(res[place[f["id"]]][1][k] for f in v), len(v))]


def _apprises(val: list[dict]) -> list[int]:
    """Les fenêtres de panne du test (validation) avec un fautif et une cause apprise (juge.noter)."""
    return [j for j, f in enumerate(val) if f["jeu"] == "test" and f["etiquette"] == "panne"
            and f["etiquette"] not in juge.ECARTEES and f["fautifs"] and f["attendue"] != "inconnue"]


def top1(val: list[dict], res: list, k: int) -> int:
    return sum(1 for j in _apprises(val) if res[j][0][k] == 1)


def _simplifiee(choix: dict, dim: str) -> dict:
    c = dict(choix)
    c[dim] = MINIMAUX[dim]
    return c


def famille_e3(groupe: tuple, base) -> str | None:
    """La famille de l'écart E-3 (§13) d'un groupe du banc, d = 400 compris ; None hors familles.
      F_C : « entrant dans tsdb-mysql-0 » (base = ses clés) ;
      F_D : cas M et M+Y ; F_R : cas R et « sortant » (la réplique)."""
    _, cas, cible, _ = groupe
    if cas == "entrant":
        return "F_C" if cible in base else None
    if cas in ("M", "M+Y"):
        return "F_D"
    if cas in ("R", "sortant"):
        return "F_R"
    return None


def colonne_e3(groupe: tuple, base) -> str | None:
    """La colonne du tableau E-3 : une famille du critère (d ∈ 75, 150, 300), ou un
    chiffre donné à titre d'information (Y, « entrant » ts-order-service, 400 ms)."""
    _, cas, _, d = groupe
    if cas == "Y":
        return "Y"
    fam = famille_e3(groupe, base)
    if d == HORS_CRITERE:
        return f"400 {fam}" if fam else None
    if fam:
        return fam
    return "ent. order" if cas == "entrant" else None


def choisir_e3(g_val: dict, t1: dict, parts: dict) -> tuple[dict, dict, list[str]]:
    """
    La règle de l'écart E-3 (§13), pour une version. Entrées par nom de combinaison, une
    valeur par graine : g_val, t1 (comme choisir) ; parts[nom][famille] : la part des cas
    de la famille au rang 1. Parmi les combinaisons dont G_val tient pour chaque graine :
    le plus grand min(F_C, F_D, F_R) (chaque F en médiane des graines) ; à TOLERANCE_E3
    près, le plus grand top-1 de validation (médiane) ; puis la plus simple. Aucune :
    B1/H0/V0 (la valeur écrite par défaut au §3.5 ; §13 ne dit rien de ce cas).
    Rend (CHOIX, {nom : min des familles}, lignes).
    """
    mins = {gnn.nom_choix(ch): min(_med(parts[gnn.nom_choix(ch)][f]) for f in FAMILLES_E3) for ch in gnn.grille()}
    tient = [ch for ch in gnn.grille() if all(n == 0 for n in g_val[gnn.nom_choix(ch)])]
    lignes = [f"règle 1 (G_val tient pour chaque graine) : {len(tient)} combinaisons sur {len(mins)}"
              + (f" ({', '.join(gnn.nom_choix(c) for c in tient)})" if tient else "")]
    if not tient:
        choix = dict(MINIMAUX)
        lignes.append(f"aucune combinaison ne tient : {gnn.nom_choix(choix)}, la valeur écrite par défaut (§3.5)")
        return choix, mins, lignes
    meilleur = max(mins[gnn.nom_choix(c)] for c in tient)
    proches = [c for c in tient if mins[gnn.nom_choix(c)] >= meilleur - TOLERANCE_E3 - 1e-9]
    t1_max = max(_med(t1[gnn.nom_choix(c)]) for c in proches)
    en_tete = [c for c in proches if _med(t1[gnn.nom_choix(c)]) == t1_max]
    choix = min(en_tete, key=gnn.simplicite)
    lignes.append(f"règle 2 (le plus grand min(F_C, F_D, F_R), médianes des graines) : {meilleur:.3f}, atteint par "
                  + ", ".join(gnn.nom_choix(c) for c in tient if mins[gnn.nom_choix(c)] == meilleur))
    lignes.append(f"règle 3 (à {TOLERANCE_E3:g} près, soit min ≥ {meilleur - TOLERANCE_E3:.3f} : le plus grand "
                  f"top-1 de validation) : " + ", ".join(f"{gnn.nom_choix(c)} (min {mins[gnn.nom_choix(c)]:.3f}, "
                                                       f"top-1 {_med(t1[gnn.nom_choix(c)]):g})" for c in proches)
                  + f" → top-1 {t1_max:g}")
    lignes.append(f"règle 4 (à égalité, la plus simple) : {gnn.nom_choix(choix)}")
    lignes.append(f"seuil d'arrêt du §13 (min(F_C, F_D, F_R) ≥ 0.5) : "
                  + ("atteint" if mins[gnn.nom_choix(choix)] >= 0.5 else
                     f"NON ATTEINT ({mins[gnn.nom_choix(choix)]:.3f}) : cette version ne peut pas être figée"))
    return choix, mins, lignes


def choisir(g_val: dict, t1: dict, banc: dict) -> tuple[dict, dict, list[str]]:
    """
    Le choix du §3.5. Entrées par nom de combinaison, une valeur par graine :
    g_val (injections accusant la base), t1 (top-1 de validation), banc (cas au rang 1,
    hors 400). Rend (CHOIX, {nom : (admissible critère 1, raisons critère 2)}, lignes).
    """
    etat = {}
    for ch in gnn.grille():
        nom = gnn.nom_choix(ch)
        c1 = all(n == 0 for n in g_val[nom])
        raisons = []
        for dim, lettre in DIMENSIONS:
            if ch[dim] != MINIMAUX[dim]:
                simple = gnn.nom_choix(_simplifiee(ch, dim))
                if _med(t1[nom]) < _med(t1[simple]):
                    raisons.append(f"{lettre} : {_med(t1[nom]):g} < {_med(t1[simple]):g} ({simple})")
        etat[nom] = (c1, raisons)
    admissibles = [ch for ch in gnn.grille() if etat[gnn.nom_choix(ch)][0] and not etat[gnn.nom_choix(ch)][1]]
    lignes = [f"critère 1 (G_val tient pour chaque graine) : {sum(1 for c1, _ in etat.values() if c1)} "
              f"combinaisons sur {len(etat)}",
              f"critère 2 (le top-1 de validation ne perd rien à aucune option) : {len(admissibles)} admissibles"
              + (f" ({', '.join(gnn.nom_choix(c) for c in admissibles)})" if admissibles else "")]
    if not admissibles:
        choix = dict(MINIMAUX)
        lignes.append(f"aucune combinaison admissible : {gnn.nom_choix(choix)}, la valeur écrite par défaut")
        return choix, etat, lignes
    meilleur = max(_med(banc[gnn.nom_choix(c)]) for c in admissibles)
    en_tete = [c for c in admissibles if _med(banc[gnn.nom_choix(c)]) == meilleur]
    choix = min(en_tete, key=gnn.simplicite)
    lignes.append(f"critère 3 (le plus de cas du banc au rang 1, médiane des graines) : {meilleur:g}, atteint par "
                  + ", ".join(gnn.nom_choix(c) for c in en_tete))
    lignes.append(f"critère 4 (à égalité, la plus simple) : {gnn.nom_choix(choix)}")
    return choix, etat, lignes


# ------------------------------------------------------------------------------
# Les données du banc
# ------------------------------------------------------------------------------
def donnees_du_banc(fen: list[dict]) -> dict:
    """Les fenêtres du banc, la validation notée, les lignes de file pleine, les pressions du leurre."""
    banc = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
    val = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    app = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "panne"]
    lentes = [f for f in app if f["cause"] == "lenteur"]
    files = [list(f["donnees"]["nodes"]["queue"]["X"][f["donnees"]["nodes"]["queue"]["names"].index(FILE)])
             for f in lentes]
    hotes = [f for f in app if f["cause"] == "hote"]
    pressions = {}
    for c in PRESSIONS:
        v = [juge._valeur(f["donnees"], "host", f["fautifs"][0].split(":", 1)[1], c) for f in hotes]
        pressions[c] = float(statistics.median([x for x in v if x is not None]))
    if not banc or not files or not hotes:
        raise juge.Refus("la validation n'a pas de quoi fabriquer le banc (normales de test, pannes lenteur "
                         "et hote d'apprentissage)")
    return {"banc": banc, "val": val, "files": files, "lentes": lentes, "hotes": hotes, "pressions": pressions}


def elements_du_banc(banc: list[dict], retards=RETARDS + (HORS_CRITERE,)) -> tuple[list[tuple], list[tuple]]:
    """(éléments à noter, groupe de chaque élément)."""
    elements, groupes = [], []
    for i, f in enumerate(banc):
        for cas, cible, d, groupe in cas_du_banc(f["donnees"], retards):
            elements.append(("banc", i, cas, cible, d))
            groupes.append(groupe)
    return elements, groupes


def _leurre_propre(banc: list[dict]) -> int:
    """Les fenêtres où Y porte un pod que la règle de couples_d exclut (la base, rabbitmq,
    le producteur, ts-order-service, la passerelle, une réplique)."""
    import couples_d
    mauvaises = 0
    for f in banc:
        inst = f["donnees"]["nodes"]["instance"]
        for n, h in zip(inst["names"], inst["hosts"]):
            ident = tn.identite("instance", n)
            if h == Y_LEURRE and (n.startswith(couples_d.BASE) or ident in couples_d.EXCLUS or ident == couples_d.CONSO):
                mauvaises += 1
                break
    return mauvaises


# ------------------------------------------------------------------------------
# Le rapport
# ------------------------------------------------------------------------------
def _colonne(groupe: tuple) -> str:
    famille, cas, _, d = groupe
    if d == HORS_CRITERE:
        return "400 (hors)"
    return {"entrant dans T": "entrant", "sortant de T": "sortant"}.get(famille, cas)


COLONNES = ("M", "R", "M+Y", "Y", "entrant", "sortant", "400 (hors)")


def _agreger(res: list, groupes: list[tuple], k: int, n_banc: int) -> dict:
    """{groupe : [au rang 1, total, Counter des premiers]} pour la combinaison k."""
    out: dict = {}
    for (rangs, _, premiers), groupe in zip(res[n_banc:], groupes):
        case = out.setdefault(groupe, [0, 0, Counter()])
        case[0] += rangs[k] == 1
        case[1] += 1
        case[2][premiers[k]] += 1
    return out


def rapport(campagnes: Path, runs: Path, graines: int, epoques: int, version: str = gnn.VERSION) -> int:
    debut_total = time.perf_counter()
    gnn._un_fil()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    try:
        gnn.charger_echelle(fige)
        fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
        b = donnees_du_banc(fen)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    banc, val = b["banc"], b["val"]
    print("# Le banc de pannes fabriquées du GNN et le choix de la grille B/H/V — écrit par graphe_en/gnn_banc.py, "
          "ne pas éditer à la main.")
    print(f"# campagnes lues : {', '.join(fautifs_module.SERIES)}")
    print("# VALIDATION seule (juge.validation) : modèles appris sur ses normales d'apprentissage ; vrai test "
          "(« hors ») jamais lu ; ni C, ni D, ni leurs essais")
    print(f"# graines 0 à {graines - 1} ; {epoques} époques ; étape 1 « complet », version {version} "
          f"({gnn.VERSIONS[version]})"
          + ("" if graines >= 5 else f" ; ATTENTION : {graines} graine(s) seulement, la spécification en "
                                     f"demande 5 (choix indicatif)"))
    duree_app = gnn.preparer(fen, fige, graines, ("complet",), epoques, version)
    etapes = {g: gnn.etape1(fen, fige, "complet", g, epoques, version) for g in range(graines)}
    e0 = etapes[0]
    print(f"# étape 1 : {e0.infos[0]['parametres']} paramètres, {e0.infos[0]['fenetres']} normales "
          f"d'apprentissage, {len(e0.campagnes)} plis ; empreintes des modèles finals : "
          + ", ".join(f"graine {g} {e.empreinte[:16]}" for g, e in etapes.items()))
    print(f"# fenêtres du banc : {len(banc)} normales jeu == « test » de la validation ("
          + ", ".join(f"{c} {n}" for c, n in Counter(f["campagne"] for f in banc).items()) + ")")
    tas = [ligne[0] for ligne in b["files"]]
    print(f"# file pleine : la ligne {FILE} de {len(b['files'])} fenêtres de panne lenteur d'apprentissage "
          f"({', '.join(sorted({f['campagne'] for f in b['lentes']}))} ; tas de {min(tas):g} à {max(tas):g}), "
          f"la i-ème pour la fenêtre de rang i modulo {len(b['files'])}")
    print(f"# leurre Y = {Y_LEURRE} (règle de couples_d, journal écart 4) ; pressions portées aux médianes de la "
          f"machine fautive de {len(b['hotes'])} fenêtres hote d'apprentissage : "
          + ", ".join(f"{c} {v:.4g}" for c, v in b["pressions"].items())
          + f" ; fenêtres où Y porte un pod exclu par la règle : {_leurre_propre(banc)}")
    elements, groupes = elements_du_banc(banc)
    n_val = len(val)
    tout = [("val", j) for j in range(n_val)] + elements
    par_groupe = Counter(groupes)
    reps = Counter(g[2] for g in groupes if g[1] == "R" and g[3] == RETARDS[0])
    entrants = Counter(g[2] for g in groupes if g[1] == "entrant" and g[3] == RETARDS[0])
    print("# X : " + ", ".join(f"{x} (réplique dans {reps.get(x, 0)} fenêtres)" for x in XS)
          + " ; cibles « entrant » (au moins 3 pods sources) : "
          + ", ".join(f"{c} ({n} fenêtres)" for c, n in sorted(entrants.items()))
          + " ; « sortant » : chaque réplique")
    dans = sum(n for g, n in par_groupe.items() if g[3] != HORS_CRITERE)
    print(f"# {len(elements)} fenêtres fabriquées ({dans} dans le critère, {len(elements) - dans} à 400 ms hors "
          f"critère ; le cas Y ne dépend ni de X ni de d : compté une fois) ; plus {n_val} fenêtres du test de la "
          f"validation pour G_val et le top-1")
    res, duree_notes, cumul = noter_tout(etapes, fige, banc, val, b["files"], b["pressions"], tout)
    print(f"# durées : apprentissage {duree_app:.0f} s ({graines * (1 + len(e0.campagnes))} entraînements, "
          f"{gnn.PROCESSUS} processus au plus) ; notation {duree_notes:.0f} s de temps réel, {cumul:.0f} s de calcul "
          f"({1000 * cumul / (len(tout) * graines):.0f} ms par fenêtre et 30 combinaisons)")

    # Les mesures, par combinaison et par graine.
    g_val, t1, total, par_col, accuse = {}, {}, {}, {}, {}
    for k, nom in enumerate(NOMS):
        g_val[nom], t1[nom], total[nom] = [], [], []
        par_col[nom] = {c: [] for c in COLONNES}
        for g in range(graines):
            r = res[g]
            acc = gval(val, r, k)
            accuse[(nom, g)] = acc
            g_val[nom].append(len(acc))
            t1[nom].append(top1(val, r, k))
            agr = _agreger(r, groupes, k, n_val)
            total[nom].append(sum(v[0] for gr, v in agr.items() if gr[3] != HORS_CRITERE))
            for c in COLONNES:
                par_col[nom][c].append(sum(v[0] for gr, v in agr.items() if _colonne(gr) == c))
    # Les familles de l'écart E-3 (§13) : part au rang 1, par graine.
    base = set(dc.cles_base(fige))
    tot_e3 = {c: sum(n for g, n in par_groupe.items() if colonne_e3(g, base) == c) for c in COLONNES_E3}
    parts = {}
    for k, nom in enumerate(NOMS):
        parts[nom] = {c: [] for c in COLONNES_E3}
        for g in range(graines):
            agr = _agreger(res[g], groupes, k, n_val)
            for c in COLONNES_E3:
                parts[nom][c].append(sum(v[0] for gr, v in agr.items() if colonne_e3(gr, base) == c) / tot_e3[c])
    choix_ancien, etat, lignes_choix = choisir(g_val, t1, total)
    choix, mins_e3, lignes_e3 = choisir_e3(g_val, t1, parts)
    n_inj = sum(1 for v in dc.par_injection(val).values() if not v[0]["jamais_vue"])
    n_app = len(_apprises(val))
    tot_col = {c: sum(n for g, n in par_groupe.items() if _colonne(g) == c) for c in COLONNES}

    print(f"\n== 1. la grille (médiane des graines [min–max] ; graine 0 seule si une graine)")
    print(f"G_val : injections de test des causes connues ({n_inj}) où la base est première dans une majorité "
          f"stricte des fenêtres, par graine ; top-1 : fenêtres de panne à cause apprise ({n_app}), sans alarme ; "
          f"banc : cas au rang 1 hors 400 ms (sur {dans})")
    tete = f"{'combinaison':<12}{'G_val':>10}{'top-1':>12}{'crit. 2':>9}{'banc':>14}" + "".join(
        f"{c + '/' + str(tot_col[c]):>18}" for c in COLONNES)
    print(tete)
    for nom in NOMS:
        c1, raisons = etat[nom]
        gv = "/".join(str(n) for n in g_val[nom]) + (" ok" if c1 else " NON")
        print(f"{nom:<12}{gv:>10}{_case(t1[nom]):>12}{('ok' if not raisons else 'NON'):>9}{_case(total[nom]):>14}"
              + "".join(f"{_case(par_col[nom][c]):>18}" for c in COLONNES))

    print(f"\n== 1 bis. les familles de l'écart E-3 (§13) : part des cas au rang 1, médiane des graines [min–max]")
    print(f"F_C : « entrant dans » {', '.join(sorted(base))}, d = {', '.join(map(str, RETARDS))} ({tot_e3['F_C']} cas) ; "
          f"F_D : M et M+Y, X = {', '.join(XS)} ({tot_e3['F_D']}) ; F_R : R et « sortant » ({tot_e3['F_R']}) ; "
          f"min : min(F_C, F_D, F_R) des médianes. À titre d'information, hors critère : Y ({tot_e3['Y']}), "
          f"« entrant » ts-order-service ({tot_e3['ent. order']}), et les trois familles à 400 ms")
    print(f"{'combinaison':<12}{'G_val':>6}{'top-1':>7}" + "".join(f"{c:>18}" for c in FAMILLES_E3)
          + f"{'min':>7}" + "".join(f"{c:>18}" for c in COLONNES_E3[3:]))

    def _part(v: list) -> str:
        t = f"{_med(v):.2f}"
        return t + (f" [{min(v):.2f}–{max(v):.2f}]" if min(v) != max(v) else "")
    for nom in NOMS:
        print(f"{nom:<12}{('ok' if etat[nom][0] else 'NON'):>6}{_med(t1[nom]):>7g}"
              + "".join(f"{_part(parts[nom][c]):>18}" for c in FAMILLES_E3) + f"{mins_e3[nom]:>7.3f}"
              + "".join(f"{_part(parts[nom][c]):>18}" for c in COLONNES_E3[3:]))

    print("\n== 2. le choix de l'écart E-3 (§13, dans l'ordre) : c'est le CHOIX")
    print("\n".join(lignes_e3))
    print(f"CHOIX = {json.dumps(choix, ensure_ascii=False)}"
          + ("" if graines >= 5 else f"   (sur {graines} graine(s) : indicatif, à refaire sur 5)"))

    print("\n== 2 bis. pour comparaison : l'ancien choix du §3.5 (remplacé par le §13)")
    print("\n".join(lignes_choix))
    for nom in NOMS:
        if etat[nom][1]:
            print(f"  {nom} écartée au critère 2 : {' ; '.join(etat[nom][1])}")
    print(f"ancien choix §3.5 = {json.dumps(choix_ancien, ensure_ascii=False)} (min(F_C, F_D, F_R) "
          f"{mins_e3[gnn.nom_choix(choix_ancien)]:.3f})")

    nom_c, nom_a, nom_p = gnn.nom_choix(choix), gnn.nom_choix(choix_ancien), gnn.nom_choix(MINIMAUX)
    titres = ((nom_c, "le choix, §13"), (nom_a, "l'ancien choix, §3.5"), (nom_p, "le plus simple"))
    for numero, nom in zip(("3", "3 bis", "3 ter"), dict.fromkeys((nom_c, nom_a, nom_p))):
        k = NOMS.index(nom)
        role = " ; ".join(t for n, t in titres if n == nom)
        print(f"\n== {numero}. le détail de {nom} ({role}), graine 0 : "
              f"au rang 1 / fenêtres, et la réponse la plus souvent première")
        agr = _agreger(res[0], groupes, k, n_val)
        for gr in sorted(agr, key=lambda x: (x[0], CAS.index(x[1]), x[2], x[3])):
            n1, n, prem = agr[gr]
            haut, fois = prem.most_common(1)[0]
            haut = tn.identite(*haut.split(":", 1))
            print(f"  {gr[0]:<15}{gr[1]:<9}{gr[2]:<30}{('d=' + str(gr[3])) if gr[3] else '':<7}"
                  f"{n1:>4}/{n:<4} premier le plus souvent : {haut} ({fois})"
                  + ("   [hors critère]" if gr[3] == HORS_CRITERE else ""))
        acc = accuse[(nom, 0)]
        print(f"  G_val, graine 0 : la base première dans {len(acc)} injections"
              + (f" ({', '.join(f'{c}#{i}' for c, i in acc)})" if acc else ""))

    print("\n== 4. G_val : les injections qui accusent la base, par combinaison qui ne tient pas (graine 0)")
    rien = True
    for nom in NOMS:
        acc = accuse[(nom, 0)]
        if acc:
            rien = False
            print(f"  {nom:<12}" + ", ".join(f"{c}#{i}" for c, i in acc))
    if rien:
        print("  aucune")
    print(f"\n# durée totale {time.perf_counter() - debut_total:.0f} s")
    return 0


# ------------------------------------------------------------------------------
# --verifier
# ------------------------------------------------------------------------------
def _cellules(donnees: dict) -> dict:
    """{(nœud|flèche, bloc, ligne, colonne) : valeur} de toute la fenêtre."""
    out = {}
    for k, b in donnees["nodes"].items():
        for i, ligne in enumerate(b["X"]):
            for j, v in enumerate(ligne):
                out[("n", k, i, b["columns"][j])] = v
    for r, e in donnees["edges"].items():
        for i, ligne in enumerate(e["X"]):
            for j, v in enumerate(ligne):
                out[("e", r, i, e["columns"][j])] = v
    return out


def _structure(donnees: dict) -> tuple:
    return (json.dumps({k: {c: v for c, v in b.items() if c != "X"} for k, b in donnees["nodes"].items()}, sort_keys=True),
            json.dumps({r: {c: v for c, v in e.items() if c != "X"} for r, e in donnees["edges"].items()}, sort_keys=True))


def _changees(avant: dict, apres: dict) -> set:
    a, b = _cellules(avant), _cellules(apres)
    return {c for c in a if a[c] != b[c]}


def _permises(donnees: dict, cas: str, cible, Y: str) -> set:
    """Les cellules que le cas a le droit de changer, écrites à part d'après la spécification."""
    inst = donnees["nodes"]["instance"]
    E = donnees["edges"]
    out = set()
    lat = lambda r, j: {("e", r, j, c) for c in LATENCES}
    pod = lambda i, cols: {("n", "instance", i, c) for c in cols}
    iq = donnees["nodes"]["queue"]["names"].index(FILE)
    file_ = {("n", "queue", iq, c) for c in donnees["nodes"]["queue"]["columns"]}
    if cas in ("M", "R", "M+Y"):
        reps = repliques(donnees, cible)
        for i in reps:
            out |= pod(i, TRAITEMENT)
            out |= {x for j, s in enumerate(E["queries"]["source"]) if s == i for x in lat("queries", j)}
            out |= {("e", "consumes", j, "rate") for j, t in enumerate(E["consumes"]["target"]) if t == i}
        out |= file_
    if cas in ("M", "M+Y"):
        sur_x = {i for i, h in enumerate(inst["hosts"]) if h == cible}
        for j, s in enumerate(E["queries"]["source"]):
            if s in sur_x:
                out |= lat("queries", j) | pod(s, TRAITEMENT + REQUETE)
        interro = {s for s in E["queries"]["source"] if s in sur_x}
        for j, (s, t) in enumerate(zip(E["calls"]["source"], E["calls"]["target"])):
            if t in interro:
                out |= lat("calls", j) | pod(s, TRAITEMENT + REQUETE)
    if cas in ("Y", "M+Y"):
        ih = donnees["nodes"]["host"]["names"].index(Y)
        out |= {("n", "host", ih, c) for c in PRESSIONS}
    if cas == "entrant":
        t = inst["names"].index(cible)
        for r in gnn.APPELS:
            for j, (s, tt) in enumerate(zip(E[r]["source"], E[r]["target"])):
                if tt == t:
                    out |= lat(r, j) | pod(s, TRAITEMENT + REQUETE)
        out |= file_
    if cas == "sortant":
        t = inst["names"].index(cible)
        for r in gnn.APPELS:
            out |= {x for j, s in enumerate(E[r]["source"]) if s == t for x in lat(r, j)}
        out |= pod(t, TRAITEMENT) | file_
    return out


def _t5(banc: list[dict], files: list, pressions: dict) -> tuple[bool, str]:
    """fabriquer ne change que les cellules prévues ; réplique de X = avant + 5d ; l'entrée est intacte."""
    soucis, n = [], 0
    for i, f in list(enumerate(banc))[:: max(1, len(banc) // 4)][:4]:
        avant = f["donnees"]
        empreinte = json.dumps(avant, sort_keys=True, default=str)
        inst = avant["nodes"]["instance"]
        pt = inst["columns"].index("process_time_p50")
        for cas, cible, d, _ in cas_du_banc(avant):
            apres = fabriquer(avant, cas, cible, d, Y_LEURRE, file=files[i % len(files)], pressions=pressions)
            n += 1
            ch = _changees(avant, apres)
            ou = f"{f['id']} {cas} {cible} d={d}"
            if _structure(avant) != _structure(apres):
                soucis.append(f"{ou} : la structure a changé")
            if not ch:
                soucis.append(f"{ou} : rien n'a changé")
            hors = ch - _permises(avant, cas, cible, Y_LEURRE)
            if hors:
                soucis.append(f"{ou} : {len(hors)} cellules hors du prévu, dont {sorted(hors, key=str)[0]}")
            if cas in ("M", "R", "M+Y"):
                for r in repliques(avant, cible):
                    for c in TRAITEMENT:
                        j = inst["columns"].index(c)
                        if inst["X"][r][j] is not None and apres["nodes"]["instance"]["X"][r][j] != inst["X"][r][j] + 5 * d:
                            soucis.append(f"{ou} : la réplique {c} n'est pas avant + 5d")
                    q = avant["edges"]["queries"]
                    for j, s in enumerate(q["source"]):
                        if s == r:
                            lp = q["columns"].index("latency_p50")
                            if q["X"][j][lp] is not None and apres["edges"]["queries"]["X"][j][lp] != q["X"][j][lp] + d:
                                soucis.append(f"{ou} : une queries de la réplique n'est pas avant + d")
                    c = avant["edges"]["consumes"]
                    for j, t in enumerate(c["target"]):
                        if t == r and inst["X"][r][pt] is not None and c["X"][j][0] is not None and \
                                apres["edges"]["consumes"]["X"][j][0] != min(c["X"][j][0], 1000.0 / (inst["X"][r][pt] + 6 * d)):
                            soucis.append(f"{ou} : la capacité de la réplique n'est pas min(rate, 1000/(p50+6d))")
                h = avant["nodes"]["host"]
                ix = h["names"].index(cible)
                if apres["nodes"]["host"]["X"][ix] != h["X"][ix]:
                    soucis.append(f"{ou} : les nombres de la machine X ont changé")
                calls = avant["edges"]["calls"]
                for j, (s, t) in enumerate(zip(calls["source"], calls["target"])):
                    if inst["hosts"][s] == cible and inst["hosts"][t] != cible and \
                            apres["edges"]["calls"]["X"][j] != calls["X"][j]:
                        soucis.append(f"{ou} : une flèche calls qui sort de X a changé")
                q = avant["edges"]["queries"]
                for j, s in enumerate(q["source"]):
                    if inst["hosts"][s] != cible and apres["edges"]["queries"]["X"][j] != q["X"][j]:
                        soucis.append(f"{ou} : un appelant de la base hors de X a changé")
            if cas in ("M", "M+Y"):
                iq = avant["nodes"]["queue"]["names"].index(FILE)
                if apres["nodes"]["queue"]["X"][iq] != files[i % len(files)]:
                    soucis.append(f"{ou} : la file n'est pas la ligne lenteur")
            if cas == "M+Y":
                seul_m = _changees(avant, fabriquer(avant, "M", cible, d, file=files[i % len(files)]))
                seul_y = _changees(avant, fabriquer(avant, "Y", None, 0, Y_LEURRE, pressions=pressions))
                if ch != seul_m | seul_y:
                    soucis.append(f"{ou} : M+Y n'est pas M plus Y")
            if cas == "sortant":
                t = inst["names"].index(cible)
                if any(inst["X"][t][inst["columns"].index(c)] is not None
                       and apres["nodes"]["instance"]["X"][t][inst["columns"].index(c)]
                       != inst["X"][t][inst["columns"].index(c)] + 5 * d for c in TRAITEMENT):
                    soucis.append(f"{ou} : T n'est pas avant + 5d")
            if cas == "entrant":
                t = inst["names"].index(cible)
                for r in gnn.APPELS:
                    e = avant["edges"][r]
                    lp = e["columns"].index("latency_p50")
                    for j, tt in enumerate(e["target"]):
                        if tt == t and e["X"][j][lp] is not None and apres["edges"][r]["X"][j][lp] != e["X"][j][lp] + d:
                            soucis.append(f"{ou} : une flèche entrante de T n'est pas avant + d")
        if json.dumps(avant, sort_keys=True, default=str) != empreinte:
            soucis.append(f"{f['id']} : l'entrée a été modifiée")
    return not soucis, f"{n} fenêtres fabriquées sur 4 fenêtres du banc, tous les cas et d = 75 à 400" + (
        f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else "")


def _t10() -> tuple[bool, str]:
    """Le choix du §3.5 sur des tables inventées, dont la réponse se lit à la main."""
    soucis = []
    zero = {n: [0, 0] for n in NOMS}
    plat = {n: [10, 10] for n in NOMS}
    # 1) tout admissible, le banc à égalité partout : la plus simple.
    c, _, _ = choisir(zero, plat, {n: [5, 5] for n in NOMS})
    if gnn.nom_choix(c) != "B1/H0/V0":
        soucis.append(f"égalité partout : {gnn.nom_choix(c)} au lieu de B1/H0/V0")
    # 2) B4/H1/V1 a le meilleur banc, mais G_val tombe pour une graine : B3/H1/V0 (le second) l'emporte.
    banc = {n: [5, 5] for n in NOMS}
    banc["B4/H1/V1"], banc["B3/H1/V0"], banc["B5/H2/V1"] = [9, 9], [8, 8], [8, 8]
    gv = dict(zero)
    gv["B4/H1/V1"] = [0, 1]
    c, _, _ = choisir(gv, plat, banc)
    if gnn.nom_choix(c) != "B3/H1/V0":
        soucis.append(f"critère 1 : {gnn.nom_choix(c)} au lieu de B3/H1/V0")
    # 3) B3/H1/V0 perd au top-1 contre B3/H0/V0 (sa remontée ramenée au plus simple) : écartée ; reste B5/H2/V1.
    t1 = dict(plat)
    t1["B3/H1/V0"] = [9, 9]
    c, etat, _ = choisir(gv, t1, banc)
    if gnn.nom_choix(c) != "B5/H2/V1" or not etat["B3/H1/V0"][1]:
        soucis.append(f"critère 2 : {gnn.nom_choix(c)} au lieu de B5/H2/V1")
    # 4) la médiane des graines, pas le maximum : [0, 20, 1] vaut 1.
    banc2 = {n: [2, 2, 2] for n in NOMS}
    banc2["B2/H0/V0"] = [0, 20, 1]
    c, _, _ = choisir({n: [0, 0, 0] for n in NOMS}, {n: [3, 3, 3] for n in NOMS}, banc2)
    if gnn.nom_choix(c) != "B1/H0/V0":
        soucis.append(f"médiane : {gnn.nom_choix(c)} au lieu de B1/H0/V0")
    # 5) rien d'admissible : B1/H0/V0.
    c, _, _ = choisir({n: [1] for n in NOMS}, {n: [3] for n in NOMS}, {n: [3] for n in NOMS})
    if gnn.nom_choix(c) != "B1/H0/V0":
        soucis.append(f"aucune admissible : {gnn.nom_choix(c)}")
    return not soucis, "5 tables inventées (égalité, critère 1, critère 2, médiane, aucune admissible)" + (
        f" ; {'; '.join(soucis)}" if soucis else "")


def _t12() -> tuple[bool, str]:
    """La règle de l'écart E-3 (§13) sur des tables inventées, et les familles des groupes."""
    soucis = []
    zero = {n: [0, 0, 0] for n in NOMS}
    t1 = {n: [10, 10, 10] for n in NOMS}

    def parts_(defaut=(0.2, 0.2, 0.2), **autres):
        p = {n: {c: [0.0] * 3 for c in COLONNES_E3} for n in NOMS}
        for n in NOMS:
            for f, v in zip(FAMILLES_E3, autres.get(n.replace("/", "_"), defaut)):
                p[n][f] = [v] * 3 if not isinstance(v, list) else v
        return p
    # 1) tout égal : la plus simple.
    c, _, _ = choisir_e3(zero, t1, parts_())
    if gnn.nom_choix(c) != "B1/H0/V0":
        soucis.append(f"égalité : {gnn.nom_choix(c)}")
    # 2) le min compte, pas la somme : B5/H2/V1 a F_C = F_D = 0.9 mais F_R = 0.1 ; B3/H1/V0 fait 0.4 partout.
    p = parts_(B5_H2_V1=(0.9, 0.9, 0.1), B3_H1_V0=(0.4, 0.4, 0.4))
    c, mins, _ = choisir_e3(zero, t1, p)
    if gnn.nom_choix(c) != "B3/H1/V0" or abs(mins["B5/H2/V1"] - 0.1) > 1e-12:
        soucis.append(f"min : {gnn.nom_choix(c)}")
    # 3) G_val tombe pour une graine sur le meilleur : le suivant.
    gv = dict(zero)
    gv["B3/H1/V0"] = [0, 1, 0]
    p = parts_(B3_H1_V0=(0.6, 0.6, 0.6), B4_H1_V1=(0.5, 0.5, 0.5))
    c, _, _ = choisir_e3(gv, t1, p)
    if gnn.nom_choix(c) != "B4/H1/V1":
        soucis.append(f"G_val : {gnn.nom_choix(c)}")
    # 4) à 0,05 près, le top-1 départage : B2/H0/V1 (0.46, top-1 20) bat B3/H1/V0 (0.50, top-1 10) ;
    #    B4/H0/V0 (0.44, top-1 30) est hors tolérance.
    p = parts_(B3_H1_V0=(0.5, 0.5, 0.5), B2_H0_V1=(0.46, 0.9, 0.9), B4_H0_V0=(0.44, 0.9, 0.9))
    t = dict(t1)
    t["B2/H0/V1"], t["B4/H0/V0"] = [20, 20, 20], [30, 30, 30]
    c, _, _ = choisir_e3(zero, t, p)
    if gnn.nom_choix(c) != "B2/H0/V1":
        soucis.append(f"tolérance : {gnn.nom_choix(c)}")
    # 5) la médiane des graines : F_R [0, 0.9, 0.1] vaut 0.1.
    p = parts_(B2_H0_V0=(0.9, 0.9, [0.0, 0.9, 0.1]), B1_H1_V0=(0.3, 0.3, 0.3))
    c, _, _ = choisir_e3(zero, t1, p)
    if gnn.nom_choix(c) != "B1/H1/V0":
        soucis.append(f"médiane : {gnn.nom_choix(c)}")
    # 6) rien ne tient : B1/H0/V0 ; et le seuil d'arrêt est dit.
    c, _, lignes = choisir_e3({n: [1] for n in NOMS}, {n: [3] for n in NOMS},
                              {n: {f: [0.9] for f in COLONNES_E3} for n in NOMS})
    if gnn.nom_choix(c) != "B1/H0/V0":
        soucis.append(f"aucune : {gnn.nom_choix(c)}")
    _, _, lignes = choisir_e3(zero, t1, parts_())
    if not any("NON ATTEINT" in x for x in lignes):
        soucis.append("le seuil d'arrêt 0,5 n'est pas signalé")
    # 7) les familles des groupes.
    base = {"instance:tsdb-mysql-0"}
    attendu = {("machine", "M", "workers0", 75): "F_D", ("machine", "M+Y", "workers5", 300): "F_D",
               ("machine", "R", "workers2", 150): "F_R", ("sortant de T", "sortant", "réplique de workers0", 75): "F_R",
               ("entrant dans T", "entrant", "instance:tsdb-mysql-0", 300): "F_C",
               ("entrant dans T", "entrant", "instance:ts-order-service", 300): "ent. order",
               ("machine", "Y", Y_LEURRE, 0): "Y", ("machine", "M", "workers0", 400): "400 F_D",
               ("entrant dans T", "entrant", "instance:tsdb-mysql-0", 400): "400 F_C",
               ("entrant dans T", "entrant", "instance:ts-order-service", 400): None}
    for g, c in attendu.items():
        if colonne_e3(g, base) != c:
            soucis.append(f"famille de {g} : {colonne_e3(g, base)} au lieu de {c}")
    return not soucis, "7 tables inventées (égalité, min, G_val, tolérance 0,05, médiane, aucune, arrêt) et " \
                       f"{len(attendu)} groupes classés" + (f" ; {'; '.join(soucis)}" if soucis else "")


class _Repondeur:
    """Une réponse de décision_c pour une combinaison, sur l'étape 1 donnée (pour dc.garde)."""

    def __init__(self, e1, choix):
        self.e1, self.choix = e1, choix

    def repondre(self, donnees):
        scores, s, _ = gnn.noter_noeuds(self.e1.sortie(donnees), self.e1.calage, self.choix)
        return {"alarme": False, "cause": "normale", "scores": scores}


def verifier(campagnes: Path, runs: Path, version: str = gnn.VERSION) -> int:
    gnn._un_fil()
    debut = time.perf_counter()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    gnn.charger_echelle(fige)
    fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
    b = donnees_du_banc(fen)
    banc, val = b["banc"], b["val"]
    resultats = {}

    # T11 : le terrain est la validation seule.
    faux = [f["id"] for f in banc + val if f["jeu"] != "test" or f["temps"] == "test"]
    faux += [f["id"] for f in b["lentes"] + b["hotes"] if f["jeu"] != "apprentissage" or f["temps"] == "test"]
    resultats["T11 la validation seule (jamais « hors »)"] = (
        not faux, f"{len(banc)} fenêtres du banc et {len(val)} de la validation notées : jeu « test » de la validation, "
                  f"aucune du vrai test ; files et pressions de l'apprentissage de la validation"
                  + (f" ; fautives : {faux[:3]}" if faux else ""))

    # T5 : le générateur.
    resultats["T5 fabriquer ne change que le prévu"] = _t5(banc, b["files"], b["pressions"])

    # T10 : le choix.
    resultats["T10 le choix du §3.5"] = _t10()
    resultats["T12 le choix de l'écart E-3 (§13)"] = _t12()

    # Un petit modèle (2 époques) pour la notation.
    petit = gnn._petit_jeu(fen)
    gnn.preparer(petit, fige, graines=1, variantes=("complet",), epoques=2, version=version)
    e1 = gnn.etape1(petit, fige, "complet", 0, 2, version)
    print(f"# version {version} : {gnn.VERSIONS[version]}")

    # T8 : la notation factorisée de la grille = gnn.noter_noeuds, combinaison par combinaison.
    pire, n8 = 0.0, 0
    essais = [f["donnees"] for f in val[:: max(1, len(val) // 3)][:3]]
    f0 = banc[0]["donnees"]
    essais += [fabriquer(f0, cas, cible, d, Y_LEURRE, file=b["files"][0], pressions=b["pressions"])
               for cas, cible, d, _ in cas_du_banc(f0, (150,))]
    for donnees in essais:
        s = gnn.residus(e1.modele, donnees)
        g = scores_grille(s, e1.calage)
        for ch in gnn.grille():
            sc, _, _ = gnn.noter_noeuds(s, e1.calage, ch)
            pire = max(pire, max(abs(sc[c] - float(x)) for c, x in zip(s.cles(), g[gnn.nom_choix(ch)])))
            n8 += 1
    resultats["T8 la grille notée comme gnn.noter_noeuds"] = (pire == 0.0, f"{n8} cas ({len(essais)} fenêtres, "
                                                                            f"30 combinaisons) ; plus grand écart {pire:.1e}")

    # T9 : les processus rendent ce que rend le processus principal (top-1, G_val, rangs du banc).
    # G_val (gnn.base_en_tete) est plus stricte que dc.garde en cas d'égalité en tête : les
    # trois combinaisons comparées ici n'en ont aucune.
    elements = [("val", j) for j in range(len(val))]
    fabr = [("banc", i, cas, cible, d) for i in range(2) for cas, cible, d, _ in cas_du_banc(banc[i]["donnees"], (150,))]
    res, duree, cumul = noter_tout({0: e1}, fige, banc, val, b["files"], b["pressions"], elements + fabr)
    r0 = res[0]
    soucis = []
    for nom in ("B1/H0/V0", "B4/H1/V1", "B5/H2/V1"):
        k = NOMS.index(nom)
        ch = dict(zip(("bout", "remontee", "explication"), nom.split("/")))
        rep = _Repondeur(e1, ch)
        reponses = {f["id"]: rep.repondre(f["donnees"]) for f in val}
        _, chiffres = juge.noter(val, reponses)
        if chiffres["top-1 causes apprises"][0] != top1(val, r0, k):
            soucis.append(f"{nom} : top-1 {top1(val, r0, k)} contre juge.noter {chiffres['top-1 causes apprises'][0]}")
        with contextlib.redirect_stdout(io.StringIO()):
            _, tient = dc.garde(val, fige, 1, [(nom, lambda fen_, g, rep=rep: rep, False)])
        if tient[nom][0] != (len(gval(val, r0, k)) == 0):
            soucis.append(f"{nom} : G_val {len(gval(val, r0, k))} injections contre decision_c.garde {tient[nom][0]}")
        for el, (rangs, _, premiers) in zip(fabr, r0[len(elements):]):
            _, i, cas, cible, d = el
            donnees = fabriquer(banc[i]["donnees"], cas, cible, d, Y_LEURRE, file=b["files"][i % len(b["files"])],
                                pressions=b["pressions"])
            sc, _, diag = gnn.noter_noeuds(gnn.residus(e1.modele, donnees), e1.calage, ch)
            att = attendue(banc[i]["donnees"], cas, cible, Y_LEURRE)
            if rangs[k] != juge.rang(att, sc, juge.noeuds(donnees)) or premiers[k] != diag["premier"]:
                soucis.append(f"{nom} : {banc[i]['id']} {cas} {cible} : rang {rangs[k]} contre "
                              f"{juge.rang(att, sc, juge.noeuds(donnees))}")
    resultats["T9 processus = processus principal"] = (
        not soucis, f"{len(val)} fenêtres de validation et {len(fabr)} fabriquées, 3 combinaisons contre juge.noter, "
                    f"decision_c.garde et gnn.noter_noeuds ; {1000 * cumul / len(elements + fabr):.0f} ms par fenêtre"
        + (f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else ""))

    echecs = 0
    for nom, (ok, detail) in sorted(resultats.items(), key=lambda x: int(x[0].split()[0][1:])):
        print(f"{nom:<44} {'réussi' if ok else 'ÉCHEC'}  ({detail})")
        echecs += not ok
    print(f"# {time.perf_counter() - debut:.0f} s")
    print("TOUT PASSE" if not echecs else f"{echecs} ÉCHEC(S)")
    return 0 if not echecs else 1


# ------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    graines, epoques, mode, version = 5, gnn.EPOQUES, "banc", gnn.VERSION
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--verifier":
                mode = "verifier"
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--epoques":
                epoques = int(args.pop(0))
                if epoques < 1:
                    raise ValueError
            elif a == "--version":
                version = args.pop(0)
                if version not in gnn.VERSIONS:
                    raise ValueError
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    if mode == "verifier":
        return verifier(campagnes, runs, version)
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(campagnes, runs, graines, epoques, version)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / gnn.nom_sortie(SORTIE, version)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
