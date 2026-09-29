"""
Ce qui décidera sur la base lente (phase C) et sur les jumeaux (phase D), écrit
AVANT C et D.

    ./.venv/bin/python decision_c.py --garde [--machines X1,X2] [options]
    ./.venv/bin/python decision_c.py --ouvrir <campagne C> --jumeaux <campagne D> [options]
    ./.venv/bin/python decision_c.py --empreintes [options]
    ./.venv/bin/python decision_c.py --empreintes --variante u|u1|u2 [options]
    ./.venv/bin/python decision_c.py --ouvrir <campagne C> --jumeaux <campagne D> --variante u|u1|u2 [options]

Les règles sont celles du journal : « Ce qui décidera sur C » (27 sept.), « Ce qui
décidera sur D », la décision 2 précisée et la table de l'axe (d) (28 sept.,
J 1537-1553, 1685-1713) ; ce fichier les calcule sans rien régler. Il importe
juge.py et les témoins figés (étiquette temoins-figes) sans les modifier ; la
règle avec l'idée « machine » (temoin_machine.py, étiquette temoin-machine-fige)
ne sert qu'à D (methodes) ; le GNN (gnn.py, étiquette gnn-fige) n'entre dans la
liste qu'à --ouvrir, ou quand l'étiquette gnn-fige existe (GNN_SPEC.md §8 étape
7) : aucun --garde ne regarde le test avec le GNN avant le gel. Le GNN a deux
réglages (écart E-2, J 2119-2126) : « GNN, sans exemples » (l'étape 1 seule, qui
porte la thèse) et « GNN, avec exemples » ; chacun a son entrée au budget de la
règle (« GNN, <réglage>, budget de la règle ») et n'est comparé qu'aux versions de
la règle du même réglage (sans contre sans, avec contre avec) : un verdict par
réglage. La décision 1 et la ligne 0 de l'axe (d) restent communes.

--garde : la garde de spécificité G, calculée tout de suite sur les deux séries.
  Pour chaque méthode, chaque réglage et chaque graine : sur combien des
  injections de test des causes connues tsdb-mysql-0 est-il premier dans plus de
  la moitié des fenêtres de panne (sans tenir compte de l'alarme) ? G tient pour
  une graine si c'est sur aucune. Écrit <campagnes>/decision-garde.txt.
  Avec --machines X1,X2 : en plus, la garde G_D de D pour chaque machine X
  (J 1547-1550 : « dès que les couples sont connus et avant d'ouvrir quoi que ce
  soit ») : X à la place de tsdb-mysql-0, sauf une injection hote dont X serait
  le fautif, avec les versions « machine » de la règle et le plancher « a priori »
  restreint aux machines. Écrit alors <campagnes>/decision-garde-d.txt.
  Une fois gnn-fige posée (le GNN entre alors dans la liste), la garde s'écrit dans
  decision-garde-gnn.txt (decision-garde-d-gnn.txt), une seule fois : la garde
  commitée avant le gel n'est jamais réécrite. Avec ce code, la garde avec le GNN
  (v12) est refusée tant que gnn-fige-2 n'est pas bien posée (gnn.raisons_scelle_2) :
  elle lit le test des deux séries avec l'alarme de u et le classement de u1 ; la
  première ouverture n'est regardée qu'après gnn-fige-2 (GNN_SPEC.md §17–§19).

--ouvrir <C> --jumeaux <D> : la lecture de C et de D, UNE fois, dans la même
  lecture (J 1538-1540), quand le GNN est figé. Refusée tant que l'étiquette git
  « gnn-fige » n'existe pas (le scellé), si le code des témoins, du juge et du GNN
  n'est plus celui de leurs étiquettes, si temoin-machine-fige n'est pas
  antérieure au premier instant de D (J 1664-1665), si C ou D a moins de 2
  injections confirmées de sa cause (« base », « reseau ») dans son déroulé (elle
  est à refaire à l'identique, J 1227, 1541-1542 ; C et D s'ouvrent ensemble : rien
  n'est lu), si les empreintes des modèles du GNN recalculées ne sont pas celles
  figées (gnn-fige:graphe_en/gnn-empreintes.txt, §8 étape 8), si une lecture de C
  ou de D est déjà écrite (« chacun passe une seule fois », J 1210), ou si
  --graines n'est pas 5 (graines 0 à 4, J 1237, 1315, 1553). Les méthodes apprennent sur
  les deux séries seules, exactement comme dans leurs sorties figées : les
  minutes normales de C et de D n'entrent dans l'apprentissage de personne.
  Elles répondent sur le test des deux séries (G, G_D, axe (a)) et sur toutes
  les minutes de C et de D. Pour chaque injection :
    compte   confirmée, la file vide avant (tas ≤ 10 la minute d'avant), la file
             qui déborde (tas > 10 dans STRICTEMENT plus de la moitié de ses
             minutes de panne ; égalité : ne déborde pas), et pas d'effondrement
             (deux veilles de suite EN_DEFAUT pendant l'injection, le leader
             perdu, ou un redémarrage de pod de train-ticket ; pour D en plus :
             un signe indirect de machine NotReady, une fenêtre de panne sans le
             nœud host X ou sans la réplique de X) ;
    F        la cible première dans plus de la moitié des fenêtres de panne de
             l'injection, sans tenir compte de l'alarme ; A : la même avec
             l'alarme. Cible : tsdb-mysql-0 pour C ; pour D, la machine X de
             l'injection (nœud host, le fautif du juge), jamais le leurre ;
    minute   la première minute de panne où la méthode sonne ET met la cible
             première, depuis la première minute de panne (« jamais » : plus
             tard que toute minute).
  TROUVE : sur une majorité stricte des graines, F sur une majorité stricte des
  injections qui comptent ET la garde (G pour C, G_D pour tous les X de D), avec
  la même graine. Puis les fausses alertes, la table de l'axe (d) (D), et
  l'ordre des décisions 1 à 3 de C, avec le verdict de chaque réglage du GNN
  contre CHAQUE version de la règle du même réglage qui TROUVE (il perd s'il est
  battu par une seule). Écrit <campagnes>/decision-<C>-<D>.txt, une seule fois.

--empreintes : les empreintes des modèles du GNN (gnn.empreintes, apprises sur les
  normales d'apprentissage des deux séries, comme à --ouvrir ; aucune réponse n'est
  calculée), écrites dans graphe_en/gnn-empreintes.txt, à commiter dans le commit
  de gnn-fige (§8 étape 8) : --ouvrir les relit par git à l'étiquette.

--variante u|u1|u2 : la SECONDE LECTURE (GNN_SPEC.md §17, §18, §19), pour UNE variante
  « GNN unique » (gnn.py, version u, u1 ou u2), figée à l'étiquette gnn-fige-2 avant tout
  regard sur la première. Exception écrite au §17 à « C et D lus une seule fois ». RÈGLE
  FINALE du §19 (qui remplace les règles de choix de §17 et §18, et sa mise à jour de
  16 h 10) : le modèle retenu parmi v12, u, u1 et u2 est choisi par l'utilisateur sur les
  seuls résultats de validation, le choix et son heure écrits au journal avant toute
  lecture de C et D pour une variante unique ; si c'est v12, aucune seconde lecture ;
  sinon UNE seule seconde lecture, pour lui seul, et ses verdicts sont ceux du modèle
  retenu (§19, point 2), avec les mêmes règles. Ce code ne choisit rien : il refuse une
  deuxième seconde lecture, de quelque variante que ce soit. Ci-dessous <v> vaut u, u1
  ou u2.
    --empreintes --variante <v> écrit graphe_en/gnn-empreintes-<v>.txt (gnn.empreintes
                                de la version <v>, avec le nom de la machine), à
                                commiter dans le commit de gnn-fige-2 ;
    --ouvrir <C> --jumeaux <D> --variante <v>
                                la même lecture que --ouvrir (mêmes règles, mêmes
                                refus : code, injections confirmées, graines 5,
                                empreintes), mais : refusée sans les étiquettes
                                gnn-fige ET gnn-fige-2, si gnn-fige-2 n'est pas posée
                                après gnn-fige (ancêtre, autre commit), si gnn-fige-2
                                ne porte pas graphe_en/gnn-empreintes-<v>.txt ou en
                                porte une autre gnn-empreintes-*.txt (une seule
                                variante figée), si graphe_en/ a changé entre gnn-fige
                                et gnn-fige-2 ailleurs que dans gnn.py, gnn_exemples.py,
                                gnn_banc.py, decision_c.py et les gnn-empreintes-<v>.txt,
                                si graphe_en/ a changé depuis gnn-fige-2, si les
                                empreintes recalculées ne sont pas celles de
                                gnn-fige-2:graphe_en/gnn-empreintes-<v>.txt, si la
                                première lecture (decision-<C>-<D>.txt) n'est pas
                                encore écrite ou est vide (son contenu n'est jamais
                                lu : sa taille et son sha256 vont dans l'en-tête), ou
                                si une seconde lecture de C ou de D existe déjà, de
                                quelque variante que ce soit (decision-*-u.txt,
                                decision-*-u1.txt, decision-*-u2.txt). Les seules
                                entrées du GNN sont celles de <v> (« GNN unique, sans
                                exemples »… pour u, « GNN unique u1, sans exemples »…
                                pour u1, « GNN unique u2, sans exemples »… pour u2 :
                                gnn.methodes de la version <v>) ; les témoins, la règle
                                et ses versions machine sont recalculés (identiques à la
                                première lecture). L'en-tête dit en plus les commits de
                                gnn-fige et gnn-fige-2, la taille et le sha256 de la
                                première lecture, la machine, numpy et scikit-learn.
                                Écrit decision-<C>-<D>-<v>.txt, une seule fois.
  --ouvrir sans --variante garde exactement son comportement (v12, gnn-fige,
  gnn-empreintes.txt, decision-<C>-<D>.txt).

comparer() calcule les axes (a), (b), (c) du journal entre le GNN et une version
de la règle ; le GNN y sonne au budget de la règle (« GNN, <réglage>, budget de la
règle », 21/249 ; les versions « machine » gardent ce budget, J 1620). Face à une
version de la règle, TROUVE, F et les minutes du GNN sont lus sur cette même
entrée ; sans adversaire (ligne 1 de l'axe (d), décision 3), sur son seuil propre.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --graines <n>          nombre de graines, à partir de 0 (défaut 5 ; à --ouvrir, 5 seulement)
  --machines <X1,X2>     avec --garde : les machines X de D (couples_d.py)
  --variante u|u1|u2     avec --ouvrir ou --empreintes : la seconde lecture (§17 à §19)
  --no-install           n'installe jamais scikit-learn
  --help                 ce texte

Code de sortie 0 ; 1 si une campagne est refusée, le scellé fermé, le code ou une
empreinte changé, une lecture déjà écrite ou une bibliothèque manque ; 2 sur un
mauvais argument (dont --graines autre que 5 à --ouvrir).
"""
from __future__ import annotations

