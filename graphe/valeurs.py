#!/usr/bin/env python3
"""
Les valeurs portées par chaque rond.

    python3 valeurs.py donnees/2026-09-09_1505-1514 --espace train-ticket

Quatrième brique. Pour chaque fenêtre et chaque rond, calcule la liste de
nombres que le papier lui associe :

    copie de service   19 nombres
    file               6 nombres
    machine            5 nombres

CINQ FAÇONS DE RÉSUMER (les « opérateurs » du papier)

    fin      la dernière valeur de la fenêtre           un niveau
    ext      le minimum ou le maximum sur la fenêtre    un creux, un pic
    inc      de combien un compteur a monté             un cumul
    quant    la valeur sous laquelle tombent q % des cas
    pente    la tendance sur H fenêtres consécutives    une dérive

Plus deux combinaisons : un rapport (a/b) et un écart (a−b).
Le débit par seconde est un rapport : inc divisé par la durée de la fenêtre.

DEUX ÉCARTS ASSUMÉS PAR RAPPORT AU PAPIER, tous deux mesurés :

  1. Le débit publié d'une file (composante 3) devait venir du compteur
     rabbitmq_queue_messages_published_total. CE COMPTEUR N'EXISTE PAS sur
     RabbitMQ 3.8 : vérifié, il n'est pas dans les 21 exportés. On le calcule
     donc à partir des notes de dépôt, symétriquement à la composante 4 que le
     papier reconstruit déjà à partir des notes de retrait. Avantage : les deux
     débits sont mesurés de la même façon, donc leur différence a un sens.

  2. « inc » est défini dans le papier comme dernière valeur moins première.
     Un compteur remis à zéro par un redémarrage rendrait alors une valeur
     NÉGATIVE, c'est-à-dire un débit négatif. On somme donc les hausses entre
     relevés consécutifs, en ignorant les baisses. Sans redémarrage les deux
     formules donnent le même résultat.

CE QUE VAUT η. Le papier corrige les comptages de notes par le taux
d'échantillonnage η. La chaîne est réglée sur « garder toutes les traces »
(OTEL_TRACES_SAMPLER=parentbased_always_on), donc η = 1 et la correction est
neutre. Le réglage existe quand même : il servira si l'échantillonnage est
activé pour tenir la charge.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoupage import Fenetre, charger, decouper       # noqa: E402
from lecture import Releve                             # noqa: E402
from ronds import Rond, _annuaire, ronds_de            # noqa: E402

QUANTILES = (0.50, 0.95, 0.99)

# --------------------------------------------------------- les cinq opérateurs
def fin(valeurs: list[tuple[int, float]]) -> float | None:
    """La dernière valeur de la fenêtre. `valeurs` = liste (instant, valeur)."""
    return max(valeurs, key=lambda x: x[0])[1] if valeurs else None


def ext(valeurs: list[tuple[int, float]], sens: str = "min") -> float | None:
    if not valeurs:
        return None
    return (min if sens == "min" else max)(v for _, v in valeurs)


def inc(valeurs: list[tuple[int, float]]) -> float | None:
    """
    De combien un compteur a monté sur la fenêtre.

    On somme les hausses entre relevés consécutifs. Une baisse signifie que le
    compteur est reparti de zéro (redémarrage) : on ne la compte pas, au lieu de
    produire un accroissement négatif.
    """
    if len(valeurs) < 2:
        return 0.0 if valeurs else None
    ordonne = sorted(valeurs)
    total = 0.0
    for (_, a), (_, b) in zip(ordonne, ordonne[1:]):
        if b >= a:
            total += b - a
        else:
            total += b          # remise à zéro : tout ce qui suit le redémarrage
    return total


def quant(durees: list[float], q: float) -> float | None:
    """La valeur sous laquelle tombe une proportion q des observations."""
    if not durees:
        return None
    v = sorted(durees)
    i = max(0, math.ceil(q * len(v)) - 1)
    return v[i]


def pente(suite: list[float | None], H: int) -> float | None:
    """
    La tendance sur les H dernières fenêtres.

    Seul opérateur qui sorte de la fenêtre : il décrit une dérive lente, qu'une
    fenêtre seule ne peut pas voir.
    """
    y = [v for v in suite[-H:] if v is not None]
    if len(y) < 2:
        return None
    n = len(y)
    mx = (n - 1) / 2
    my = sum(y) / n
    haut = sum((i - mx) * (v - my) for i, v in enumerate(y))
    bas = sum((i - mx) ** 2 for i in range(n))
    return haut / bas if bas else None


def rap(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def ecart(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


# ------------------------------------------------------- regrouper les relevés
def _series(releves: list[Releve]) -> dict[tuple, list[tuple[int, float]]]:
    """
    Un compteur porte plusieurs suites en parallèle — une par jeu d'étiquettes.
    Les mélanger fausserait tout accroissement, on les sépare d'abord.
    """
    par_serie: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for r in releves:
        par_serie[tuple(sorted(r.etiquettes.items()))].append((r.instant_ns, r.valeur))
    return par_serie


def _somme_inc(releves: list[Releve]) -> float | None:
    """Accroissement total, séries additionnées."""
    if not releves:
        return None
    return sum(v for v in (inc(s) for s in _series(releves).values()) if v is not None)


def _somme_fin(releves: list[Releve]) -> float | None:
    if not releves:
        return None
    return sum(v for v in (fin(s) for s in _series(releves).values()) if v is not None)


def _sans_doublon_conteneur(releves: list[Releve]) -> list[Releve]:
    """
    cAdvisor publie deux niveaux pour un même pod : une ligne par conteneur, et
    une ligne d'ensemble sans nom de conteneur. Les additionner compterait tout
    en double. On garde les conteneurs nommés dès qu'il y en a.
    """
    nommes = [r for r in releves if r.etiquettes.get("container")]
    return nommes or releves


# --------------------------------------------------------------- les vecteurs
@dataclass(slots=True)
class Vecteur:
    rond: Rond
    noms: list[str]
    valeurs: list[float | None] = field(default_factory=list)

    def __getitem__(self, i: int) -> float | None:
        return self.valeurs[i]

    @property
    def remplissage(self) -> float:
        return sum(1 for v in self.valeurs if v is not None) / len(self.valeurs)


NOMS_COPIE = [
    "duree_traitement_q50", "duree_traitement_q95", "duree_traitement_q99",
    "debit_traitement",
    "duree_requete_q50", "duree_requete_q95", "duree_requete_q99",
    "taux_erreur",
    "taux_etranglement_cpu", "debit_cpu",
    "memoire_finale", "memoire_pente", "memoire_limite", "quota_cpu",
    "redemarrages",
    "paquets_recus_perdus", "paquets_emis_perdus", "erreurs_reception",
    "octets_recus",
]
NOMS_FILE = ["niveau", "niveau_pente", "debit_publie", "debit_consomme",
             "ecart_debits", "consommateurs"]
NOMS_MACHINE = ["attente_cpu", "attente_memoire", "attente_io",
                "memoire_dispo_min", "occupation_cpu"]


def _rel_par_pod(fenetre: Fenetre, annuaire: dict) -> dict[str, list[Releve]]:
    """Range les relevés de conteneur sous l'identifiant du pod."""
    uid_par_nom = {v["pod"]: uid for uid, v in annuaire.items() if v["pod"]}
    par_pod: dict[str, list[Releve]] = defaultdict(list)
    for r in fenetre.releves:
        nom = r.etiquettes.get("pod")
        uid = uid_par_nom.get(nom) if nom else None
        if uid:
            par_pod[uid].append(r)
    return par_pod


