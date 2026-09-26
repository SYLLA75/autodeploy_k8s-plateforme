"""
Témoin 3 : la règle qui suit les flèches. Écrite à la main ; elle lit la structure.

    python3 temoin_fleches.py [options] [campagne ...]

Phase B.5. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. Définie le 24 sept. 2026 : « la file → ses
répliques → ce qu'elles appellent → le dernier composant anormal ». Écrite
comme par un ingénieur qui connaît la plateforme, le graphe figé et les quatre
causes apprises : sa structure reprend le tableau « quelle panne fait bouger
quoi » du LEXIQUE. C'est la référence experte sur les pannes connues ; ses
presque 100 % y sont un plafond par construction, pas une preuve qu'elle
généralise. Ce qui la départage du GNN : les fausses alertes, la base lente
(phase C), les jumeaux (phase D), et une panne qui ne remplit pas la file.

CE QU'ELLE SAIT, en plus des nombres de la fenêtre (le GNN n'a pas tout cela)
  - le normal de chaque nœud (temoin_noeud.Normal), connu par son nom ;
  - le normal de chaque flèche, même recette (temoin_noeud.echelles), connu par
    (relation, identité de la source, identité de la cible) : les trois
    répliques d'un service partagent le leur ; le plancher mis en commun par
    relation. Le GNN n'a qu'une mise à l'échelle par relation et aucun nom ;
  - qui consomme chaque file dans le normal : une réplique gelée n'a plus de
    flèche consumes, la règle sait qu'elle devrait en avoir une ;
  - la signature des quatre causes, écrite à la main.

LA MARCHE, fenêtre par fenêtre (s_f, s_m : limites d'alarme de la file et
des machines ; s : limite de marche)
  1. une file se remplit-elle ? (backlog, backlog_slope ou rate_imbalance
     au-dessus de s_f ; la plus pleine d'abord)
       non : une machine est-elle saturée ? (cpu_pressure, memory_pressure ou
             io_pressure au-dessus de s_m) → hote, la plus saturée ; sinon
             normale
  2. ses consommateurs :
       une réplique qui ne consomme plus (pas de flèche consumes depuis la
       file, débit sous −s, ou plus aucun temps de traitement alors que son
       normal en a) → blocage, ces répliques
       des répliques plus lentes (un temps de traitement au-dessus de s) → 3.
       aucune : la file se remplit avec des répliques saines, donc on y
       dépose plus qu'elles ne peuvent prendre → charge, aucun fautif
  3. ce qui explique la lenteur, en suivant les flèches des répliques lentes :
       leur machine (le champ hosts des nœuds, identique aux flèches
       executes_on) saturée au-dessus de s_m → hote, la machine
       une flèche sortante (calls, queries) plus lente (une latence au-dessus
       de s) vers une cible t :
         littérale      t est-elle anormale elle-même (son plus grand |z|
                        au-dessus de s) ? → t, cause « inconnue » (le dernier
                        composant anormal, la définition du 24 sept.)
         cause commune  la plupart des AUTRES services qui appellent t (au
                        moins deux ; un par service, sa flèche la plus lente)
                        la voient-ils aussi plus lente ? → t, cause « inconnue »
       sinon → lenteur, les répliques lentes
  Le classement de tous les nœuds : les désignés (même score pour tous), puis
  le chemin parcouru (même score), puis tous les autres par leur écart (le
  score sans exemples du témoin 2) ; entre égaux, le juge départage contre le
  témoin. L'alarme : une cause autre que « normale ».
  La saturation d'une machine, c'est sa pression, pas son occupation (méthode
  USE) : cpu_busy monte avec le travail de ts-order-service, qui grandit avec la
  table des commandes au fil d'une campagne.

DEUX VERSIONS, notées côte à côte. Sur la validation, elles répondent pareil
aux quatre causes connues ; pas sur le test : la littérale y accuse la base
dans une bonne part des fenêtres de lenteur, car son épreuve « la cible
est-elle anormale » compare à s_f (calée sur les trois nombres de la file) le
plus grand |z| des douze nombres de la base, qui la dépasse dans 7 à 18 % des
fenêtres normales mises de côté : devant la base lente, sa réponse dépend du
bruit. Non corrigée (vue sur le test, version secondaire) ; la garde de
spécificité de la table de décision (journal) l'écarte si elle accuse la base
dans une panne connue. La cause commune, elle, ne se déclenche sur aucune des
quatre causes connues. La
cause commune (« la cible est-elle lente pour tout le monde, ou pour moi
seulement ? ») est un premier réflexe de diagnostic général, sans rien de
propre à une base ; elle change « composant anormal » en « preuve sur les
flèches », ce qui est l'hypothèse H1 écrite à la main. Choisie par celui qui
prépare la base lente, entre deux règles que les données ne distinguent pas :
d'où les deux, et leur réponse attendue écrite avant la phase C (journal).
  littérale      l'ingénieur qui ne pense pas à une base lente : devant elle,
                 attendue « lenteur, les répliques » (le nœud de la base ne
                 bouge pas)
  cause commune  la plus forte : attendue « inconnue, tsdb-mysql-0 », si la
                 base lente remplit la file et fait passer la flèche des
                 répliques vers la base au-dessus de s

DEUX RÉGLAGES (fautifs.py). Dans les deux, la STRUCTURE a été écrite en
regardant les pannes d'apprentissage : « sans exemples » veut dire que les
limites viennent du normal seul.
  s_f, s_m   les mêmes pour les deux, calés sur le normal seul : chaque
             campagne mise de côté à son tour, le normal appris sur les
             autres ; s_f = 95e centile, sur ses fenêtres normales
             d'apprentissage, du plus haut écart des files (remplissage), s_m
             de même pour les machines (saturation). Ensemble, elles sonnent
             sur plus de 5 % de ces fenêtres : l'en-tête du résultat dit combien
  sans exemples  s = s_f : ce qui compte comme un écart pour la file compte
             pour ses répliques
  avec exemples  s choisi dans une grille, celui qui nomme le mieux la cause
             et le fautif (top-1) des fenêtres de panne d'apprentissage ; à
             égalité, le plus proche de s_f
Elle porte les noms des quatre causes : dans la répétition « panne jamais
vue », sa colonne « inconnue » est sans objet, et sa désignation ne dit rien
de l'inconnu (chaque branche a été écrite pour sa cause).

VERSIONS ÉCARTÉES, dites honnêtement (sorties dans
campagnes/versions-vues-sur-test/, chiffres dans le journal) :
  1. la première version a été NOTÉE SUR LE TEST, puis changée : une seule
     limite d'alarme pour la file et les machines (8,6, fixée par le bruit des
     machines ; la file des blocages et des charges ne s'écarte que de 4 à
     10, vu sur les pannes d'apprentissage) ; la charge nommée par un dépôt
     au-dessus de s, et une sortie « file pleine inexpliquée → inconnue »,
     remplacées par la charge par élimination ; la machine des répliques à s au
     lieu de s_m ; et le plancher d'échelle fautif de l'ancien témoin 2 (c'est
     lui qui la rendait aveugle à la lenteur). Détection 107/153, cause 52/153,
     lenteur top-1 0/38. L'étape de la cause commune y était déjà. Les chiffres
     de la règle sur les causes connues sont donc « après une révision
     informée par le test » ; la base lente ne l'est pas si la règle est figée
     avant la phase C ;
  2. après deux relectures, vérifié sur la validation seule : cpu_busy retiré de
     la saturation (21 → 2 fausses alertes sur 102 : c'était la dérive de
     ts-order-service, pas un reste de la panne) ; une réplique sans temps de
     traitement (et non « une valeur absente de plus ») ; les autres appelants
     comptés par service ; mêmes scores pour les désignés ; les deux versions.

HASARD : aucun, une seule note par version et par réglage.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage (sans
exemples : les normales seules) ; au test, les nombres, les flèches et les
noms des nœuds de la fenêtre (repondre ne reçoit que fen["donnees"]).

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --validation           la coupure répétée dans l'apprentissage (juge.validation),
                         le vrai test jamais lu : pour régler ; écrit
                         <campagnes>/temoin_fleches-validation.txt
  --help                 ce texte

Écrit <campagnes>/temoin_fleches.txt et affiche le même texte. Code de sortie
0, 1 si une campagne est refusée, 2 sur un mauvais argument. Bibliothèque
standard seulement.
"""
from __future__ import annotations

