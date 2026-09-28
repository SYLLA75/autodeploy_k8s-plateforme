"""
La seule vérification d'un essai de D (journal, D.1) : le temps de traitement
des trois répliques du consommateur, rien d'autre.

    ./.venv/bin/python essai_d.py <run> <campagne> [--campaigns <d>]

Les essais de D sont sous le scellé de D. Ce script ne lit, dans le graphe de
l'essai, que les nœuds des répliques (colonne process_time_p50) et leurs
flèches executes_on (leur machine). Il écrit, pour chaque réplique, sa machine
et la médiane de process_time_p50 sur les fenêtres normales AVANT l'injection et
sur les fenêtres entièrement DANS l'injection, puis le verdict écrit avant les
essais (journal, D.3) :

  la réplique de X est nettement plus lente si sa médiane pendant la panne vaut
  au moins 1,5 fois la plus grande médiane des deux autres pendant la panne.

Il vérifie que le moyen a agi comme prévu (écart 3, journal D.5) : pendant la
panne, la médiane de la réplique de X doit valoir sa médiane d'avant + 5 × d, à
10 % près (d lu dans le registre) ; sinon « MOYEN NON CONFORME » (un retard
perdu ou doublé sur la réplique), arrêt.

Il compte aussi, sans en lire aucune valeur, les fenêtres de panne où manque le
nœud host X ou la réplique de X : une seule suffit à l'effondrement de D.1.

Il écrit enfin le dépôt et le retrait de la file (publish_rate, consume_rate du
nœud queue:food_delivery, médianes avant / pendant), que D.1 permet de lire pour
choisir le cran (« lue seulement sur les relevés, la file et le dépôt »), et ce
qu'en dit la règle de montée, fixée avant le premier verdict (journal, D.5) :
dépôt proche = médiane pendant ≥ 0,9 × médiane avant ; au-dessus du retrait =
médiane de (dépôt − retrait) pendant ≥ −0,1 message/s. Ceci ne change pas le
code de sortie.

Code de sortie : 0 nettement plus lente ; 1 non, ou effondrement (arrêt,
décision avec l'utilisateur) ; 2 lecture impossible ou essai mal formé.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import fautifs as fautifs_module

HERE = Path(__file__).resolve().parent
CONSO = "ts-delivery-service-"
COLONNE = "process_time_p50"
NETTEMENT = 1.5
FILE = "food_delivery"
PROCHE, ECART = 0.9, -0.1
TOLERANCE = 0.10


def file(d: dict) -> tuple[float | None, float | None]:
    """(dépôt, retrait) de la file dans une fenêtre, en messages/s."""
    bloc = d["nodes"]["queue"]
    if FILE not in bloc["names"]:
        return None, None
    ligne = bloc["X"][bloc["names"].index(FILE)]
    return ligne[bloc["columns"].index("publish_rate")], ligne[bloc["columns"].index("consume_rate")]


def _instant(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def repliques(d: dict) -> dict[str, tuple[str | None, float | None]]:
    """{réplique : (machine, process_time_p50)} pour une fenêtre."""
    bloc = d["nodes"]["instance"]
    machine = {}
    e = d["edges"].get("executes_on")
    if e:
        sn = d["nodes"][e["source_kind"]]["names"]
        tg = d["nodes"][e["target_kind"]]["names"]
        for s, t in zip(e["source"], e["target"]):
            machine[sn[s]] = tg[t]
    col = bloc["columns"].index(COLONNE)
    return {n: (machine.get(n), bloc["X"][i][col])
            for i, n in enumerate(bloc["names"]) if n.startswith(CONSO)}


def main(argv: list[str]) -> int:
    try:
        return verifier(argv)
    except (OSError, KeyError, ValueError, IndexError, TypeError) as e:
        print(f"REFUS  lecture impossible : {type(e).__name__} {e}")
        return 2


def verifier(argv: list[str]) -> int:
    args = argv[1:]
    campagnes = HERE.parent / "campagnes"
    if "--campaigns" in args:
        i = args.index("--campaigns")
        campagnes = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__.strip())
        return 2
    run, nom = Path(args[0]), args[1]
    paires, soucis = fautifs_module.injections(campagnes / nom / "campagne.yaml")
    if soucis or len(paires) != 1:
        print(f"REFUS  {nom} : {soucis[0] if soucis else f'{len(paires)} injections, il en faut une'}")
        return 2
    p = paires[0]
    if p["cause"] != "reseau" or not p["confirmee"] or p["registre"] is None:
        print(f"REFUS  {nom} : injection {p['cause']}, "
              f"{'confirmée' if p['confirmee'] else 'NON confirmée'}, "
              f"{'registre lu' if p['registre'] else 'registre illisible'}")
        return 2
    x = p["registre"][5].split("@")[0]
    d_ms = float(p["registre"][4])

    if not run.is_dir():
        print(f"REFUS  run introuvable : {run}")
        return 2
    avant: dict[str, list[float]] = {}
    pendant: dict[str, list[float]] = {}
    ou_avant: dict[str, set[str]] = {}    # machines de chaque réplique, avant / pendant la panne
    ou_pendant: dict[str, set[str]] = {}
    presentes: list[set[str]] = []        # répliques présentes, fenêtre de panne par fenêtre
    sans_x = 0                            # fenêtres de panne sans le nœud host X
    n_avant = n_pendant = 0
    depot: dict[str, list[float]] = {"avant": [], "pendant": []}
    ecart: list[float] = []
    for d in fautifs_module.fenetres(run):
        debut, fin = _instant(d["window"]["start_ns"]), _instant(d["window"]["end_ns"])
        if fin <= p["debut"]:
            cible, ou, n_avant = avant, ou_avant, n_avant + 1
        elif debut >= p["debut"] and fin <= p["fin"]:
            cible, ou, n_pendant = pendant, ou_pendant, n_pendant + 1
            sans_x += x not in d["nodes"]["host"]["names"]
        else:
            continue
        reps = repliques(d)
        dep, ret = file(d)
        if dep is not None:
            depot["avant" if cible is avant else "pendant"].append(dep)
            if cible is pendant and ret is not None:
                ecart.append(dep - ret)
        if cible is pendant:
            presentes.append(set(reps))
        for n, (m, v) in reps.items():
            if m:
                ou.setdefault(n, set()).add(m)
            if v is not None:
                cible.setdefault(n, []).append(v)
    print(f"{nom} : X = {x} ; {n_avant} fenêtres avant l'injection, {n_pendant} pendant")
    if n_pendant == 0:
        print("REFUS  aucune fenêtre entièrement dans l'injection")
        return 2
    # La réplique de X : celle que les fenêtres d'AVANT placent sur X (à défaut, celles
    # de la panne) ; une réplique recréée sous un autre nom manque alors pendant la panne.
    sur_x = sorted(n for n, m in ou_avant.items() if m == {x}) if ou_avant else []
    if len(sur_x) != 1:
        sur_x = sorted(n for n, m in ou_pendant.items() if m == {x})
    ou_tout = {n: ou_avant.get(n, set()) | ou_pendant.get(n, set()) for n in set(ou_avant) | set(ou_pendant)}
    for n in sorted(set(avant) | set(pendant)):
        a = f"{median(avant[n]):8.1f}" if avant.get(n) else "       —"
        b = f"{median(pendant[n]):8.1f}" if pendant.get(n) else "       —"
        print(f"  {n:40s} {','.join(sorted(ou_tout.get(n, {'?'}))):10s} avant {a} ms   pendant {b} ms"
              f"   ({len(pendant.get(n, []))} fenêtres)")
    if depot["avant"] and depot["pendant"] and ecart:
        da, dp, e = median(depot["avant"]), median(depot["pendant"]), median(ecart)
        print(f"  file {FILE} : dépôt avant {da:.2f}/s, pendant {dp:.2f}/s ; dépôt − retrait pendant {e:+.2f}/s"
              f" → dépôt {'proche' if dp >= PROCHE * da else 'PAS proche'} de celui d'avant,"
              f" {'au-dessus du' if e >= ECART else 'SOUS le'} retrait")
    else:
        print(f"  file {FILE} : dépôt illisible")
    sans_rep = sum(sur_x[0] not in s for s in presentes) if len(sur_x) == 1 else n_pendant
    print(f"  fenêtres de panne sans le nœud host {x} : {sans_x} ; sans la réplique de {x} : {sans_rep}")
    if sans_x or sans_rep:
        print("EFFONDREMENT  (D.1 : une seule fenêtre de panne sans X ou sans sa réplique) — arrêt, "
              "décision avec l'utilisateur")
        return 1
    rep_x = sur_x[0]
    autres = sorted(n for n in pendant if n != rep_x)
    if len(autres) != 2 or rep_x not in pendant:
        print(f"REFUS  il faut la réplique de {x} et deux autres pendant la panne "
              f"(lu : {len(autres)} autres{'' if rep_x in pendant else f', aucune valeur pour {rep_x}'})")
        return 2
    mx = median(pendant[rep_x])
    if not avant.get(rep_x):
        print(f"REFUS  aucune valeur avant l'injection pour la réplique de {x} : le moyen ne peut pas être contrôlé")
        return 2
    attendu = median(avant[rep_x]) + 5 * d_ms
    print(f"  réplique de {x} : {mx:.0f} ms pendant, attendu {attendu:.0f} ms (avant + 5 × {d_ms:.0f})")
    if abs(mx - attendu) > TOLERANCE * attendu:
        print("MOYEN NON CONFORME  la réplique de X ne suit pas avant + 5 × d à 10 % près — arrêt, "
              "décision avec l'utilisateur")
        return 1
    mo = max(median(pendant[n]) for n in autres)
    rapport = mx / mo if mo > 0 else float("inf")
    if rapport >= NETTEMENT:
        print(f"NETTEMENT PLUS LENTE  la réplique de {x} : {rapport:.2f} fois la plus lente des deux autres")
        return 0
    print(f"PAS NETTEMENT PLUS LENTE  la réplique de {x} : {rapport:.2f} fois la plus lente des deux autres "
          f"(il faut {NETTEMENT}) — arrêt, décision avec l'utilisateur")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
