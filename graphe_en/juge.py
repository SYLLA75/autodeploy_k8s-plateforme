"""
Le juge commun : lit les graphes figés, étiquette chaque minute, coupe
apprentissage et test, et note les réponses d'un témoin ou du GNN.

    ./.venv/bin/python juge.py [options] [campagne ...]

Phase B.2. Tous les témoins de la phase B, puis le GNN de la phase E, passent
par ce fichier : mêmes minutes, mêmes étiquettes, même coupure, même notation.
Il applique les règles écrites dans fautifs.py (« COMMENT ON JUGE »), fixées le
26 sept. 2026 avant tout calcul des témoins ; il n'en ajoute aucune.

CE QUE LIT LE JUGE

Chaque campagne nommée (sans nom : les dix des deux séries, fautifs.SERIES) :
son déroulé (campagne.yaml), et les fenêtres de SON graphe figé (le run nommé
en tête de lecture.txt), refusé s'il n'est pas conforme au gel (gel.py).

L'ÉTIQUETTE DE CHAQUE MINUTE (règles de ligne_de_base.py, reproduites à
l'identique et contrôlées contre lui)

  panne          entièrement dans une injection confirmée : sa cause et ses
                 fautifs (fautifs.py)
  a_cheval       à cheval sur une injection ou un retrait            écartée
  non_confirmee  dans une injection non confirmée                    écartée
  vidange        la première fenêtre après un retrait, puis chacune
                 tant que le tas de food_delivery dépasse 10 messages écartée
  normale        tout le reste

LA COUPURE, par le temps : la dernière injection de chaque campagne, avec les
fenêtres depuis dix minutes avant elle, est le test ; une campagne sans
injection donne son dernier tiers. Une cause « jamais vue » (base, reseau par
défaut) est jugée sur toutes ses injections : ses fenêtres de panne sont
toutes au test, et la bonne cause y est « inconnue ». Les fenêtres de saine-09
sont marquées « vues » : la mise à l'échelle figée a été calée sur elles.

CE QU'UN TÉMOIN REND, pour chaque fenêtre qu'on lui donne (clé : fen["id"]) :

    {"alarme": True | False,
     "cause": "blocage" | … | "normale" | "inconnue",
     "scores": {"instance:<pod>": 3.2, "host:workers0": 0.4,
                "queue:food_delivery": 1.1, …}}      plus haut = plus suspect

Les clés des nœuds viennent de noeuds(fenêtre), toujours par le NOM (jamais
l'uid du champ « keys »). Le fautif est classé parmi TOUS les nœuds de la
fenêtre : un nœud absent des scores, ou noté None ou NaN (de n'importe quel
type, float32 compris), passe dernier. Les égalités sont départagées contre le
témoin : le fautif passe après tous ceux qui ont le même score. L'ordre des
nœuds n'intervient jamais. Une réponse mal formée est refusée (alarme qui
n'est pas True ou False, cause qui n'est pas un texte, scores qui ne sont pas
un dictionnaire, nœud inconnu, score qui n'est pas un nombre).

LA NOTE (noter), sur les fenêtres de test non écartées :
  détection     fenêtres de panne avec alarme ; fausses alertes : fenêtres
                normales avec alarme, saine-09 à part (« vues »)
  cause         fenêtres de panne avec la bonne cause
  fautif        top-1 et top-3 : un fautif parmi les k premiers ; sans tenir
                compte de l'alarme (mesure principale), puis « avec alarme »
                (une panne manquée compte comme fausse) ; la charge n'y entre
                pas. Par cause, par série, causes jamais vues à part, et selon
                que le fautif l'était déjà à l'apprentissage pour la même cause
                ou non : un classement qui ne lit rien devine un fautif déjà
                vu, jamais un nouveau
  par injection une injection est trouvée si la majorité de ses fenêtres de
                panne au test le sont (à égalité : non trouvée)
La bonne cause de chaque fenêtre est fixée par lire(), d'après tout
l'apprentissage lu ; noter() ne la recalcule pas sur la liste qu'on lui passe.

CE QUE FAIT LE SCRIPT

Affiche et écrit <campagnes>/etiquettes.txt : les comptes par campagne, puis
chaque campagne en tranches de minutes consécutives de même étiquette. Contrôle
que ses étiquettes et sa coupure sont celles de ligne_de_base.py, minute par
minute. Puis éprouve le juge sur des témoins factices dont la note est connue
d'avance (l'oracle à 100 % ; « sans avis », « vide » et un fautif noté NaN
float32 à 0), vérifie qu'il refuse des réponses mal formées, et note
« a priori », qui ne lit aucune donnée : le plancher à battre.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --consumer <prefixe>   les répliques du consommateur (défaut ts-delivery-service-)
  --drain <n>            tas sous lequel la file compte comme vidée (défaut 10)
  --help                 ce texte

Code de sortie 0 si tout est lu, conforme et identique à ligne_de_base.py, et
si chaque essai du juge donne le résultat attendu ; 1 sinon ; 2 sur un
mauvais argument. Bibliothèque standard seulement.
"""
from __future__ import annotations