import contextlib
import io
import math
import sys
from collections import Counter
from pathlib import Path

import fautifs as fautifs_module
import gel
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
FILE_PLEINE = ("backlog", "backlog_slope", "rate_imbalance")
# La saturation, pas l'occupation (méthode USE : cpu_busy dit combien la machine
# travaille, la pression dit combien de tâches attendent).
SATURATION = ("cpu_pressure", "memory_pressure", "io_pressure")
TEMPS = ("process_time_p50", "process_time_p95", "process_time_p99")
LATENCES = ("latency_p50", "latency_p95", "latency_p99")
APPELS = ("calls", "queries")
GRILLE = (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100)
REGLAGES = ("sans exemples", "avec exemples")
VARIANTES = ("littérale", "cause commune")


def _haut(z: dict[str, float], colonnes) -> float:
    """Le plus grand écart vers le haut parmi ces nombres ; −inf si aucun."""
    return max((z[c] for c in colonnes if c in z), default=-math.inf)


def _ident(cle: str) -> str:
    return tn.identite(*cle.split(":", 1))


class NormalFleches:
    """Le normal de chaque flèche, et qui consomme chaque file dans le normal."""

    def __init__(self, fenetres: list[dict], fige: dict):
        self.log = {r: set(v) for r, v in fige["log_avant_echelle"]["relations"].items()}
        valeurs: dict[tuple, dict[str, list[float]]] = {}
        self.consommateurs: dict[str, set[str]] = {}
        for f in fenetres:
            for rel, src, tgt, ligne in self._fleches(f["donnees"]):
                cle = (rel, _ident(src), _ident(tgt))
                for c, v in ligne.items():
                    valeurs.setdefault(cle, {}).setdefault(c, []).append(v)
                if rel == "consumes":
                    self.consommateurs.setdefault(src, set()).add(cle[2])
        self.stats = tn.echelles(valeurs, lambda cle: cle[0])

    def _fleches(self, donnees: dict):
        """(relation, clé source, clé cible, {nombre : valeur transformée}) ; les absents omis."""
        for rel, bloc in donnees["edges"].items():
            sn = donnees["nodes"][bloc["source_kind"]]["names"]
            tg = donnees["nodes"][bloc["target_kind"]]["names"]
            for s, t, row in zip(bloc["source"], bloc["target"], bloc["X"]):
                ligne = {c: (math.log1p(max(0.0, v)) if c in self.log.get(rel, ()) else float(v))
                         for c, v in zip(bloc["columns"], row) if v is not None}
                yield rel, juge._cle(bloc["source_kind"], sn[s]), juge._cle(bloc["target_kind"], tg[t]), ligne

    def ecarts(self, donnees: dict) -> list[tuple[str, str, str, dict[str, float]]]:
        out = []
        for rel, src, tgt, ligne in self._fleches(donnees):
            st = self.stats.get((rel, _ident(src), _ident(tgt)), {})
            out.append((rel, src, tgt, {c: (v - st[c][0]) / st[c][1] for c, v in ligne.items() if c in st}))
        return out


