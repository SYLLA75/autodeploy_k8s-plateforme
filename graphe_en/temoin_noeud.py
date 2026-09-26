"""
Témoin 2 : le score par nœud. Chaque nœud comparé à son propre normal, aucune flèche.

    ./.venv/bin/python temoin_noeud.py [options] [campagne ...]

Phase B.4. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. Il ressemble à la première étape du GNN sans les
flèches, sans lui être équivalent : le GNN reconstruira le normal d'un nœud
avec ses voisins et des poids partagés ; ce témoin compare chaque nœud à son
seul passé, et il connaît chaque nœud par son nom (pour retrouver son normal),
ce que le GNN ne fait pas. Inspiré des lignes de base publiées qui classent
les composants par l'écart de leurs mesures à leur normal (N-sigma ; BARO et
son échelle robuste) ; celles-ci prennent pour normal la période juste avant
l'incident et ne font que classer. Ici chaque fenêtre est jugée seule, comme
pour tous les témoins et le GNN.

LE NORMAL D'UN NŒUD, appris sur les fenêtres normales d'apprentissage seules

  son identité  une machine, une file : son nom ; un pod de StatefulSet
                (tsdb-mysql-0, nacos-1) : son nom, qui est stable ; un pod de
                Deployment : son service, car le pod change de nom quand il est
                recréé, et ses répliques font le même travail
  ses nombres   ceux du graphe figé, passés en log1p pour les colonnes que le
                gel met en log avant l'échelle ; plus un : le nombre de ses
                valeurs absentes (un pod gelé ne rend plus de durées)
  par nombre    s'il a au moins 10 valeurs (répliques d'un service mises
                ensemble) : sa médiane, et son échelle, un écart-type robuste,
                le plus grand de l'écart interquartile / 1,349 et de l'écart
                entre 1er et 99e centiles / 4,653 (égaux pour une courbe en
                cloche)
  le plancher   l'échelle ne descend jamais sous celle des écarts de chaque
                nœud à SA médiane, mis en commun sur les nœuds de la même
                sorte : le bruit ordinaire d'un nombre, sans les différences de
                niveau entre nœuds. S'il est nul (un nombre constant pour tous
                dans le normal, comme les redémarrages ou error_ratio), PLANCHER
                fois l'écart-type brut de la sorte, et 1 si celui-ci est nul
                aussi, comme la mise à l'échelle figée du GNN : l'échelle est
                alors 0,1 dans l'unité du nombre
  l'écart       z = (valeur − médiane) / échelle
Une valeur absente ne donne pas d'écart (seul le compte des absents en donne
un). Un nœud dont l'identité n'a pas de normal n'a pas de score : dernier ; un
nœud d'un nom jamais vu (une nouvelle machine) ne peut donc pas être désigné.

DEUX RÉGLAGES (fautifs.py : sans exemple de panne, puis avec)

  sans exemples  il ne connaît que le normal. Score d'un nœud : le plus grand
                 |z| de ses nombres. Alarme si le plus haut score de la fenêtre
                 dépasse le seuil d'alarme ; la cause est alors « inconnue » (il
                 ne sait nommer aucune panne), « normale » sinon
  avec exemples  l'alarme : un détecteur appris, une forêt aléatoire (200
                 arbres, le même apprenant que le tableau) « panne ou non » sur
                 le profil d'écart de la fenêtre (ci-dessous), plus l'alarme sans
                 exemples. Le détecteur apprend sur des écarts CROISÉS : chaque
                 fenêtre d'apprentissage vue par un normal appris sans sa
                 campagne (appris sur des écarts à un normal qui contient la
                 fenêtre elle-même, il apprendrait que tout ce qui sort de cette
                 enveloppe est une panne). Rejet des deux côtés, comme le
                 tableau : alarme du détecteur, cause nommée par les
                 prototypes ; alarme sans exemples seule, cause « inconnue ».
                 La cause : le prototype le plus proche, comme le classifieur à
                 prototypes du GNN. Le profil d'une fenêtre : pour chaque sorte
                 et chaque nombre, le plus grand et le plus petit z sur ses
                 nœuds, compressés en log1p (signe gardé) ; le prototype d'une
                 cause : la moyenne des profils de ses fenêtres de panne
                 d'apprentissage ; la distance divise chaque dimension par son
                 écart-type sur ces profils ; « inconnue » si la distance au
                 plus proche dépasse le seuil de rejet.
                 Le fautif d'une panne reconnue (une cause apprise) : une
                 régression logistique partagée par tous les nœuds, un poids par
                 sorte et par nombre, sur la part positive et la part négative
                 de chaque écart (compressées en log1p), apprise sur les nœuds
                 des fenêtres d'apprentissage, fautifs ou non ; aucun nom de
                 nœud n'y entre. Elle ne connaît que les motifs des causes
                 apprises : devant une panne « inconnue » (ou prise pour
                 normale), le témoin classe par l'écart seul, comme sans
                 exemples. Le GNN, lui, désignera toujours par sa première
                 étape, apprise sur le normal seul

LES SEUILS, jamais sur le test, calés comme face à du nouveau (fautifs.py)
  alarme  chaque campagne mise de côté à son tour : le normal (et, avec
          exemples, le détecteur, croisé de même à l'intérieur) appris sur les
          autres, le score de ses fenêtres normales d'apprentissage ; seuil =
          95e centile de ces scores. Seuils réglés sur le normal seul. Avec
          exemples, les deux alarmes ensemble sonnent sur plus de 5 % des
          fenêtres mises de côté : l'en-tête du résultat donne combien. Ce
          calage est un peu plus sévère que la situation du test, où les
          premières fenêtres de la campagne sont déjà dans le normal
  rejet   chaque injection d'apprentissage mise de côté à son tour : les
          prototypes appris sans elle ; seuil = 95e centile des distances de
          ses fenêtres bien classées. Même règle que le tableau et le GNN

HASARD : sans exemples, aucun (médianes) : une seule note. Avec exemples, la
forêt du détecteur tire au hasard : graines 0 à 4 (fautifs.py), note détaillée
de la graine 0, puis chaque nombre avec son minimum, sa médiane et son maximum.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage avec
leur étiquette, leur cause et leurs fautifs (sans exemples : les normales
seules) ; au test, les nombres et les noms des nœuds de la fenêtre (repondre
ne reçoit que fen["donnees"], et n'en lit pas les flèches).

VERSIONS ÉCARTÉES, dites honnêtement (le journal donne leurs chiffres) :
  1. échelle par l'écart interquartile seul : un nombre presque toujours nul
     avec de rares pics (cpu_throttle_ratio, memory_slope) donnait des |z| de
     plusieurs centaines dans des fenêtres normales, seuil d'alarme 138. Défaut
     vu sur le calage, mais la version avait aussi été NOTÉE SUR LE TEST
     (détection 48/153) ; corrigé par l'écart entre 1er et 99e centiles ;
  2. détecteur en régression logistique : seuil calé 0,043, 28 % de fausses
     alertes AU TEST ; remplacé par la forêt APRÈS avoir vu ce test (choix
     informé par le test, dans le sens qui aide le témoin) ;
  3. plancher = PLANCHER × écart-type brut de la sorte : il mesurait les
     différences de niveau entre nœuds, pas le bruit (0,28 en log pour le
     temps de traitement, 7 fois l'échelle propre des répliques : la lenteur
     n'y faisait que z = 1,5), et il était minuscule pour les nombres presque
     nuls (cpu_throttle_ratio) ; détecteur appris sur des écarts non croisés ;
     fautif appris même devant l'inconnu ; distances aux prototypes non mises
     à l'échelle. La version 4ca7001 avait été NOTÉE SUR LE TEST (sortie dans
     campagnes/versions-vues-sur-test/ ; lenteur top-1 0/38 sans exemples).
     Ces défauts ont été relevés par deux relectures indépendantes, et leurs
     corrections vérifiées sur la validation (juge.validation), pas sur le test.
Depuis, tout choix se fait sur la validation de juge.py.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --validation           la coupure répétée dans l'apprentissage (juge.validation),
                         le vrai test jamais lu : pour régler ; écrit
                         <campagnes>/temoin_noeud-validation.txt
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


def echelle(vals: list[float]) -> float:
    """Un écart-type robuste : le plus grand de l'écart interquartile / 1,349 et de
    l'écart entre 1er et 99e centiles / 4,653 (égaux pour une courbe en cloche)."""
    return max((_q(vals, 0.75) - _q(vals, 0.25)) / 1.349, (_q(vals, 0.99) - _q(vals, 0.01)) / 4.653)