import ast
import contextlib
import io
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import bootstrap
import fautifs as fautifs_module
import gel
import juge
import temoin_machine as tm
import temoins as temoins_module

HERE = Path(__file__).resolve().parent
TAS_COORDINATION = 10.0      # le même seuil que la vidange du juge (juge.lire, videe)
CONSOMMATEUR = "ts-delivery-service-"   # les répliques (juge.lire, consommateur)
ETIQUETTE_TEMOINS = "temoins-figes"
ETIQUETTE_SCELLE = "gnn-fige"
ETIQUETTE_MACHINE = "temoin-machine-fige"   # la règle avec l'idée « machine », figée avant D
FIGES_TEMOINS = ("temoin_tableau.py", "temoin_noeud.py", "temoin_fleches.py", "temoins.py", "juge.py")
# Les noms du GNN (gnn.methodes, GNN_SPEC.md §6) : seul le complet figé entre dans les
# décisions (J 1262) ; contre la règle il sonne à son budget (J 1248-1250) ; la variante
# « sans aucune arête » (quel que soit son réglage) renvoie à la décision 1 (J 1262-1263)
# et à la ligne 0 de l'axe (d). Deux réglages (écart E-2, J 2119-2126), chacun comparé
# aux versions de la règle du même réglage ; « sans exemples » porte la thèse, il est lu
# en premier.
REGLAGES = ("sans exemples", "avec exemples")
GNN = {r: f"GNN, {r}" for r in REGLAGES}
GNN_REGLE = {r: f"GNN, {r}, budget de la règle" for r in REGLAGES}
GNN_SANS_ARETE = "GNN sans aucune arête"
GRAINES_ECRITES = 5          # graines 0 à 4, écrites avant C et D (J 1237, 1315, 1553)
FICHIER_EMPREINTES = "gnn-empreintes.txt"   # dans graphe_en/, commité avec gnn-fige (§8 étape 8)
PLANCHER_D = "a priori, machines seules"   # le plancher de D (J 1551-1552)
# La seconde lecture (GNN_SPEC.md §17, §18, §19) : UNE variante « GNN unique » (u, u1 ou u2), figée
# à gnn-fige-2 après gnn-fige et avant tout regard sur la première lecture. Ses noms commencent par
# « GNN unique » (u), « GNN unique u1 » ou « GNN unique u2 » (gnn.PREFIXES) ; ses empreintes sont dans
# graphe_en/gnn-empreintes-<variante>.txt. Une seule seconde lecture, quelle que soit la variante.
VARIANTES_GNN = {"u": "GNN unique", "u1": "GNN unique u1", "u2": "GNN unique u2"}
SECTIONS_GNN = {"u": "§17", "u1": "§18", "u2": "§19"}
ETIQUETTE_SCELLE_2 = "gnn-fige-2"
# Ce qui peut changer dans graphe_en/ entre gnn-fige et gnn-fige-2 (relecture B, constat 2) : le code
# du GNN et de la lecture, et les empreintes des variantes uniques.
PERMIS_SCELLE_2 = ("gnn.py", "gnn_exemples.py", "gnn_banc.py", "decision_c.py")


def noms_gnn(variante: str | None = None) -> dict:
    """Les noms du GNN que lisent les décisions : {« propre » : {réglage : nom}, « regle » :
    {réglage : nom au budget de la règle}, « sans_arete » : nom}. Sans variante, GNN,
    GNN_REGLE et GNN_SANS_ARETE (la première lecture, v12) ; pour u, « GNN unique » en tête."""
    if variante is None:
        return {"propre": GNN, "regle": GNN_REGLE, "sans_arete": GNN_SANS_ARETE}
    p = VARIANTES_GNN[variante]
    return {"propre": {r: f"{p}, {r}" for r in REGLAGES}, "regle": {r: f"{p}, {r}, budget de la règle" for r in REGLAGES},
            "sans_arete": f"{p} sans aucune arête"}


def etiquette_scelle(variante: str | None = None) -> str:
    return ETIQUETTE_SCELLE if variante is None else ETIQUETTE_SCELLE_2


def fichier_empreintes(variante: str | None = None) -> str:
    """gnn-empreintes.txt (première lecture) ou gnn-empreintes-<variante>.txt."""
    return FICHIER_EMPREINTES if variante is None else FICHIER_EMPREINTES[:-len(".txt")] + f"-{variante}.txt"


def cles_base(fige: dict) -> list[str]:
    return sorted(juge._cle("instance", n) for n in fige["bases"].values())


def premier(f: dict, rep: dict, base: list[str]) -> bool:
    """La cible (tsdb-mysql-0, ou X pour D) est-elle première dans cette fenêtre,
    égalités contre la méthode ?"""
    return juge.rang(base, rep["scores"], juge.noeuds(f["donnees"])) == 1


def par_injection(fen: list[dict]) -> dict[tuple[str, int], list[dict]]:
    """{(campagne, injection) : ses fenêtres de panne, dans l'ordre du temps}."""
    out: dict[tuple[str, int], list[dict]] = {}
    for f in fen:
        if f["etiquette"] == "panne":
            out.setdefault((f["campagne"], f["injection"]), []).append(f)
    for v in out.values():
        v.sort(key=lambda f: f["debut"])
    return out


def reponses(fabrique, fen_apprentissage: list[dict], a_repondre: list[dict], graine: int) -> dict:
    t = fabrique(fen_apprentissage, graine)
    return {f["id"]: {k: v for k, v in t.repondre(f["donnees"]).items() if not k.startswith("_")}
            for f in a_repondre}


def toutes_reponses(liste: list, fen_apprentissage: list[dict], a_repondre: list[dict],
                    graines: int) -> dict[str, list[dict]]:
    """{méthode : [réponses par graine]} : un apprentissage par méthode et par graine,
    qui répond d'un coup au test des séries, à C et à D (les réponses d'une fenêtre ne
    dépendent pas des autres fenêtres lues)."""
    return {nom: [reponses(fabrique, fen_apprentissage, a_repondre, g) for g in range(graines if hasard else 1)]
            for nom, fabrique, hasard in liste}


class APrioriMachines:
    """
    Le plancher de D (J 1551-1552) : « a priori » (juge.factices) restreint aux
    machines. Ne lit aucune donnée : chaque nœud host est noté par le nombre de ses
    fenêtres fautives à l'apprentissage ; les autres nœuds ne sont pas notés (ils
    passent derniers, juge._val). S'il TROUVE, D ne décide rien.
    """

    def __init__(self, fen: list[dict]):
        self.deja: dict[str, int] = {}
        for f in fen:
            if f["etiquette"] == "panne" and f["jeu"] == "apprentissage":
                for c in f["fautifs"]:
                    if c.startswith("host:"):
                        self.deja[c] = self.deja.get(c, 0) + 1

    def repondre(self, donnees: dict) -> dict:
        return {"alarme": False, "cause": "normale",
                "scores": {k: float(self.deja.get(k, 0)) for k in juge.noeuds(donnees) if k.startswith("host:")}}


def methodes(fige: dict, machine: bool = False, gnn: bool = False,
             variante: str | None = None) -> list[tuple[str, object, bool]]:
    """
    Les témoins figés ; pour D (machine=True), aussi la règle avec l'idée « machine »
    (option B, décidée le 28 sept. avant D). C garde la liste écrite avant C : l'idée
    ne relève jamais le score de la base (elle ne joue qu'après « blocage » ou
    « lenteur », où des répliques sont déjà à 1e9), F, G et TROUVE de C n'en
    changeraient pas. Avec gnn=True, le GNN et ses variantes (gnn.methodes, noms
    commençant par « GNN ») ; gnn.py n'est importé qu'alors (torch), jamais par un
    --garde d'avant le gel. Avec une variante (§17), le GNN est celui de cette version
    seule (gnn.methodes(fige, version=variante)), noms commençant par « GNN unique ».
    """
    out = temoins_module.temoins(fige)
    if machine:
        out += [
            ("règle cause commune + machine, sans exemples", lambda fen, g: tm.Machine(fen, "sans exemples", fige), False),
            ("règle cause commune + machine, avec exemples", lambda fen, g: tm.Machine(fen, "avec exemples", fige), False),
        ]
    if gnn:
        import gnn as gnn_module   # import paresseux : torch n'est chargé qu'une fois le GNN admis
        du_gnn = gnn_module.methodes(fige) if variante is None else gnn_module.methodes(fige, version=variante)
        tete = "GNN" if variante is None else VARIANTES_GNN[variante]
        hors = [n for n, _, _ in du_gnn if not n.startswith(tete)]
        if hors:   # les décisions trient les méthodes par le début de leur nom
            raise ValueError(f"gnn.methodes : noms qui ne commencent pas par « {tete} » : {', '.join(hors)}")
        out += du_gnn
    return out


def _case(valeurs: list, total: int | None = None) -> str:
    m = statistics.median(valeurs)
    texte = f"{m:g}" + (f"/{total}" if total is not None else "")
    if min(valeurs) != max(valeurs):
        texte += f" [{min(valeurs)}–{max(valeurs)}]"
    return texte


def majorite(n: int, total: int) -> bool:
    return 2 * n > total


def sans_structure(nom: str, noms: dict | None = None) -> bool:
    """Les méthodes de la décision 1 : le tableau, le score par nœud, et la variante
    du GNN sans aucune arête (J 1241-1243, 1262-1263)."""
    sans_arete = (noms or noms_gnn())["sans_arete"]
    return nom.startswith("tableau") or nom.startswith("score par nœud") or nom.startswith(sans_arete)


