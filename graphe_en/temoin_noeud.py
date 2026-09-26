"""
Témoin 2 : le score par nœud. Chaque nœud comparé à son propre normal, aucune flèche.

    ./.venv/bin/python temoin_noeud.py [options] [campagne ...]

Phase B.4. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. C'est la première étape du GNN sans les flèches : le
GNN reconstruira le normal de chaque nœud avec ses voisins, ce témoin le
compare à son seul passé. Même idée que les lignes de base publiées qui
classent les composants par l'écart de leurs mesures à leur période normale
(N-sigma ; BARO et son échelle robuste, médiane et écart interquartile).

LE NORMAL D'UN NŒUD, appris sur les fenêtres normales d'apprentissage seules

  son identité  une machine, une file : son nom ; un pod de StatefulSet
                (tsdb-mysql-0, nacos-1) : son nom, qui est stable ; un pod de
                Deployment : son service, car le pod change de nom quand il est
                recréé, et ses répliques font le même travail
  ses nombres   ceux du graphe figé, passés en log1p pour les colonnes que le
                gel met en log avant l'échelle ; plus un : le nombre de ses
                valeurs absentes (un pod gelé ne rend plus de durées)
  par nombre    s'il est présent dans au moins 10 fenêtres normales : sa
                médiane, et son échelle, la plus grande de deux estimations d'un
                écart-type : l'écart interquartile / 1,349, et l'écart entre
                1er et 99e centiles / 4,653 (égales pour une courbe en cloche ;
                la seconde tient compte des pics rares d'un nombre presque
                toujours nul, comme cpu_throttle_ratio)
  l'écart       z = (valeur − médiane) / échelle ; l'échelle ne descend jamais
                sous PLANCHER fois l'écart-type du nombre sur tous les nœuds de
                la même sorte (un nombre constant dans le normal, comme les
                redémarrages, aurait sinon une échelle nulle)
Une valeur absente ne donne pas d'écart (seul le compte des absents en donne
un). Un nœud dont l'identité n'a pas de normal n'a pas de score : dernier.

DEUX RÉGLAGES (fautifs.py : sans exemple de panne, puis avec)

  sans exemples  il ne connaît que le normal. Score d'un nœud : le plus grand
                 |z| de ses nombres. Alarme si le plus haut score de la fenêtre
                 dépasse le seuil d'alarme ; la cause est alors « inconnue » (il
                 ne sait nommer aucune panne), « normale » sinon
  avec exemples  l'alarme : un détecteur appris, une forêt aléatoire (200
                 arbres, le même apprenant que le tableau) « panne ou non » sur
                 le profil d'écart de la fenêtre (ci-dessous), qui apprend quels
                 écarts comptent ; plus l'alarme sans exemples, pour ne pas taire
                 une panne qui ne ressemble à aucune apprise. Rejet des deux
                 côtés, comme le tableau : alarme du détecteur, cause nommée par
                 les prototypes ; alarme sans exemples seule, cause « inconnue ».
                 La cause : le prototype le plus proche, comme le classifieur à
                 prototypes du GNN. Le profil d'une fenêtre : pour chaque sorte
                 et chaque nombre, le plus grand et le plus petit z sur ses
                 nœuds, compressés en log1p (signe gardé) ; le prototype d'une
                 cause : la moyenne des profils de ses fenêtres de panne
                 d'apprentissage ; « inconnue » si la distance au plus proche
                 dépasse le seuil de rejet.
                 Le fautif : une régression logistique partagée par tous les
                 nœuds, comme le GNN partage ses poids : un poids par sorte et
                 par nombre, sur la part positive et la part négative de chaque
                 écart (compressées en log1p), apprise sur les nœuds des fenêtres
                 d'apprentissage, fautifs ou non. Aucun nom de nœud n'y entre :
                 c'est le « plus grand écart » dont les exemples ont appris quels
                 nombres comptent

LES SEUILS, jamais sur le test, calés comme face à du nouveau (fautifs.py)
  alarme  chaque campagne mise de côté à son tour : le normal (et, avec
          exemples, le détecteur) appris sur les autres, le score de ses
          fenêtres normales d'apprentissage ; seuil = 95e centile de ces
          scores. Seuils réglés sur le normal seul (fautifs.py). Le seuil sans
          exemples sert aux deux réglages
  rejet   chaque injection d'apprentissage mise de côté à son tour : les
          prototypes appris sans elle ; seuil = 95e centile des distances de
          ses fenêtres bien classées. Même règle que le tableau et le GNN

HASARD : sans exemples, aucun (médianes) : une seule note. Avec exemples, la
forêt du détecteur tire au hasard : graines 0 à 4 (fautifs.py), note détaillée
de la graine 0, puis chaque nombre avec son minimum, sa médiane et son maximum.

DEUX ESSAIS ÉCARTÉS, dits honnêtement :
  - l'échelle par l'écart interquartile seul : un nombre presque toujours nul
    avec de rares pics (cpu_throttle_ratio, memory_slope) donnait des |z| de
    plusieurs centaines dans des fenêtres normales, et un seuil d'alarme de
    138. Vu sur le calage (fenêtres normales seules) ; corrigé par l'écart
    entre 1er et 99e centiles ;
  - le détecteur en régression logistique : trop sûre d'elle, elle donnait
    presque 0 aux fenêtres normales mises de côté, d'où un seuil de 0,043 que
    le moindre glissement de fin de campagne dépassait (28 % de fausses
    alertes au test). Remplacée par la forêt.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage avec
leur étiquette, leur cause et leurs fautifs (sans exemples : les normales
seules) ; au test, les seuls nombres des nœuds de la fenêtre (repondre ne
reçoit que fen["donnees"], et n'en lit pas les flèches).

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --graines <n>          nombre de graines, à partir de 0 (défaut 5)
  --no-install           n'installe jamais scikit-learn
  --help                 ce texte

Écrit <campagnes>/temoin_noeud.txt et affiche le même texte. Code de sortie
0, 1 si une campagne est refusée ou une bibliothèque manque, 2 sur un mauvais
argument.
"""
from __future__ import annotations

