"""
Témoin 3 bis : la règle « cause commune » avec l'idée « machine », écrite AVANT D.

    ./.venv/bin/python temoin_machine.py [options]

Décidé par l'utilisateur le 28 sept. (option B du journal, D.1) : l'idée qui
sépare les jumeaux de D est évidente, une règle honnête doit l'avoir. Sans elle,
aucun témoin ne pourrait désigner une machine muette, et une victoire du GNN sur D
ne dirait rien. Ce fichier n'ouvre ni ne modifie temoin_fleches.py (figé sous
l'étiquette temoins-figes) : il en hérite.

L'IDÉE. Quand la règle « cause commune » accuse des répliques (« blocage » ou
« lenteur »), elle regarde encore leur machine h, celle qui porte une majorité
stricte des répliques accusées (une panne de machine n'explique pas des répliques
lentes sur plusieurs machines). Si la plupart des AUTRES pods actifs de h sont
lents eux aussi, et pas la plupart des pods actifs des autres machines hors de
l'amont de h, la cause est commune à la machine. Elle accuse alors la machine,
cause « inconnue » (la règle ne connaît pas cette panne), les répliques restant sur
le chemin.

  actif    un pod qui, dans la fenêtre lue, est source d'une flèche calls ou
           queries vers un pod placé sur une autre machine que lui ;
  amont    les services qui appellent, d'après les fenêtres normales
           d'apprentissage (directement ou de proche en proche), un service
           placé sur h : ils ralentissent avec h (le retard de h leur revient),
           D.1 les met hors de la comparaison ;
  lent     le plus haut écart d'un pod parmi ses temps (traitement ou requête),
           ses flèches queries sortantes et les flèches calls qui entrent chez lui
           (mesurées chez l'appelé) dépasse s_l ;
  s_l      la limite de cette statistique, calée comme s_f : son 95e centile sur
           les pods actifs des fenêtres normales d'apprentissage, chaque campagne
           mise de côté à son tour ; toujours sans exemples ;
  il faut au moins deux autres pods actifs sur h (la marge écrite en D.1), une
  majorité stricte d'entre eux lents, au moins deux pods actifs ailleurs hors de
  l'amont, et au plus la moitié d'entre eux lents.

Les limites d'alarme s_f et s_m sont celles de la règle : même alarme, même budget.
Sans exemples, s = s_f comme la règle. Avec exemples, s est choisie par la même
grille que la règle, mais notée sur les réponses de la règle AVEC l'idée (quand
l'idée accuse une machine dans une panne connue, la note change d'au plus deux
points, la cause et le fautif ; sur l'apprentissage des deux séries : −2, par
blocage-02/0057).

Première version (28 sept., jamais commitée ni figée) : « ailleurs » comptait l'amont,
l'idée jouait avec des répliques accusées sur plusieurs machines, « lent »
reprenait s, « actif » était lu sur le normal seul, et la grille avec exemples
ignorait l'idée. Elle a été vue aussi sur des fenêtres du test (son --comparer, et
deux relecteurs) ; les corrections sont choisies par principe (le texte de D.1, une
machine et non trois, s_l calée comme s_f), leur effet sur D est inconnu (journal,
D.1, suite).

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --comparer             sur la VALIDATION des deux séries seulement (jamais une
                         fenêtre « hors »), les fenêtres où l'idée change la
                         réponse de la règle, et ses limites
  --help                 ce texte
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import fautifs as fautifs_module
import juge
import temoin_fleches as tf
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
REQUETES = ("request_time_p50", "request_time_p95", "request_time_p99")
MARGE_SERVICES = 2


def _machines(donnees: dict) -> dict[str, str]:
    """{clé de pod : sa machine}, lue dans le champ hosts des nœuds."""
    inst = donnees["nodes"]["instance"]
    return {juge._cle("instance", n): h for n, h in zip(inst["names"], inst["hosts"]) if h}


def _actifs(machine: dict[str, str], ze: list) -> set[str]:
    """Les pods source, dans la fenêtre, d'une flèche calls ou queries vers une autre machine."""
    return {src for rel, src, tgt, _ in ze
            if rel in tf.APPELS and src in machine and tgt in machine and machine[tgt] != machine[src]}


