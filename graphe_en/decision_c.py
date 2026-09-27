"""
Ce qui décidera sur la base lente (phase C), écrit AVANT C.

    ./.venv/bin/python decision_c.py --garde [options]
    ./.venv/bin/python decision_c.py --ouvrir <campagne C> [options]

Les règles sont celles du journal (section du 27 sept., « Ce qui décidera sur C ») ;
ce fichier les calcule sans rien régler. Il importe juge.py et les témoins figés
(étiquette temoins-figes) sans les modifier.

--garde : la garde de spécificité G, calculée tout de suite sur les deux séries.
  Pour chaque méthode, chaque réglage et chaque graine : sur combien des
  injections de test des causes connues tsdb-mysql-0 est-il premier dans plus de
  la moitié des fenêtres de panne (sans tenir compte de l'alarme) ? G tient pour
  une graine si c'est sur aucune. Écrit <campagnes>/decision-garde.txt.

--ouvrir <C> : la lecture de C, UNE fois, quand le GNN est figé. Refusée tant que
  l'étiquette git « gnn-fige » n'existe pas (le scellé), et si le code des
  témoins, du juge et du GNN n'est plus celui de leurs étiquettes. Les méthodes
  apprennent sur les deux séries seules, exactement comme dans leurs sorties
  figées : les minutes normales de C n'entrent dans l'apprentissage de personne.
  Elles répondent ensuite sur toutes les minutes de C. Pour chaque injection :
    compte   confirmée, la file vide avant (tas ≤ 10 la minute d'avant), la file
             qui déborde (tas > 10 dans STRICTEMENT plus de la moitié de ses
             minutes de panne ; égalité : ne déborde pas), et pas d'effondrement
             (deux veilles de suite EN_DEFAUT pendant l'injection, le leader
             perdu, ou un redémarrage de pod de train-ticket) ;
    F        tsdb-mysql-0 premier dans plus de la moitié de ses fenêtres de
             panne, sans tenir compte de l'alarme ; A : la même avec l'alarme ;
    minute   la première minute de panne où la méthode sonne ET met
             tsdb-mysql-0 premier, depuis la première minute de panne
             (« jamais » : plus tard que toute minute).
  TROUVE : sur une majorité stricte des graines, F sur une majorité stricte des
  injections qui comptent ET G, avec la même graine. Puis les fausses alertes
  sur les minutes normales de C, et l'ordre des décisions 1 à 3.
  Écrit <campagnes>/decision-<C>.txt.

comparer() calcule les axes (a), (b), (c) du journal entre le GNN et chaque
version de la règle qui TROUVE ; le GNN s'ajoute à methodes() en phase E, avec
une alarme calée au budget de la méthode à laquelle il est comparé.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --graines <n>          nombre de graines, à partir de 0 (défaut 5)
  --no-install           n'installe jamais scikit-learn
  --help                 ce texte

Code de sortie 0 ; 1 si une campagne est refusée, le scellé fermé, le code changé
ou une bibliothèque manque ; 2 sur un mauvais argument.
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
import temoins as temoins_module

HERE = Path(__file__).resolve().parent
TAS_COORDINATION = 10.0      # le même seuil que la vidange du juge (juge.lire, videe)
ETIQUETTE_TEMOINS = "temoins-figes"
ETIQUETTE_SCELLE = "gnn-fige"
FIGES_TEMOINS = ("temoin_tableau.py", "temoin_noeud.py", "temoin_fleches.py", "temoins.py", "juge.py")


def cles_base(fige: dict) -> list[str]:
    return sorted(juge._cle("instance", n) for n in fige["bases"].values())


def premier(f: dict, rep: dict, base: list[str]) -> bool:
    """tsdb-mysql-0 est-il premier dans cette fenêtre, égalités contre la méthode ?"""
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


def methodes(fige: dict) -> list[tuple[str, object, bool]]:
    """Les témoins figés. Le GNN s'ajoutera ici en phase E (nom commençant par « GNN »)."""
    return temoins_module.temoins(fige)


def _case(valeurs: list, total: int | None = None) -> str:
    m = statistics.median(valeurs)
    texte = f"{m:g}" + (f"/{total}" if total is not None else "")
    if min(valeurs) != max(valeurs):
        texte += f" [{min(valeurs)}–{max(valeurs)}]"
    return texte