def echelles(valeurs: dict, groupe) -> dict:
    """
    {clé : {nombre : (médiane, échelle)}} pour chaque clé (un nœud, une flèche) et
    chaque nombre présent au moins MIN_OBS fois. Le plancher, par (groupe, nombre) :
    l'échelle des écarts de chaque clé à SA médiane, mis en commun sur les clés du
    groupe (la même sorte de nœud, la même relation) ; s'il est nul (un nombre
    constant pour tous dans le normal), PLANCHER fois l'écart-type brut du groupe,
    et 1 si celui-ci est nul aussi, comme la mise à l'échelle figée du GNN
    (export_pyg.py).
    """
    brutes: dict = {}
    residus: dict = {}
    for cle, par in valeurs.items():
        for c, vals in par.items():
            brutes.setdefault((groupe(cle), c), []).extend(vals)
            if len(vals) >= MIN_OBS:
                m = statistics.median(vals)
                residus.setdefault((groupe(cle), c), []).extend(v - m for v in vals)
    plancher = {}
    for k, r in residus.items():
        s = echelle(r)
        if s <= 1e-12:
            sd = statistics.pstdev(brutes[k]) if len(brutes[k]) > 1 else 0.0
            s = PLANCHER * (sd if sd > 1e-12 else 1.0)
        plancher[k] = s
    return {cle: {c: (statistics.median(vals), max(echelle(vals), plancher[(groupe(cle), c)]))
                  for c, vals in par.items() if len(vals) >= MIN_OBS}
            for cle, par in valeurs.items()}