def reglage_de(nom: str) -> str | None:
    """Le réglage d'une version de la règle, lu à la fin de son nom (« …, sans exemples »,
    versions « machine » comprises) ; None s'il n'y en a pas."""
    return next((r for r in REGLAGES if nom.endswith(f", {r}")), None)


def ecart_budget(res: dict, reglage: str, noms: dict | None = None) -> list[str]:
    """Une ligne si TROUVE ou F du GNN diffère entre son seuil propre et le budget de la
    règle (l'alarme peut changer les scores, E-2) : face à la règle, c'est le budget qui est lu."""
    noms = noms or noms_gnn()
    propre, budget = noms["propre"][reglage], noms["regle"][reglage]
    p, b = res.get(propre), res.get(budget)
    if p is not None and b is not None and (p["trouve"] != b["trouve"] or p["n_f"] != b["n_f"]):
        return [f"    (TROUVE ou F de « {propre} » diffère au budget de la règle ; face à la règle, "
                f"c'est « {budget} » qui est lu)"]
    return []


# ------------------------------------------------------------------------------
# La garde G (et G_D), sur les deux séries
# ------------------------------------------------------------------------------
def garde(fen: list[dict], fige: dict, graines: int, liste: list, *, cible: list[str] | None = None,
          quoi: str = "base", reps: dict | None = None, a_priori: bool = True,
          nom_garde: str = "G") -> tuple[list[str], dict[str, list[bool]]]:
    """
    (lignes du rapport, {méthode : [la garde tient ? par graine]}).

    Par défaut G de C : la base, les 8 injections de test des causes connues.
    cible=[« host:X »] : G_D de D pour la machine X (J 1547-1550), sans l'injection
    hote dont X serait le fautif. reps : les réponses déjà calculées
    (toutes_reponses) ; sinon chaque méthode apprend ici. a_priori : la ligne du
    plancher « a priori » du juge (G_D met le plancher des machines dans la liste).
    """
    base = cible or cles_base(fige)
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    injections = {k: v for k, v in par_injection(test).items() if not v[0]["jamais_vue"]
                  and not (cible and v[0]["cause"] == "hote" and sorted(v[0]["fautifs"]) == sorted(cible))}
    lignes = [f"injections de test des causes connues : {len(injections)} "
              f"({', '.join(f'{c}#{k}' for c, k in sorted(injections))})"]
    tient: dict[str, list[bool]] = {}
    w = max([38] + [len(n) for n, _, _ in liste])   # 38 : la largeur d'avant les versions machine
    for nom, fabrique, hasard in liste:
        comptes, detail = [], []
        for g in range(graines if hasard else 1):
            rep = reps[nom][g] if reps is not None else reponses(fabrique, fen, test, g)
            accuse = [k for k, v in injections.items()
                      if majorite(sum(premier(f, rep[f["id"]], base) for f in v), len(v))]
            comptes.append(len(accuse))
            detail.append(accuse)
        tient[nom] = [c == 0 for c in comptes]
        verdict = "tient" if all(tient[nom]) else ("NE TIENT PAS" if not any(tient[nom])
                                                    else f"tient pour {sum(tient[nom])} graines sur {len(comptes)}")
        lignes.append(f"  {nom:<{w}} {quoi} première dans {_case(comptes, len(injections))} injections : "
                      f"{nom_garde} {verdict}")
        vues = sorted({f"{c}#{k}" for d in detail for c, k in d})
        if vues:
            lignes.append(f"  {'':<{w}} (injections accusant {'la base' if quoi == 'base' else quoi} : {', '.join(vues)})")
    if a_priori:
        rep = juge.factices(fen)["a priori"]
        accuse = [k for k, v in injections.items()
                  if majorite(sum(premier(f, rep[f["id"]], base) for f in v), len(v))]
        lignes.append(f"  {'a priori (ne lit rien)':<{w}} {quoi} première dans {len(accuse)}/{len(injections)} "
                      f"injections : {nom_garde} {'tient' if not accuse else 'NE TIENT PAS'}")
    return lignes, tient


def garde_d(fen: list[dict], fige: dict, graines: int, liste: list, machines: list[str],
            reps: dict | None = None) -> tuple[list[str], dict[str, list[bool]]]:
    """G_D pour chaque X (clés « host:X ») ; TROUVE exige G_D pour TOUS les X employés
    (J 1549-1550) : par graine, la conjonction sur les X."""
    lignes: list[str] = []
    par_x = {}
    for x in machines:
        lignes.append(f"-- X = {x}")
        l, par_x[x] = garde(fen, fige, graines, liste, cible=[x], quoi=x, reps=reps, a_priori=False,
                            nom_garde="G_D")
        lignes += l
    tient = {nom: [all(par_x[x][nom][g] for x in machines) for g in range(graines if hasard else 1)]
             for nom, _, hasard in liste}
    return lignes, tient


# ------------------------------------------------------------------------------
# Le scellé et le code
# ------------------------------------------------------------------------------
def _git(*args: str) -> subprocess.CompletedProcess:
    """git lancé depuis la racine du dépôt : les chemins s'écrivent « graphe_en/… »."""
    return subprocess.run(["git", "-C", str(HERE.parent), *args], capture_output=True, text=True)


def etiquette_existe(nom: str) -> bool:
    """L'étiquette git existe-t-elle ? (lecture seule ; faux sans git)"""
    try:
        r = _git("rev-parse", "-q", "--verify", f"refs/tags/{nom}")
    except OSError:
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _sans_main(source: str) -> str:
    arbre = ast.parse(source)
    arbre.body = [n for n in arbre.body if not (isinstance(n, ast.FunctionDef) and n.name == "main")]
    return ast.dump(arbre)


def premier_instant(campagne_yaml: Path) -> datetime | None:
    """Le premier instant du déroulé d'une campagne (None s'il est illisible)."""
    texte = campagne_yaml.read_text() if campagne_yaml.is_file() else ""
    deroule = texte.split("\nderoule:", 1)[1] if "\nderoule:" in texte else ""
    m = re.search(r"instant: (\S+), action:", deroule)
    return datetime.strptime(m.group(1), fautifs_module.TS).replace(tzinfo=timezone.utc) if m else None


def machine_avant_d(campagne_yaml: Path) -> list[str]:
    """J 1664-1665 (« à faire en D.3 ») : le commit de temoin-machine-fige doit être
    antérieur au premier instant du déroulé de D (date du commit, lue par git)."""
    t = _git("log", "-1", "--format=%ct", f"refs/tags/{ETIQUETTE_MACHINE}^{{commit}}").stdout.strip()
    debut = premier_instant(campagne_yaml)
    if not t.isdigit():
        return [f"date du commit de {ETIQUETTE_MACHINE} illisible"]
    if debut is None:
        return [f"{campagne_yaml} : premier instant du déroulé illisible"]
    fige = datetime.fromtimestamp(int(t), tz=timezone.utc)
    if not fige < debut:
        return [f"le commit de {ETIQUETTE_MACHINE} ({fige:%Y-%m-%d %H:%M:%S} UTC) n'est pas antérieur au "
                f"premier instant de {campagne_yaml.parent.name} ({debut:%Y-%m-%d %H:%M:%S} UTC)"]
    return []


def commit_de(etiquette: str) -> str:
    """Le commit d'une étiquette (git rev-parse <étiquette>^{commit}) ; « » si elle n'existe pas."""
    return _git("rev-parse", "-q", "--verify", f"refs/tags/{etiquette}^{{commit}}").stdout.strip()


def scelle_2_mal_pose(variante: str) -> list[str]:
    """
    La seconde lecture (§17 à §19), gnn-fige et gnn-fige-2 existant, gnn-fige ancêtre de
    gnn-fige-2 : ce qui empêche encore de lire.
      - gnn-fige-2 posée sur le commit même de gnn-fige (pas APRÈS lui) ;
      - §18, une seule seconde lecture : gnn-fige-2 doit porter graphe_en/gnn-empreintes-<variante>.txt
        et AUCUNE autre graphe_en/gnn-empreintes-*.txt (sinon deux variantes pourraient être lues) ;
      - relecture B, constat 2 : entre gnn-fige et gnn-fige-2, graphe_en/ ne change que dans
        gnn.py, gnn_exemples.py, gnn_banc.py, decision_c.py et les gnn-empreintes-<u|u1|u2>.txt.
    """
    scelle = etiquette_scelle(variante)
    c1, c2 = commit_de(ETIQUETTE_SCELLE), commit_de(scelle)
    if not c1 or not c2 or c1 == c2:
        return [f"l'étiquette {scelle} n'est pas posée APRÈS {ETIQUETTE_SCELLE} (même commit, ou illisible) : la "
                f"variante {variante} se fige après v12 ({SECTIONS_GNN[variante]})."]
    soucis = []
    voulu = f"graphe_en/{fichier_empreintes(variante)}"
    prefixe = FICHIER_EMPREINTES[:-len(".txt")] + "-"
    r = _git("ls-tree", "-z", "--name-only", c2, "graphe_en/")
    portees = sorted(n for n in r.stdout.split("\0") if n.startswith("graphe_en/" + prefixe) and n.endswith(".txt"))
    if r.returncode != 0 or portees != [voulu]:
        soucis.append(f"{scelle} doit porter {voulu} et aucune autre empreinte de variante unique (§18 : une seule "
                      f"seconde lecture) ; elle porte : {', '.join(portees) or 'aucune'}")
    permis = {f"graphe_en/{x}" for x in PERMIS_SCELLE_2} | {f"graphe_en/{fichier_empreintes(w)}" for w in VARIANTES_GNN}
    r = _git("diff", "-z", "--name-only", "--no-renames", c1, c2, "--", "graphe_en/")
    hors = sorted(n for n in r.stdout.split("\0") if n and n not in permis)
    if r.returncode != 0:
        soucis.append(f"git diff {ETIQUETTE_SCELLE} {scelle} illisible : le changement du code n'est pas contrôlé")
    elif hors:
        soucis.append(f"graphe_en/ a changé entre {ETIQUETTE_SCELLE} et {scelle} hors de "
                      f"{', '.join(sorted(permis))} : {', '.join(hors)}")
    return soucis