import contextlib
import io
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fautifs as fautifs_module
import gel

HERE = Path(__file__).resolve().parent
FILE = "food_delivery"
JAMAIS_VUES = {"base", "reseau"}
PREMIERE = set(fautifs_module.SERIES[:5])
SECONDE = set(fautifs_module.SERIES[5:])
ECARTEES = {"a_cheval", "non_confirmee", "vidange"}


class Refus(Exception):
    """Une campagne que le juge ne peut pas lire honnêtement."""


# ------------------------------------------------------------------------------
# Lire et étiqueter
# ------------------------------------------------------------------------------
def _cle(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def noeuds(donnees: dict) -> list[str]:
    """
    Les clés de tous les nœuds d'une fenêtre, dans la forme que le juge attend :
    « instance:<nom du pod> », « queue:<nom> », « host:<nom> ».

    Toujours par le NOM. Le champ « keys » des fenêtres (et keys_ de graph.pt)
    porte l'uid du pod pour les instances : un témoin qui noterait par uid
    serait refusé.
    """
    return [_cle(k, n) for k in ("instance", "queue", "host") for n in donnees["nodes"][k]["names"]]


def campagne(nom: str, campagnes: Path, runs: Path, fige: dict, tag: dict,
             consommateur: str, videe: float, jamais_vues: set[str]) -> list[dict]:
    """Les fenêtres d'une campagne, étiquetées, coupées, avec leurs données."""
    dossier = campagnes / nom
    run_nom = fautifs_module.run_de(dossier / "lecture.txt")
    if not run_nom:
        raise Refus(f"{nom} : lecture.txt ne nomme pas son run")
    run = runs / run_nom.split("/", 1)[1]
    if not run.is_dir():
        raise Refus(f"{nom} : run introuvable {run}")
    ecarts, _ = gel.run(run, fige, tag)
    if ecarts:
        raise Refus(f"{nom} : graphe non conforme au gel : {ecarts[0]}")
    injections, soucis = fautifs_module.injections(dossier / "campagne.yaml")
    if soucis:
        raise Refus(f"{nom} : déroulé : {soucis[0]}")
    donnees = fautifs_module.fenetres(run)
    if not donnees:
        raise Refus(f"{nom} : aucune fenêtre")

    fen = []
    for i, d in enumerate(donnees, 1):
        debut = datetime.fromtimestamp(d["window"]["start_ns"] / 1e9, tz=timezone.utc)
        fin = datetime.fromtimestamp(d["window"]["end_ns"] / 1e9, tz=timezone.utc)
        fen.append({"id": f"{nom}/{i:04d}", "campagne": nom, "numero": i, "debut": debut,
                    "fin": fin, "vue": nom == "saine-09",
                    "serie": "1" if nom in PREMIERE else "2" if nom in SECONDE else "hors séries",
                    "etiquette": "normale", "cause": None, "fautifs": [], "injection": None,
                    "jeu": "apprentissage", "donnees": d})

    # Même boucle que ligne_de_base.label_windows : la dernière injection qui
    # touche la fenêtre décide.
    for k, p in enumerate(injections, 1):
        for f in fen:
            if f["debut"] >= p["debut"] and f["fin"] <= p["fin"]:
                if p["confirmee"]:
                    f.update(etiquette="panne", cause=p["cause"], injection=k)
                else:
                    f.update(etiquette="non_confirmee", cause=None, injection=None)
            elif f["debut"] < p["debut"] < f["fin"] or f["debut"] < p["fin"] < f["fin"]:
                f.update(etiquette="a_cheval", cause=None, injection=None)
    for p in injections:
        garde = 1
        for f in (f for f in fen if f["debut"] >= p["fin"]):
            if f["etiquette"] != "normale":
                continue
            tas = _valeur(f["donnees"], "queue", FILE, "backlog")
            if (tas is not None and tas > videe) or garde > 0:
                f["etiquette"] = "vidange"
                garde -= 1
            else:
                break

    # Les fautifs, injection par injection, avec les instances vues pendant elle.
    for k, p in enumerate(injections, 1):
        if not p["confirmee"]:
            continue
        dedans = [f for f in fen if f["injection"] == k]
        instances = {n for f in dedans for n in f["donnees"]["nodes"]["instance"]["names"]}
        try:
            noms, _ = fautifs_module.fautifs(p, fige, consommateur, instances)
        except ValueError as e:
            raise Refus(f"{nom} : injection {k} : {e}") from e
        sorte = fautifs_module.SORTE[p["cause"]]
        for f in dedans:
            f["fautifs"] = [_cle(sorte, n) for n in noms]

    # La coupure.
    if injections:
        limite = injections[-1]["debut"] - timedelta(minutes=10)
        for f in fen:
            if f["debut"] >= limite:
                f["jeu"] = "test"
    else:
        for f in fen[len(fen) * 2 // 3:]:
            f["jeu"] = "test"
    for f in fen:
        if f["etiquette"] == "panne" and f["cause"] in jamais_vues:
            f["jeu"] = "test"
    return fen


def _valeur(d: dict, kind: str, name: str, column: str):
    bloc = d["nodes"][kind]
    if name not in bloc["names"]:
        return None
    return bloc["X"][bloc["names"].index(name)][bloc["columns"].index(column)]


def lire(noms: list[str], campagnes: Path | None = None, runs: Path | None = None,
         consommateur: str = "ts-delivery-service-", videe: float = 10.0,
         jamais_vues: set[str] = JAMAIS_VUES) -> list[dict]:
    """Toutes les fenêtres des campagnes nommées, dans l'ordre. Lève Refus."""
    campagnes = campagnes or HERE.parent / "campagnes"
    runs = runs or HERE / "runs"
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        raise Refus(ecarts_ref[0])
    tag = gel._empreintes_du_tag(fige)
    fen = []
    for nom in noms:
        fen += campagne(nom, campagnes, runs, fige, tag, consommateur, videe, jamais_vues)
    # La bonne cause de chaque fenêtre, fixée ici une fois pour toutes, d'après
    # TOUT l'apprentissage lu : noter() ne la recalcule jamais sur la liste qu'on
    # lui passe (une liste de test seule rendrait toute cause « inconnue »).
    apprises = causes_apprises(fen)
    # Un fautif « déjà vu » l'a été pour la MÊME cause à l'apprentissage.
    deja = {(f["cause"], c) for f in fen if f["etiquette"] == "panne" and f["jeu"] == "apprentissage"
            for c in f["fautifs"]}
    for f in fen:
        f["attendue"] = cause_attendue(f, apprises)
        f["fautif_vu"] = any((f["cause"], c) in deja for c in f["fautifs"])
        # Pour une cause jamais vue : son fautif l'a-t-il été pour une AUTRE cause ?
        # (un classement qui se souvient des anciens fautifs le devinerait)
        f["fautif_vu_ailleurs"] = any(c in {d for _, d in deja} for c in f["fautifs"])
    return fen


def causes_apprises(fen: list[dict]) -> set[str]:
    return {f["cause"] for f in fen if f["etiquette"] == "panne" and f["jeu"] == "apprentissage"}


def cause_attendue(f: dict, apprises: set[str]) -> str:
    if f["etiquette"] != "panne":
        return "normale"
    return f["cause"] if f["cause"] in apprises else "inconnue"


# ------------------------------------------------------------------------------
# Noter
# ------------------------------------------------------------------------------
def _val(v) -> float:
    """Un score en nombre ; absent, None ou NaN (de quelque type que ce soit)
    vaut moins que tout."""
    if v is None:
        return -math.inf
    x = float(v)
    return -math.inf if math.isnan(x) else x


def rang(fautifs: list[str], scores: dict, tous: list[str]) -> int:
    """
    Le rang du mieux placé des fautifs parmi TOUS les nœuds de la fenêtre,
    égalités départagées contre le témoin.

    Un nœud que le témoin n'a pas noté vaut moins que tout, comme un score None
    ou NaN : un témoin qui ne note rien, ou peu de nœuds, ne gagne rien. Le
    fautif passe après chaque autre nœud dont le score est au moins le sien :
    c'est le pire rang qu'un départage des égalités pourrait lui donner.
    """
    meilleur = max(_val(scores.get(c)) for c in fautifs)
    return 1 + sum(1 for k in tous if k not in fautifs and _val(scores.get(k)) >= meilleur)


def verifier(f: dict, rep) -> None:
    """Refuse une réponse mal formée au lieu de la lire à l'avantage du témoin."""
    if not isinstance(rep, dict):
        raise ValueError(f"{f['id']} : la réponse n'est pas un dictionnaire")
    a = rep.get("alarme")
    if not (a is True or a is False or type(a).__name__ == "bool_"):
        raise ValueError(f"{f['id']} : alarme {a!r}, il faut True ou False (pas une probabilité, "
                         f"pas un texte)")
    if not isinstance(rep.get("cause"), str):
        raise ValueError(f"{f['id']} : cause {rep.get('cause')!r}, il faut un texte")
    scores = rep.get("scores")
    if not isinstance(scores, dict):
        raise ValueError(f"{f['id']} : scores {type(scores).__name__}, il faut un dictionnaire "
                         f"(vide s'il le faut)")
    inconnus = set(scores) - set(noeuds(f["donnees"]))
    if inconnus:
        raise ValueError(f"{f['id']} : nœuds inconnus dans les scores, dont {sorted(inconnus)[0]} "
                         f"(clés : juge.noeuds, par le nom)")
    for k, v in scores.items():
        if isinstance(v, (bool, str)) or type(v).__name__ == "bool_":
            raise ValueError(f"{f['id']} : score de {k} = {v!r}, il faut un nombre ou None")
        try:
            float(v) if v is not None else None
        except (TypeError, ValueError):
            raise ValueError(f"{f['id']} : score de {k} = {v!r}, il faut un nombre ou None") from None


def _part(n: int, total: int) -> str:
    return f"{n}/{total}" + (f" ({100 * n / total:.0f} %)" if total else "")


def noter(fen: list[dict], reponses: dict, titre: str = "") -> tuple[list[str], dict]:
    """
    La note d'un témoin sur les fenêtres de test non écartées, en texte et en
    nombres. `reponses` : {fen["id"]: {"alarme", "cause", "scores"}}. Une
    fenêtre de test sans réponse, ou une réponse mal formée, est une erreur.
    `fen` : des fenêtres rendues par lire() (la bonne cause y est déjà fixée).
    """
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in ECARTEES]
    manque = [f["id"] for f in test if f["id"] not in reponses]
    if manque:
        raise ValueError(f"{len(manque)} fenêtres de test sans réponse, dont {manque[0]}")
    for f in test:
        verifier(f, reponses[f["id"]])
    lignes = [f"== {titre}" if titre else "=="]
    chiffres: dict = {}

    pannes = [f for f in test if f["etiquette"] == "panne"]
    normales = [f for f in test if f["etiquette"] == "normale"]
    alarme = lambda f: bool(reponses[f["id"]]["alarme"])
    bonne_cause = lambda f: reponses[f["id"]]["cause"] == f["attendue"]

    # Détection et fausses alertes.
    det = sum(1 for f in pannes if alarme(f))
    chiffres["detection"] = (det, len(pannes))
    lignes.append(f"détection      {_part(det, len(pannes))} fenêtres de panne avec alarme")
    for nom, groupe in (("non vues", [f for f in normales if not f["vue"]]),
                        ("vues (saine-09)", [f for f in normales if f["vue"]])):
        fa = sum(1 for f in groupe if alarme(f))
        chiffres[f"fausses alertes {nom}"] = (fa, len(groupe))
        detail = ", ".join(f"{c} {sum(1 for f in groupe if f['campagne'] == c and alarme(f))}/"
                           f"{sum(1 for f in groupe if f['campagne'] == c)}"
                           for c in dict.fromkeys(f["campagne"] for f in groupe))
        lignes.append(f"fausses alertes {nom} : {_part(fa, len(groupe))}   {detail}")

    # Cause.
    bonne = sum(1 for f in pannes if bonne_cause(f))
    chiffres["cause"] = (bonne, len(pannes))
    jamais = sorted({f["cause"] for f in pannes if f["attendue"] == "inconnue"})
    lignes.append(f"cause          {_part(bonne, len(pannes))} fenêtres de panne bien nommées"
                  + (f"  (jamais vues : {', '.join(jamais)}, bonne réponse « inconnue »)" if jamais else ""))
    # L'épreuve décisive, à part : une cause jamais vue, détectée ? dite « inconnue » ?
    for c in jamais:
        groupe = [f for f in pannes if f["cause"] == c and f["attendue"] == "inconnue"]
        d = sum(1 for f in groupe if alarme(f))
        b = sum(1 for f in groupe if bonne_cause(f))
        chiffres[f"detection jamais vue : {c}"] = (d, len(groupe))
        chiffres[f"cause jamais vue : {c}"] = (b, len(groupe))
        lignes.append(f"  jamais vue : {c:<10} détection {_part(d, len(groupe))}, "
                      f"« inconnue » {_part(b, len(groupe))}")

    # Fautif : causes apprises et jamais vues à part ; par cause, par série, et
    # selon que le fautif l'était déjà à l'apprentissage (un classement qui ne lit
    # rien peut deviner un fautif déjà vu, jamais un nouveau).
    avec_fautif = [f for f in pannes if f["fautifs"]]
    rangs = {f["id"]: rang(f["fautifs"], reponses[f["id"]]["scores"], noeuds(f["donnees"]))
             for f in avec_fautif}
    lignes.append(f"fautif{'':<36}{'top-1':>17}{'top-3':>17}{'top-1 alarme':>17}{'top-3 alarme':>17}")
    apprises = [f for f in avec_fautif if f["attendue"] != "inconnue"]
    groupes = [("causes apprises", apprises)]
    groupes += [(c, [f for f in apprises if f["cause"] == c]) for c in sorted({f["cause"] for f in apprises})]
    groupes += [(f"série {s}", [f for f in apprises if f["serie"] == s]) for s in ("1", "2", "hors séries")]
    groupes += [("fautif déjà vu", [f for f in apprises if f["fautif_vu"]]),
                ("fautif nouveau", [f for f in apprises if not f["fautif_vu"]])]
    for c in jamais:
        groupe = [f for f in avec_fautif if f["attendue"] == "inconnue" and f["cause"] == c]
        groupes += [(f"jamais vue : {c}", groupe),
                    (f"jamais vue {c}, fautif déjà vu ailleurs", [f for f in groupe if f["fautif_vu_ailleurs"]]),
                    (f"jamais vue {c}, jamais fautif", [f for f in groupe if not f["fautif_vu_ailleurs"]])]
    for nom, groupe in groupes:
        if not groupe:
            continue
        valeurs = []
        for k, avec_alarme in ((1, False), (3, False), (1, True), (3, True)):
            n = sum(1 for f in groupe if rangs[f["id"]] <= k and (alarme(f) or not avec_alarme))
            chiffres[f"top-{k}{' avec alarme' if avec_alarme else ''} {nom}"] = (n, len(groupe))
            valeurs.append(_part(n, len(groupe)))
        lignes.append(f"  {nom:<40}" + "".join(f"{v:>17}" for v in valeurs))

    # Par injection : la majorité de ses fenêtres de panne au test.
    injections: dict = {}
    for f in pannes:
        injections.setdefault((f["campagne"], f["injection"]), []).append(f)
    lignes.append("par injection  (trouvée si la majorité de ses fenêtres de test le sont ; "
                  "a = avec alarme)")
    cles = ["détectée", "cause", "top-1", "top-3", "top-1 a", "top-3 a"]
    trouvees = dict.fromkeys(cles, 0)
    avec = 0
    for (c, k), groupe in sorted(injections.items()):
        maj = lambda ok: 2 * sum(1 for f in groupe if ok(f)) > len(groupe)
        r = {"détectée": maj(alarme), "cause": maj(bonne_cause)}
        if groupe[0]["fautifs"]:
            avec += 1
            for j in (1, 3):
                r[f"top-{j}"] = maj(lambda f: rangs[f["id"]] <= j)
                r[f"top-{j} a"] = maj(lambda f: rangs[f["id"]] <= j and alarme(f))
        for cle in cles:
            trouvees[cle] += bool(r.get(cle))
        oui = lambda x: "—" if x is None else ("oui" if x else "non")
        lignes.append(f"  {c:<12} injection {k}  {groupe[0]['cause']:<8} {len(groupe):>3} fenêtres  "
                      + "  ".join(f"{cle} {oui(r.get(cle))}" for cle in cles))
    n = len(injections)
    chiffres["injections"] = {k: (v, avec if k.startswith("top") else n) for k, v in trouvees.items()}
    lignes.append("  total : " + ", ".join(f"{k} {v}/{avec if k.startswith('top') else n}"
                                          for k, v in trouvees.items()))
    return lignes, chiffres


# ------------------------------------------------------------------------------
# Le script : bilan des étiquettes, contrôle, essai du juge
# ------------------------------------------------------------------------------
def tranches(fen: list[dict]) -> list[str]:
    out, debut = [], 0
    for i in range(1, len(fen) + 1):
        cle = lambda f: (f["etiquette"], f["cause"], f["jeu"])
        if i == len(fen) or cle(fen[i]) != cle(fen[debut]):
            a, b = fen[debut], fen[i - 1]
            quoi = a["etiquette"] + (f" {a['cause']}" if a["cause"] else "")
            if a["fautifs"]:
                quoi += " — " + ", ".join(x.split(":", 1)[1].replace("ts-delivery-service-79c46f4f45-", "…")
                                          for x in a["fautifs"])
            out.append(f"  {a['debut']:%H:%M}–{b['fin']:%H:%M}  {i - debut:>3}  {a['jeu']:<13} {quoi}")
            debut = i
    return out


def controle(fen: list[dict], campagnes: Path, noms: list[str], consommateur: str,
             videe: float) -> list[str]:
    """Les étiquettes et la coupure de ligne_de_base.py, minute par minute."""
    import ligne_de_base
    ecarts = []
    for nom in noms:
        notes: list[str] = []
        with contextlib.redirect_stdout(io.StringIO()):
            lignes = ligne_de_base.label_windows(nom, campagnes / nom, consommateur, videe, notes)
        ref = {r["window"]: r for r in lignes}
        miens = [f for f in fen if f["campagne"] == nom]
        for f in miens:
            w = f["donnees"]["window"]["start_ns"] // 60_000_000_000
            r = ref.get(w)
            mien = f["cause"] if f["etiquette"] == "panne" else \
                ("normal" if f["etiquette"] == "normale" else f["etiquette"])
            if r is None:
                ecarts.append(f"{f['id']} : absente de ligne_de_base.py")
            elif r["truth"] != mien or r["test"] != (f["jeu"] == "test"):
                ecarts.append(f"{f['id']} : {mien}/{f['jeu']} ici, {r['truth']}/"
                              f"{'test' if r['test'] else 'apprentissage'} dans ligne_de_base.py")
        if len(ref) != len(miens):
            ecarts.append(f"{nom} : {len(miens)} fenêtres ici, {len(ref)} dans ligne_de_base.py")
    return ecarts


class _NaN32:
    """Un NaN qui n'est pas un float Python, comme numpy.float32 ou un tenseur."""
    def __float__(self):
        return math.nan


def factices(fen: list[dict]) -> dict[str, dict]:
    """
    Des témoins dont la note est connue d'avance, pour éprouver le juge ; et
    « a priori », qui ne lit aucune donnée : il classe les nœuds par le nombre
    de fois qu'ils ont été fautifs à l'apprentissage. C'est le plancher à
    battre : il devine un fautif déjà vu, jamais un nouveau.
    """
    deja: dict[str, int] = {}
    for f in fen:
        if f["etiquette"] == "panne" and f["jeu"] == "apprentissage":
            for c in f["fautifs"]:
                deja[c] = deja.get(c, 0) + 1
    t = {"oracle": {}, "sans avis": {}, "vide": {}, "NaN non float": {}, "a priori": {}}
    for f in fen:
        tous = noeuds(f["donnees"])
        t["oracle"][f["id"]] = {"alarme": f["etiquette"] == "panne", "cause": f["attendue"],
                                "scores": {n: (1.0 if n in f["fautifs"] else 0.0) for n in tous}}
        t["sans avis"][f["id"]] = {"alarme": False, "cause": "normale", "scores": {n: 0.0 for n in tous}}
        t["vide"][f["id"]] = {"alarme": False, "cause": "normale", "scores": {}}
        t["NaN non float"][f["id"]] = {"alarme": False, "cause": "normale",
                                       "scores": {n: (_NaN32() if n in f["fautifs"] else 1.0) for n in tous}}
        t["a priori"][f["id"]] = {"alarme": False, "cause": "normale",
                                  "scores": {n: float(deja.get(n, 0)) for n in tous}}
    return t


def _refuse(fen: list[dict], reponses: dict) -> bool:
    try:
        noter(fen, reponses)
    except ValueError:
        return True
    return False


def rapport(noms: list[str], campagnes: Path, runs: Path, consommateur: str, videe: float) -> int:
    try:
        fen = lire(noms, campagnes, runs, consommateur, videe)
    except Refus as e:
        print(f"REFUS  {e}")
        return 1
    print("# Étiquettes des minutes — écrit par graphe_en/juge.py, ne pas éditer à la main.")
    print("# Règles : fautifs.py, « COMMENT ON JUGE » (26 sept. 2026) ; graphes figés, contrôlés par gel.py.")
    print(f"# causes apprises : {', '.join(sorted(causes_apprises(fen)))} ; "
          f"jamais vues par défaut : {', '.join(sorted(JAMAIS_VUES))}")
    print()
    sortes = ["normale", "panne", "vidange", "a_cheval", "non_confirmee"]
    print(f"{'campagne':<12}{'run':<17}" + "".join(f"{s:>14}" for s in sortes) + f"{'test':>7}")
    for nom in noms:
        miens = [f for f in fen if f["campagne"] == nom]
        run = fautifs_module.run_de(campagnes / nom / "lecture.txt")
        print(f"{nom:<12}{run.split('/')[1]:<17}"
              + "".join(f"{sum(1 for f in miens if f['etiquette'] == s):>14}" for s in sortes)
              + f"{sum(1 for f in miens if f['jeu'] == 'test'):>7}")
    print(f"{'total':<29}" + "".join(f"{sum(1 for f in fen if f['etiquette'] == s):>14}" for s in sortes)
          + f"{sum(1 for f in fen if f['jeu'] == 'test'):>7}")
    for jeu in ("apprentissage", "test"):
        garde = [f for f in fen if f["jeu"] == jeu and f["etiquette"] not in ECARTEES]
        par = ", ".join(f"{c} {sum(1 for f in garde if (f['cause'] or 'normale') == c)}"
                        for c in ["normale"] + sorted({f["cause"] for f in garde if f["cause"]}))
        print(f"{jeu} (sans les écartées) : {len(garde)} fenêtres — {par}")

    problemes = 0
    print("\n# contrôle contre ligne_de_base.py (étiquette et coupure, minute par minute)")
    ecarts = controle(fen, campagnes, noms, consommateur, videe)
    for e in ecarts[:10]:
        print(f"  ÉCART  {e}")
    print(f"  {'identiques' if not ecarts else f'{len(ecarts)} écart(s)'} sur {len(fen)} fenêtres")
    problemes += bool(ecarts)

    print("\n# essai du juge sur des témoins factices, dont la note est connue d'avance")
    t = factices(fen)
    notes = {}
    for nom, titre in (("oracle", "alarme, cause et fautif justes : tout à 100 %"),
                       ("sans avis", "même score pour tous, jamais d'alarme : tout à 0"),
                       ("vide", "aucun score : le fautif est dernier, tout à 0"),
                       ("NaN non float", "fautif noté NaN d'un type non float : dernier, tout à 0"),
                       ("a priori", "ne lit aucune donnée : le plancher à battre")):
        lignes, notes[nom] = noter(fen, t[nom], f"{nom} : {titre}")
        print("\n".join(lignes))
    fautif = lambda n: [v for k, v in notes[n].items() if k.startswith("top-")]
    verdicts = {
        "oracle": all(v[0] == v[1] for k, v in notes["oracle"].items()
                      if k not in ("injections",) and not k.startswith("fausses"))
                  and all(v[0] == 0 for k, v in notes["oracle"].items() if k.startswith("fausses")),
        "sans avis": notes["sans avis"]["detection"][0] == 0 and all(v[0] == 0 for v in fautif("sans avis")),
        "vide": all(v[0] == 0 for v in fautif("vide")),
        "NaN non float": all(v[0] == 0 for v in fautif("NaN non float")),
    }
    # Des réponses mal formées doivent être refusées, jamais lues à l'avantage du témoin.
    def abime(champ, valeur):
        return {i: {**r, champ: valeur} for i, r in t["oracle"].items()}
    un = next(f for f in fen if f["jeu"] == "test" and f["fautifs"])
    par_uid = {i: dict(r) for i, r in t["oracle"].items()}
    uid = un["donnees"]["nodes"]["instance"]["keys"][0]
    par_uid[un["id"]] = {**par_uid[un["id"]], "scores": {f"instance:{uid}": 1.0}}
    verdicts["refus : alarme texte"] = _refuse(fen, abime("alarme", "False"))
    verdicts["refus : alarme probabilité"] = _refuse(fen, abime("alarme", 0.03))
    verdicts["refus : scores absents"] = _refuse(fen, {i: {k: v for k, v in r.items() if k != "scores"}
                                                     for i, r in t["oracle"].items()})
    verdicts["refus : nœud par uid"] = _refuse(fen, par_uid)
    print()
    for nom, ok in verdicts.items():
        print(f"  {nom:<28} {'comme attendu' if ok else 'ÉCART'}")
    problemes += sum(1 for ok in verdicts.values() if not ok)

    print("\n# chaque campagne en tranches (début–fin UTC, fenêtres, jeu, étiquette)")
    for nom in noms:
        print(f"\n{nom}")
        print("\n".join(tranches([f for f in fen if f["campagne"] == nom])))
    print(f"\n{'JUGE PRÊT' if not problemes else f'{problemes} PROBLÈME(S)'}")
    return 0 if not problemes else 1


def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    consommateur, videe = "ts-delivery-service-", 10.0
    noms: list[str] = []
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            elif a == "--consumer":
                consommateur = args.pop(0)
            elif a == "--drain":
                videe = float(args.pop(0))
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    noms = noms or fautifs_module.SERIES
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(noms, campagnes, runs, consommateur, videe)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / "etiquettes.txt"
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
