"""
Témoin 1 : le tableau équitable. Tous les nombres, aucune structure de flèche.

    ./.venv/bin/python temoin_tableau.py [options] [campagne ...]

Phase B.3. Écrit avant toute donnée de la base lente, jugé par juge.py avec
les règles de fautifs.py. « Équitable » : l'ancien tableau plat des lignes de
base (16 nombres) avait été construit en suivant les flèches à la main. Celui-ci
reçoit tous les nombres des nœuds, la base de données comprise, et les nombres
des flèches résumés sans leur structure : il sait qu'un appel vers une base a
ralenti quelque part, jamais qui appelle qui ni qui tourne où. Ce qui lui manque
est exactement ce que le GNN a en plus : la structure.

CE QUE VOIT LE TABLEAU, par fenêtre

  les cases   les nombres de chaque nœud (instances 18, files 6, hôtes 9) à
              une place fixe : sa case est son service et son rang parmi les
              pods de ce service triés par nom (ts-delivery-service#0 à #2…),
              parce qu'un pod recréé change de nom. 1128 nombres
  les résumés pour chaque sorte de nœud et chaque colonne : le maximum, le
              minimum, la médiane sur les nœuds, et le nombre d'absents ; pour
              chaque relation : le nombre de flèches, et pour chaque colonne le
              maximum et la médiane sur les flèches, sans leurs extrémités
Une valeur absente vaut -1e9 : un arbre la sépare de toute vraie valeur. Les
nombres sont bruts (fenêtres JSON) : un arbre ne dépend pas de l'échelle.

DEUX FORÊTS ALÉATOIRES (200 arbres)

  la cause   sur les cases et les résumés : normale ou une cause apprise.
             Rejet des deux côtés, pour être aussi équipé que le GNN (sa
             première étape repère l'écart au normal, son classifieur à
             prototypes rejette l'inconnu) :
               - une panne prédite avec une probabilité sous le seuil des
                 pannes devient « inconnue » ;
               - une fenêtre prédite normale avec une probabilité d'être
                 normale sous le seuil du normal devient alarme et « inconnue ».
             Les seuils se calent comme face à du nouveau, jamais sur le test :
             chaque injection d'apprentissage (pour les pannes), chaque
             campagne (pour le normal) est mise de côté à son tour, la forêt
             apprend sur le reste et prédit ce qu'on a mis de côté ; seuil =
             5e centile des probabilités obtenues (pannes bien classées ;
             fenêtres normales). Même règle de calage pour le GNN.
  le fautif  UNE forêt pour tous les nœuds, comme le GNN partage ses poids :
             une ligne par nœud et par fenêtre, avec la sorte du nœud, ses
             propres nombres et les résumés de sa fenêtre ; réponse « ce nœud
             est-il fautif ». Le score d'un nœud est cette probabilité. Aucun
             nom de nœud n'y entre : un nœud jamais fautif peut être désigné
             si ses nombres le trahissent. (Premier essai, une sortie par case :
             il ne pouvait désigner que les six cases déjà fautives, et plaçait
             la base dernière d'avance ; remplacé.)

RÉGLAGE : seulement avec exemples de pannes. Sans exemple, un tableau ne peut
qu'apprendre le normal et désigner ce qui s'en écarte : c'est le témoin 2, le
score par nœud.

HASARD : chaque forêt tire au hasard. Le témoin est appris et noté avec les
graines 0 à 4 (fautifs.py) : la note détaillée est celle de la graine 0, puis
chaque nombre avec son minimum, sa médiane et son maximum sur les cinq graines.

CE QUE LE TÉMOIN VOIT : à l'apprentissage, les fenêtres d'apprentissage avec
leur étiquette, leur cause et leurs fautifs ; au test, les nombres de la
fenêtre et les noms de ses nœuds, qui donnent les cases (repondre ne reçoit que
fen["donnees"]). Deux nombres de configuration (memory_limit, cpu_quota)
distinguent les pods MySQL, jamais fautifs à l'apprentissage : la forêt du
fautif peut apprendre qu'ils ne le sont jamais.

BUDGET DE FAUSSES ALERTES : le seuil du normal est au-dessus de 0,5, donc les
deux rejets ensemble sonnent sur les seules fenêtres sous ce seuil : 5 % des
fenêtres normales mises de côté, le budget le plus serré des trois témoins
(l'en-tête du résultat donne le compte).

VERSIONS ÉCARTÉES, dites honnêtement : les deux changements de B.3 ont été faits
APRÈS avoir noté le tableau sur le test (juge.validation n'existait pas encore) :
le rejet calé « hors sac » (cause 33 %), puis le fautif appris case par case, sans
les flèches résumées, rejet d'un seul côté (commit 974ba15 : cause 144/153, fautif
top-1 94/115, fautif nouveau 0/19 ; sortie dans campagnes/versions-vues-sur-test/).
Chaque fois dans le sens qui renforce le témoin. Depuis, tout choix se fait sur
la validation de juge.py.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --validation           la coupure répétée dans l'apprentissage (juge.validation),
                         le vrai test jamais lu : pour régler ; écrit
                         <campagnes>/temoin_tableau-validation.txt
  --graines <n>          nombre de graines, à partir de 0 (défaut 5)
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
import statistics
import sys
from pathlib import Path

import bootstrap
import fautifs as fautifs_module
import juge

HERE = Path(__file__).resolve().parent
ARBRES = 200
CENTILE = 5
ABSENT = -1e9
SORTES = ("instance", "queue", "host")
LARGEUR = 18                    # la plus longue ligne de nœud (instance)


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


def _nombre(v) -> float:
    return ABSENT if v is None else float(v)


def resumes(donnees: dict) -> list[float]:
    """Les résumés d'une fenêtre : par sorte de nœud et par relation, sans identité."""
    out = []
    for kind in SORTES:
        bloc = donnees["nodes"][kind]
        for j in range(len(bloc["columns"])):
            vals = [r[j] for r in bloc["X"] if r[j] is not None]
            out += ([max(vals), min(vals), statistics.median(vals)] if vals else [ABSENT] * 3)
            out.append(float(len(bloc["X"]) - len(vals)))
    for rel in sorted(donnees["edges"]):
        bloc = donnees["edges"][rel]
        out.append(float(len(bloc["X"])))
        for j in range(len(bloc["columns"])):
            vals = [r[j] for r in bloc["X"] if r[j] is not None]
            out += ([max(vals), statistics.median(vals)] if vals else [ABSENT] * 2)
    return out