import contextlib
import io
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import bootstrap
import fautifs as fautifs_module
import gel
import juge

HERE = Path(__file__).resolve().parent
PLANCHER = 0.1
ARBRES = 200
CENTILE = 5
MIN_OBS = 10
ABSENTS = "absents"
SORTES = ("instance", "queue", "host")
REGLAGES = ("sans exemples", "avec exemples")


def identite(kind: str, nom: str) -> str:
    """Le nœud dont on apprend le normal : le service pour un pod de Deployment.

    Le hachage d'un ReplicaSet n'emploie que 4-9, b, c, d, f (SafeEncodeString
    d'un nombre décimal) : le motif hexadécimal le reconnaît toujours."""
    if kind == "instance":
        m = re.match(r"^(.*)-[0-9a-f]{6,10}-[a-z0-9]{5}$", nom)
        if m:
            return f"instance:{m.group(1)}"
    return f"{kind}:{nom}"


def _colonnes(fige: dict) -> dict[str, list[str]]:
    return {k: list(fige["noeuds"][k]) + [ABSENTS] for k in SORTES}


def _q(vals: list[float], p: float) -> float:
    """Quantile par interpolation linéaire (celui de numpy par défaut)."""
    s = sorted(vals)
    x = (len(s) - 1) * p
    i = int(math.floor(x))
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (x - i)