class Normal:
    """Le normal de chaque nœud : médiane et échelle de chacun de ses nombres."""

    def __init__(self, fenetres: list[dict], fige: dict):
        self.colonnes = _colonnes(fige)
        self.log = {k: set(fige["log_avant_echelle"]["noeuds"].get(k, [])) for k in SORTES}
        valeurs: dict[str, dict[str, list[float]]] = {}
        for f in fenetres:
            for kind, nom, ligne in self._lignes(f["donnees"]):
                ident = valeurs.setdefault(identite(kind, nom), {})
                for c, v in ligne.items():
                    ident.setdefault(c, []).append(v)
        self.stats = echelles(valeurs, lambda ident: ident.split(":", 1)[0])

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


class Normaux:
    """Des normaux appris chacun sans certaines campagnes, gardés une fois appris."""

    def __init__(self, normales: list[dict], fige: dict):
        self.normales, self.fige, self.faits = normales, fige, {}

    def sans(self, *campagnes: str) -> Normal:
        cle = frozenset(campagnes)
        if cle not in self.faits:
            self.faits[cle] = Normal([f for f in self.normales if f["campagne"] not in cle], self.fige)
        return self.faits[cle]


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


class Prototypes:
    """Une moyenne de profil par cause ; distance euclidienne, chaque dimension
    divisée par son écart-type sur les profils de panne qui les ont appris (sans
    quoi les dimensions qui bougent le plus font toute la distance)."""

    def __init__(self, profils: list[list[float]], causes: list[str]):
        n = len(profils)
        moy = [sum(col) / n for col in zip(*profils)]
        self.ecart = [(sd if (sd := math.sqrt(sum((x - m) ** 2 for x in col) / n)) > 1e-6 else 1.0)
                      for col, m in zip(zip(*profils), moy)]
        par: dict[str, list[list[float]]] = {}
        for p, c in zip(profils, causes):
            par.setdefault(c, []).append(p)
        self.moyennes = {c: [sum(col) / len(ps) for col in zip(*ps)] for c, ps in par.items()}

    def plus_proche(self, p: list[float]) -> tuple[str, float]:
        d = lambda q: math.sqrt(sum(((x - y) / e) ** 2 for x, y, e in zip(p, q, self.ecart)))
        return min(((c, d(q)) for c, q in sorted(self.moyennes.items())), key=lambda t: t[1])