class Tableau:
    """Le tableau appris : ses cases, ses deux forêts, ses deux seuils de rejet."""

    def __init__(self, fen: list[dict], graine: int = 0):
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier

        self.graine = graine
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        if not garde:
            raise ValueError("aucune fenêtre d'apprentissage")
        colonnes: dict[str, list[str]] = {}
        for f in garde:
            for cle, case in cases(f["donnees"]).items():
                colonnes.setdefault(case, f["donnees"]["nodes"][cle.split(":", 1)[0]]["columns"])
        self.cases = sorted(colonnes)
        self.colonnes = colonnes
        foret = lambda: RandomForestClassifier(n_estimators=ARBRES, random_state=graine, n_jobs=-1)

        # La cause, et ses deux seuils de rejet.
        x = np.array([self.ligne(f["donnees"]) for f in garde])
        y = [f["cause"] if f["etiquette"] == "panne" else "normale" for f in garde]
        self.cause = foret().fit(x, y)
        injection = [(f["campagne"], f["injection"]) if f["etiquette"] == "panne" else None for f in garde]
        pannes_bien = []
        for g in sorted(set(filter(None, injection))):
            dehors = np.array([k == g for k in injection])
            m = foret().fit(x[~dehors], [c for c, d in zip(y, dehors) if not d])
            cl = list(m.classes_)
            for p, c in zip(m.predict_proba(x[dehors]), [c for c, d in zip(y, dehors) if d]):
                if cl[int(p.argmax())] == c:
                    pannes_bien.append(float(p.max()))
        normales = []
        campagne = [f["campagne"] for f in garde]
        for c in sorted({k for k, e in zip(campagne, y) if e == "normale"}):
            dehors = np.array([k == c for k in campagne])
            m = foret().fit(x[~dehors], [e for e, d in zip(y, dehors) if not d])
            cl = list(m.classes_)
            ici = [i for i, d in enumerate(dehors) if d and y[i] == "normale"]
            if "normale" in cl and ici:
                normales += [float(p[cl.index("normale")]) for p in m.predict_proba(x[ici])]
        self.seuil_panne = float(np.percentile(pannes_bien, CENTILE)) if pannes_bien else 0.0
        self.seuil_normal = float(np.percentile(normales, CENTILE)) if normales else 0.0
        self.calage = (len(set(filter(None, injection))), len({k for k, e in zip(campagne, y) if e == "normale"}))
        # Le budget de fausses alertes : le seuil du normal dépasse 0,5, donc une fenêtre
        # mise de côté que la forêt prend pour une panne est déjà sous ce seuil.
        self.calage_normal = (sum(1 for v in normales if v < self.seuil_normal), len(normales))
        self.calage_pannes = len(pannes_bien)

        # Le fautif : une forêt pour tous les nœuds.
        xs, ys = [], []
        for f in garde:
            r = resumes(f["donnees"])
            for cle, ligne in self.noeuds(f["donnees"], r):
                xs.append(ligne)
                ys.append(1 if cle in f["fautifs"] else 0)
        self.fautif = foret().fit(np.array(xs), ys)
        self.fautifs_appris = sum(ys)

    def ligne(self, donnees: dict) -> list[float]:
        """Les cases puis les résumés d'une fenêtre."""
        valeurs: dict[str, list] = {}
        for cle, case in cases(donnees).items():
            kind, nom = cle.split(":", 1)
            bloc = donnees["nodes"][kind]
            valeurs[case] = bloc["X"][bloc["names"].index(nom)]
        out = []
        for case in self.cases:
            ligne = valeurs.get(case)
            out += [ABSENT if ligne is None else _nombre(ligne[j]) for j in range(len(self.colonnes[case]))]
        return out + resumes(donnees)

    @staticmethod
    def noeuds(donnees: dict, r: list[float]) -> list[tuple[str, list[float]]]:
        """Une ligne par nœud : sa sorte, ses nombres (à LARGEUR), les résumés de la fenêtre."""
        out = []
        for i, kind in enumerate(SORTES):
            bloc = donnees["nodes"][kind]
            sorte = [1.0 if j == i else 0.0 for j in range(len(SORTES))]
            for nom, row in zip(bloc["names"], bloc["X"]):
                propre = [_nombre(v) for v in row] + [ABSENT] * (LARGEUR - len(row))
                out.append((juge._cle(kind, nom), sorte + propre + r))
        return out

    def cases_inconnues(self, donnees: dict) -> int:
        return sum(1 for c in cases(donnees).values() if c not in self.colonnes)

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir de ses seuls nombres."""
        import numpy as np
        p = self.cause.predict_proba(np.array([self.ligne(donnees)]))[0]
        cl = list(self.cause.classes_)
        cause = cl[int(p.argmax())]
        if cause == "normale":
            if p[cl.index("normale")] < self.seuil_normal:
                cause = "inconnue"
        elif p.max() < self.seuil_panne:
            cause = "inconnue"
        lignes = self.noeuds(donnees, resumes(donnees))
        proba = self.fautif.predict_proba(np.array([l for _, l in lignes]))
        un = list(self.fautif.classes_).index(1) if 1 in self.fautif.classes_ else None
        scores = {cle: (float(pr[un]) if un is not None else 0.0) for (cle, _), pr in zip(lignes, proba)}
        return {"alarme": cause != "normale", "cause": cause, "scores": scores,
                "_sans_rejet": cl[int(p.argmax())]}


def _resume_graines(notes: list[dict]) -> list[str]:
    """Chaque nombre de la note, sur les graines : minimum, médiane, maximum."""
    out = [f"{'mesure':<52}{'min':>8}{'médiane':>9}{'max':>8}{'sur':>6}"]
    cles = [k for k in notes[0] if k != "injections"]
    for k in cles:
        v = [n[k][0] for n in notes if k in n]
        out.append(f"{k:<52}{min(v):>8}{statistics.median(v):>9g}{max(v):>8}{notes[0][k][1]:>6}")
    for k in notes[0]["injections"]:
        v = [n["injections"][k][0] for n in notes]
        out.append(f"{'injections, ' + k:<52}{min(v):>8}{statistics.median(v):>9g}{max(v):>8}"
                   f"{notes[0]['injections'][k][1]:>6}")
    return out


def rapport(noms: list[str], campagnes: Path, runs: Path, graines: int, validation: bool = False) -> int:
    try:
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    print("# Témoin 1, le tableau équitable — écrit par graphe_en/temoin_tableau.py, ne pas éditer à la main.")
    notes = []
    for g in range(graines):
        tableau = Tableau(fen, graine=g)
        reponses = {f["id"]: tableau.repondre(f["donnees"]) for f in test}
        lignes, chiffres = juge.noter(fen, {i: {k: v for k, v in r.items() if not k.startswith("_")}
                                            for i, r in reponses.items()},
                                      f"tableau équitable, graine {g}")
        notes.append(chiffres)
        if g == 0:
            pannes = [f for f in test if f["etiquette"] == "panne"]
            sans_rejet = sum(1 for f in pannes if reponses[f["id"]]["_sans_rejet"] == f["attendue"])
            n_col = len(tableau.ligne(test[0]["donnees"]))
            print(f"# {len(tableau.cases)} cases et leurs résumés : {n_col} nombres par fenêtre ; "
                  f"structure des flèches : aucune ; {ARBRES} arbres par forêt")
            print(f"# rejet : panne sous {tableau.seuil_panne:.3f} ({tableau.calage[0]} injections mises de "
                  f"côté), normal sous {tableau.seuil_normal:.3f} ({tableau.calage[1]} campagnes mises de côté), "
                  f"{CENTILE}e centile")
            print(f"# le rejet du normal sonne sur {tableau.calage_normal[0]}/{tableau.calage_normal[1]} fenêtres "
                  f"normales mises de côté (celles prises pour une panne comprises)")
            if not tableau.calage_pannes:
                print("# ATTENTION : aucune injection mise de côté n'est bien classée : le rejet des pannes est coupé")
            print(f"# fautif : une forêt pour tous les nœuds, {tableau.fautifs_appris} lignes fautives à "
                  f"l'apprentissage")
            inconnues = sum(1 for f in test if tableau.cases_inconnues(f["donnees"]))
            print(f"# fenêtres de test avec une case jamais vue à l'apprentissage : {inconnues}")
            print(f"# cause sans le rejet (pour voir ce qu'il coûte) : {sans_rejet}/{len(pannes)} "
                  f"fenêtres de panne")
            print()
            print("\n".join(lignes))
    print(f"\n# sur {graines} graines (0 à {graines - 1}) : chaque nombre de la note")
    print("\n".join(_resume_graines(notes)))
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
        cible = campagnes / juge.sortie("temoin_tableau", noms, validation)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