def _hauts(zn: dict, ze: list) -> dict[str, float]:
    """Pour chaque pod, le plus haut écart parmi ses temps, ses queries sortantes, ses calls entrants."""
    haut = {k: tf._haut(z, tf.TEMPS + REQUETES) for k, z in zn.items()}
    for rel, src, tgt, z in ze:
        if rel == "queries":
            haut[src] = max(haut.get(src, -math.inf), tf._haut(z, tf.LATENCES))
        elif rel == "calls":
            haut[tgt] = max(haut.get(tgt, -math.inf), tf._haut(z, tf.LATENCES))
    return haut


class Machine(tf.Fleches):
    """La règle « cause commune », plus l'idée « machine »."""

    def __init__(self, fen: list[dict], reglage: str, fige: dict):
        if reglage not in tf.REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        # La règle sans exemples donne les normaux, s_f et s_m ; s est choisie plus bas.
        super().__init__(fen, "sans exemples", fige, "cause commune")
        self.reglage = reglage
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        campagnes = sorted({f["campagne"] for f in normales})

        # Qui appelle qui dans le normal, par identité de service (pour l'amont).
        self.paires: set[tuple[str, str]] = set()
        for f in normales:
            for rel, src, tgt, _ in self.fleches._fleches(f["donnees"]):
                if rel in tf.APPELS:
                    self.paires.add((tf._ident(src), tf._ident(tgt)))

        # s_l : chaque campagne mise de côté à son tour, sur le normal seul.
        normaux, valeurs = tn.Normaux(normales, fige), []
        for c in campagnes:
            noeuds = normaux.sans(c)
            fleches = tf.NormalFleches([f for f in normales if f["campagne"] != c], fige)
            for f in (f for f in normales if f["campagne"] == c):
                ze = fleches.ecarts(f["donnees"])
                haut = _hauts(noeuds.ecarts(f["donnees"]), ze)
                valeurs += [haut[k] for k in _actifs(_machines(f["donnees"]), ze) if haut.get(k, -math.inf) > -math.inf]
        self.s_l = tn._q(valeurs, 1 - tn.CENTILE / 100) if valeurs else 0.0
        self.calage_l = (len(campagnes), len(valeurs))
        if reglage == "sans exemples":
            return

        # Avec exemples : la grille de la règle, notée sur les réponses AVEC l'idée.
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        ecarts = {f["id"]: (self.noeuds.ecarts(f["donnees"]), self.fleches.ecarts(f["donnees"])) for f in pannes}
        notes = {}
        for s in tf.GRILLE:
            juste = 0
            for f in pannes:
                zn, ze = ecarts[f["id"]]
                cause, designes, _, _ = self._marche(f["donnees"], zn, ze, s)
                juste += (cause == f["cause"]) + bool(f["fautifs"] and designes and designes[0] in f["fautifs"])
            notes[s] = juste
        meilleur = max(notes.values())
        self.s = min((s for s, n in notes.items() if n == meilleur),
                     key=lambda s: abs(math.log(s / self.s_f)) if self.s_f > 0 else s)
        self.grille = notes
        self.grille_sur = sum(1 + bool(f["fautifs"]) for f in pannes)

    def amont(self, services: set[str]) -> set[str]:
        """Les services qui appellent ces services, directement ou de proche en proche (hors eux)."""
        vus, bord = set(), set(services)
        while bord:
            bord = {p for p, t in self.paires if t in bord} - vus - services
            vus |= bord
        return vus

    def machine_commune(self, donnees: dict, zn: dict, ze: list, designes: list[str]) -> str | None:
        """Le nœud host de la machine des désignés dont les services ralentissent ensemble, sinon None."""
        machine = _machines(donnees)
        leurs = [machine[c] for c in designes if c in machine]
        h = next((m for m in set(leurs) if 2 * leurs.count(m) > len(designes)), None)
        if h is None:
            return None
        actifs, haut = _actifs(machine, ze), _hauts(zn, ze)
        lent = lambda k: haut.get(k, -math.inf) > self.s_l
        amont = self.amont({tf._ident(k) for k, m in machine.items() if m == h})
        ici = [k for k in actifs if machine[k] == h and k not in designes]
        ailleurs = [k for k in actifs if machine[k] != h and tf._ident(k) not in amont]
        if (len(ici) >= MARGE_SERVICES and 2 * sum(map(lent, ici)) > len(ici)
                and len(ailleurs) >= MARGE_SERVICES and 2 * sum(map(lent, ailleurs)) <= len(ailleurs)):
            return juge._cle("host", h)
        return None

    def _marche(self, donnees: dict, zn: dict, ze: list, s: float) -> tuple[str, list[str], list[str], str]:
        """(cause, désignés, chemin, branche) : la règle, puis l'idée « machine »."""
        cause, designes, chemin, branche = tf.marche(donnees, zn, ze, self.fleches.consommateurs, self.avec_temps,
                                                     self.s_f, self.s_m, s, self.variante)
        if cause in ("blocage", "lenteur"):
            h = self.machine_commune(donnees, zn, ze, designes)
            if h is not None:
                return "inconnue", [h], chemin + designes, "4 machine dont les services ralentissent ensemble"
        return cause, designes, chemin, branche

    def repondre(self, donnees: dict) -> dict:
        """La réponse du témoin pour une fenêtre, à partir de ses seuls nombres et flèches."""
        zn = self.noeuds.ecarts(donnees)
        ze = self.fleches.ecarts(donnees)
        cause, designes, chemin, branche = self._marche(donnees, zn, ze, self.s)
        scores = {k: (min(v, 1e7) if (v := tn.score(z)) is not None else None) for k, z in zn.items()}
        for k in chemin:
            scores[k] = 1e8
        for k in designes:
            scores[k] = 1e9
        return {"alarme": cause != "normale", "cause": cause, "scores": scores, "_branche": branche}