def en_tete_seconde_lecture(variante: str, premiere: Path) -> list[str]:
    """
    Ce qui identifie la seconde lecture (relecture B, constats 3 à 5), sans rien lire de la
    première : les commits de gnn-fige et de gnn-fige-2 (une étiquette déplacée se verrait) ;
    la taille et le sha256 de la première lecture (son contenu est haché, jamais lu ni
    affiché) ; la machine, numpy et scikit-learn (torch est sur la ligne du GNN).
    """
    import hashlib
    import platform
    from importlib import metadata
    h = hashlib.sha256()
    with open(premiere, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 16), b""):
            h.update(bloc)

    def version_de(paquet: str) -> str:
        try:
            return metadata.version(paquet)
        except metadata.PackageNotFoundError:
            return "absent"
    return [f"# étiquettes : {ETIQUETTE_SCELLE} = commit {commit_de(ETIQUETTE_SCELLE) or '?'} ; "
            f"{etiquette_scelle(variante)} = commit {commit_de(etiquette_scelle(variante)) or '?'}",
            f"# première lecture {premiere.name} : {premiere.stat().st_size} octets, sha256 {h.hexdigest()} "
            f"(hachée, jamais lue ni affichée)",
            f"# machine {platform.node()} ; numpy {version_de('numpy')} ; scikit-learn {version_de('scikit-learn')}"]


def controle_du_code(jumeaux_yaml: Path | None = None, variante: str | None = None) -> list[str]:
    """Ce qui empêche d'ouvrir C et D : le scellé fermé, ou un code qui a changé depuis son étiquette.
    Avec une variante (§17 à §19) : gnn-fige ET gnn-fige-2, gnn-fige-2 posée après gnn-fige et ne
    portant que les empreintes de cette variante, graphe_en/ limité entre les deux étiquettes
    (scelle_2_mal_pose), et le code comparé à gnn-fige-2."""
    scelle = etiquette_scelle(variante)
    if _git("tag", "--list", ETIQUETTE_SCELLE).stdout.strip() != ETIQUETTE_SCELLE:
        return [f"SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; C ne se lit qu'une fois le GNN figé."]
    if variante is not None:
        if _git("tag", "--list", scelle).stdout.strip() != scelle:
            return [f"SCELLÉ FERMÉ : l'étiquette « {scelle} » n'existe pas ; la seconde lecture (variante {variante}, "
                    f"{SECTIONS_GNN[variante]}) ne se fait qu'une fois la variante figée."]
        if _git("merge-base", "--is-ancestor", ETIQUETTE_SCELLE, scelle).returncode != 0:
            return [f"l'étiquette {ETIQUETTE_SCELLE} n'est pas antérieure à {scelle} : v12 est figée en premier "
                    f"(§17, §18)."]
        soucis2 = scelle_2_mal_pose(variante)
        if soucis2:
            return soucis2
    # Le contrôle doit voir une différence connue : decision_c.py n'existe pas à temoins-figes.
    if _git("diff", "--quiet", ETIQUETTE_TEMOINS, "--", "graphe_en/decision_c.py").returncode != 1:
        return ["LE CONTRÔLE NE VOIT RIEN : git ne voit pas que decision_c.py est né après "
                f"{ETIQUETTE_TEMOINS} ; aucun contrôle de code n'est fiable, C ne s'ouvre pas."]
    soucis = []
    for f in FIGES_TEMOINS:
        if _git("diff", "--quiet", ETIQUETTE_TEMOINS, "--", f"graphe_en/{f}").returncode != 0:
            soucis.append(f"graphe_en/{f} a changé depuis l'étiquette {ETIQUETTE_TEMOINS}")
    # fautifs.py : seul le nom de son fichier de sortie (main) a changé depuis le gel.
    ancien = _git("show", f"{ETIQUETTE_TEMOINS}:graphe_en/fautifs.py").stdout
    if not ancien or _sans_main(ancien) != _sans_main((HERE / "fautifs.py").read_text()):
        soucis.append(f"graphe_en/fautifs.py a changé (hors main) depuis l'étiquette {ETIQUETTE_TEMOINS}")
    # La règle « machine » : suivie, présente dans son étiquette, inchangée, figée avant le GNN.
    machine = "graphe_en/temoin_machine.py"
    if not _git("rev-parse", "-q", "--verify", f"refs/tags/{ETIQUETTE_MACHINE}").stdout.strip():
        soucis.append(f"l'étiquette {ETIQUETTE_MACHINE} n'existe pas")
    elif _git("cat-file", "-e", f"{ETIQUETTE_MACHINE}:{machine}").returncode != 0:
        soucis.append(f"{machine} n'est pas dans l'étiquette {ETIQUETTE_MACHINE}")
    else:
        if _git("diff", "--quiet", ETIQUETTE_MACHINE, "--", machine).returncode != 0:
            soucis.append(f"{machine} a changé depuis l'étiquette {ETIQUETTE_MACHINE}")
        if _git("merge-base", "--is-ancestor", ETIQUETTE_MACHINE, scelle).returncode != 0:
            soucis.append(f"l'étiquette {ETIQUETTE_MACHINE} n'est pas antérieure à {scelle}")
        if jumeaux_yaml is not None:
            soucis += machine_avant_d(jumeaux_yaml)
    if _git("ls-files", "--error-unmatch", machine).returncode != 0:
        soucis.append(f"{machine} n'est pas suivi par git")
    if _git("diff", "--quiet", scelle, "--", "graphe_en/").returncode != 0:
        soucis.append(f"graphe_en/ a changé depuis l'étiquette {scelle}")
    # git diff ne voit pas un fichier non suivi : aucun .py non suivi dans graphe_en/.
    hors = _git("ls-files", "--others", "--exclude-standard", "--", "graphe_en/*.py").stdout.split()
    if hors:
        soucis.append(f"fichiers Python non suivis dans graphe_en/ : {', '.join(hors)}")
    return soucis


def injections_confirmees(campagne_yaml: Path, cause: str) -> int:
    """Les injections confirmées de cette cause dans le déroulé de la campagne : « la panne
    posée et confirmée », que le scellé laisse lire (J 1206-1207) ; 0 sans déroulé."""
    if not campagne_yaml.is_file():
        return 0
    return sum(1 for p in fautifs_module.injections(campagne_yaml)[0] if p["confirmee"] and p["cause"] == cause)


def lire_empreintes(texte: str) -> dict[str, str]:
    """{clé : sha256} d'un fichier d'empreintes (« <clé> <sha256> » par ligne, « # » : commentaire)."""
    out = {}
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            cle, _, sha = ligne.rpartition(" ")
            out[cle.strip()] = sha
    return out


def empreintes_figees(variante: str | None = None) -> dict[str, str] | None:
    """Les empreintes notées au gel (§8 étape 8) : graphe_en/gnn-empreintes.txt tel qu'il est
    DANS l'étiquette gnn-fige (git show), jamais la copie de travail ; None s'il n'y est pas.
    Variante u (§17) : graphe_en/gnn-empreintes-u.txt dans l'étiquette gnn-fige-2."""
    r = _git("show", f"{etiquette_scelle(variante)}:graphe_en/{fichier_empreintes(variante)}")
    return lire_empreintes(r.stdout) if r.returncode == 0 else None


def empreintes_du_gnn(gnn_module, fen_series: list[dict], fige: dict, graines: int,
                      version: str | None = None) -> dict[str, str] | None:
    """
    Les empreintes recalculées après gnn.preparer, par gnn.empreintes(fen, fige, graines) :
    {clé : sha256 de torch.save en mémoire}, une clé par réglage ou variante et par graine
    qui entre dans les décisions, modèle final ET modèles des plis (ils calent le seuil).
    gnn.py la fournit (son auteur) ; None si elle manque. `version` : celle d'une variante
    (§17), passée à gnn.empreintes ; sans elle, l'appel d'avant.
    """
    f = getattr(gnn_module, "empreintes", None)
    if f is None:
        return None
    emp = f(fen_series, fige, graines) if version is None else f(fen_series, fige, graines, version=version)
    return {str(k): str(v) for k, v in emp.items()}


def controle_empreintes(calculees: dict[str, str] | None, figees: dict[str, str] | None,
                        variante: str | None = None) -> list[str]:
    """Ce qui empêche d'ouvrir C et D côté modèles : l'absence de l'une ou l'autre liste, ou
    la moindre différence (une autre version, d'autres époques, une autre bibliothèque)."""
    source = f"{etiquette_scelle(variante)}:graphe_en/{fichier_empreintes(variante)}"
    if calculees is None:
        return ["gnn.py ne fournit pas empreintes(fen, fige, graines) : les modèles ne peuvent pas être "
                "comparés à ceux du gel (§8 étape 8) ; C ne s'ouvre pas."]
    if not figees:
        return [f"{source} n'existe pas ou est vide : les empreintes du gel manquent (§8 étape 8, "
                f"« decision_c.py --empreintes{'' if variante is None else ' --variante ' + variante} » avant "
                f"{etiquette_scelle(variante)}) ; C ne s'ouvre pas."]
    ecarts = [k for k in sorted(set(figees) | set(calculees)) if figees.get(k) != calculees.get(k)]
    return [f"empreinte {k} : figée {(figees.get(k) or 'absente')[:16]}, recalculée "
            f"{(calculees.get(k) or 'absente')[:16]} ; le GNN n'est plus celui du gel, C ne s'ouvre pas."
            for k in ecarts]


def en_tete_gnn(gnn_module, emp: dict[str, str] | None, version: str | None = None) -> list[str]:
    """Ce qui identifie le GNN lu : version (celle de la variante s'il y en a une), époques,
    torch, et chaque empreinte."""
    torch_v = getattr(sys.modules.get("torch"), "__version__", "?")
    lignes = [f"# GNN : version {version or getattr(gnn_module, 'VERSION', '?')}, {getattr(gnn_module, 'EPOQUES', '?')} "
              f"époques, torch {torch_v}"]
    if emp is None:
        return lignes + ["#   (gnn.empreintes absent : aucune empreinte)"]
    return lignes + [f"#   empreinte {k} {v}" for k, v in sorted(emp.items())]


# ------------------------------------------------------------------------------
# La lecture de C et de D
# ------------------------------------------------------------------------------
def tas(f: dict) -> float | None:
    return juge._valeur(f["donnees"], "queue", juge.FILE, "backlog")


