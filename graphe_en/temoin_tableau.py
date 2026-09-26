"""
Témoin 1 : le tableau équitable. Tous les nombres de tous les nœuds, aucune flèche.

    ./.venv/bin/python temoin_tableau.py [options] [campagne ...]

Phase B.3. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. « Équitable » : l'ancien tableau plat des lignes de
base (16 nombres) avait été construit en suivant les flèches à la main (la file,
les répliques du consommateur, les hôtes). Celui-ci reçoit TOUT ce que le graphe
mesure, la base de données comprise, et rien de ce que disent les flèches : ni
qui appelle qui, ni qui tourne où.

LA LIGNE D'UNE FENÊTRE

Les nombres de chaque nœud, instances (18), files (6) et hôtes (9), mis bout à
bout. Un nœud occupe la même case d'une fenêtre à l'autre : sa case est son
service et son rang parmi les pods de ce service triés par nom
(ts-delivery-service#0 à #2, tsdb-mysql#0 à #2, ts-order-service#0…), parce
qu'un pod recréé change de nom (order, seat et travel entre les deux séries).
Une valeur absente vaut -1e9 : un arbre la sépare de toute vraie valeur. Les
nombres sont bruts (fenêtres JSON) : un arbre ne dépend pas de l'échelle.

DEUX FORÊTS ALÉATOIRES (200 arbres, graine 0, comme ligne_de_base.py)

  la cause   normale ou une des causes apprises. Alarme : la cause prédite
             n'est pas « normale ». Rejet, pour être aussi équipé que le
             classifieur à prototypes du GNN : une panne prédite avec une
             probabilité sous le seuil devient « inconnue ». Le seuil se cale
             comme face à une panne nouvelle : chaque injection d'apprentissage
             est mise de côté à son tour, la forêt apprend sur le reste et
             prédit ses fenêtres ; seuil = 5e centile des probabilités des
             fenêtres ainsi bien classées. Jamais sur le test. (Premier essai,
             hors sac : trop sévère, les fenêtres voisines de la même injection
             étaient dans les arbres ; même règle pour le rejet du GNN.)
  le fautif  une sortie « est fautif » par case, apprise sur toutes les
             fenêtres d'apprentissage non écartées (normales et charge : aucun
             fautif). Le score d'un nœud est la probabilité prédite pour sa
             case. Une case jamais fautive à l'apprentissage vaut 0 : un tableau
             ne peut pas désigner ce qu'il n'a jamais vu fautif.

RÉGLAGE : seulement avec exemples de pannes. Sans exemple, un tableau ne peut
qu'apprendre le normal et désigner ce qui s'en écarte : c'est le témoin 2, le
score par nœud.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage avec
leur étiquette, leur cause et leurs fautifs ; au test, les seuls nombres de la
fenêtre (repondre ne reçoit que fen["donnees"]).

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --no-install           n'installe jamais scikit-learn
  --help                 ce texte

Écrit <campagnes>/temoin_tableau.txt et affiche le même texte. Code de sortie
0, 1 si une campagne est refusée ou une bibliothèque manque, 2 sur un mauvais
argument.
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

import bootstrap
import fautifs as fautifs_module
import juge

HERE = Path(__file__).resolve().parent
ARBRES = 200
GRAINE = 0
CENTILE_REJET = 5
ABSENT = -1e9
SORTES = ("instance", "queue", "host")


def service(nom: str) -> str:
    """ts-order-service-76b7f658c6-z6t7d → ts-order-service ; tsdb-mysql-0 → tsdb-mysql."""
    m = re.match(r"^(.*)-[0-9a-f]{6,10}-[a-z0-9]{5}$", nom)
    if m:
        return m.group(1)
    m = re.match(r"^(.*)-\d+$", nom)
    return m.group(1) if m else nom


def cases(donnees: dict) -> dict[str, str]:
    """{clé du juge (« instance:<pod> ») : case du tableau (« instance:<service>#<rang> »)}."""
    out = {}
    for kind in SORTES:
        par_service: dict[str, list[str]] = {}
        for n in sorted(donnees["nodes"][kind]["names"]):
            par_service.setdefault(service(n) if kind == "instance" else n, []).append(n)
        for s, noms in par_service.items():
            for rang, n in enumerate(noms):
                out[juge._cle(kind, n)] = f"{kind}:{s}#{rang}"
    return out


class Tableau:
    """Le tableau appris : ses colonnes, ses deux forêts, son seuil de rejet."""

    def __init__(self, apprentissage: list[dict]):
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier

        garde = [f for f in apprentissage if f["jeu"] == "apprentissage"
                 and f["etiquette"] not in juge.ECARTEES]
        if not garde:
            raise ValueError("aucune fenêtre d'apprentissage")
        # Les colonnes : chaque case vue à l'apprentissage, avec les colonnes de sa sorte.
        colonnes: dict[str, list[str]] = {}
        for f in garde:
            for cle, case in cases(f["donnees"]).items():
                kind = cle.split(":", 1)[0]
                colonnes.setdefault(case, f["donnees"]["nodes"][kind]["columns"])
        self.cases = sorted(colonnes)
        self.colonnes = colonnes
        x = np.array([self.ligne(f["donnees"]) for f in garde])

        # La cause.
        y = [f["cause"] if f["etiquette"] == "panne" else "normale" for f in garde]
        foret = lambda: RandomForestClassifier(n_estimators=ARBRES, random_state=GRAINE, n_jobs=-1)
        self.cause = foret().fit(x, y)
        # Le seuil de rejet, injection par injection mise de côté.
        groupes = [(f["campagne"], f["injection"]) if f["etiquette"] == "panne" else None for f in garde]
        bien = []
        for g in sorted(set(filter(None, groupes))):
            dehors = np.array([k == g for k in groupes])
            modele = foret().fit(x[~dehors], [c for c, d in zip(y, dehors) if not d])
            proba = modele.predict_proba(x[dehors])
            classes = list(modele.classes_)
            vraies = [c for c, d in zip(y, dehors) if d]
            bien += [float(p.max()) for p, c in zip(proba, vraies) if classes[int(p.argmax())] == c]
        self.seuil = float(np.percentile(bien, CENTILE_REJET)) if bien else 0.0
        self.injections_calage = len(set(filter(None, groupes)))

        # Le fautif : une sortie par case.
        fautives = [{cases(f["donnees"])[c] for c in f["fautifs"]} for f in garde]
        self.sorties = self.cases
        yf = np.array([[1 if case in fv else 0 for case in self.sorties] for fv in fautives])
        self.jamais = {case for j, case in enumerate(self.sorties) if not yf[:, j].any()}
        self.fautif = RandomForestClassifier(n_estimators=ARBRES, random_state=GRAINE,
                                             n_jobs=-1).fit(x, yf)

    def ligne(self, donnees: dict) -> list[float]:
        """Les nombres de la fenêtre, case par case, colonne par colonne."""
        valeurs: dict[str, list] = {}
        for cle, case in cases(donnees).items():
            kind, nom = cle.split(":", 1)
            bloc = donnees["nodes"][kind]
            valeurs[case] = bloc["X"][bloc["names"].index(nom)]
        out = []
        for case in self.cases:
            ligne = valeurs.get(case)
            for j in range(len(self.colonnes[case])):
                v = None if ligne is None else ligne[j]
                out.append(ABSENT if v is None else float(v))
        return out

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir de ses seuls nombres."""
        import numpy as np
        x = np.array([self.ligne(donnees)])
        proba = self.cause.predict_proba(x)[0]
        classes = list(self.cause.classes_)
        cause = classes[int(proba.argmax())]
        if cause != "normale" and proba.max() < self.seuil:
            cause = "inconnue"
        par_sortie = self.fautif.predict_proba(x)
        score_case = {}
        for j, case in enumerate(self.sorties):
            p, cl = par_sortie[j][0], list(self.fautif.classes_[j])
            score_case[case] = float(p[cl.index(1)]) if 1 in cl else 0.0
        scores = {cle: score_case.get(case, 0.0) for cle, case in cases(donnees).items()}
        return {"alarme": cause != "normale", "cause": cause, "scores": scores}


def rapport(noms: list[str], campagnes: Path, runs: Path) -> int:
    try:
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    tableau = Tableau(fen)
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    reponses = {f["id"]: tableau.repondre(f["donnees"]) for f in test}
    n_col = sum(len(c) for c in tableau.colonnes.values())
    print("# Témoin 1, le tableau équitable — écrit par graphe_en/temoin_tableau.py, ne pas éditer à la main.")
    print(f"# {len(tableau.cases)} cases (nœuds), {n_col} nombres par fenêtre, aucune flèche ; "
          f"{ARBRES} arbres, graine {GRAINE}")
    print(f"# seuil de rejet (« inconnue ») : probabilité < {tableau.seuil:.3f} "
          f"({CENTILE_REJET}e centile, {tableau.injections_calage} injections d'apprentissage "
          f"mises de côté à tour de rôle)")
    print(f"# cases jamais fautives à l'apprentissage (score 0) : {len(tableau.jamais)} sur {len(tableau.sorties)}")
    print()
    lignes, _ = juge.noter(fen, reponses, "tableau équitable, réglé avec exemples")
    print("\n".join(lignes))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, installer = HERE.parent / "campagnes", HERE / "runs", True
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
            elif a == "--no-install":
                installer = False
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except IndexError:
        print("option sans valeur", file=sys.stderr)
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
        code = rapport(noms, campagnes, runs)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / "temoin_tableau.txt"
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