def comparer(campagnes: Path, runs: Path) -> int:
    """Sur la validation des deux séries : où l'idée « machine » change-t-elle la réponse de la règle ?"""
    import gel
    fige, _, _ = gel.reference()
    try:
        fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    lues = [f for f in fen if f["jeu"] != "hors" and f["etiquette"] not in juge.ECARTEES]
    for reglage in tf.REGLAGES:
        regle = tf.Fleches(fen, reglage, fige, "cause commune")
        bis = Machine(fen, reglage, fige)
        print(f"{reglage} : s_f = {bis.s_f:.2f}, s_l = {bis.s_l:.2f} ({bis.calage_l[1]} pods actifs, "
              f"{bis.calage_l[0]} campagnes), s = {bis.s:g} (règle : {regle.s:g})")
        diff = []
        for f in lues:
            a, b = regle.repondre(f["donnees"]), bis.repondre(f["donnees"])
            if b["_branche"].startswith("4"):
                h = max(b["scores"], key=lambda k: b["scores"][k] or -math.inf)
                diff.append((f["id"], f["jeu"], f["etiquette"], f["cause"], a["cause"], h))
        print(f"  {len(diff)} fenêtres sur {len(lues)} (validation, hors « hors ») où l'idée accuse une machine")
        for d in diff[:30]:
            print(f"    {d[0]}  ({d[1]}, {d[2]}, {d[3]}) : {d[4]} → {d[5]}")
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, faire = HERE.parent / "campagnes", HERE / "runs", False
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
            elif a == "--comparer":
                faire = True
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except IndexError:
        print("option sans valeur", file=sys.stderr)
        return 2
    if not faire:
        print(__doc__.strip())
        return 0
    return comparer(campagnes.resolve(), runs.resolve())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