def vecteur_copie(rond: Rond, fenetre: Fenetre, rel: list[Releve],
                  W: float, eta: float) -> Vecteur:
    notes = [n for n in fenetre.notes if n.pod_uid == rond.cle]
    traitements = [n for n in notes if n.genre == 5]        # CONSOMMATEUR
    serveur = [n for n in notes if n.genre == 2]            # SERVEUR
    http = [n for n in notes if "http.response.status_code" in n.attributs]
    erreurs = [n for n in http if n.attributs.get("error.type")]

    def compteur(nom: str) -> list[Releve]:
        return _sans_doublon_conteneur([r for r in rel if r.nom == nom])

    def taux(nom: str) -> float | None:
        return rap(_somme_inc(compteur(nom)), W)

    d_trait = [n.duree_ns / 1e6 for n in traitements]
    d_serv = [n.duree_ns / 1e6 for n in serveur]

    v = [quant(d_trait, q) for q in QUANTILES]
    v.append(rap(len(traitements) / eta, W) if notes or rel else None)
    v += [quant(d_serv, q) for q in QUANTILES]
    v.append(rap(len(erreurs), len(http)) if http else None)

    v.append(rap(_somme_inc(compteur("container_cpu_cfs_throttled_periods_total")),
                 _somme_inc(compteur("container_cpu_cfs_periods_total"))))
    v.append(taux("container_cpu_usage_seconds_total"))
    v.append(_somme_fin(compteur("container_memory_working_set_bytes")))
    v.append(None)                                     # pente : seconde passe
    v.append(_somme_fin(compteur("container_spec_memory_limit_bytes")))
    v.append(_somme_fin(compteur("container_spec_cpu_quota")))
    v.append(_somme_inc([r for r in rel
                         if r.nom == "kube_pod_container_status_restarts_total"]))
    v.append(taux("container_network_receive_packets_dropped_total"))
    v.append(taux("container_network_transmit_packets_dropped_total"))
    v.append(taux("container_network_receive_errors_total"))
    v.append(taux("container_network_receive_bytes_total"))
    return Vecteur(rond, NOMS_COPIE, v)


