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

Il compte aussi, sans en lire aucune valeur, les fenêtres de panne où manque le
nœud host X ou la réplique de X : une seule suffit à l'effondrement de D.1.

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

    if not run.is_dir():
        print(f"REFUS  run introuvable : {run}")
        return 2
    avant: dict[str, list[float]] = {}
    pendant: dict[str, list[float]] = {}
    ou: dict[str, set[str]] = {}          # machines de chaque réplique PENDANT la panne
    presentes: list[set[str]] = []        # répliques présentes, fenêtre de panne par fenêtre
    sans_x = 0                            # fenêtres de panne sans le nœud host X
    n_avant = n_pendant = 0
    for d in fautifs_module.fenetres(run):
        debut, fin = _instant(d["window"]["start_ns"]), _instant(d["window"]["end_ns"])
        if fin <= p["debut"]:
            cible, n_avant = avant, n_avant + 1
        elif debut >= p["debut"] and fin <= p["fin"]:
            cible, n_pendant = pendant, n_pendant + 1
            sans_x += x not in d["nodes"]["host"]["names"]
        else:
            continue
        reps = repliques(d)
        if cible is pendant:
            presentes.append(set(reps))
        for n, (m, v) in reps.items():
            if m and cible is pendant:
                ou.setdefault(n, set()).add(m)
            if v is not None:
                cible.setdefault(n, []).append(v)
    sur_x = sorted(n for n in pendant if ou.get(n) == {x})
    autres = sorted(n for n in pendant if n not in sur_x)
    print(f"{nom} : X = {x} ; {n_avant} fenêtres avant l'injection, {n_pendant} pendant")
    for n in sorted(set(avant) | set(pendant)):
        a = f"{median(avant[n]):8.1f}" if avant.get(n) else "       —"
        b = f"{median(pendant[n]):8.1f}" if pendant.get(n) else "       —"
        print(f"  {n:40s} {','.join(sorted(ou.get(n, {'?'}))):10s} avant {a} ms   pendant {b} ms"
              f"   ({len(pendant.get(n, []))} fenêtres)")
    if len(sur_x) != 1 or len(autres) != 2:
        print(f"REFUS  il faut une réplique sur {x} et deux ailleurs pendant la panne "
              f"(lu : {len(sur_x)} sur {x}, {len(autres)} ailleurs)")
        return 2
    sans_rep = sum(sur_x[0] not in s for s in presentes)
    print(f"  fenêtres de panne sans le nœud host {x} : {sans_x} ; sans la réplique de {x} : {sans_rep}")
    if n_pendant == 0 or sans_x or sans_rep:
        print("EFFONDREMENT  (D.1 : une seule fenêtre de panne sans X ou sans sa réplique) — arrêt, "
              "décision avec l'utilisateur")
        return 1
    mx = median(pendant[sur_x[0]])
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
