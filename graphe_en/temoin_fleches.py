"""
Témoin 3 : la règle qui suit les flèches. Écrite à la main ; elle lit la structure.

    ./.venv/bin/python temoin_fleches.py [options] [campagne ...]

Phase B.5. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. Définie le 24 sept. 2026 : « la file → ses
répliques → ce qu'elles appellent → le dernier composant anormal ». Écrite
comme par un ingénieur qui connaît la plateforme, le graphe figé et les quatre
causes apprises, et rien d'autre : aucun cas particulier pour une base de
données. Là où les témoins 1 et 2 n'ont pas la structure, celui-ci n'a que
la structure et quelques limites : si le GNN ne fait pas mieux, les flèches
suffisent et le modèle appris n'apporte rien.

« ANORMAL », en écarts z au normal propre (la recette du témoin 2)
  un nœud     les écarts de temoin_noeud.Normal
  une flèche  la même recette (temoin_noeud.echelles) sur les nombres de
              chaque flèche ; son identité est (relation, identité de la source,
              identité de la cible), la même pour les trois répliques d'un
              service ; le plancher mis en commun par relation
  Les consommateurs d'une file : les identités qui la consomment dans les
  fenêtres normales (une réplique gelée n'a plus de flèche consumes : on sait
  par le normal qu'elle devrait en avoir une).

LA MARCHE, fenêtre par fenêtre (s_f, s_m : limites d'alarme de la file et
des machines ; s : limite de marche)
  1. une file se remplit-elle ? (backlog, backlog_slope ou rate_imbalance
     au-dessus de s_f ; la plus pleine d'abord)
       non : une machine est-elle saturée ? (cpu_busy, cpu_pressure,
             memory_pressure ou io_pressure au-dessus de s_m) → hote, la plus
             saturée ; sinon normale
  2. ses consommateurs :
       une réplique qui ne consomme plus (pas de flèche consumes depuis la
       file, débit sous −s, ou plus de valeurs absentes que son normal de
       plus de s) → blocage, ces répliques
       des répliques plus lentes (un temps de traitement au-dessus de s) → 3.
       aucune : la file se remplit avec des répliques saines, donc on y
       dépose plus qu'elles ne peuvent prendre → charge, aucun fautif
  3. ce qui explique la lenteur, en suivant les flèches des répliques lentes :
       leur machine (executes_on) saturée au-dessus de s_m → hote, la machine
       une flèche sortante (calls, queries) plus lente (une latence au-dessus
       de s) vers une cible t, et la plupart des AUTRES appelants de t (au
       moins deux) la voient aussi plus lente → la cause est t (principe de
       la cause commune ; aucune des quatre causes : « inconnue »)
       sinon → lenteur, les répliques lentes
  Le classement de tous les nœuds : les désignés, puis ceux du chemin
  parcouru, puis tous les autres par leur écart (le score sans exemples du
  témoin 2). L'alarme : une cause autre que « normale ».
  Pourquoi la cause commune : pour la lenteur, le retard est posé sur ce que
  les répliques envoient à la base ; une règle qui suivrait ces flèches
  jusqu'au bout accuserait la base. Ce qui innocente la base, c'est que ses
  autres appelants ne voient rien. Principe général du diagnostic, écrit pour
  la lenteur ; il peut aussi, par construction, désigner une dépendance lente
  pour tous, et c'est voulu : le témoin qui suit les flèches doit être le
  plus fort possible.

DEUX RÉGLAGES (fautifs.py)
  s_f, s_m   les mêmes pour les deux, calés sur le normal seul (fautifs.py) :
             chaque campagne mise de côté à son tour, les normaux appris sur
             les autres ; s_f = 95e centile, sur ses fenêtres normales
             d'apprentissage, du plus haut écart des files (remplissage), s_m
             de même pour les machines (saturation)
  sans exemples  s = s_f : ce qui compte comme un écart pour la file compte
             pour ses répliques
  avec exemples  s choisi dans une grille, celui qui nomme le mieux la cause
             et le fautif (top-1) des fenêtres de panne d'apprentissage ; à
             égalité, le plus proche de s_f
PREMIER ESSAI ÉCARTÉ (vu sur les pannes d'apprentissage) : une seule limite
d'alarme pour la file et les machines (8,6), fixée par le bruit de saturation
des machines ; la file des blocages et des charges ne s'écarte que de 4 à 10
et restait souvent dessous. Et la charge nommée par un dépôt au-dessus de s
(il ne l'était que de 2 à 3) : remplacée par l'élimination ci-dessus.
Les noms des quatre causes sont écrits dans la règle (l'ingénieur les connaît) :
dans la répétition « panne jamais vue », seule sa désignation compte.

HASARD : aucun, une seule note.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage (sans
exemples : les normales seules) ; au test, les seuls nombres et flèches de la
fenêtre (repondre ne reçoit que fen["donnees"]).

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
import statistics
import sys
from collections import Counter
from pathlib import Path

import fautifs as fautifs_module
import gel
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
FILE_PLEINE = ("backlog", "backlog_slope", "rate_imbalance")
SATURATION = ("cpu_busy", "cpu_pressure", "memory_pressure", "io_pressure")
TEMPS = ("process_time_p50", "process_time_p95", "process_time_p99")
LATENCES = ("latency_p50", "latency_p95", "latency_p99")
APPELS = ("calls", "queries")
GRILLE = (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100)
REGLAGES = ("sans exemples", "avec exemples")


def _haut(z: dict[str, float], colonnes) -> float:
    """Le plus grand écart vers le haut parmi ces nombres ; −inf si aucun."""
    return max((z[c] for c in colonnes if c in z), default=-math.inf)


class NormalFleches:
    """Le normal de chaque flèche, et qui consomme chaque file dans le normal."""

    def __init__(self, fenetres: list[dict], fige: dict):
        self.log = {r: set(v) for r, v in fige["log_avant_echelle"]["relations"].items()}
        valeurs: dict[tuple, dict[str, list[float]]] = {}
        self.consommateurs: dict[str, set[str]] = {}
        for f in fenetres:
            for rel, src, tgt, ligne in self._fleches(f["donnees"]):
                cle = (rel, tn.identite(*src.split(":", 1)), tn.identite(*tgt.split(":", 1)))
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
            st = self.stats.get((rel, tn.identite(*src.split(":", 1)), tn.identite(*tgt.split(":", 1))), {})
            out.append((rel, src, tgt, {c: (v - st[c][0]) / st[c][1] for c, v in ligne.items() if c in st}))
        return out


def remplissage(zn: dict[str, dict[str, float]]) -> float:
    """Le plus haut écart des files vers le remplissage."""
    return max([_haut(z, FILE_PLEINE) for k, z in zn.items() if k.startswith("queue:")] + [-math.inf])


def saturation(zn: dict[str, dict[str, float]]) -> float:
    """Le plus haut écart des machines vers la saturation."""
    return max([_haut(z, SATURATION) for k, z in zn.items() if k.startswith("host:")] + [-math.inf])


def marche(donnees: dict, zn: dict, ze: list, consommateurs: dict, s_f: float, s_m: float,
           s: float) -> tuple[str, list[str], list[str], str]:
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
    geles = [c for c in conso if c not in debit or debit[c].get("rate", 0.0) < -s
             or zn.get(c, {}).get(tn.ABSENTS, 0.0) > s]
    if geles:
        return "blocage", geles, [file], "2 réplique qui ne consomme plus"
    lents = [c for c in conso if _haut(zn.get(c, {}), TEMPS) > s]
    if not lents:
        return "charge", [], [file] + conso, "2 répliques saines : trop de dépôts"

    # 3. ce qui explique la lenteur : les machines des répliques lentes…
    machine = dict(zip((juge._cle("instance", n) for n in inst["names"]), inst["hosts"]))
    leurs = sorted({juge._cle("host", machine[c]) for c in lents if machine.get(c)})
    satures = sorted(((_haut(zn.get(h, {}), SATURATION), h) for h in leurs), reverse=True)
    if satures and satures[0][0] > s_m:
        return "hote", [satures[0][1]], [file] + lents, "3 machine des répliques saturée"
    # … puis ce qu'elles appellent, avec la cause commune.
    cibles = Counter(tgt for rel, src, tgt, z in ze if rel in APPELS and src in lents and _haut(z, LATENCES) > s)
    for t, _ in sorted(cibles.items(), key=lambda kv: (-kv[1], kv[0])):
        autres = [z for rel, src, tgt, z in ze if rel in APPELS and tgt == t and src not in lents]
        plus_lents = sum(1 for z in autres if _haut(z, LATENCES) > s)
        if len(autres) >= 2 and 2 * plus_lents > len(autres):
            return "inconnue", [t], [file] + lents, "3 dépendance lente pour tous"
    return "lenteur", lents, [file], "3 répliques lentes"


class Fleches:
    """La règle réglée : les normaux des nœuds et des flèches, ses deux limites."""

    def __init__(self, fen: list[dict], reglage: str, fige: dict):
        if reglage not in REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        self.reglage = reglage
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        if not normales:
            raise ValueError("aucune fenêtre normale d'apprentissage")
        self.noeuds = tn.Normal(normales, fige)
        self.fleches = NormalFleches(normales, fige)

        # s_f et s_m : chaque campagne mise de côté à son tour, sur le normal seul.
        files, machines = [], []
        campagnes = sorted({f["campagne"] for f in normales})
        for c in campagnes:
            autres = [f for f in normales if f["campagne"] != c]
            if autres:
                n = tn.Normal(autres, fige)
                for f in (f for f in normales if f["campagne"] == c):
                    zn = n.ecarts(f["donnees"])
                    files.append(remplissage(zn))
                    machines.append(saturation(zn))
        centile = lambda v: tn._q([x for x in v if x > -math.inf], 1 - tn.CENTILE / 100) \
            if any(x > -math.inf for x in v) else 0.0
        self.s_f, self.s_m = centile(files), centile(machines)
        self.calage = (len(campagnes), len(files))
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
                cause, designes, _, _ = marche(f["donnees"], zn, ze, self.fleches.consommateurs,
                                               self.s_f, self.s_m, s)
                juste += (cause == f["cause"]) + bool(f["fautifs"] and designes and designes[0] in f["fautifs"])
            notes[s] = juste
        meilleur = max(notes.values())
        self.s = min((s for s, n in notes.items() if n == meilleur),
                     key=lambda s: abs(math.log(s / self.s_f)) if self.s_f > 0 else s)
        self.grille = notes

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir de ses seuls nombres et flèches."""
        zn = self.noeuds.ecarts(donnees)
        ze = self.fleches.ecarts(donnees)
        cause, designes, chemin, branche = marche(donnees, zn, ze, self.fleches.consommateurs,
                                                  self.s_f, self.s_m, self.s)
        scores = {k: (min(v, 1e7) if (v := tn.score(z)) is not None else None) for k, z in zn.items()}
        for i, k in enumerate(chemin):
            scores[k] = 1e8 - i
        for i, k in enumerate(designes):
            scores[k] = 1e9 - i
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
    for reglage in REGLAGES:
        t = Fleches(fen, reglage, fige)
        reponses = {f["id"]: t.repondre(f["donnees"]) for f in test}
        propres = {i: {k: v for k, v in r.items() if not k.startswith("_")} for i, r in reponses.items()}
        lignes, _ = juge.noter(fen, propres, f"règle qui suit les flèches, {reglage}")
        print()
        if reglage == "sans exemples":
            conso = "; ".join(f"{q} ← {', '.join(sorted(v))}" for q, v in sorted(t.fleches.consommateurs.items()))
            print(f"# consommateurs dans le normal : {conso}")
        print(f"# limites d'alarme : file s_f = {t.s_f:.2f}, machines s_m = {t.s_m:.2f} (plus haut écart ; "
              f"{t.calage[0]} campagnes mises de côté, {t.calage[1]} fenêtres, {100 - tn.CENTILE}e centile)")
        if reglage == "avec exemples":
            print(f"# limite de marche s = {t.s:g}, choisie sur les pannes d'apprentissage "
                  f"(cause juste + fautif top-1, sur 2 par fenêtre) : "
                  + ", ".join(f"{s:g}:{n}" for s, n in t.grille.items()))
        else:
            print(f"# limite de marche s = s_f")
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
        code = rapport(noms, campagnes, runs, validation)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / ("temoin_fleches-validation.txt" if validation else "temoin_fleches.txt")
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