class Normal:
    """Le normal de chaque nœud : médiane et échelle de chacun de ses nombres."""

    def __init__(self, fenetres: list[dict], fige: dict):
        self.colonnes = _colonnes(fige)
        self.log = {k: set(fige["log_avant_echelle"]["noeuds"].get(k, [])) for k in SORTES}
        valeurs: dict[str, dict[str, list[float]]] = {}
        sorte: dict[str, dict[str, list[float]]] = {k: {} for k in SORTES}
        for f in fenetres:
            for kind, nom, ligne in self._lignes(f["donnees"]):
                ident = valeurs.setdefault(identite(kind, nom), {})
                for c, v in ligne.items():
                    ident.setdefault(c, []).append(v)
                    sorte[kind].setdefault(c, []).append(v)
        self.ecart_type = {}
        for kind in SORTES:
            for c, vals in sorte[kind].items():
                sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
                self.ecart_type[(kind, c)] = sd if sd > 1e-12 else 1.0
        self.stats: dict[str, dict[str, tuple[float, float]]] = {}
        for ident, par in valeurs.items():
            kind = ident.split(":", 1)[0]
            self.stats[ident] = {}
            for c, vals in par.items():
                if len(vals) < MIN_OBS:
                    continue
                propre = max((_q(vals, 0.75) - _q(vals, 0.25)) / 1.349,
                             (_q(vals, 0.99) - _q(vals, 0.01)) / 4.653)
                self.stats[ident][c] = (statistics.median(vals),
                                        max(propre, PLANCHER * self.ecart_type[(kind, c)]))

    def _lignes(self, donnees: dict):
        """(sorte, nom, {nombre: valeur transformée}) pour chaque nœud ; les absents omis."""
        for kind in SORTES:
            bloc = donnees["nodes"][kind]
            for nom, row in zip(bloc["names"], bloc["X"]):
                ligne = {ABSENTS: float(sum(1 for v in row if v is None))}
                for c, v in zip(bloc["columns"], row):
                    if v is not None:
                        ligne[c] = math.log1p(max(0.0, v)) if c in self.log[kind] else float(v)
                yield kind, nom, ligne

    def ecarts(self, donnees: dict) -> dict[str, dict[str, float]]:
        """{clé du juge : {nombre : z}} ; {} pour un nœud dont l'identité n'a pas de normal."""
        out = {}
        for kind, nom, ligne in self._lignes(donnees):
            st = self.stats.get(identite(kind, nom), {})
            out[juge._cle(kind, nom)] = {c: (v - st[c][0]) / st[c][1] for c, v in ligne.items() if c in st}
        return out


def score(z: dict[str, float]) -> float | None:
    """Sans exemples : le plus grand |z| du nœud."""
    return max((abs(v) for v in z.values()), default=None)


def score_fenetre(ecarts: dict[str, dict[str, float]]) -> float:
    return max((s for s in map(score, ecarts.values()) if s is not None), default=0.0)


def _c(x: float) -> float:
    """Écart compressé, signe gardé : les écarts énormes ne font pas toute la distance."""
    return math.copysign(math.log1p(abs(x)), x)


def profil(ecarts: dict[str, dict[str, float]], colonnes: dict[str, list[str]]) -> list[float]:
    """Pour chaque sorte et chaque nombre, le plus grand et le plus petit z sur les nœuds."""
    out = []
    for kind in SORTES:
        for c in colonnes[kind]:
            vals = [z[c] for cle, z in ecarts.items() if cle.startswith(kind + ":") and c in z]
            out += [_c(max(vals)), _c(min(vals))] if vals else [0.0, 0.0]
    return out


def ligne_noeud(cle: str, z: dict[str, float], colonnes: dict[str, list[str]]) -> list[float]:
    """La ligne d'un nœud pour la régression : sa sorte, puis un bloc par sorte (le
    sien rempli, les autres à zéro) : part positive et part négative de chaque écart."""
    kind = cle.split(":", 1)[0]
    out = [1.0 if kind == k else 0.0 for k in SORTES]
    for k in SORTES:
        for c in colonnes[k]:
            v = z.get(c) if k == kind else None
            out += [math.log1p(max(v, 0.0)), math.log1p(max(-v, 0.0))] if v is not None else [0.0, 0.0]
    return out


def _dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _prototypes(profils: list[list[float]], causes: list[str]) -> dict[str, list[float]]:
    par: dict[str, list[list[float]]] = {}
    for p, c in zip(profils, causes):
        par.setdefault(c, []).append(p)
    return {c: [sum(col) / len(ps) for col in zip(*ps)] for c, ps in par.items()}


def _plus_proche(p: list[float], protos: dict[str, list[float]]) -> tuple[str, float]:
    return min(((c, _dist(p, q)) for c, q in sorted(protos.items())), key=lambda t: t[1])


