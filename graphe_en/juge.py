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

Un nœud absent des scores, ou dont le score est None ou NaN, est classé
dernier. Les égalités sont départagées contre le témoin : le fautif passe
après tous ceux qui ont le même score. L'ordre des nœuds n'intervient jamais.

LA NOTE (noter), sur les fenêtres de test non écartées :
  détection     fenêtres de panne avec alarme ; fausses alertes : fenêtres
                normales avec alarme, saine-09 à part (« vues »)
  cause         fenêtres de panne avec la bonne cause
  fautif        top-1 et top-3 : un fautif parmi les k premiers ; sans tenir
                compte de l'alarme (mesure principale), puis « avec alarme »
                (une panne manquée compte comme fausse) ; la charge n'y entre pas
  par injection une injection est trouvée si la majorité de ses fenêtres de
                panne au test le sont

CE QUE FAIT LE SCRIPT

Affiche et écrit <campagnes>/etiquettes.txt : les comptes par campagne, puis
chaque campagne en tranches de minutes consécutives de même étiquette. Contrôle
que ses étiquettes et sa coupure sont celles de ligne_de_base.py, minute par
minute. Puis essaie le juge sur deux témoins factices, dont la note est connue
d'avance : l'oracle (alarme, cause et fautif justes : tout à 100 %) et le
témoin sans avis (même score pour tous, jamais d'alarme : fautif jamais au
premier rang, aucune détection).

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --consumer <prefixe>   les répliques du consommateur (défaut ts-delivery-service-)
  --drain <n>            tas sous lequel la file compte comme vidée (défaut 10)
  --help                 ce texte

Code de sortie 0 si tout est lu, conforme et identique à ligne_de_base.py, et
si les deux témoins factices ont la note attendue ; 1 sinon ; 2 sur un
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
ECARTEES = {"a_cheval", "non_confirmee", "vidange"}


class Refus(Exception):
    """Une campagne que le juge ne peut pas lire honnêtement."""


# ------------------------------------------------------------------------------
# Lire et étiqueter
# ------------------------------------------------------------------------------
def _cle(kind: str, name: str) -> str:
    return f"{kind}:{name}"


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
                    "fin": fin, "serie": 1 if nom in PREMIERE else 2, "vue": nom == "saine-09",
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
def rang(fautifs: list[str], scores: dict) -> int:
    """
    Le rang du mieux placé des fautifs, égalités départagées contre le témoin.

    Un score absent, None ou NaN vaut moins que tout. Le fautif passe après
    chaque autre nœud dont le score est au moins le sien : c'est le pire rang
    qu'un départage des égalités pourrait lui donner.
    """
    def val(v):
        return -math.inf if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    meilleur = max(val(scores.get(c)) for c in fautifs)
    autres = [k for k in scores if k not in fautifs]
    return 1 + sum(1 for k in autres if val(scores[k]) >= meilleur)


def _part(n: int, total: int) -> str:
    return f"{n}/{total}" + (f" ({100 * n / total:.0f} %)" if total else "")