def veilles(campagne_yaml: Path) -> list[tuple[datetime, str, str]]:
    """(instant, résultat, leader) de chaque veille du déroulé."""
    out = []
    for m in re.finditer(r"instant: (\S+), action: veille_parcours, resultat: (\w+)(?:, file: [^,}]*)?"
                         r"(?:, leader: ([^,}\s]+))?", campagne_yaml.read_text()):
        out.append((datetime.strptime(m.group(1), fautifs_module.TS).replace(tzinfo=timezone.utc),
                    m.group(2), m.group(3) or "?"))
    return out


def effondrement(v: list[dict], debut: datetime, fin: datetime, les_veilles: list) -> list[str]:
    """Les raisons d'effondrement de l'injection (vide : pas d'effondrement)."""
    raisons = []
    dedans = [x for x in les_veilles if debut <= x[0] <= fin]
    for a, b in zip(dedans, dedans[1:]):
        if a[1] == "EN_DEFAUT" and b[1] == "EN_DEFAUT":
            raisons.append(f"deux veilles de suite EN_DEFAUT ({a[0]:%H:%M}, {b[0]:%H:%M})")
            break
    if any(x[2] == "PERDU" for x in dedans):
        raisons.append("leader perdu à une veille")
    # Les redémarrages, lus dans le graphe : un pod dont le compteur monte pendant la panne.
    vus: dict[str, float] = {}
    for f in v:
        bloc = f["donnees"]["nodes"]["instance"]
        col = bloc["columns"].index("restarts")
        for nom, x in zip(bloc["names"], bloc["X"]):
            r = x[col]
            if r is None:
                continue
            if nom in vus and r > vus[nom]:
                raisons.append(f"redémarrage de {nom}")
            vus[nom] = max(vus.get(nom, r), r)
    return sorted(set(raisons))


def machines_sans_mesure(campagne_yaml: Path) -> list[tuple[datetime, str]]:
    """
    (instant du témoin, machine) pour chaque machine que « kubectl top nodes » n'a pas
    pu mesurer (« <unknown> ») à un témoin du compte rendu (panne.sh temoin, recopié en
    commentaire par campagne.sh) : le signe d'un kubelet qui ne répond pas, signe
    INDIRECT d'une machine NotReady (un seul relevé manqué suffit). campagne.sh ne
    note pas l'état des nœuds lui-même.
    """
    out: list[tuple[datetime, str]] = []
    instant, hotes = None, False
    for ligne in campagne_yaml.read_text().splitlines():
        m = re.match(r"#\s+--- témoin « [^»]* » à (\S+)\s*$", ligne)
        if m:
            instant, hotes = datetime.strptime(m.group(1), fautifs_module.TS).replace(tzinfo=timezone.utc), False
            continue
        if re.match(r"#\s+---", ligne) or not ligne.startswith("#"):
            instant, hotes = None, False
            continue
        if instant is None:
            continue
        if re.match(r"#\s+hôtes :\s*$", ligne):
            hotes = True
            continue
        if hotes:
            m = re.match(r"#\s+(\S+)\s+cpu (.*)$", ligne)
            if m is None:
                hotes = False
            elif "<unknown>" in m.group(2):
                out.append((instant, m.group(1)))
    return out


def effondrement_d(v: list[dict], x: str, avant: list[dict], debut: datetime, fin: datetime,
                   sans_mesure: list[tuple[datetime, str]]) -> list[str]:
    """
    Ce que D ajoute à l'effondrement de C (J 1530-1531, 1541-1544) : une machine
    NotReady, ou une seule fenêtre de panne sans le nœud host X ou sans la réplique
    de X. NotReady n'est pas noté par campagne.sh ; il est lu par deux signes
    INDIRECTS (lecture opérationnelle, à écrire au journal avant gnn-fige) : une
    machine du graphe d'avant l'injection absente d'une fenêtre de panne (ou sans
    aucune mesure node-exporter), et une machine « <unknown> » à kubectl top à un
    témoin pendant l'injection (le signe d'un kubelet qui ne répond pas).
    """
    raisons = []
    nom_x = x.split(":", 1)[1]
    avant_machines = set(avant[-1]["donnees"]["nodes"]["host"]["names"]) if avant else set()
    for f in v:
        hotes = f["donnees"]["nodes"]["host"]
        mesurees = {n for n, ligne in zip(hotes["names"], hotes["X"]) if any(c is not None for c in ligne)}
        if nom_x not in hotes["names"]:
            raisons.append(f"fenêtre {f['debut']:%H:%M} sans le nœud host {nom_x}")
        inst = f["donnees"]["nodes"]["instance"]
        if not any(n.startswith(CONSOMMATEUR) and h == nom_x for n, h in zip(inst["names"], inst["hosts"])):
            raisons.append(f"fenêtre {f['debut']:%H:%M} sans la réplique de {nom_x}")
        for m in sorted(avant_machines - mesurees):
            raisons.append(f"machine {m} absente du graphe ou sans mesure à {f['debut']:%H:%M} "
                           "(signe indirect de NotReady)")
    for t, m in sans_mesure:
        if debut <= t <= fin:
            raisons.append(f"machine {m} non mesurée par kubectl top au témoin de {t:%H:%M} "
                           "(signe indirect de NotReady)")
    return sorted(set(raisons))


def lire_campagne(fen_x: list[dict], nom: str, lettre: str, cause: str, cible, campagnes: Path,
                  graines: int, tient: dict[str, list[bool]], liste: list, reps: dict,
                  jumeaux: bool = False) -> tuple[list[str], dict, dict, int]:
    """
    La lecture d'une campagne sous scellé : C (cause « base », cible la base) ou D
    (cause « reseau », cible X de chaque injection, jumeaux=True pour l'effondrement
    de D). cible(v) rend les clés visées par l'injection v. Rend (lignes,
    {méthode : résultats}, {injection : compte ?}, nombre d'injections confirmées).
    """
    injections = par_injection([f for f in fen_x if f["cause"] == cause])
    yaml = campagnes / nom / "campagne.yaml"
    bornes = {k + 1: p for k, p in enumerate(fautifs_module.injections(yaml)[0])}
    les_veilles = veilles(yaml)
    sans_mesure = machines_sans_mesure(yaml) if jumeaux else []
    comptent = {}
    lignes = ["", f"Injections de {lettre} (confirmées) :"]
    for k, v in sorted(injections.items()):
        p = bornes[k[1]]
        avant = [f for f in fen_x if f["fin"] <= p["debut"]]
        vide_avant = bool(avant) and (tas(avant[-1]) or 0.0) <= TAS_COORDINATION
        pleines = sum(1 for f in v if (tas(f) or 0.0) > TAS_COORDINATION)
        deborde = majorite(pleines, len(v))
        # « confirmée » : le juge ne met en panne que les injections confirmées ; pour D, panne.sh
        # ne confirme que si le retard ET le leurre sont posés (J 1543, 1985-1987).
        raisons = effondrement(v, p["debut"], p["fin"], les_veilles)
        if jumeaux:   # J 1530-1531 : NotReady, une fenêtre sans X ou sans sa réplique
            raisons = sorted(set(raisons) | set(effondrement_d(v, cible(v)[0], avant, p["debut"], p["fin"],
                                                               sans_mesure)))
        comptent[k] = vide_avant and deborde and not raisons
        motif = ("compte" if comptent[k] else "NE COMPTE PAS : " + ", ".join(
            ([] if vide_avant else ["file pas vide avant"]) + ([] if deborde else ["la file ne déborde pas"])
            + [f"effondrement ({r})" for r in raisons]))
        lignes.append(f"  {k[0]}#{k[1]}{' (X = ' + cible(v)[0] + ')' if jumeaux else ''} : {len(v)} minutes "
                      f"de panne, tas > {TAS_COORDINATION:g} dans {pleines} : {motif}")
    n_comptent = sum(comptent.values())
    if len(injections) < 2:
        lignes.append(f"MOINS DE 2 INJECTIONS CONFIRMÉES : {lettre} est à refaire à l'identique "
                      f"(règle écrite avant {lettre}).")
        return lignes, {}, comptent, len(injections)
    if n_comptent < 2:
        lignes.append(f"MOINS DE 2 INJECTIONS QUI COMPTENT : {lettre} ne décide rien (règle écrite avant {lettre}).")
    normales = [f for f in fen_x if f["etiquette"] == "normale"]
    lignes += ["", f"Par méthode (apprise sur les deux séries seules ; {len(normales)} minutes normales de {lettre}) :"]
    res: dict[str, dict] = {}
    w = max([38] + [len(n) for n, _, _ in liste])
    for nom_m, _, hasard in liste:
        n_f, n_a, fa, trouve_g, minutes = [], [], [], [], []
        for g in range(graines if hasard else 1):
            rep = reps[nom_m][g]
            f_ok = {k: majorite(sum(premier(f, rep[f["id"]], cible(v)) for f in v), len(v))
                    for k, v in injections.items()}
            a_ok = {k: majorite(sum(rep[f["id"]]["alarme"] and premier(f, rep[f["id"]], cible(v)) for f in v), len(v))
                    for k, v in injections.items()}
            n_f.append(sum(f_ok[k] for k in injections if comptent[k]))
            n_a.append(sum(a_ok[k] for k in injections if comptent[k]))
            fa.append(sum(1 for f in normales if rep[f["id"]]["alarme"]))
            trouve_g.append(n_comptent >= 2 and majorite(n_f[-1], n_comptent) and tient[nom_m][g])
            m = {}
            for k, v in injections.items():
                t = next((f for f in v if rep[f["id"]]["alarme"] and premier(f, rep[f["id"]], cible(v))), None)
                m[k] = None if t is None else round((t["debut"] - v[0]["debut"]).total_seconds() / 60)
            minutes.append(m)
        trouve = majorite(sum(trouve_g), len(trouve_g))
        res[nom_m] = {"n_f": n_f, "n_a": n_a, "fa": fa, "trouve_g": trouve_g, "minutes": minutes, "trouve": trouve}
        lignes.append(f"  {nom_m:<{w}} F {_case(n_f, n_comptent)} ; A {_case(n_a, n_comptent)} ; "
                      f"fausses alertes {lettre} {_case(fa, len(normales))} ; TROUVE : {'oui' if trouve else 'non'}"
                      + (f" ({sum(trouve_g)} graines sur {len(trouve_g)})" if hasard else ""))
        for k in sorted(injections):
            vus = [m[k] for m in minutes]
            quoi = "la base première" if not jumeaux else f"{cible(injections[k])[0]} premier"
            lignes.append(f"  {'':<{w}} {k[0]}#{k[1]} : sonne et met {quoi} à la minute "
                          f"{', '.join('jamais' if x is None else str(x) for x in vus)} de la panne")
    return lignes, res, comptent, len(injections)