class Noeud:
    """Le score par nœud appris : son normal, son seuil d'alarme ; avec exemples,
    sa régression du fautif, ses prototypes et son seuil de rejet."""

    def __init__(self, fen: list[dict], reglage: str, fige: dict, graine: int = 0):
        if reglage not in REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        self.reglage = reglage
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        if not normales:
            raise ValueError("aucune fenêtre normale d'apprentissage")
        self.normal = Normal(normales, fige)
        self.colonnes = self.normal.colonnes

        # Le seuil d'alarme : chaque campagne mise de côté à son tour.
        tenus = []
        campagnes = sorted({f["campagne"] for f in normales})
        for c in campagnes:
            autres = [f for f in normales if f["campagne"] != c]
            if not autres:
                continue
            n = Normal(autres, fige)
            tenus += [score_fenetre(n.ecarts(f["donnees"])) for f in normales if f["campagne"] == c]
        self.seuil_alarme = _q(tenus, 1 - CENTILE / 100) if tenus else 0.0
        self.calage_alarme = (len(campagnes), len(tenus))
        if reglage == "sans exemples":
            return

        # Avec exemples : le détecteur, et son seuil, chaque campagne mise de côté.
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        regression = lambda: LogisticRegression(max_iter=5000, class_weight="balanced")
        foret = lambda: RandomForestClassifier(n_estimators=ARBRES, random_state=graine, n_jobs=-1)
        ecarts = {f["id"]: self.normal.ecarts(f["donnees"]) for f in garde}
        panne = [1 if f["etiquette"] == "panne" else 0 for f in garde]
        self.detecteur = foret().fit(
            np.array([profil(ecarts[f["id"]], self.colonnes) for f in garde]), panne)
        tenus = []
        for c in campagnes:
            n = Normal([f for f in normales if f["campagne"] != c], fige)
            autres = [(f, y) for f, y in zip(garde, panne) if f["campagne"] != c]
            if len({y for _, y in autres}) < 2:
                continue
            d = foret().fit(np.array([profil(n.ecarts(f["donnees"]), self.colonnes) for f, _ in autres]),
                                 [y for _, y in autres])
            ici = [f for f in normales if f["campagne"] == c]
            tenus += [float(p[1]) for p in d.predict_proba(
                np.array([profil(n.ecarts(f["donnees"]), self.colonnes) for f in ici]))]
        self.seuil_detecteur = _q(tenus, 1 - CENTILE / 100) if tenus else 1.0

        # Le fautif, une régression pour tous les nœuds.
        xs, ys = [], []
        for f in garde:
            for cle, z in ecarts[f["id"]].items():
                xs.append(ligne_noeud(cle, z, self.colonnes))
                ys.append(1 if cle in f["fautifs"] else 0)
        self.fautifs_appris = sum(ys)
        self.fautif = regression().fit(np.array(xs), ys) if 0 < sum(ys) < len(ys) else None

        # La cause : prototypes et seuil de rejet, chaque injection mise de côté à son tour.
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        profils = {f["id"]: profil(ecarts[f["id"]], self.colonnes) for f in pannes}
        self.prototypes = _prototypes([profils[f["id"]] for f in pannes], [f["cause"] for f in pannes])
        bien = []
        injections = sorted({(f["campagne"], f["injection"]) for f in pannes})
        for g in injections:
            reste = [f for f in pannes if (f["campagne"], f["injection"]) != g]
            protos = _prototypes([profils[f["id"]] for f in reste], [f["cause"] for f in reste])
            for f in (f for f in pannes if (f["campagne"], f["injection"]) == g):
                cause, d = _plus_proche(profils[f["id"]], protos) if protos else (None, 0.0)
                if cause == f["cause"]:
                    bien.append(d)
        self.seuil_rejet = _q(bien, 1 - CENTILE / 100) if bien else math.inf
        self.calage_rejet = (len(injections), len(bien))

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir des seuls nombres de ses nœuds."""
        ecarts = self.normal.ecarts(donnees)
        alarme = score_fenetre(ecarts) > self.seuil_alarme
        if self.reglage == "sans exemples":
            return {"alarme": alarme, "cause": "inconnue" if alarme else "normale",
                    "scores": {cle: score(z) for cle, z in ecarts.items()}}
        import numpy as np
        cles = list(ecarts)
        if self.fautif is not None:
            un = list(self.fautif.classes_).index(1)
            proba = self.fautif.predict_proba(np.array([ligne_noeud(k, ecarts[k], self.colonnes) for k in cles]))
            scores = {k: (float(p[un]) if ecarts[k] else None) for k, p in zip(cles, proba)}
        else:
            scores = {k: None for k in cles}
        p = profil(ecarts, self.colonnes)
        detecte = float(self.detecteur.predict_proba(np.array([p]))[0][1]) > self.seuil_detecteur
        cause, brute = "normale", None
        if detecte and self.prototypes:
            brute, d = _plus_proche(p, self.prototypes)
            cause = brute if d <= self.seuil_rejet else "inconnue"
        elif detecte or alarme:
            cause = "inconnue"
        return {"alarme": detecte or alarme, "cause": cause, "scores": scores, "_sans_rejet": brute}


def premiers(fen: list[dict], reponses: dict) -> list[str]:
    """Qui est désigné en premier, par cause, sur les fenêtres de panne du test."""
    par: dict[str, Counter] = {}
    for f in fen:
        if f["jeu"] != "test" or f["etiquette"] != "panne":
            continue
        sc = reponses[f["id"]]["scores"]
        haut = max(juge.noeuds(f["donnees"]), key=lambda k: (juge._val(sc.get(k)), k not in f["fautifs"]))
        nom = "le fautif" if haut in f["fautifs"] else identite(*haut.split(":", 1))
        par.setdefault(f["cause"], Counter())[nom] += 1
    return [f"  {c:<9}" + ", ".join(f"{n} {k}" for n, k in cnt.most_common(4)) for c, cnt in sorted(par.items())]


def rapport(noms: list[str], campagnes: Path, runs: Path, graines: int) -> int:
    import temoin_tableau
    try:
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    fige, _, _ = gel.reference()
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    print("# Témoin 2, le score par nœud — écrit par graphe_en/temoin_noeud.py, ne pas éditer à la main.")
    for reglage in REGLAGES:
        notes = []
        for g in range(graines if reglage == "avec exemples" else 1):
            t = Noeud(fen, reglage, fige, graine=g)
            reponses = {f["id"]: t.repondre(f["donnees"]) for f in test}
            propres = {i: {k: v for k, v in r.items() if not k.startswith("_")} for i, r in reponses.items()}
            titre = f"score par nœud, {reglage}" + (f", graine {g}" if reglage == "avec exemples" else "")
            lignes, chiffres = juge.noter(fen, propres, titre)
            notes.append(chiffres)
            if g > 0:
                continue
            print()
            if reglage == "sans exemples":
                print(f"# normal de {len(t.normal.stats)} identités, sur les fenêtres normales "
                      f"d'apprentissage ; plancher d'échelle {PLANCHER} ; aucune flèche lue")
            print(f"# alarme sans exemples au-dessus de {t.seuil_alarme:.2f} (plus grand |z| de la "
                  f"fenêtre ; {t.calage_alarme[0]} campagnes mises de côté, {t.calage_alarme[1]} fenêtres, "
                  f"{100 - CENTILE}e centile)")
            if reglage == "avec exemples":
                print(f"# détecteur : alarme au-dessus de {t.seuil_detecteur:.3f} (probabilité de panne, "
                      f"{ARBRES} arbres ; mêmes campagnes mises de côté, {100 - CENTILE}e centile)")
                print(f"# fautif : une régression logistique pour tous les nœuds, {t.fautifs_appris} lignes "
                      f"fautives à l'apprentissage")
                print(f"# cause : {len(t.prototypes)} prototypes ({', '.join(sorted(t.prototypes))}) ; rejet "
                      f"au-dessus de {t.seuil_rejet:.2f} ({t.calage_rejet[0]} injections mises de côté, "
                      f"{t.calage_rejet[1]} fenêtres bien classées, {100 - CENTILE}e centile)")
                pannes = [f for f in test if f["etiquette"] == "panne"]
                sans_rejet = sum(1 for f in pannes if reponses[f["id"]]["_sans_rejet"] == f["attendue"])
                print(f"# cause sans le rejet (pour voir ce qu'il coûte) : {sans_rejet}/{len(pannes)} "
                      f"fenêtres de panne")
            print("\n".join(lignes))
            print("désigné en premier, par cause (fenêtres de panne du test)")
            print("\n".join(premiers(fen, propres)))
        if reglage == "avec exemples":
            print(f"\n# avec exemples, sur {graines} graines (0 à {graines - 1}) : chaque nombre de la note")
            print("\n".join(temoin_tableau._resume_graines(notes)))
    print("\n# le plancher à battre, qui ne lit aucune donnée (juge.py)")
    lignes, _ = juge.noter(fen, juge.factices(fen)["a priori"], "a priori")
    print("\n".join(l for l in lignes if not l.startswith("  ") or "injection" not in l))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, installer, graines = HERE.parent / "campagnes", HERE / "runs", True, 5
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
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--no-install":
                installer = False
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
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
    noms = noms or fautifs_module.SERIES
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(noms, campagnes, runs, graines)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / "temoin_noeud.txt"
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