def vecteur_file(rond: Rond, fenetre: Fenetre, W: float, eta: float) -> Vecteur:
    nom_file = rond.nom
    rel = [r for r in fenetre.releves if r.file == nom_file]

    def niveau(nom: str) -> float | None:
        return fin([(r.instant_ns, r.valeur) for r in rel if r.nom == nom])

    depots = [n for n in fenetre.depots if n.nom_file == nom_file]
    retraits = [n for n in fenetre.retraits if n.nom_file == nom_file]
    d_pub = rap(len(depots) / eta, W)
    d_cons = rap(len(retraits) / eta, W)

    return Vecteur(rond, NOMS_FILE, [
        niveau("rabbitmq_queue_messages_ready"),
        None,                                          # pente : seconde passe
        d_pub, d_cons, ecart(d_pub, d_cons),
        niveau("rabbitmq_queue_consumers"),
    ])


def vecteur_machine(rond: Rond, fenetre: Fenetre, W: float) -> Vecteur:
    nom = rond.nom
    rel = [r for r in fenetre.releves if r.etiquettes.get("node") == nom]

    def taux(m: str) -> float | None:
        return rap(_somme_inc([r for r in rel if r.nom == m]), W)

    dispo = [(r.instant_ns, r.valeur) for r in rel
             if r.nom == "node_memory_MemAvailable_bytes"]

    cpu = [r for r in rel if r.nom == "node_cpu_seconds_total"]
    coeurs = len({r.etiquettes.get("cpu") for r in cpu if r.etiquettes.get("cpu")})
    occupe = _somme_inc([r for r in cpu if r.etiquettes.get("mode") != "idle"])
    occupation = rap(occupe, W * coeurs) if coeurs else None

    return Vecteur(rond, NOMS_MACHINE, [
        taux("node_pressure_cpu_waiting_seconds_total"),
        taux("node_pressure_memory_waiting_seconds_total"),
        taux("node_pressure_io_waiting_seconds_total"),
        ext(dispo, "min"),
        occupation,
    ])


# ----------------------------------------------------------------- assemblage
def calculer(fenetres: list[Fenetre], espace: str | None, W: float,
             H: int, eta: float) -> list[dict[str, Vecteur]]:
    """Un dictionnaire de vecteurs par fenêtre, puis les pentes en seconde passe."""
    suite: list[dict[str, Vecteur]] = []
    for f in fenetres:
        annuaire = _annuaire(f)
        rel_pod = _rel_par_pod(f, annuaire)
        vecteurs: dict[str, Vecteur] = {}
        for cle, rond in ronds_de(f, espace).items():
            if rond.genre == "copie":
                vecteurs[cle] = vecteur_copie(rond, f, rel_pod.get(cle, []), W, eta)
            elif rond.genre == "file":
                vecteurs[cle] = vecteur_file(rond, f, W, eta)
            else:
                vecteurs[cle] = vecteur_machine(rond, f, W)
        suite.append(vecteurs)

    # seconde passe : la pente regarde les H fenêtres précédentes
    for k in range(len(suite)):
        for cle, vec in suite[k].items():
            if vec.rond.genre == "copie":
                i_val, i_pente = 10, 11
            elif vec.rond.genre == "file":
                i_val, i_pente = 0, 1
            else:
                continue
            histoire = [suite[j][cle].valeurs[i_val] if cle in suite[j] else None
                        for j in range(max(0, k - H + 1), k + 1)]
            vec.valeurs[i_pente] = pente(histoire, H)
    return suite