# ------------------------------------------------------------------------------
# Les axes du GNN contre une version de la règle (journal, décision 2)
# ------------------------------------------------------------------------------
def axe_a(fa_gnn: list[int], fa_regle: int) -> str:
    """(a) : au moins 3 fausses alertes de moins ET au moins 25 % de moins, à budget égal ;
    gagné sur toutes les graines, perdu (l'image) sur une majorité stricte."""
    def mieux(x: int, y: int) -> bool:
        return x <= y - 3 and x <= 0.75 * y
    g = sum(mieux(x, fa_regle) for x in fa_gnn)
    p = sum(mieux(fa_regle, x) for x in fa_gnn)
    return "gagné" if g == len(fa_gnn) else ("perdu" if majorite(p, len(fa_gnn)) else "égal")


def comparer(fa_gnn: list[int] | None, fa_regle: int | None, minutes_gnn: list[dict], minutes_regle: dict,
             f_gnn: list[int], f_regle: int, comptent: dict) -> dict[str, str]:
    """
    Chaque axe vaut « gagné », « perdu » ou « égal ». Le GNN a une valeur par
    graine ; la règle, qui ne tire pas au hasard, une seule. Gagner demande
    TOUTES les graines ; perdre, une majorité stricte des graines (la marge est
    la même dans les deux sens).
      (a) fausses alertes à budget égal sur les 120 minutes normales non vues du
          test des deux séries : au moins 3 de moins ET au moins 25 % de moins ;
          fa_gnn=None : pas d'axe (a) (D, J 1705-1706 : mêmes minutes que C) ;
      (b) plus tôt : au moins une minute d'avance sur une majorité stricte des
          injections qui comptent (« jamais » est plus tard que tout ; jamais
          contre jamais : égalité) ;
      (c) plus d'injections trouvées (F) : gagné si toutes les graines en
          trouvent plus que la règle, perdu si une majorité stricte des graines
          en trouve moins (la médiane est donnée à côté dans le rapport).
    """
    tot = len(f_gnn)
    axes = {}
    if fa_gnn is not None:
        axes["a"] = axe_a(fa_gnn, fa_regle)

    def devant(x, y) -> bool:   # x au moins une minute avant y ; « jamais » (None) après tout
        return x is not None and (y is None or x + 1 <= y)
    ks = [k for k, v in comptent.items() if v]
    avance = [sum(devant(m[k], minutes_regle[k]) for k in ks) for m in minutes_gnn]
    retard = [sum(devant(minutes_regle[k], m[k]) for k in ks) for m in minutes_gnn]
    axes["b"] = ("gagné" if all(majorite(a, len(ks)) for a in avance)
                 else "perdu" if majorite(sum(majorite(r, len(ks)) for r in retard), tot) else "égal")
    axes["c"] = ("gagné" if all(x > f_regle for x in f_gnn)
                 else "perdu" if majorite(sum(x < f_regle for x in f_gnn), tot) else "égal")
    return axes


def contre_chacune(trouve_gnn: bool, nf_gnn: list[int], adversaires: dict[str, tuple[int, dict]]) -> tuple[str, list[str]]:
    """
    Le verdict de la décision 2 (J 1244-1251, précisée J 1690-1695 ; même forme pour
    la ligne 2 de l'axe (d), J 1703-1709). adversaires : {version de la règle qui
    TROUVE : (ses injections F, les axes du GNN contre elle)}.
      le GNN gagne contre R : il TROUVE, avec au moins autant d'injections (médiane
        des graines), et gagne nettement sur au moins un axe sans perdre sur aucun ;
      l'image contre R : R TROUVE (elle est ici par construction) avec au moins
        autant d'injections que le GNN, et le GNN perd sur un axe sans gagner sur aucun ;
      « perdu » si c'est l'image contre AU MOINS UNE version ; « gagné » s'il gagne
      contre CHACUNE ; sinon « égal ».
    """
    med = statistics.median(nf_gnn) if nf_gnn else 0
    lignes, gagne, image = [], {}, {}
    for r, (nf_r, ax) in adversaires.items():
        vals = set(ax.values())
        gagne[r] = trouve_gnn and med >= nf_r and "gagné" in vals and "perdu" not in vals
        image[r] = nf_r >= med and "perdu" in vals and "gagné" not in vals
        lignes.append(f"    contre {r} : " + " ; ".join(f"({k}) {v}" for k, v in ax.items())
                      + f" ; F : GNN {_case(nf_gnn) if nf_gnn else '—'}, règle {nf_r} → "
                      + ("le GNN gagne" if gagne[r] else "l'image : le GNN perd" if image[r] else "ni l'un ni l'autre"))
    verdict = "perdu" if any(image.values()) else ("gagné" if adversaires and all(gagne.values()) else "égal")
    return verdict, lignes


def table_axe_d(n_confirmees: int, n_comptent: int, res: dict,
                comptent: dict, noms: dict | None = None) -> tuple[dict[str, str] | None, list[str]]:
    """
    L'axe (d) de C, lu sur D (table du 28 sept., J 1697-1713, qui remplace celle de
    J 1561-1564). Les lignes se lisent DANS L'ORDRE ; la première qui s'applique
    donne l'axe. « Version de la règle » comprend les deux versions machine. La
    ligne 0 est commune ; les lignes 1 à 4 se lisent par réglage du GNN, contre les
    seules versions de la règle du même réglage (E-2, J 2119-2126). Rend
    ({réglage : valeur}, lignes) ; None si D est à refaire (moins de 2 injections
    confirmées, J 1541-1542 : D refaite à l'identique). `noms` : ceux du GNN lu (noms_gnn).
    """
    noms = noms or noms_gnn()
    if n_confirmees < 2:
        return None, ["  D est à refaire à l'identique (moins de 2 injections confirmées) : l'axe (d) n'est pas établi."]
    trouve = {n: r["trouve"] for n, r in res.items()}
    regles = [n for n in trouve if n.startswith("règle") and trouve[n]]
    structure = [n for n in trouve if (n.startswith("tableau") or n.startswith("score par nœud")) and trouve[n]]
    # 0. (J 1700-1701) moins de 2 qui comptent, le plancher, la décision 1 sur D, ou « sans aucune arête » trouve X
    raisons0 = ((["moins de 2 injections qui comptent sur D"] if n_comptent < 2 else [])
                + ([f"le plancher « {PLANCHER_D} » TROUVE"] if trouve.get(PLANCHER_D) else [])
                + ([f"décision 1 sur D : {', '.join(structure)} TROUVE"] if structure else [])
                + ([f"« {n} » TROUVE X (la remontée écrite à la main trouve, pas le GNN, J 1597-1599)"
                    for n in trouve if n.startswith(noms["sans_arete"]) and trouve[n]]))
    if raisons0:
        return {r: "égal" for r in REGLAGES}, [f"  ligne 0 : {' ; '.join(raisons0)} → égal (les deux réglages)"]
    valeurs, lignes = {}, []
    for reg in REGLAGES:
        propre, budget = noms["propre"][reg], noms["regle"][reg]
        regles_r = [n for n in regles if reglage_de(n) == reg]
        if not regles_r:
            # 1. (J 1702-1703) aucune version de ce réglage ne TROUVE et le GNN TROUVE ; 4. (J 1712) personne
            if trouve.get(propre, False):
                valeurs[reg] = "gagné"
                lignes.append(f"  [{reg}] ligne 1 : aucune version « …, {reg} » de la règle ne TROUVE X, "
                              f"« {propre} » TROUVE → gagné")
            else:
                valeurs[reg] = "égal"
                lignes.append(f"  [{reg}] ligne 4 : personne ne TROUVE X (réglage « {reg} ») → égal")
        elif trouve.get(budget, False):
            # 2. (J 1704-1710) des versions TROUVENT et le GNN aussi : axes (b) et (c) lus sur D,
            #    contre chacune, le GNN au budget de la règle (les versions machine le gardent, J 1620)
            adversaires = {}
            for r in regles_r:
                ax = comparer(None, None, res[budget]["minutes"], res[r]["minutes"][0], res[budget]["n_f"],
                              res[r]["n_f"][0], comptent)
                adversaires[r] = (res[r]["n_f"][0], ax)
            valeurs[reg], detail = contre_chacune(True, res[budget]["n_f"], adversaires)
            lignes += ([f"  [{reg}] ligne 2 : {', '.join(regles_r)} et « {budget} » TROUVENT ; axes (b), (c) "
                        f"sur D → {valeurs[reg]}"] + detail)
        else:
            # 3. (J 1711) une version TROUVE et pas le GNN
            valeurs[reg] = "perdu"
            lignes.append(f"  [{reg}] ligne 3 : {', '.join(regles_r)} TROUVE X, pas « {budget} » → perdu")
        lignes += ecart_budget(res, reg, noms)
    return valeurs, lignes