def majorite(n: int, total: int) -> bool:
    return 2 * n > total


# ------------------------------------------------------------------------------
# La garde G, sur les deux séries
# ------------------------------------------------------------------------------
def garde(fen: list[dict], fige: dict, graines: int) -> tuple[list[str], dict[str, list[bool]]]:
    """(lignes du rapport, {méthode : [G tient ? par graine]})."""
    base = cles_base(fige)
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    injections = {k: v for k, v in par_injection(test).items() if not v[0]["jamais_vue"]}
    lignes = [f"injections de test des causes connues : {len(injections)} "
              f"({', '.join(f'{c}#{k}' for c, k in sorted(injections))})"]
    tient: dict[str, list[bool]] = {}
    for nom, fabrique, hasard in methodes(fige):
        comptes, detail = [], []
        for g in range(graines if hasard else 1):
            rep = reponses(fabrique, fen, test, g)
            accuse = [k for k, v in injections.items()
                      if majorite(sum(premier(f, rep[f["id"]], base) for f in v), len(v))]
            comptes.append(len(accuse))
            detail.append(accuse)
        tient[nom] = [c == 0 for c in comptes]
        verdict = "tient" if all(tient[nom]) else ("NE TIENT PAS" if not any(tient[nom])
                                                    else f"tient pour {sum(tient[nom])} graines sur {len(comptes)}")
        lignes.append(f"  {nom:<38} base première dans {_case(comptes, len(injections))} injections : G {verdict}")
        vues = sorted({f"{c}#{k}" for d in detail for c, k in d})
        if vues:
            lignes.append(f"  {'':<38} (injections accusant la base : {', '.join(vues)})")
    rep = juge.factices(fen)["a priori"]
    accuse = [k for k, v in injections.items()
              if majorite(sum(premier(f, rep[f["id"]], base) for f in v), len(v))]
    lignes.append(f"  {'a priori (ne lit rien)':<38} base première dans {len(accuse)}/{len(injections)} "
                  f"injections : G {'tient' if not accuse else 'NE TIENT PAS'}")
    return lignes, tient


# ------------------------------------------------------------------------------
# Le scellé et le code
# ------------------------------------------------------------------------------
def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, text=True)


def _sans_main(source: str) -> str:
    arbre = ast.parse(source)
    arbre.body = [n for n in arbre.body if not (isinstance(n, ast.FunctionDef) and n.name == "main")]
    return ast.dump(arbre)


def controle_du_code() -> list[str]:
    """Ce qui empêche d'ouvrir C : le scellé fermé, ou un code qui a changé depuis son étiquette."""
    if _git("tag", "--list", ETIQUETTE_SCELLE).stdout.strip() != ETIQUETTE_SCELLE:
        return [f"SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; C ne se lit qu'une fois le GNN figé."]
    soucis = []
    for f in FIGES_TEMOINS:
        if _git("diff", "--quiet", ETIQUETTE_TEMOINS, "--", f"graphe_en/{f}").returncode != 0:
            soucis.append(f"graphe_en/{f} a changé depuis l'étiquette {ETIQUETTE_TEMOINS}")
    # fautifs.py : seul le nom de son fichier de sortie (main) a changé depuis le gel.
    ancien = _git("show", f"{ETIQUETTE_TEMOINS}:graphe_en/fautifs.py").stdout
    if not ancien or _sans_main(ancien) != _sans_main((HERE / "fautifs.py").read_text()):
        soucis.append(f"graphe_en/fautifs.py a changé (hors main) depuis l'étiquette {ETIQUETTE_TEMOINS}")
    if _git("diff", "--quiet", ETIQUETTE_SCELLE, "--", "graphe_en/").returncode != 0:
        soucis.append(f"graphe_en/ a changé depuis l'étiquette {ETIQUETTE_SCELLE}")
    return soucis


# ------------------------------------------------------------------------------
# La lecture de C
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