# ------------------------------------------------------------------ affichage
def _n(v: float | None) -> str:
    if v is None:
        return "     —"
    if v == 0:
        return "     0"
    if abs(v) >= 1e6 or abs(v) < 1e-3:
        return f"{v:>6.1e}"
    return f"{v:>6.3g}"


def montrer(fenetres: list[Fenetre], suite: list[dict[str, Vecteur]],
            W: float, H: int, eta: float) -> None:
    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t("RÉGLAGES")
    print(f"  fenêtre W = {W:g} s · horizon de pente H = {H} fenêtres · "
          f"échantillonnage η = {eta:g}")
    print(f"  quantiles : {', '.join(str(q) for q in QUANTILES)}")

    t("REMPLISSAGE — combien de composantes sont calculées, et non vides")
    print(f"  {'fenêtre':>8} │ {'copies':>16} │ {'files':>14} │ {'machines':>14}")
    print("  " + "─" * 8 + "┼" + "─" * 18 + "┼" + "─" * 16 + "┼" + "─" * 16)
    for f, vecs in zip(fenetres, suite):
        lig = f"  {f.horodatage:>8} │"
        for genre, d in (("copie", 19), ("file", 6), ("machine", 5)):
            lot = [v for v in vecs.values() if v.rond.genre == genre]
            if not lot:
                lig += f" {'—':>16} │"
                continue
            moy = sum(v.remplissage for v in lot) / len(lot)
            lig += f" {len(lot):3d} ronds {100*moy:4.0f}% │"
        print(lig)

    derniere = -1
    f, vecs = fenetres[derniere], suite[derniere]

    t(f"LES FILES, fenêtre {f.horodatage}")
    for v in [x for x in vecs.values() if x.rond.genre == "file"]:
        print(f"\n  file « {v.rond.nom} »")
        for nom, val in zip(v.noms, v.valeurs):
            print(f"    {nom:<16} {_n(val)}")

    t(f"LES MACHINES, fenêtre {f.horodatage}")
    lot = sorted((x for x in vecs.values() if x.rond.genre == "machine"),
                 key=lambda v: v.rond.nom)
    print(f"  {'machine':<12}" + "".join(f"{n:>20}" for n in NOMS_MACHINE))
    for v in lot:
        print(f"  {v.rond.nom:<12}" + "".join(f"{_n(x):>20}" for x in v.valeurs))

    t(f"TROIS COPIES, fenêtre {f.horodatage}")
    lot = sorted((x for x in vecs.values() if x.rond.genre == "copie"),
                 key=lambda v: -v.remplissage)[:3]
    for v in lot:
        print(f"\n  {v.rond.nom}   ({100*v.remplissage:.0f} % rempli)")
        for i in range(0, 19, 1):
            print(f"    {i+1:2d}. {v.noms[i]:<24} {_n(v.valeurs[i])}")

    t("COMPOSANTES JAMAIS CALCULÉES sur toute la plage")
    manquant = []
    for genre, noms in (("copie", NOMS_COPIE), ("file", NOMS_FILE),
                        ("machine", NOMS_MACHINE)):
        for i, nom in enumerate(noms):
            vu = any(v.valeurs[i] is not None
                     for vecs in suite for v in vecs.values()
                     if v.rond.genre == genre)
            if not vu:
                manquant.append(f"{genre} {i+1}. {nom}")
    if manquant:
        for m in manquant:
            print(f"    {m}")
    else:
        print("    aucune — toutes les composantes ont été produites au moins une fois.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier")
    p.add_argument("--largeur", type=float, default=60)
    p.add_argument("--pas", type=float, default=None)
    p.add_argument("--espace", default=None)
    p.add_argument("--horizon", type=int, default=3,
                   help="H : nombre de fenêtres regardées par la pente (défaut 3)")
    p.add_argument("--echantillon", type=float, default=1.0,
                   help="η : proportion de traces conservées (défaut 1 = toutes)")
    args = p.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        sys.exit(f"dossier introuvable : {dossier}")

    notes, releves = charger(dossier)
    print(f"chargé : {len(notes)} notes · {len(releves)} relevés")
    pas = args.pas if args.pas is not None else args.largeur
    fenetres, rapport = decouper(notes, releves, args.largeur, pas)
    print(f"fenêtres retenues : {rapport['gardees']}")
    if not fenetres:
        return 1

    suite = calculer(fenetres, args.espace, args.largeur, args.horizon,
                     args.echantillon)
    montrer(fenetres, suite, args.largeur, args.horizon, args.echantillon)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