def decision_c(n_comptent: int, res: dict, comptent: dict, fa_test: dict, axe_d: dict[str, str] | None,
               regles_c: list[str], noms: dict | None = None) -> list[str]:
    """Les décisions 1 à 3 de C (J 1241-1263), le verdict de chaque réglage du GNN contre
    CHAQUE version de la règle du même réglage (J 1690-1695, 2119-2126), l'axe (d) venant de D.
    La décision 1 est commune aux deux réglages ; les décisions 2 et 3 se lisent par réglage.
    `noms` : ceux du GNN lu (noms_gnn ; la première lecture par défaut)."""
    noms = noms or noms_gnn()
    lignes = ["", "Décision sur C (ordre écrit avant C) :"]
    trouve = {n: r["trouve"] for n, r in res.items()}
    structure = [n for n in trouve if sans_structure(n, noms) and trouve[n]]
    regles = [n for n in trouve if n.startswith("règle") and trouve[n]]
    avec_gnn = all(noms["propre"][r] in res and noms["regle"][r] in res for r in REGLAGES)
    d_txt = (lambda reg: "non établi (D à refaire)" if axe_d is None else axe_d[reg])
    if n_comptent < 2:
        lignes.append("  aucune : moins de 2 injections qui comptent.")
    elif structure:
        lignes.append(f"  1. {', '.join(structure)} TROUVE : sans la structure des flèches, les nombres suffisent "
                      f"sur C ; aucune conclusion sur le GNN n'est tirée de C (D et l'axe (a) restent).")
        if avec_gnn:
            for r in regles_c:
                b = noms["regle"][reglage_de(r)]
                lignes.append(f"    axe (a) de « {b} » contre {r} : {axe_a(fa_test[b], fa_test[r][0])} (fausses "
                              f"alertes du test non vues : GNN {_case(fa_test[b])}, règle {fa_test[r][0]})")
    elif not avec_gnn:
        lignes.append(f"  2. {', '.join(regles)} TROUVE : H1 soutenue." if regles
                      else "  3. personne ne trouve.")
        lignes.append("  le GNN n'est pas dans la liste : pas de verdict.")
    else:
        for reg in REGLAGES:
            propre, budget = noms["propre"][reg], noms["regle"][reg]
            regles_r = [n for n in regles if reglage_de(n) == reg]
            lignes.append(f"  -- « {propre} », contre les versions « …, {reg} » de la règle (E-2, J 2119-2126)")
            if regles_r:
                lignes.append(f"  2. {', '.join(regles_r)} TROUVE : H1 soutenue ; « {budget} » est comparé à "
                              f"CHACUNE (axes a, b, c, et d venant de D).")
                adversaires = {}
                for r in regles_r:
                    ax = comparer(fa_test[budget], fa_test[r][0], res[budget]["minutes"], res[r]["minutes"][0],
                                  res[budget]["n_f"], res[r]["n_f"][0], comptent)
                    if axe_d is not None:
                        ax["d"] = axe_d[reg]
                    adversaires[r] = (res[r]["n_f"][0], ax)
                verdict, detail = contre_chacune(trouve[budget], res[budget]["n_f"], adversaires)
                lignes += detail
                if axe_d is None:   # en secours : --ouvrir refuse déjà une D à refaire
                    lignes.append(f"  VERDICT DU GNN SUR C, {reg} : suspendu (D à refaire : l'axe (d) n'est pas établi)")
                    lignes.append(f"    (axes (a), (b), (c) seuls, ce n'est pas un verdict : {verdict})")
                else:
                    lignes.append(f"  VERDICT DU GNN SUR C, {reg} : {verdict}")
                    # Gagné contre chacune sans « perdu » : la victoire contre R tient à (d) si (d) est
                    # le seul axe gagné contre R ; sans D, elle tomberait (J 1564, 1713).
                    par_d = [r for r, (_, ax) in adversaires.items()
                             if "gagné" not in {v for k, v in ax.items() if k != "d"}]
                    if verdict == "gagné" and par_d:
                        lignes.append(f"  (gagné grâce à l'axe (d) contre {', '.join(par_d)} : sans D, pas de "
                                      f"victoire contre elle{'s' if len(par_d) > 1 else ''} ; le rapport ne présentera "
                                      f"pas cette victoire comme indépendante de D, J 1564, 1713)")
            else:
                lignes.append(f"  3. aucune version « …, {reg} » de la règle ne TROUVE : « {propre} » gagne sur C "
                              f"s'il TROUVE.")
                lignes.append(f"  VERDICT DU GNN SUR C, {reg} : {'gagné' if trouve[propre] else 'égal'}"
                              + ("" if axe_d is not None else " (D à refaire : l'axe (d) n'est pas établi)"))
            lignes += ecart_budget(res, reg, noms)
    if avec_gnn:
        lignes += [f"  axe (d), de D, {reg} : {d_txt(reg)}" for reg in REGLAGES]
    return lignes