def lire_c(fen_series: list[dict], fen_c: list[dict], c: str, campagnes: Path, fige: dict,
           graines: int, tient: dict[str, list[bool]]) -> list[str]:
    base = cles_base(fige)
    injections = par_injection([f for f in fen_c if f["cause"] == "base"])
    bornes = {k + 1: p for k, p in enumerate(fautifs_module.injections(campagnes / c / "campagne.yaml")[0])}
    les_veilles = veilles(campagnes / c / "campagne.yaml")
    comptent = {}
    lignes = ["", "Injections de C (confirmées) :"]
    for k, v in sorted(injections.items()):
        p = bornes[k[1]]
        avant = [f for f in fen_c if f["fin"] <= p["debut"]]
        vide_avant = bool(avant) and (tas(avant[-1]) or 0.0) <= TAS_COORDINATION
        pleines = sum(1 for f in v if (tas(f) or 0.0) > TAS_COORDINATION)
        deborde = majorite(pleines, len(v))
        raisons = effondrement(v, p["debut"], p["fin"], les_veilles)
        comptent[k] = vide_avant and deborde and not raisons
        motif = ("compte" if comptent[k] else "NE COMPTE PAS : " + ", ".join(
            ([] if vide_avant else ["file pas vide avant"]) + ([] if deborde else ["la file ne déborde pas"])
            + [f"effondrement ({r})" for r in raisons]))
        lignes.append(f"  {k[0]}#{k[1]} : {len(v)} minutes de panne, tas > {TAS_COORDINATION:g} dans {pleines} : {motif}")
    n_comptent = sum(comptent.values())
    if len(injections) < 2:
        lignes.append("MOINS DE 2 INJECTIONS CONFIRMÉES : C est à refaire à l'identique (règle écrite avant C).")
        return lignes
    if n_comptent < 2:
        lignes.append("MOINS DE 2 INJECTIONS QUI COMPTENT : C ne décide rien (règle écrite avant C).")
    normales = [f for f in fen_c if f["etiquette"] == "normale"]
    a_repondre = [f for f in fen_c if f["etiquette"] in ("normale", "panne")]
    lignes += ["", f"Par méthode (apprise sur les deux séries seules ; {len(normales)} minutes normales de C) :"]
    trouve: dict[str, bool] = {}
    for nom, fabrique, hasard in methodes(fige):
        n_f, n_a, fa, trouve_g, minutes = [], [], [], [], []
        for g in range(graines if hasard else 1):
            rep = reponses(fabrique, fen_series, a_repondre, g)
            f_ok = {k: majorite(sum(premier(f, rep[f["id"]], base) for f in v), len(v)) for k, v in injections.items()}
            a_ok = {k: majorite(sum(rep[f["id"]]["alarme"] and premier(f, rep[f["id"]], base) for f in v), len(v))
                    for k, v in injections.items()}
            n_f.append(sum(f_ok[k] for k in injections if comptent[k]))
            n_a.append(sum(a_ok[k] for k in injections if comptent[k]))
            fa.append(sum(1 for f in normales if rep[f["id"]]["alarme"]))
            trouve_g.append(n_comptent >= 2 and majorite(n_f[-1], n_comptent) and tient[nom][g])
            m = {}
            for k, v in injections.items():
                t = next((f for f in v if rep[f["id"]]["alarme"] and premier(f, rep[f["id"]], base)), None)
                m[k] = None if t is None else round((t["debut"] - v[0]["debut"]).total_seconds() / 60)
            minutes.append(m)
        trouve[nom] = majorite(sum(trouve_g), len(trouve_g))
        lignes.append(f"  {nom:<38} F {_case(n_f, n_comptent)} ; A {_case(n_a, n_comptent)} ; "
                      f"fausses alertes C {_case(fa, len(normales))} ; TROUVE : {'oui' if trouve[nom] else 'non'}"
                      + (f" ({sum(trouve_g)} graines sur {len(trouve_g)})" if hasard else ""))
        for k in sorted(injections):
            vus = [m[k] for m in minutes]
            lignes.append(f"  {'':<38} {k[0]}#{k[1]} : sonne et met la base première à la minute "
                          f"{', '.join('jamais' if x is None else str(x) for x in vus)} de la panne")
    lignes += ["", "Décision (ordre écrit avant C) :"]
    sans_structure = [n for n in trouve if (n.startswith("tableau") or n.startswith("score par nœud")) and trouve[n]]
    regles = [n for n in trouve if n.startswith("règle") and trouve[n]]
    if n_comptent < 2:
        lignes.append("  aucune : moins de 2 injections qui comptent.")
    elif sans_structure:
        lignes.append(f"  1. {', '.join(sans_structure)} TROUVE : sans la structure des flèches, les nombres suffisent "
                      f"sur C ; aucune conclusion sur le GNN n'est tirée de C (D et l'axe (a) restent).")
    elif regles:
        lignes.append(f"  2. {', '.join(regles)} TROUVE : H1 soutenue ; le GNN est comparé à chacune par comparer() "
                      f"(axes a, b, c du journal), D à part.")
    else:
        lignes.append("  3. personne ne trouve : le GNN gagne sur C s'il TROUVE.")
    return lignes