def noter(fen: list[dict], reponses: dict, titre: str = "") -> tuple[list[str], dict]:
    """
    La note d'un témoin sur les fenêtres de test non écartées, en texte et en
    nombres. `reponses` : {fen["id"]: {"alarme", "cause", "scores"}} ; une
    fenêtre de test sans réponse est une erreur.
    """
    apprises = causes_apprises(fen)
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in ECARTEES]
    manque = [f["id"] for f in test if f["id"] not in reponses]
    if manque:
        raise ValueError(f"{len(manque)} fenêtres de test sans réponse, dont {manque[0]}")
    lignes = [f"== {titre}" if titre else "=="]
    chiffres: dict = {}

    pannes = [f for f in test if f["etiquette"] == "panne"]
    normales = [f for f in test if f["etiquette"] == "normale"]
    alarme = lambda f: bool(reponses[f["id"]].get("alarme"))

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
    bonne = [f for f in pannes if reponses[f["id"]].get("cause") == cause_attendue(f, apprises)]
    chiffres["cause"] = (len(bonne), len(pannes))
    lignes.append(f"cause          {_part(len(bonne), len(pannes))} fenêtres de panne bien nommées"
                  + ("" if not (set(f['cause'] for f in pannes) - apprises)
                     else f"  (jamais vues : {', '.join(sorted(set(f['cause'] for f in pannes) - apprises))},"
                          f" bonne réponse « inconnue »)"))

    # Fautif, par cause et par série.
    avec_fautif = [f for f in pannes if f["fautifs"]]
    rangs = {f["id"]: rang(f["fautifs"], reponses[f["id"]].get("scores") or {}) for f in avec_fautif}
    lignes.append(f"fautif         {'':<18}{'top-1':>14}{'top-3':>14}{'top-1 avec alarme':>22}")
    groupes = [("tout", avec_fautif)]
    groupes += [(c, [f for f in avec_fautif if f["cause"] == c])
                for c in sorted({f["cause"] for f in avec_fautif})]
    groupes += [(f"série {s}", [f for f in avec_fautif if f["serie"] == s]) for s in (1, 2)]
    for nom, groupe in groupes:
        if not groupe:
            continue
        t1 = sum(1 for f in groupe if rangs[f["id"]] <= 1)
        t3 = sum(1 for f in groupe if rangs[f["id"]] <= 3)
        t1a = sum(1 for f in groupe if rangs[f["id"]] <= 1 and alarme(f))
        chiffres[f"top-1 {nom}"], chiffres[f"top-3 {nom}"] = (t1, len(groupe)), (t3, len(groupe))
        chiffres[f"top-1 avec alarme {nom}"] = (t1a, len(groupe))
        lignes.append(f"  {nom:<29}{_part(t1, len(groupe)):>14}{_part(t3, len(groupe)):>14}"
                      f"{_part(t1a, len(groupe)):>22}")

    # Par injection : la majorité de ses fenêtres de panne au test.
    injections: dict = {}
    for f in pannes:
        injections.setdefault((f["campagne"], f["injection"]), []).append(f)
    lignes.append("par injection  (trouvée si la majorité de ses fenêtres de test le sont)")
    trouvees = {"détectée": 0, "cause": 0, "top-1": 0, "top-3": 0}
    avec = 0
    for (c, k), groupe in sorted(injections.items()):
        maj = lambda ok: 2 * sum(1 for f in groupe if ok(f)) > len(groupe)
        d = maj(alarme)
        b = maj(lambda f: reponses[f["id"]].get("cause") == cause_attendue(f, apprises))
        r1 = r3 = None
        if groupe[0]["fautifs"]:
            avec += 1
            r1, r3 = maj(lambda f: rangs[f["id"]] <= 1), maj(lambda f: rangs[f["id"]] <= 3)
            trouvees["top-1"] += r1
            trouvees["top-3"] += r3
        trouvees["détectée"] += d
        trouvees["cause"] += b
        oui = lambda x: "—" if x is None else ("oui" if x else "non")
        lignes.append(f"  {c:<12} injection {k}  {groupe[0]['cause']:<8} {len(groupe):>3} fenêtres   "
                      f"détectée {oui(d):<4}cause {oui(b):<4}top-1 {oui(r1):<4}top-3 {oui(r3)}")
    n = len(injections)
    chiffres["injections"] = {k: (v, avec if k.startswith("top") else n) for k, v in trouvees.items()}
    lignes.append(f"  total : détectées {trouvees['détectée']}/{n}, bonne cause {trouvees['cause']}/{n}, "
                  f"fautif top-1 {trouvees['top-1']}/{avec}, top-3 {trouvees['top-3']}/{avec}")
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


def factices(fen: list[dict]) -> tuple[dict, dict]:
    apprises = causes_apprises(fen)
    oracle, sans_avis = {}, {}
    for f in fen:
        noeuds = [_cle(k, n) for k in ("instance", "queue", "host")
                  for n in f["donnees"]["nodes"][k]["names"]]
        oracle[f["id"]] = {"alarme": f["etiquette"] == "panne",
                           "cause": cause_attendue(f, apprises),
                           "scores": {n: (1.0 if n in f["fautifs"] else 0.0) for n in noeuds}}
        sans_avis[f["id"]] = {"alarme": False, "cause": "normale",
                              "scores": {n: 0.0 for n in noeuds}}
    return oracle, sans_avis


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

    print("\n# essai du juge sur deux témoins factices, dont la note est connue d'avance")
    oracle, sans_avis = factices(fen)
    lignes, n_or = noter(fen, oracle, "oracle : alarme, cause et fautif justes")
    print("\n".join(lignes))
    lignes, n_sa = noter(fen, sans_avis, "sans avis : même score pour tous, jamais d'alarme")
    print("\n".join(lignes))
    attendu_or = all(v[0] == v[1] for k, v in n_or.items() if k != "injections"
                     and not k.startswith("fausses")) and all(v[0] == 0 for k, v in n_or.items()
                                                              if k.startswith("fausses"))
    attendu_sa = n_sa["detection"][0] == 0 and all(v[0] == 0 for k, v in n_sa.items()
                                                   if k.startswith("top-1"))
    print(f"\n  oracle : {'note attendue' if attendu_or else 'ÉCART'} ; "
          f"sans avis : {'note attendue' if attendu_sa else 'ÉCART'}")
    problemes += (not attendu_or) + (not attendu_sa)

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