def lecture(fen_series: list[dict], fen_c: list[dict], fen_d: list[dict], c: str, d: str, campagnes: Path,
            fige: dict, graines: int, gnn: bool, variante: str | None = None) -> list[str]:
    """C et D dans la même lecture (J 1538-1540) : G, G_D, les deux campagnes, l'axe (d), puis C.
    Avec une variante (§17), le GNN de cette variante seule, sous ses noms (noms_gnn)."""
    noms = noms_gnn(variante)
    liste_c = methodes(fige, gnn=gnn, variante=variante)
    liste_d = methodes(fige, machine=True, gnn=gnn, variante=variante) + \
        [(PLANCHER_D, lambda fen, g: APrioriMachines(fen), False)]
    noms_c = [n for n, _, _ in liste_c]
    attendus = [n for r in REGLAGES for n in (noms["propre"][r], noms["regle"][r])]
    if gnn and not set(attendus) <= set(noms_c):   # E-2 : les deux réglages et leur budget (J 2119-2126)
        raise ValueError(f"gnn.methodes ne rend pas {', '.join(f'« {n} »' for n in attendus if n not in noms_c)}")
    test = [f for f in fen_series if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    a_repondre = test + [f for f in fen_c + fen_d if f["etiquette"] in ("normale", "panne")]
    reps = toutes_reponses(liste_d, fen_series, a_repondre, graines)   # liste_d contient liste_c

    lignes = ["", "== La garde de spécificité G (test des deux séries)"]
    l, tient_c = garde(fen_series, fige, graines, liste_c, reps=reps)
    lignes += l
    xs = sorted({f["fautifs"][0] for f in fen_d if f["etiquette"] == "panne" and f["cause"] == "reseau" and f["fautifs"]})
    lignes += ["", f"== La garde G_D (test des deux séries), pour chaque X employé par {d} : {', '.join(xs) or 'aucun'}"]
    l, tient_d = garde_d(fen_series, fige, graines, liste_d, xs, reps)
    lignes += l

    # Axe (a) : alarmes sur les minutes normales non vues du test des deux séries (J 1252-1253).
    normales_test = [f for f in test if f["etiquette"] == "normale" and not f["vue"]]
    fa_test = {nom: [sum(1 for f in normales_test if r[f["id"]]["alarme"]) for r in reps[nom]] for nom in reps}
    lignes += ["", f"== Fausses alertes sur les {len(normales_test)} minutes normales non vues du test des deux séries (axe a)"]
    w = max([38] + [len(n) for n in noms_c])
    lignes += [f"  {nom:<{w}} {_case(fa_test[nom], len(normales_test))}" for nom in noms_c]

    lignes += ["", f"== La lecture de {c} (C)"]
    base = cles_base(fige)
    l, res_c, comptent_c, _ = lire_campagne(fen_c, c, "C", "base", lambda v: base, campagnes, graines,
                                            tient_c, liste_c, reps)
    lignes += l
    lignes += ["", f"== La lecture de {d} (D)"]
    l, res_d, comptent_d, n_conf_d = lire_campagne(fen_d, d, "D", "reseau", lambda v: v[0]["fautifs"][:1],
                                                   campagnes, graines, tient_d, liste_d, reps, jumeaux=True)
    lignes += l

    lignes += ["", "== L'axe (d), lu sur D (table du 28 sept., lignes lues dans l'ordre)"]
    axe_d, l = table_axe_d(n_conf_d, sum(comptent_d.values()), res_d, comptent_d, noms)
    lignes += l
    if res_c:
        regles_c = [n for n in noms_c if n.startswith("règle")]
        lignes += decision_c(sum(comptent_c.values()), res_c, comptent_c, fa_test, axe_d, regles_c, noms)
    return lignes


# ------------------------------------------------------------------------------
def rapport(mode: str, c: str | None, campagnes: Path, runs: Path, graines: int,
            d: str | None = None, machines: list[str] | None = None, gnn: bool | None = None,
            variante: str | None = None) -> int:
    fige, _, _ = gel.reference()
    # La version du GNN passée à gnn.py : celle de la variante (§17), sinon rien (l'appel d'avant).
    kw_version = {} if variante is None else {"version": variante}
    if mode == "ouvrir":
        soucis = controle_du_code(campagnes / d / "campagne.yaml") if variante is None else \
            controle_du_code(campagnes / d / "campagne.yaml", variante)
        if soucis:
            print("\n".join(soucis))
            return 1
        premiere = campagnes / f"decision-{c}-{d}.txt"
        if variante is not None and (not premiere.is_file() or premiere.stat().st_size == 0):
            # §17 : la seconde lecture vient après la première (v12, déjà lue) ; seules son
            # existence et sa taille sont regardées ici, jamais son contenu (relecture B, constat 4).
            print(f"la première lecture (decision-{c}-{d}.txt) n'est pas écrite, ou est vide : la seconde lecture "
                  f"(variante {variante}, {SECTIONS_GNN[variante]}) ne vient qu'après elle ; rien n'est lu.")
            return 1
        # C et D s'ouvrent ensemble (J 1540) : une campagne à refaire arrête tout, avant toute lecture
        # et tout calcul (J 1227, 1541-1542). Compter par cause couvre aussi C et D échangées.
        for x, lettre, cause in ((c, "C", "base"), (d, "D", "reseau")):
            n = injections_confirmees(campagnes / x / "campagne.yaml", cause)
            if n < 2:
                soucis.append(f"{lettre} ({x}) : {n} injection(s) confirmée(s) de cause « {cause} », moins de 2 : "
                              f"{lettre} est à refaire à l'identique avant d'ouvrir (J 1227, 1541-1542) ; "
                              f"C et D s'ouvrent ensemble, rien n'est lu.")
        if soucis:
            print("\n".join(soucis))
            return 1
    try:
        fen_series = juge.lire(fautifs_module.SERIES, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if mode == "empreintes":   # §8 étape 8 : les modèles appris comme à --ouvrir, aucune réponse
        import gnn as gnn_module
        with contextlib.redirect_stdout(sys.stderr):
            gnn_module.preparer(fen_series, fige, graines, **kw_version)
        emp = empreintes_du_gnn(gnn_module, fen_series, fige, graines, variante)
        if emp is None:
            print("gnn.py ne fournit pas empreintes(fen, fige, graines)")
            return 1
        if variante is None:
            print(f"# Empreintes du GNN (GNN_SPEC.md §8 étape 8) — écrit par graphe_en/decision_c.py --empreintes, "
                  f"graines 0 à {graines - 1} ; à commiter avec gnn-fige.")
        else:
            print(f"# Empreintes du GNN, variante {variante} (GNN_SPEC.md {SECTIONS_GNN[variante]}) — écrit par "
                  f"graphe_en/decision_c.py --empreintes --variante {variante}, graines 0 à {graines - 1} ; à commiter "
                  f"avec {etiquette_scelle(variante)}.")
        print("\n".join(en_tete_gnn(gnn_module, None, variante)[:1]))
        if variante is not None:   # §18 : les empreintes ne sont reproductibles que sur la même machine
            import platform
            print(f"# machine {platform.node()}")
        print("\n".join(f"{k} {v}" for k, v in sorted(emp.items())))
        return 0
    if machines:
        connues = {n for f in fen_series for n in f["donnees"]["nodes"]["host"]["names"]}
        inconnues = [m for m in machines if m not in connues]
        if inconnues:
            print(f"machines inconnues des deux séries : {', '.join(inconnues)}")
            return 1
    # Le GNN : à --ouvrir, ou une fois gnn-fige posée ; jamais avant (GNN_SPEC.md §8 étape 7).
    if gnn is None:
        gnn = mode == "ouvrir" or etiquette_existe(ETIQUETTE_SCELLE)
    print("# Décision sur la base lente — écrit par graphe_en/decision_c.py, ne pas éditer à la main.")
    print(f"# règles : notes/JOURNAL.md, 27 sept. ; graines 0 à {graines - 1} pour ce qui tire au hasard")
    if variante is not None:
        # §19, RÈGLE FINALE (remplace les règles de choix de §17 et §18) et sa mise à jour de 16 h 10 : la
        # seconde lecture est celle du MODÈLE RETENU, choisi par l'utilisateur sur la validation seule avant
        # toute lecture ; ses verdicts sont ceux du modèle retenu (point 2), quelle que soit la variante.
        sections = ", ".join(sorted({"§17", SECTIONS_GNN[variante], "§19"}))
        print(f"# SECONDE LECTURE (GNN_SPEC.md {sections}, règle finale, mise à jour de 16 h 10) : la variante "
              f"« {VARIANTES_GNN[variante]} » ({variante}) seule, figée à {etiquette_scelle(variante)} : le modèle "
              f"retenu, choisi par l'utilisateur parmi v12, u, u1 et u2 au vu des seuls résultats de validation (choix "
              f"et heure écrits au journal avant toute lecture de C et D pour une variante unique) ; ses verdicts sont "
              f"ceux du modèle retenu (§19, point 2), avec les mêmes règles ; témoins et règle recalculés")
        if mode == "ouvrir":
            print("\n".join(en_tete_seconde_lecture(variante, campagnes / f"decision-{c}-{d}.txt")))
    if gnn:
        import gnn as gnn_module
        with contextlib.redirect_stdout(sys.stderr):   # ses messages à l'écran, pas dans le rapport
            gnn_module.preparer(fen_series, fige, graines, **kw_version)
        emp = empreintes_du_gnn(gnn_module, fen_series, fige, graines, variante)
        if mode == "ouvrir":   # §8 étape 8 : les modèles sont ceux du gel, ou C et D ne s'ouvrent pas
            soucis = controle_empreintes(emp, empreintes_figees()) if variante is None else \
                controle_empreintes(emp, empreintes_figees(variante), variante)
            if soucis:
                print("\n".join(soucis))
                return 1
        print("\n".join(en_tete_gnn(gnn_module, emp, variante)))
    if mode == "garde":
        print("\n== La garde de spécificité G (test des deux séries)")
        liste = methodes(fige, gnn=gnn)   # la même liste pour la garde et la lecture
        lignes, _ = garde(fen_series, fige, graines, liste)
        print("\n".join(lignes))
        if machines:
            liste_d = methodes(fige, machine=True, gnn=gnn) + [(PLANCHER_D, lambda fen, g: APrioriMachines(fen), False)]
            print(f"\n== La garde G_D de D (test des deux séries), pour chaque X : {', '.join(machines)}")
            lignes, _ = garde_d(fen_series, fige, graines, liste_d, [juge._cle("host", m) for m in machines])
            print("\n".join(lignes))
        return 0
    try:
        fen_c = juge.lire([c], campagnes, runs)
        fen_d = juge.lire([d], campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    print(f"# et sur les jumeaux : C = {c}, D = {d}, ouvertes dans la même lecture")
    print("\n".join(lecture(fen_series, fen_c, fen_d, c, d, campagnes, fige, graines, gnn, variante)))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, installer, graines = HERE.parent / "campagnes", HERE / "runs", True, GRAINES_ECRITES
    mode, c, d, machines, variante = None, None, None, None, None
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--garde":
                mode = "garde"
            elif a == "--ouvrir":
                mode, c = "ouvrir", args.pop(0)
            elif a == "--empreintes":
                mode = "empreintes"
            elif a == "--jumeaux":
                d = args.pop(0)
            elif a == "--machines":
                machines = [m for m in args.pop(0).split(",") if m]
                if not machines:
                    raise ValueError
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--variante":
                variante = args.pop(0)
                if variante not in VARIANTES_GNN:
                    raise ValueError
            elif a == "--no-install":
                installer = False
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    if mode is None:
        print("--garde, --empreintes ou --ouvrir <campagne C> --jumeaux <campagne D>", file=sys.stderr)
        return 2
    if mode == "empreintes" and (d is not None or machines is not None):
        print("--empreintes ne prend ni --jumeaux ni --machines", file=sys.stderr)
        return 2
    if mode == "ouvrir" and d is None:
        print("C et D s'ouvrent dans la même lecture (journal, « Ce qui décidera sur D ») : "
              "--ouvrir <C> --jumeaux <D>", file=sys.stderr)
        return 2
    if mode == "garde" and d is not None:
        print("--jumeaux ne va qu'avec --ouvrir", file=sys.stderr)
        return 2
    if mode == "ouvrir" and graines != GRAINES_ECRITES:
        print(f"à --ouvrir, les graines sont 0 à {GRAINES_ECRITES - 1}, écrites avant C et D (J 1237, 1315, 1553) : "
              f"--graines {GRAINES_ECRITES} ou rien", file=sys.stderr)
        return 2
    if mode == "ouvrir" and machines is not None:
        print("--machines ne va qu'avec --garde (à --ouvrir, les X sont ceux de D)", file=sys.stderr)
        return 2
    if variante is not None and mode not in ("ouvrir", "empreintes"):
        print(f"--variante ne va qu'avec --ouvrir ou --empreintes (variantes : {', '.join(VARIANTES_GNN)})",
              file=sys.stderr)
        return 2
    for x, quoi in ((c, "C"), (d, "D")):
        if x is not None and x in fautifs_module.SERIES:
            print(f"{x} est une campagne des deux séries, pas {quoi}", file=sys.stderr)
            return 2
    if c is not None and c == d:
        print("C et D sont deux campagnes différentes", file=sys.stderr)
        return 2
    req = bootstrap.REQUIREMENTS["baseline"]
    if not bootstrap.is_available(req.module):
        if installer and bootstrap.in_virtualenv():
            fait, detail = bootstrap.install(req)
            if not fait:
                print(f"impossible d'installer {req.package} : {detail}", file=sys.stderr)
                return 1
        else:
            print(f"{req.package} manque : {bootstrap.manual_command(req)}", file=sys.stderr)
            return 1
    campagnes, runs = campagnes.resolve(), runs.resolve()
    # « Chacun passe une seule fois » (J 1210) : une lecture de C ou de D déjà écrite, ou la garde
    # avec le GNN d'après le gel, n'est jamais refaite ni écrasée ; refusé avant tout calcul. La
    # garde d'avant le gel (sans le GNN) se refait à l'identique dans decision-garde(-d).txt.
    gnn = mode == "ouvrir" or (mode == "garde" and etiquette_existe(ETIQUETTE_SCELLE))
    if mode == "garde" and gnn:
        # §17–§19 : la garde avec le GNN lit le test des deux séries avec v12, dont l'alarme est celle
        # de u et le classement celui de u1 ; comme gnn.py --test, pas avant gnn-fige-2 bien posée.
        import gnn as gnn_module
        ferme = gnn_module.raisons_scelle_2(gnn_module.VERSION)
        if ferme:
            print(f"--garde refusé : l'étiquette {ETIQUETTE_SCELLE} existe, le GNN ({gnn_module.VERSION}) entrerait "
                  f"dans la garde et y lirait le test des deux séries ; {'; '.join(ferme)}", file=sys.stderr)
            return 1
    if mode == "empreintes":
        cible, une_fois = HERE / fichier_empreintes(variante), False
    elif mode == "garde":
        cible = campagnes / ("decision-garde" + ("-d" if machines else "") + ("-gnn" if gnn else "") + ".txt")
        une_fois = gnn
    elif variante is None:
        cible, une_fois = campagnes / f"decision-{c}-{d}.txt", True
    else:   # la seconde lecture (§17 à §19) : son propre fichier, une seule seconde lecture
        cible, une_fois = campagnes / f"decision-{c}-{d}-{variante}.txt", True
    if mode != "ouvrir":
        deja = [cible] if cible.exists() else []
    elif variante is None:
        deja = sorted(set(campagnes.glob(f"decision-{c}-*.txt")) | set(campagnes.glob(f"decision-*-{d}.txt")))
    else:   # §18, §19 : UNE seule seconde lecture, quelle que soit la variante (u, u1 ou u2)
        deja = sorted({x for w in VARIANTES_GNN for x in (set(campagnes.glob(f"decision-{c}-*-{w}.txt"))
                                                          | set(campagnes.glob(f"decision-*-{d}-{w}.txt")))})
    if une_fois and deja:
        print(f"déjà écrit : {', '.join(str(x) for x in deja)} ; chacun passe une seule fois (J 1210) : "
              f"rien n'est relu ni écrasé", file=sys.stderr)
        return 1
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(mode, c, campagnes, runs, graines, d, machines, gnn=gnn if mode != "empreintes" else None,
                       variante=variante)
    texte = sortie.getvalue()
    if code == 0:   # écrit AVANT d'être affiché : une lecture montrée est toujours une lecture écrite
        try:
            with open(cible, "x" if une_fois else "w") as f:   # « x » : deux lancements ne s'écrasent pas
                f.write(texte)
        except FileExistsError:
            print(f"{cible} est apparu pendant le calcul : rien n'est écrasé ni affiché", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"{cible} n'a pas pu être écrit ({e}) : rien n'est affiché", file=sys.stderr)
            return 1
    print(texte, end="")
    if code == 0:
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