# ------------------------------------------------------------------------------
# Les axes du GNN contre une version de la règle (journal, décision 2)
# ------------------------------------------------------------------------------
def comparer(fa_gnn: list[int], fa_regle: int, minutes_gnn: list[dict], minutes_regle: dict,
             f_gnn: list[int], f_regle: int, comptent: dict) -> dict[str, str]:
    """
    Chaque axe vaut « gagné », « perdu » ou « égal ». Le GNN a une valeur par
    graine ; la règle, qui ne tire pas au hasard, une seule. Gagner demande
    TOUTES les graines ; perdre, une majorité stricte des graines (la marge est
    la même dans les deux sens).
      (a) fausses alertes à budget égal sur les 120 minutes normales non vues du
          test des deux séries : au moins 3 de moins ET au moins 25 % de moins ;
      (b) plus tôt : au moins une minute d'avance sur une majorité stricte des
          injections qui comptent (« jamais » est plus tard que tout ; jamais
          contre jamais : égalité) ;
      (c) plus d'injections trouvées (F, médiane des graines).
    """
    def mieux(x: int, y: int) -> bool:
        return x <= y - 3 and x <= 0.75 * y

    tot = len(fa_gnn)
    axes = {}
    g = sum(mieux(x, fa_regle) for x in fa_gnn)
    p = sum(mieux(fa_regle, x) for x in fa_gnn)
    axes["a"] = "gagné" if g == tot else ("perdu" if majorite(p, tot) else "égal")

    def devant(x, y) -> bool:   # x au moins une minute avant y ; « jamais » (None) après tout
        return x is not None and (y is None or x + 1 <= y)
    ks = [k for k, v in comptent.items() if v]
    avance = [sum(devant(m[k], minutes_regle[k]) for k in ks) for m in minutes_gnn]
    retard = [sum(devant(minutes_regle[k], m[k]) for k in ks) for m in minutes_gnn]
    axes["b"] = ("gagné" if all(majorite(a, len(ks)) for a in avance)
                 else "perdu" if majorite(sum(majorite(r, len(ks)) for r in retard), tot) else "égal")
    axes["c"] = "gagné" if statistics.median(f_gnn) > f_regle else "égal"
    return axes


# ------------------------------------------------------------------------------
def rapport(mode: str, c: str | None, campagnes: Path, runs: Path, graines: int) -> int:
    fige, _, _ = gel.reference()
    if mode == "ouvrir":
        soucis = controle_du_code()
        if soucis:
            print("\n".join(soucis))
            return 1
    try:
        fen_series = juge.lire(fautifs_module.SERIES, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    print("# Décision sur la base lente — écrit par graphe_en/decision_c.py, ne pas éditer à la main.")
    print(f"# règles : notes/JOURNAL.md, 27 sept. ; graines 0 à {graines - 1} pour ce qui tire au hasard")
    print("\n== La garde de spécificité G (test des deux séries)")
    lignes, tient = garde(fen_series, fige, graines)
    print("\n".join(lignes))
    if mode == "garde":
        return 0
    try:
        fen_c = juge.lire([c], campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    print(f"\n== La lecture de {c}")
    print("\n".join(lire_c(fen_series, fen_c, c, campagnes, fige, graines, tient)))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, installer, graines = HERE.parent / "campagnes", HERE / "runs", True, 5
    mode, c = None, None
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
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    if mode is None:
        print("--garde ou --ouvrir <campagne C>", file=sys.stderr)
        return 2
    if c is not None and c in fautifs_module.SERIES:
        print(f"{c} est une campagne des deux séries, pas C", file=sys.stderr)
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
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(mode, c, campagnes, runs, graines)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / ("decision-garde.txt" if mode == "garde" else f"decision-{c}.txt")
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