class Noeud:
    """Le score par nœud appris : son normal, son seuil d'alarme ; avec exemples,
    son détecteur, sa régression du fautif, ses prototypes et son seuil de rejet."""

    def __init__(self, fen: list[dict], reglage: str, fige: dict, graine: int = 0):
        if reglage not in REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        self.reglage = reglage
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        campagnes = sorted({f["campagne"] for f in normales})
        if len(campagnes) < 2:
            raise ValueError("il faut des fenêtres normales d'apprentissage dans au moins deux campagnes "
                             "(le seuil d'alarme se cale en en mettant une de côté)")
        normaux = Normaux(normales, fige)
        self.normal = normaux.sans()
        self.colonnes = self.normal.colonnes

        # Le seuil d'alarme : chaque campagne mise de côté à son tour.
        tenus = {c: [score_fenetre(normaux.sans(c).ecarts(f["donnees"])) for f in normales if f["campagne"] == c]
                 for c in campagnes}
        self.seuil_alarme = _q([v for c in campagnes for v in tenus[c]], 1 - CENTILE / 100)
        self.calage_alarme = (len(campagnes), sum(len(v) for v in tenus.values()))
        if reglage == "sans exemples":
            return

        # Avec exemples : le détecteur, appris sur des écarts « croisés » : chaque
        # fenêtre vue par un normal appris sans sa campagne. Appris sur des écarts
        # au normal qui contient la fenêtre elle-même, il apprendrait que tout ce
        # qui sort de cette enveloppe est une panne.
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        foret = lambda: RandomForestClassifier(n_estimators=ARBRES, random_state=graine, n_jobs=-1)
        panne = {f["id"]: 1 if f["etiquette"] == "panne" else 0 for f in garde}
        if len(set(panne.values())) < 2:
            raise ValueError("avec exemples : aucune fenêtre de panne à l'apprentissage")

        def detecteur(fenetres: list[dict], sans: tuple = ()):
            x = [profil(normaux.sans(f["campagne"], *sans).ecarts(f["donnees"]), self.colonnes) for f in fenetres]
            y = [panne[f["id"]] for f in fenetres]
            return foret().fit(np.array(x), y) if len(set(y)) == 2 else None

        self.detecteur = detecteur(garde)
        # Son seuil : chaque campagne mise de côté, le même croisement à l'intérieur.
        probas = []
        for c in campagnes:
            d = detecteur([f for f in garde if f["campagne"] != c], (c,))
            if d is not None:
                ici = [f for f in normales if f["campagne"] == c]
                x = np.array([profil(normaux.sans(c).ecarts(f["donnees"]), self.colonnes) for f in ici])
                probas += [(c, float(p[list(d.classes_).index(1)])) for p in d.predict_proba(x)]
        self.seuil_detecteur = _q([p for _, p in probas], 1 - CENTILE / 100) if probas else 1.0
        # Ce que coûtent les deux alarmes ensemble, sur les mêmes fenêtres mises de côté.
        z_haut = [v > self.seuil_alarme for c in campagnes for v in tenus[c]]
        d_haut = [p > self.seuil_detecteur for _, p in probas]
        self.calage_union = (sum(1 for a, b in zip(z_haut, d_haut) if a or b), len(d_haut)) \
            if len(z_haut) == len(d_haut) else None

        # Le fautif d'une panne reconnue : une régression pour tous les nœuds.
        ecarts = {f["id"]: self.normal.ecarts(f["donnees"]) for f in garde}
        xs, ys = [], []
        for f in garde:
            for cle, z in ecarts[f["id"]].items():
                xs.append(ligne_noeud(cle, z, self.colonnes))
                ys.append(1 if cle in f["fautifs"] else 0)
        self.fautifs_appris = sum(ys)
        self.fautif = LogisticRegression(max_iter=5000, class_weight="balanced").fit(np.array(xs), ys) \
            if 0 < sum(ys) < len(ys) else None

        # La cause : prototypes et seuil de rejet, chaque injection mise de côté à son tour.
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        profils = {f["id"]: profil(ecarts[f["id"]], self.colonnes) for f in pannes}
        self.prototypes = Prototypes([profils[f["id"]] for f in pannes], [f["cause"] for f in pannes])
        bien = []
        injections = sorted({(f["campagne"], f["injection"]) for f in pannes})
        for g in injections:
            reste = [f for f in pannes if (f["campagne"], f["injection"]) != g]
            if not reste:
                continue
            protos = Prototypes([profils[f["id"]] for f in reste], [f["cause"] for f in reste])
            for f in (f for f in pannes if (f["campagne"], f["injection"]) == g):
                cause, d = protos.plus_proche(profils[f["id"]])
                if cause == f["cause"]:
                    bien.append(d)
        self.seuil_rejet = _q(bien, 1 - CENTILE / 100) if bien else math.inf
        self.calage_rejet = (len(injections), len(bien))

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir des seuls nombres de ses nœuds."""
        ecarts = self.normal.ecarts(donnees)
        alarme = score_fenetre(ecarts) > self.seuil_alarme
        ecart = {cle: score(z) for cle, z in ecarts.items()}
        if self.reglage == "sans exemples":
            return {"alarme": alarme, "cause": "inconnue" if alarme else "normale", "scores": ecart}
        import numpy as np
        p = profil(ecarts, self.colonnes)
        detecte = False
        if self.detecteur is not None:
            detecte = float(self.detecteur.predict_proba(np.array([p]))[0][
                list(self.detecteur.classes_).index(1)]) > self.seuil_detecteur
        cause, brute = "normale", None
        if detecte:
            brute, d = self.prototypes.plus_proche(p)
            cause = brute if d <= self.seuil_rejet else "inconnue"
        elif alarme:
            cause = "inconnue"
        # Le fautif : la régression ne connaît que les pannes apprises ; devant
        # une panne qu'il ne reconnaît pas, le témoin classe par l'écart seul.
        scores = ecart
        if cause not in ("normale", "inconnue") and self.fautif is not None:
            cles = list(ecarts)
            un = list(self.fautif.classes_).index(1)
            proba = self.fautif.predict_proba(np.array([ligne_noeud(k, ecarts[k], self.colonnes) for k in cles]))
            scores = {k: (float(pr[un]) if ecarts[k] else None) for k, pr in zip(cles, proba)}
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


def rapport(noms: list[str], campagnes: Path, runs: Path, graines: int, validation: bool = False) -> int:
    import temoin_tableau
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
                      f"d'apprentissage ; plancher : écarts de chaque nœud à sa médiane ; aucune flèche lue")
            print(f"# alarme sans exemples au-dessus de {t.seuil_alarme:.2f} (plus grand |z| de la "
                  f"fenêtre ; {t.calage_alarme[0]} campagnes mises de côté, {t.calage_alarme[1]} fenêtres, "
                  f"{100 - CENTILE}e centile)")
            if reglage == "avec exemples":
                print(f"# détecteur : alarme au-dessus de {t.seuil_detecteur:.3f} (probabilité de panne, "
                      f"{ARBRES} arbres, écarts croisés ; mêmes campagnes mises de côté, {100 - CENTILE}e centile)")
                if t.calage_union:
                    print(f"# les deux alarmes ensemble sonnent sur {t.calage_union[0]}/{t.calage_union[1]} "
                          f"fenêtres normales mises de côté")
                print(f"# fautif : une régression logistique pour tous les nœuds, {t.fautifs_appris} lignes "
                      f"fautives à l'apprentissage")
                print(f"# cause : {len(t.prototypes.moyennes)} prototypes "
                      f"({', '.join(sorted(t.prototypes.moyennes))}) ; rejet "
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
        print(f"# campagnes lues : {', '.join(noms)}")
        code = rapport(noms, campagnes, runs, graines, validation)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / juge.sortie("temoin_noeud", noms, validation)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