def remplissage(zn: dict[str, dict[str, float]]) -> float:
    """Le plus haut écart des files vers le remplissage."""
    return max([_haut(z, FILE_PLEINE) for k, z in zn.items() if k.startswith("queue:")] + [-math.inf])


def saturation(zn: dict[str, dict[str, float]]) -> float:
    """Le plus haut écart des machines vers la saturation."""
    return max([_haut(z, SATURATION) for k, z in zn.items() if k.startswith("host:")] + [-math.inf])


def marche(donnees: dict, zn: dict, ze: list, consommateurs: dict, avec_temps: set[str],
           s_f: float, s_m: float, s: float, variante: str) -> tuple[str, list[str], list[str], str]:
    """(cause, désignés, chemin, branche) : la règle, pas à pas."""
    files = sorted(((_haut(z, FILE_PLEINE), k) for k, z in zn.items() if k.startswith("queue:")), reverse=True)
    hotes = sorted(((_haut(z, SATURATION), k) for k, z in zn.items() if k.startswith("host:")), reverse=True)
    if not files or files[0][0] <= s_f:
        if hotes and hotes[0][0] > s_m:
            return "hote", [hotes[0][1]], [], "1 machine saturée"
        return "normale", [], [], "1 rien"
    file = files[0][1]
    inst = donnees["nodes"]["instance"]
    conso = [juge._cle("instance", n) for n in inst["names"]
             if tn.identite("instance", n) in consommateurs.get(file, set())]
    debit = {tgt: z for rel, src, tgt, z in ze if rel == "consumes" and src == file}
    muet = lambda c: _ident(c) in avec_temps and not any(t in zn.get(c, {}) for t in TEMPS)
    geles = [c for c in conso if c not in debit or debit[c].get("rate", 0.0) < -s or muet(c)]
    if geles:
        return "blocage", geles, [file], "2 réplique qui ne consomme plus"
    lents = [c for c in conso if _haut(zn.get(c, {}), TEMPS) > s]
    if not lents:
        return "charge", [], [file] + conso, "2 répliques saines : trop de dépôts"

    # 3. ce qui explique la lenteur : les machines des répliques lentes (le champ
    # « hosts » des nœuds, identique aux flèches executes_on)…
    machine = dict(zip((juge._cle("instance", n) for n in inst["names"]), inst["hosts"]))
    leurs = sorted({juge._cle("host", machine[c]) for c in lents if machine.get(c)})
    satures = sorted(((_haut(zn.get(h, {}), SATURATION), h) for h in leurs), reverse=True)
    if satures and satures[0][0] > s_m:
        return "hote", [satures[0][1]], [file] + lents, "3 machine des répliques saturée"
    # … puis ce qu'elles appellent.
    cibles = Counter(tgt for rel, src, tgt, z in ze if rel in APPELS and src in lents and _haut(z, LATENCES) > s)
    lents_id = {_ident(c) for c in lents}
    for t, _ in sorted(cibles.items(), key=lambda kv: (-kv[1], kv[0])):
        if variante == "littérale":
            # le dernier composant anormal : la cible, si ses propres nombres le sont
            if (tn.score(zn.get(t, {})) or 0.0) > s:
                return "inconnue", [t], [file] + lents, "3 dépendance anormale"
            continue
        # cause commune : les AUTRES services qui l'appellent (un par service, sa
        # flèche la plus lente) la voient-ils aussi plus lente ?
        autres: dict[str, float] = {}
        for rel, src, tgt, z in ze:
            if rel in APPELS and tgt == t and _ident(src) not in lents_id:
                autres[_ident(src)] = max(autres.get(_ident(src), -math.inf), _haut(z, LATENCES))
        plus_lents = sum(1 for v in autres.values() if v > s)
        if len(autres) >= 2 and 2 * plus_lents > len(autres):
            return "inconnue", [t], [file] + lents, "3 dépendance lente pour tous"
    return "lenteur", lents, [file], "3 répliques lentes"


class Fleches:
    """La règle réglée : les normaux des nœuds et des flèches, ses limites."""

    def __init__(self, fen: list[dict], reglage: str, fige: dict, variante: str = "cause commune"):
        if reglage not in REGLAGES or variante not in VARIANTES:
            raise ValueError(f"réglage ou variante inconnus : {reglage}, {variante}")
        self.reglage, self.variante = reglage, variante
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        campagnes = sorted({f["campagne"] for f in normales})
        if len(campagnes) < 2:
            raise ValueError("il faut des fenêtres normales d'apprentissage dans au moins deux campagnes")
        normaux = tn.Normaux(normales, fige)
        self.noeuds = normaux.sans()
        self.fleches = NormalFleches(normales, fige)
        self.avec_temps = {i for i, st in self.noeuds.stats.items() if any(t in st for t in TEMPS)}

        # s_f et s_m : chaque campagne mise de côté à son tour, sur le normal seul.
        files, machines = [], []
        for c in campagnes:
            for f in (f for f in normales if f["campagne"] == c):
                zn = normaux.sans(c).ecarts(f["donnees"])
                files.append(remplissage(zn))
                machines.append(saturation(zn))
        centile = lambda v: tn._q([x for x in v if x > -math.inf], 1 - tn.CENTILE / 100) \
            if any(x > -math.inf for x in v) else 0.0
        self.s_f, self.s_m = centile(files), centile(machines)
        self.calage = (len(campagnes), len(files),
                       sum(1 for a, b in zip(files, machines) if a > self.s_f or b > self.s_m))
        self.s = self.s_f
        if reglage == "sans exemples":
            return

        # Avec exemples : s, sur les fenêtres de panne d'apprentissage.
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        ecarts = {f["id"]: (self.noeuds.ecarts(f["donnees"]), self.fleches.ecarts(f["donnees"])) for f in pannes}
        notes = {}
        for s in GRILLE:
            juste = 0
            for f in pannes:
                zn, ze = ecarts[f["id"]]
                cause, designes, _, _ = marche(f["donnees"], zn, ze, self.fleches.consommateurs, self.avec_temps,
                                               self.s_f, self.s_m, s, variante)
                juste += (cause == f["cause"]) + bool(f["fautifs"] and designes and designes[0] in f["fautifs"])
            notes[s] = juste
        meilleur = max(notes.values())
        self.s = min((s for s, n in notes.items() if n == meilleur),
                     key=lambda s: abs(math.log(s / self.s_f)) if self.s_f > 0 else s)
        self.grille = notes
        self.grille_sur = sum(1 + bool(f["fautifs"]) for f in pannes)

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir de ses seuls nombres et flèches."""
        zn = self.noeuds.ecarts(donnees)
        ze = self.fleches.ecarts(donnees)
        cause, designes, chemin, branche = marche(donnees, zn, ze, self.fleches.consommateurs, self.avec_temps,
                                                  self.s_f, self.s_m, self.s, self.variante)
        scores = {k: (min(v, 1e7) if (v := tn.score(z)) is not None else None) for k, z in zn.items()}
        # Même score pour tous les désignés, et pour tout le chemin : entre eux,
        # le juge départage contre le témoin (jamais l'ordre des noms).
        for k in chemin:
            scores[k] = 1e8
        for k in designes:
            scores[k] = 1e9
        return {"alarme": cause != "normale", "cause": cause, "scores": scores, "_branche": branche}


def rapport(noms: list[str], campagnes: Path, runs: Path, validation: bool = False) -> int:
    try:
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    fige, _, _ = gel.reference()
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    print("# Témoin 3, la règle qui suit les flèches — écrit par graphe_en/temoin_fleches.py, "
          "ne pas éditer à la main.")
    for variante in VARIANTES:
        for reglage in REGLAGES:
            t = Fleches(fen, reglage, fige, variante)
            reponses = {f["id"]: t.repondre(f["donnees"]) for f in test}
            propres = {i: {k: v for k, v in r.items() if not k.startswith("_")} for i, r in reponses.items()}
            lignes, _ = juge.noter(fen, propres, f"règle qui suit les flèches, {variante}, {reglage}")
            print()
            if variante == VARIANTES[0] and reglage == "sans exemples":
                conso = "; ".join(f"{q} ← {', '.join(sorted(v))}"
                                  for q, v in sorted(t.fleches.consommateurs.items()))
                print(f"# consommateurs dans le normal : {conso}")
                print(f"# limites d'alarme : file s_f = {t.s_f:.2f}, machines s_m = {t.s_m:.2f} (plus haut "
                      f"écart ; {t.calage[0]} campagnes mises de côté, {t.calage[1]} fenêtres, "
                      f"{100 - tn.CENTILE}e centile chacune) ; les deux ensemble sonnent sur "
                      f"{t.calage[2]}/{t.calage[1]} de ces fenêtres")
            if reglage == "avec exemples":
                print(f"# limite de marche s = {t.s:g}, choisie sur les pannes d'apprentissage (cause juste "
                      f"+ fautif top-1, sur {t.grille_sur}) : " + ", ".join(f"{s:g}:{n}" for s, n in t.grille.items()))
            else:
                print(f"# limite de marche s = s_f = {t.s:.2f}")
            print("\n".join(lignes))
            print("branche de la règle, par étiquette (fenêtres de test)")
            par: dict[str, Counter] = {}
            for f in test:
                par.setdefault(f["cause"] or "normale", Counter())[reponses[f["id"]]["_branche"]] += 1
            for c, cnt in sorted(par.items()):
                print(f"  {c:<9}" + ", ".join(f"{b} {n}" for b, n in cnt.most_common()))
    print("\n# le plancher à battre, qui ne lit aucune donnée (juge.py)")
    lignes, _ = juge.noter(fen, juge.factices(fen)["a priori"], "a priori")
    print("\n".join(l for l in lignes if not l.startswith("  ") or "injection" not in l))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    validation = False
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
            elif a == "--validation":
                validation = True
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except IndexError:
        print("option sans valeur", file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    noms = noms or fautifs_module.SERIES
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        print(f"# campagnes lues : {', '.join(noms)}")
        code = rapport(noms, campagnes, runs, validation)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / juge.sortie("temoin_fleches", noms, validation)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
