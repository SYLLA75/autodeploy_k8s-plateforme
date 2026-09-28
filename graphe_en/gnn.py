"""
Le GNN : reconstruire le normal de chaque nœud par ses voisins, puis nommer la cause.

    ./.venv/bin/python gnn.py --verifier [--version v1|v2|v3]
    ./.venv/bin/python gnn.py --validation [--graines n] [--epoques e] [--sans-temoins]
                              [--variantes a,b|toutes] [--repetition] [--version v1|v2|v3]
    ./.venv/bin/python gnn.py --repetition [mêmes options]
    ./.venv/bin/python gnn.py --test [mêmes options]       refusé sans l'étiquette gnn-fige

Phase E. Écrit d'après notes/GNN_SPEC.md (§1 à §6, §8 et les amendements du §10),
jugé par juge.py avec les règles de fautifs.py, comme les témoins. Le banc de
pannes fabriquées (§7) est dans gnn_banc.py, qui importe ce fichier.

LES DONNÉES
  Les fenêtres des deux séries seules (fautifs.SERIES), lues par le juge. Le GNN
  reçoit toutes les fenêtres et ne garde que jeu == « apprentissage » hors des
  écartées : l'étape 1 n'apprend QUE sur les normales, l'étape 2 sur les pannes.
  La conversion est celle du graphe figé (export_pyg.convert, absents en masque,
  sans flèches inverses), avec scaler.json contrôlé par son sha256 contre
  graphe_fige.json de l'étiquette ; jamais recalé. Puis asinh (en entrée comme en
  cible) : en panne, certaines colonnes dépassent de 10² à 10³ fois l'écart-type de
  saine-09 ; asinh est monotone et sans plafond, donc ne crée pas d'égalités.
  memory_limit et cpu_quota sont du CONTEXTE : toujours en entrée, jamais masqués,
  jamais reconstruits, jamais notés. Ils distinguent les pods MySQL : c'est une
  quasi-identité, à dire au rapport. AUCUN nom (names, keys, hosts) n'entre dans
  le modèle : les noms ne servent qu'à écrire les clés de la réponse.

L'ÉTAPE 1 : le Reconstructeur, un R-GCN hétérogène (H = 32, 2 couches, ReLU,
  LayerNorm, moyenne des messages), un encodeur par sorte de nœud, les 5 relations
  du gel et leurs inverses ajoutées DANS le modèle, un canal d'arête φ_r sur chaque
  relation chiffrée (calls, queries, publishes, consumes ; partagé entre r et
  rev_r ; executes_on n'a pas de colonnes). La tâche : masquer un nœud ET toutes
  ses flèches entrantes, puis les reconstruire (Huber δ = 1 sur les valeurs, plus
  0,5 × BCE sur la présence de chaque colonne d'état). Adam 3e-3, wd 1e-4, 150
  époques, lots de 16 graphes, p = 0,15. Déterministe : graine × 1009 + rang (0 le
  modèle final, 1 à n les plis dans l'ordre trié des campagnes), un fil, algorithmes
  déterministes. Chaque campagne mise de côté à son tour (un pli) : ses normales
  sont notées par le modèle appris sans elle.

LA NOTE D'UNE FENÊTRE : un passage par nœud, en lot (N copies de la fenêtre, la
  copie i masque le nœud i et ses flèches entrantes). Résidus signés, puis écarts
  z = (résidu − médiane) / échelle robuste, médiane et échelle par (sorte,
  colonne) et par (relation, colonne), calculées sur les résidus tenus hors pli.
  Erreur d'un nœud : max |z| (absents compris) ; d'une flèche : max |z|.

LE POST-TRAITEMENT, écrit à la main (principe P du journal), en fonctions pures :
  B (le bout des flèches anormales, ε > κ_r) : B1 cible-max, B2 source-max,
    B3 deux-max, B4 cible-somme, B5 part ; t_v = max(r_v, e_v) ; ŝ_v = t_v / τ_k ;
  H (la remontée pods → machine, par le champ hosts) : H0 aucune, H1 somme à
    seuil (au moins deux pods anormaux), H2 concentrée ;
  V (l'explication par les dépendances) : V0 aucune, V1 héritage.
  CHOIX (CHOIX_VERSIONS, un par version) est fixé par le banc (gnn_banc.py).

LES TROIS VERSIONS DE L'ÉTAPE 1 (écart E-1, §11 de la spécification, fixées avant
  tout calcul ; VERSION, v1 par défaut) :
    v1 : ce qui précède (masque, asinh, calage par sorte) ;
    v2 : masque, SANS asinh, calage des résidus PAR IDENTITÉ (temoin_noeud.identite,
         médiane et échelle de temoin_noeud.echelles par (identité, colonne) sur les
         résidus tenus hors pli, plancher par sorte ; flèches : (relation, identité
         source, identité cible), plancher par relation) ; une identité sans normal
         retombe sur le calage par sorte ;
    v3 : v2, mais un auto-encodeur SANS masque : goulot de dimension 8 après la
         dernière couche, les décodeurs ne lisent que ce plongement ; une passe par
         fenêtre, perte sur tous les nœuds et toutes les flèches.
  En aucune version l'identité n'entre dans le modèle : elle ne cale que la sortie.
  La version entre dans la clé du cache et le nom des sorties, et s'imprime à côté
  de l'empreinte (qui reste le sha256 du §8, sans la version).

L'ALARME : le plus haut score de nœud de la fenêtre, celui qui sert au classement.
  Seuil propre : 95e centile des scores des normales tenues hors pli ; face à une
  autre méthode, son budget (BUDGETS, sur 249 minutes, mis à l'échelle si N ≠ 249).

L'ÉTAPE 2 : les profils d'écart signés du modèle final (sans identité), les
  prototypes du témoin 2 (temoin_noeud.Prototypes, importés sans modification),
  le rejet calé en mettant chaque injection de côté (95e centile des distances des
  fenêtres bien classées). « avec exemples » : la cause du prototype le plus proche
  quand l'alarme sonne, « inconnue » au-delà du rejet ; « sans exemples » :
  « inconnue » si l'alarme sonne. Le classement et l'alarme viennent toujours de
  l'étape 1 : les deux réglages ne diffèrent que par la cause.

LE SCELLÉ : juge.lire n'est appelé qu'avec fautifs.SERIES ; --validation et
  --repetition ne lisent que juge.validation (jamais « hors ») ; --test est refusé
  tant que l'étiquette gnn-fige n'existe pas.

Options :
  --verifier             les contrôles T1 à T4, T6, T7 de la spécification, T12
                         (le calage de la sortie) et T13 (l'empreinte), sur 20 fenêtres de validation et
                         2 époques, pour la version donnée
  --validation           le tableau de bord sur juge.validation ; écrit
                         <campagnes>/gnn-validation.txt
  --repetition           la répétition « panne jamais vue », dans la validation
  --test                 le vrai test : refusé sans l'étiquette gnn-fige
  --graines <n>          graines 0 à n−1 (défaut 5)
  --epoques <e>          époques d'apprentissage (défaut 150)
  --sans-temoins         ne recalcule pas les témoins (seulement « a priori »)
  --variantes <liste>    variantes en plus du complet, séparées par des virgules,
                         ou « toutes »
  --version <v>          v1 (défaut), v2 ou v3 ; les sorties d'une version autre
                         que v1 portent son nom (gnn-validation-v2.txt)
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --help                 ce texte

Code de sortie 0 ; 1 si une campagne est refusée, un contrôle échoue ou le scellé
est fermé ; 2 sur un mauvais argument.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import math
import multiprocessing
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

import export_pyg
import fautifs as fautifs_module
import gel
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
ETIQUETTE_SCELLE = "gnn-fige"
SORTES = ("instance", "queue", "host")
# (source, cible) de chaque relation du gel, dans l'ordre d'edges.RELATIONS.
RELATIONS = {r: (s, d) for r, (s, d, _) in export_pyg.RELATIONS.items()}
CHIFFREES = tuple(r for r, (_, _, c) in export_pyg.RELATIONS.items() if c)
APPELS = ("calls", "queries")
CONTEXTE = {"instance": ("memory_limit", "cpu_quota"), "queue": (), "host": ()}
ABSENTS = tn.ABSENTS

# L'étape 1 (spécification §2.1-2.2), valeurs figées, sans recherche.
H = 32
COUCHES = 2
P_MASQUE = 0.15
HUBER = 1.0
POIDS_PRESENCE = 0.5
LR = 3e-3
WD = 1e-4
EPOQUES = 150
LOT = 16
PROCESSUS = 6            # au plus 6 entraînements en parallèle sur vms0
CENTILE = 95

# Les budgets de fausses alertes des témoins, sur 249 minutes normales mises de
# côté (journal 1165-1169) ; les versions « machine » gardent celui de la règle.
BUDGETS = {"tableau": 13, "score par nœud, sans": 13, "score par nœud, avec": 25, "règle": 21}
MINUTES_BUDGET = 249

# La grille du post-traitement (§3.5), dans l'ordre de simplicité.
BOUTS = ("B1", "B2", "B3", "B4", "B5")
REMONTEES = ("H0", "H1", "H2")
EXPLICATIONS = ("V0", "V1")
# Le résultat du banc de gnn_banc.py (§3.5), codé en dur : chaque version a le
# sien, fixé par SON banc (§11), validation seule, graines 0 à 4, 150 époques.
# CHOIX est celui de la version 1. CHOIX_SOURCES dit d'où vient chacun (None :
# PROVISOIRE, la valeur écrite par défaut B1/H0/V0).
CHOIX = {"bout": "B5", "remontee": "H1", "explication": "V1"}
CHOIX_VERSIONS = {"v1": CHOIX,
                  "v2": {"bout": "B2", "remontee": "H0", "explication": "V1"},
                  "v3": {"bout": "B2", "remontee": "H0", "explication": "V1"}}
CHOIX_SOURCES = {v: f"fixé par campagnes/{'gnn-banc-validation.txt' if v == 'v1' else f'gnn-banc-validation-{v}.txt'}"
                    f", 5 graines, 150 époques" for v in ("v1", "v2", "v3")}

# Les trois versions de l'étape 1 (écart E-1, §11 de la spécification, fixées avant
# tout calcul) : masque (reconstruire un nœud masqué par ses voisins) ou
# auto-encodeur sans masque à goulot ; asinh sur les nombres ou non ; calage des
# résidus par sorte ou par identité (temoin_noeud.identite). L'identité ne sert
# qu'à caler la SORTIE, jamais en entrée du modèle, en aucune version.
VERSIONS = {"v1": {"masque": True, "asinh": True, "identite": False},
            "v2": {"masque": True, "asinh": False, "identite": True},
            "v3": {"masque": False, "asinh": False, "identite": True}}
VERSION = "v1"
GOULOT = 8               # v3 : la dimension du plongement final, lu seul par les décodeurs

# Les variantes du retrait des flèches (§6) : relations du passage de messages,
# canal d'arête, un seul W lié, flèches notées, relations lues par V (H2 lit toujours
# calls et queries de la fenêtre, comme le complet).
TOUTES = frozenset(RELATIONS)


def _variante(relations, canal=True, lie=False, notees=None, deps=None) -> dict:
    relations = frozenset(relations)
    return {"relations": relations, "canal": canal, "lie": lie,
            "notees": frozenset(CHIFFREES) & relations if notees is None else frozenset(notees),
            "deps": relations if deps is None else frozenset(deps)}


VARIANTES = {
    "complet": _variante(TOUTES),
    "sans aucune arête": _variante((), canal=False, notees=(), deps=()),
    "sans queries": _variante(TOUTES - {"queries"}),
    "sans calls": _variante(TOUTES - {"calls"}),
    "sans publishes": _variante(TOUTES - {"publishes"}),
    "sans consumes": _variante(TOUTES - {"consumes"}),
    "sans executes_on": _variante(TOUTES - {"executes_on"}, deps=TOUTES),
    "sans canal d'arête": _variante(TOUTES, canal=False, notees=()),
    "un seul type sans canal": _variante(TOUTES, canal=False, lie=True, notees=()),
}


# ------------------------------------------------------------------------------
# L'échelle figée et la conversion
# ------------------------------------------------------------------------------
_ECHELLE: dict | None = None
_GRAPHES: dict[tuple, tuple[dict, "Graphe"]] = {}


def charger_echelle(fige: dict) -> dict:
    """scaler.json, refusé si son sha256 n'est pas celui du graphe figé. Jamais recalé."""
    global _ECHELLE
    brut = (HERE / "scaler.json").read_bytes()
    empreinte = hashlib.sha256(brut).hexdigest()
    if empreinte != fige["echelle"]["sha256"]:
        raise juge.Refus(f"scaler.json : sha256 {empreinte[:12]}…, le gel attend "
                         f"{fige['echelle']['sha256'][:12]}… : ce n'est pas l'échelle figée")
    _ECHELLE = json.loads(brut)["scaler"]
    return _ECHELLE


def _echelle() -> dict:
    if _ECHELLE is None:
        fige, ecarts, _ = gel.reference()
        if ecarts:
            raise juge.Refus(ecarts[0])
        charger_echelle(fige)
    return _ECHELLE


@dataclass
class Graphe:
    """Une fenêtre en tenseurs, SANS aucun nom : ce que voit le modèle."""
    x: dict          # sorte -> [n, d_état] asinh, un absent vaut 0
    p: dict          # sorte -> [n, d_état] présence (0 ou 1)
    ctx: dict        # sorte -> [n, d_ctx] asinh (memory_limit, cpu_quota)
    ei: dict         # relation -> [2, E] indices dans les lignes de chaque sorte
    ea: dict         # relation -> [E, d_r] asinh
    n: dict          # sorte -> nombre de nœuds


def convertir(donnees: dict, asinh: bool = True) -> Graphe:
    """La conversion du graphe figé (export_pyg), puis asinh (version 1 ; pas en
    versions 2 et 3), contexte à part. Gardée en mémoire par objet : `donnees` est
    partagé par les copies de juge.validation."""
    cle = (id(donnees), asinh)
    if cle in _GRAPHES and _GRAPHES[cle][0] is donnees:
        return _GRAPHES[cle][1]
    h = export_pyg.convert([donnees], _echelle(), "mask", False, "cpu")[0]
    f = torch.asinh if asinh else torch.clone
    x, p, ctx, n = {}, {}, {}, {}
    for k in SORTES:
        cols = list(h[k].columns)
        etat = [i for i, c in enumerate(cols) if c not in CONTEXTE[k]]
        contexte = [i for i, c in enumerate(cols) if c in CONTEXTE[k]]
        x[k] = f(h[k].x[:, etat]).contiguous()
        p[k] = h[k].present[:, etat].float().contiguous()
        ctx[k] = f(h[k].x[:, contexte]).contiguous()
        n[k] = int(h[k].num_nodes)
    ei, ea = {}, {}
    for r, (s, d) in RELATIONS.items():
        ei[r] = h[s, r, d].edge_index.contiguous()
        ea[r] = f(h[s, r, d].edge_attr).contiguous()
    g = Graphe(x, p, ctx, ei, ea, n)
    _GRAPHES[cle] = (donnees, g)
    return g


def dimensions(fige: dict) -> dict:
    """Les largeurs d'entrée, lues dans le graphe figé."""
    return {"etat": {k: sum(1 for c in fige["noeuds"][k] if c not in CONTEXTE[k]) for k in SORTES},
            "ctx": {k: sum(1 for c in fige["noeuds"][k] if c in CONTEXTE[k]) for k in SORTES},
            "rel": {r: len(fige["relations"][r]["colonnes"]) for r in RELATIONS}}


def assembler(graphes: list[Graphe]) -> Graphe:
    """Un lot : les fenêtres mises bout à bout, indices des flèches décalés."""
    decal = dict.fromkeys(SORTES, 0)
    ei = {r: [] for r in RELATIONS}
    for g in graphes:
        for r, (s, d) in RELATIONS.items():
            ei[r].append(g.ei[r] + torch.tensor([[decal[s]], [decal[d]]]))
        for k in SORTES:
            decal[k] += g.n[k]
    return Graphe({k: torch.cat([g.x[k] for g in graphes]) for k in SORTES},
                  {k: torch.cat([g.p[k] for g in graphes]) for k in SORTES},
                  {k: torch.cat([g.ctx[k] for g in graphes]) for k in SORTES},
                  {r: torch.cat(ei[r], 1) for r in RELATIONS},
                  {r: torch.cat([g.ea[r] for g in graphes]) for r in RELATIONS},
                  decal)


def _copies(g: Graphe, n: int) -> Graphe:
    """N copies de la même fenêtre, en un lot."""
    ei = {}
    for r, (s, d) in RELATIONS.items():
        e = g.ei[r].shape[1]
        o = torch.arange(n).repeat_interleave(e)
        ei[r] = g.ei[r].repeat(1, n) + torch.stack([o * g.n[s], o * g.n[d]])
    return Graphe({k: g.x[k].repeat(n, 1) for k in SORTES}, {k: g.p[k].repeat(n, 1) for k in SORTES},
                  {k: g.ctx[k].repeat(n, 1) for k in SORTES}, ei,
                  {r: g.ea[r].repeat(n, 1) for r in RELATIONS}, {k: g.n[k] * n for k in SORTES})


# ------------------------------------------------------------------------------
# Le modèle
# ------------------------------------------------------------------------------
def _moyenne(msg: torch.Tensor, idx: torch.Tensor, n: int) -> torch.Tensor:
    """La moyenne des messages reçus par chaque nœud (0 sans message) ; index_add, déterministe."""
    somme = msg.new_zeros(n, msg.shape[1]).index_add_(0, idx, msg)
    compte = msg.new_zeros(n).index_add_(0, idx, torch.ones(idx.shape[0], dtype=msg.dtype))
    return somme / compte.clamp(min=1.0).unsqueeze(1)


class Reconstructeur(nn.Module):
    """
    R-GCN hétérogène : un encodeur par sorte, des poids par relation (directe ou
    inverse), partagés par tous les nœuds d'une sorte et toutes les flèches d'une
    relation ; un canal d'arête φ_r par relation chiffrée, partagé entre r et rev_r.
    Entrée d'un nœud : [asinh(état)·(1−m), présence·(1−m), asinh(contexte), m].
    Entrée d'une flèche : [asinh(e)·(1−m_e), m_e], m_e = sa cible est masquée.
    Version 2 : les mêmes, sans asinh. Version 3 (auto-encodeur, §11) : pas de
    masque ni de drapeau m ([état, présence, contexte] ; [e]), et un goulot de
    dimension GOULOT par sorte après la dernière couche : les décodeurs ne lisent
    que ce plongement final.
    """

    def __init__(self, dims: dict, variante: str = "complet", version: str = VERSION):
        super().__init__()
        cfg = VARIANTES[variante]
        self.dims, self.lie = dims, cfg["lie"]
        self.version, self.masque = version, VERSIONS[version]["masque"]
        drapeau = 1 if self.masque else 0
        self.canal = [r for r in CHIFFREES if cfg["canal"] and r in cfg["relations"] and dims["rel"][r]]
        self.notees = [r for r in CHIFFREES if r in cfg["notees"] and dims["rel"][r]]
        self.passages = []
        for r, (s, d) in RELATIONS.items():
            if r in cfg["relations"]:
                self.passages += [(r, r, s, d, True), (f"rev_{r}", r, d, s, False)]
        de, dc = dims["etat"], dims["ctx"]
        self.enc = nn.ModuleDict({k: nn.Linear(2 * de[k] + dc[k] + drapeau, H) for k in SORTES})
        self.phi = nn.ModuleDict({r: nn.Sequential(nn.Linear(dims["rel"][r] + drapeau, H), nn.ReLU(), nn.Linear(H, H))
                                  for r in self.canal})
        self.soi = nn.ModuleList([nn.ModuleDict({k: nn.Linear(H, H) for k in SORTES}) for _ in range(COUCHES)])
        if self.lie:
            self.W = nn.ModuleList([nn.Linear(H, H) for _ in range(COUCHES)])
        else:
            self.W = nn.ModuleList([nn.ModuleDict({nom: nn.Linear(2 * H if r in self.canal else H, H)
                                                   for nom, r, _, _, _ in self.passages}) for _ in range(COUCHES)])
        self.norme = nn.ModuleList([nn.ModuleDict({k: nn.LayerNorm(H) for k in SORTES}) for _ in range(COUCHES)])
        # v3 : le goulot, créé après les couches (v1 et v2 gardent l'ordre de création, donc leurs poids initiaux).
        self.goulot = None if self.masque else nn.ModuleDict({k: nn.Linear(H, GOULOT) for k in SORTES})
        lu = H if self.masque else GOULOT                  # ce que lisent les décodeurs
        self.dec = nn.ModuleDict({k: nn.Sequential(nn.Linear(lu, H), nn.ReLU(), nn.Linear(H, 2 * de[k]))
                                  for k in SORTES})
        self.dec_e = nn.ModuleDict({r: nn.Sequential(nn.Linear(2 * lu, H), nn.ReLU(), nn.Linear(H, dims["rel"][r]))
                                    for r in self.notees})

    def forward(self, g: Graphe, m: dict | None):
        """m : sorte -> masque des nœuds (versions à masque) ; ignoré en version 3."""
        h = {}
        if self.masque:
            for k in SORTES:
                mk = m[k].float().unsqueeze(1)
                h[k] = self.enc[k](torch.cat([g.x[k] * (1 - mk), g.p[k] * (1 - mk), g.ctx[k], mk], 1))
            me = {r: m[RELATIONS[r][1]][g.ei[r][1]].float().unsqueeze(1) for r in RELATIONS}
            phi = {r: self.phi[r](torch.cat([g.ea[r] * (1 - me[r]), me[r]], 1)) for r in self.canal}
        else:
            h = {k: self.enc[k](torch.cat([g.x[k], g.p[k], g.ctx[k]], 1)) for k in SORTES}
            phi = {r: self.phi[r](g.ea[r]) for r in self.canal}
        for couche in range(COUCHES):
            a = {k: self.soi[couche][k](h[k]) for k in SORTES}
            for nom, r, s, d, directe in self.passages:
                i_s, i_d = (g.ei[r][0], g.ei[r][1]) if directe else (g.ei[r][1], g.ei[r][0])
                entree = h[s][i_s]
                if r in self.canal:
                    entree = torch.cat([entree, phi[r]], 1)
                w = self.W[couche] if self.lie else self.W[couche][nom]
                a[d] = a[d] + _moyenne(w(entree), i_d, g.n[d])
            h = {k: self.norme[couche][k](h[k] + F.relu(a[k])) for k in SORTES}
        if self.goulot is not None:
            h = {k: self.goulot[k](h[k]) for k in SORTES}
        valeurs, logits = {}, {}
        for k in SORTES:
            v, lo = self.dec[k](h[k]).split(self.dims["etat"][k], 1)
            valeurs[k], logits[k] = v, lo
        fleches = {}
        for r in self.notees:
            s, d = RELATIONS[r]
            fleches[r] = self.dec_e[r](torch.cat([h[s][g.ei[r][0]], h[d][g.ei[r][1]]], 1))
        return valeurs, logits, fleches


def perte_masquee(modele: Reconstructeur, g: Graphe, m: dict):
    """Huber sur les valeurs présentes et 0,5 × BCE sur la présence des nœuds masqués ;
    Huber sur les flèches masquées ; moyenne par sorte, moyenne par relation. En
    version 3 (sans masque), m vaut 1 partout : la perte porte sur tous les nœuds et
    toutes les flèches, et le modèle ne voit pas m."""
    valeurs, logits, fleches = modele(g, m)
    noeuds = []
    for k in SORTES:
        lignes = m[k]
        if not bool(lignes.any()) or valeurs[k].shape[1] == 0:
            continue
        pr, x = g.p[k][lignes], g.x[k][lignes]
        v, lo = valeurs[k][lignes], logits[k][lignes]
        la = pr > 0.5
        hub = F.huber_loss(v[la], x[la], delta=HUBER) if bool(la.any()) else v.sum() * 0.0
        noeuds.append(hub + POIDS_PRESENCE * F.binary_cross_entropy_with_logits(lo, pr))
    aretes = []
    for r in modele.notees:
        me = m[RELATIONS[r][1]][g.ei[r][1]]
        if bool(me.any()):
            aretes.append(F.huber_loss(fleches[r][me], g.ea[r][me], delta=HUBER))
    if not noeuds and not aretes:
        return None
    perte = torch.stack(noeuds).mean() if noeuds else 0.0
    return perte + (torch.stack(aretes).mean() if aretes else 0.0)


def _un_fil() -> None:
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def entrainer(graphes: list[Graphe], dims: dict, variante: str, graine: int, rang_pli: int,
              epoques: int = EPOQUES, version: str = VERSION) -> tuple[dict, dict]:
    """(state_dict, informations). Déterministe : graine × 1009 + rang_pli, un fil.
    Les graphes sont convertis pour la version (asinh ou non)."""
    _un_fil()
    debut = time.perf_counter()
    germe = graine * 1009 + rang_pli
    torch.manual_seed(germe)
    gen = torch.Generator().manual_seed(germe)
    modele = Reconstructeur(dims, variante, version)
    opt = torch.optim.Adam(modele.parameters(), lr=LR, weight_decay=WD)
    pertes = []
    for _ in range(epoques):
        ordre = torch.randperm(len(graphes), generator=gen).tolist()
        total, pas = 0.0, 0
        for i in range(0, len(ordre), LOT):
            g = assembler([graphes[j] for j in ordre[i:i + LOT]])
            if modele.masque:
                m = {k: torch.rand(g.n[k], generator=gen) < P_MASQUE for k in SORTES}
            else:
                m = {k: torch.ones(g.n[k], dtype=torch.bool) for k in SORTES}
            perte = perte_masquee(modele, g, m)
            if perte is None:
                continue
            opt.zero_grad()
            perte.backward()
            opt.step()
            total, pas = total + float(perte), pas + 1
        pertes.append(total / max(pas, 1))
    etat = {k: v.detach().clone() for k, v in modele.state_dict().items()}
    return etat, {"duree": time.perf_counter() - debut, "pertes": pertes, "fenetres": len(graphes),
                  "parametres": sum(p.numel() for p in modele.parameters())}


# Les entraînements en parallèle : les fenêtres converties sont envoyées une fois
# à chaque processus (initializer), chaque tâche ne porte que des identifiants.
_TRAVAIL: dict = {}


def _en_octets(obj) -> bytes:
    """Les tenseurs passent entre processus en octets : le partage de descripteurs de
    torch.multiprocessing casse sur de nombreux tenseurs (« received 0 items of ancdata »)."""
    tampon = io.BytesIO()
    torch.save(obj, tampon)
    return tampon.getvalue()


def _des_octets(brut: bytes):
    return torch.load(io.BytesIO(brut), weights_only=False)


def _init_processus(graphes: bytes) -> None:
    global _TRAVAIL
    _un_fil()
    _TRAVAIL = _des_octets(graphes)


def _tache(t: tuple) -> bytes:
    ids, dims, variante, graine, rang_pli, epoques, version = t
    return _en_octets(entrainer([_TRAVAIL[i] for i in ids], dims, variante, graine, rang_pli, epoques, version))


def entrainer_tous(taches: list[tuple], graphes: dict) -> list[tuple[dict, dict]]:
    """Chaque tâche (ids, dims, variante, graine, rang, époques, version), sur au plus PROCESSUS
    processus (contexte spawn, un fil chacun), dans l'ordre des tâches."""
    if not taches:
        return []
    with ProcessPoolExecutor(max_workers=min(PROCESSUS, len(taches)),
                             mp_context=multiprocessing.get_context("spawn"),
                             initializer=_init_processus, initargs=(_en_octets(graphes),)) as ex:
        return [_des_octets(b) for b in ex.map(_tache, taches)]


def charger(etat: dict, dims: dict, variante: str, version: str = VERSION) -> Reconstructeur:
    modele = Reconstructeur(dims, variante, version)
    modele.load_state_dict(etat)
    return modele.eval()


# ------------------------------------------------------------------------------
# La note d'une fenêtre : résidus, écarts, post-traitement
# ------------------------------------------------------------------------------
@dataclass
class Sortie:
    """Les résidus d'une fenêtre, un passage par nœud masqué. Les noms et hosts ne
    servent qu'au post-traitement (H, V) et aux clés de la réponse."""
    res_n: dict                    # sorte -> [n, d_état + 1] : résidus signés, NaN si absent ; absents
    res_e: dict                    # relation notée -> [E, d_r]
    edges: dict                    # relation -> [2, E] (indices locaux)
    n: dict                        # sorte -> nombre
    names: dict                    # sorte -> noms
    hosts: list                    # machine (nom) de chaque instance, ou None
    decal: dict = field(default_factory=dict)

    def __post_init__(self):
        o = 0
        for k in SORTES:
            self.decal[k] = o
            o += self.n[k]
        self.total = o

    def cles(self) -> list[str]:
        return [juge._cle(k, nom) for k in SORTES for nom in self.names[k]]

    def machine(self) -> np.ndarray:
        """L'indice global de la machine de chaque instance (−1 sans machine connue)."""
        place = {nom: self.decal["host"] + i for i, nom in enumerate(self.names["host"])}
        return np.array([place.get(h, -1) for h in self.hosts], dtype=int)

    def globaux(self, r: str) -> tuple[np.ndarray, np.ndarray]:
        s, d = RELATIONS[r]
        e = self.edges[r]
        return e[0] + self.decal[s], e[1] + self.decal[d]

    def identites(self) -> tuple[dict, dict]:
        """({sorte : identité de chaque nœud}, {relation : (relation, identité source,
        identité cible) de chaque flèche}), temoin_noeud.identite : pour le SEUL
        calage de la sortie (versions 2 et 3), jamais pour le modèle."""
        if getattr(self, "_identites", None) is None:
            noeuds = {k: [tn.identite(k, nom) for nom in self.names[k]] for k in SORTES}
            fleches = {r: [(r, noeuds[s][a], noeuds[d][b]) for a, b in zip(*self.edges[r].tolist())]
                       for r, (s, d) in RELATIONS.items()}
            self._identites = (noeuds, fleches)
        return self._identites


def residus(modele: Reconstructeur, donnees: dict) -> Sortie:
    """Versions à masque : un passage par nœud, en lot (la copie i masque le nœud i et
    ses flèches entrantes). Version 3 : une seule passe, sans masque, les résidus de
    tous les nœuds et de toutes les flèches d'un coup."""
    g = convertir(donnees, VERSIONS[modele.version]["asinh"])
    n = {k: g.n[k] for k in SORTES}
    total = sum(n.values())
    decal, o = {}, 0
    for k in SORTES:
        decal[k], o = o, o + n[k]
    if modele.masque:
        lot = _copies(g, total)
        m = {}
        for k in SORTES:
            mk = torch.zeros(total * n[k], dtype=torch.bool)
            i = torch.arange(n[k])
            mk[(decal[k] + i) * n[k] + i] = True
            m[k] = mk
        with torch.no_grad():
            valeurs, logits, fleches = modele(lot, m)
    else:
        with torch.no_grad():
            valeurs, logits, fleches = modele(g, None)
    res_n = {}
    for k in SORTES:
        i = torch.arange(n[k])
        lignes = (decal[k] + i) * n[k] + i if modele.masque else i
        r = (g.x[k] - valeurs[k][lignes]).numpy().astype(float)
        r[g.p[k].numpy() < 0.5] = np.nan
        absents = (g.p[k] - torch.sigmoid(logits[k][lignes])).sum(1).numpy().astype(float)
        res_n[k] = np.concatenate([r, absents[:, None]], 1)
    res_e = {}
    for r in modele.notees:
        s, d = RELATIONS[r]
        e = g.ei[r].shape[1]
        lignes = (decal[d] + g.ei[r][1]) * e + torch.arange(e) if modele.masque else torch.arange(e)
        res_e[r] = (g.ea[r] - fleches[r][lignes]).numpy().astype(float) if e else np.zeros((0, g.ea[r].shape[1]))
    inst = donnees["nodes"]["instance"]
    return Sortie(res_n, res_e, {r: g.ei[r].numpy() for r in RELATIONS}, n,
                  {k: list(donnees["nodes"][k]["names"]) for k in SORTES}, list(inst.get("hosts") or [None] * n["instance"]))


def _echelle_robuste(vals: np.ndarray) -> float:
    """tn.echelle (quantiles linéaires), plancher de tn.echelles : 0,1 × pstdev, ou 0,1."""
    if len(vals) == 0:
        return 1.0
    q01, q25, q75, q99 = np.quantile(vals, [0.01, 0.25, 0.75, 0.99])
    s = max((q75 - q25) / 1.349, (q99 - q01) / 4.653)
    if s <= 1e-12:
        sd = float(np.std(vals))
        s = tn.PLANCHER * (sd if sd > 1e-12 else 1.0)
    return float(s)


def _q95(vals) -> float:
    return tn._q(list(map(float, vals)), CENTILE / 100)


def ecarts(sortie: Sortie, calage: "Calage") -> tuple[dict, np.ndarray, dict, dict]:
    """(z des nœuds par sorte, erreur r_v de chaque nœud en indices globaux, z des
    flèches par relation notée, erreur ε de chaque flèche). Médiane et échelle par
    sorte (version 1) ou par identité (versions 2 et 3) : Calage.lignes."""
    med_n, ech_n, med_e, ech_e = calage.lignes(sortie)
    z_n, r = {}, np.zeros(sortie.total)
    for k in SORTES:
        z = (sortie.res_n[k] - med_n[k]) / ech_n[k]
        z_n[k] = z
        if len(z):
            o = sortie.decal[k]
            r[o:o + sortie.n[k]] = np.nanmax(np.abs(z), axis=1)   # la colonne absents n'est jamais NaN
    z_e, eps = {}, {}
    for rel in calage.notees:
        z = (sortie.res_e[rel] - med_e[rel]) / ech_e[rel]
        z_e[rel] = z
        eps[rel] = np.abs(z).max(axis=1) if len(z) else np.zeros(0)
    return z_n, r, z_e, eps


def bout(b: str, sortie: Sortie, eps: dict, kappa: dict) -> np.ndarray:
    """e_v, ce que chaque nœud reçoit des flèches ANORMALES (ε > κ_r), selon B."""
    e = np.zeros(sortie.total)
    for rel, ep in eps.items():
        if not len(ep):
            continue
        src, dst = sortie.globaux(rel)
        an = ep > kappa[rel]
        if not an.any():
            continue
        if b in ("B1", "B3"):
            np.maximum.at(e, dst[an], ep[an])
        if b in ("B2", "B3"):
            np.maximum.at(e, src[an], ep[an])
        if b == "B4":
            np.add.at(e, dst[an], ep[an])
        if b == "B5":
            entrant, entrant_an = np.zeros(sortie.total), np.zeros(sortie.total)
            sortant, sortant_an = np.zeros(sortie.total), np.zeros(sortie.total)
            np.add.at(entrant, dst, 1.0)
            np.add.at(entrant_an, dst[an], 1.0)
            np.add.at(sortant, src, 1.0)
            np.add.at(sortant_an, src[an], 1.0)
            fin = entrant_an[dst[an]] / entrant[dst[an]]
            fout = sortant_an[src[an]] / sortant[src[an]]
            np.add.at(e, dst[an], ep[an] * fin / (fin + fout))
            np.add.at(e, src[an], ep[an] * fout / (fin + fout))
    return e


def normaliser(sortie: Sortie, r: np.ndarray, e: np.ndarray, tau: dict) -> np.ndarray:
    """ŝ_v = max(r_v, e_v) / τ_k : « 1 = l'extrême normal de sa sorte »."""
    t = np.maximum(r, e)
    s = np.empty_like(t)
    for k in SORTES:
        o = sortie.decal[k]
        s[o:o + sortie.n[k]] = t[o:o + sortie.n[k]] / tau[k]
    return s


def _actifs(sortie: Sortie, machine: np.ndarray, rels) -> set[int]:
    """Les pods source d'une flèche calls ou queries vers un pod d'une autre machine."""
    out = set()
    for rel in APPELS:
        if rel not in rels:
            continue
        src, dst = sortie.globaux(rel)
        for a, b in zip(src.tolist(), dst.tolist()):
            if machine[a] >= 0 and machine[b] >= 0 and machine[a] != machine[b]:
                out.add(a)
    return out


def _amont(sortie: Sortie, rels, cibles: set[int]) -> set[int]:
    """Les pods qui atteignent l'un des pods cibles par les flèches calls et queries de
    la fenêtre (sans nom), hors les cibles elles-mêmes."""
    appelants: dict[int, set[int]] = {}
    for rel in APPELS:
        if rel in rels:
            src, dst = sortie.globaux(rel)
            for a, b in zip(src.tolist(), dst.tolist()):
                appelants.setdefault(b, set()).add(a)
    vus, bord = set(), set(cibles)
    while bord:
        bord = {a for b in bord for a in appelants.get(b, ())} - vus - cibles
        vus |= bord
    return vus


def remontee(hh: str, s: np.ndarray, sortie: Sortie, rels) -> np.ndarray:
    """H : l'erreur des pods remonte à leur machine (par le champ hosts)."""
    out = s.copy()
    if hh == "H0":
        return out
    machine = sortie.machine()
    inst = np.arange(sortie.decal["instance"], sortie.decal["instance"] + sortie.n["instance"])
    actifs = _actifs(sortie, machine, rels) if hh == "H2" else set()
    for hote in range(sortie.decal["host"], sortie.decal["host"] + sortie.n["host"]):
        pods = [int(p) for p in inst if machine[p] == hote]
        anormaux = [p for p in pods if s[p] > 1]
        if len(anormaux) < 2:
            continue
        if hh == "H2":
            ici = [p for p in pods if p in actifs]
            if not 2 * sum(1 for p in ici if s[p] > 1) > len(ici):
                continue
            amont = _amont(sortie, rels, set(pods))
            ailleurs = [p for p in actifs if machine[p] != hote and p not in amont]
            if 2 * sum(1 for p in ailleurs if s[p] > 1) > len(ailleurs):
                continue
        out[hote] = max(out[hote], float(sum(s[p] for p in anormaux)))
    return out


def dependances(sortie: Sortie, rels) -> list[set[int]]:
    """D(v) lu dans la fenêtre : une file dépend de ses consommateurs et producteurs ;
    une instance des cibles de ses calls et queries, et de sa machine ; une machine de rien."""
    dep = [set() for _ in range(sortie.total)]
    if "consumes" in rels:
        src, dst = sortie.globaux("consumes")
        for q, i in zip(src.tolist(), dst.tolist()):
            dep[q].add(i)
    if "publishes" in rels:
        src, dst = sortie.globaux("publishes")
        for i, q in zip(src.tolist(), dst.tolist()):
            dep[q].add(i)
    for rel in APPELS:
        if rel in rels:
            src, dst = sortie.globaux(rel)
            for a, b in zip(src.tolist(), dst.tolist()):
                if a != b:
                    dep[a].add(b)
    for p, h in zip(range(sortie.decal["instance"], sortie.decal["instance"] + sortie.n["instance"]),
                    sortie.machine().tolist()):
        if h >= 0:
            dep[p].add(h)
    return dep


def explication(v: str, s: np.ndarray, sortie: Sortie, rels) -> tuple[np.ndarray, dict, dict]:
    """V : une anomalie qui s'explique par une dépendance anormale passe à cette
    dépendance, jusqu'au dernier composant anormal. (ŝ', pointeurs, racines)."""
    if v == "V0":
        return s.copy(), {}, {}
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    anorm = s > 1
    dep = dependances(sortie, rels)
    lignes, colonnes = [], []
    for a in np.flatnonzero(anorm).tolist():
        for u in dep[a]:
            if anorm[u]:
                lignes.append(a)
                colonnes.append(u)
    graphe = csr_matrix((np.ones(len(lignes)), (lignes, colonnes)), shape=(sortie.total, sortie.total))
    _, scc = connected_components(graphe, directed=True, connection="strong")
    pointeur = {}
    for a in np.flatnonzero(anorm).tolist():
        cand = [u for u in dep[a] if anorm[u] and scc[u] != scc[a]]
        if cand:
            # égalité : le plus haut ŝ, puis le plus petit indice ; jamais le nom
            pointeur[a] = max(cand, key=lambda u: (s[u], -u))
    racine = {}
    for a in pointeur:
        r = a
        while r in pointeur:
            r = pointeur[r]
        racine[a] = r
    out = s.copy()
    for a in pointeur:
        out[a] = 1.0 - math.exp(-s[a])
    for a, r in racine.items():
        out[r] = max(out[r], s[r], s[a])
    return out, pointeur, racine


def noter_noeuds(sortie: Sortie, calage: "Calage", choix: dict | None = None,
                 variante: str | None = None) -> tuple[dict, float, dict]:
    """(score ŝ' de chaque clé du juge, score de la fenêtre S = max ŝ', diagnostic). La
    variante est celle du calage (celle de l'étape 1 qui l'a produit) ; le choix par
    défaut, celui de la version du calage."""
    choix = choix or CHOIX_VERSIONS[calage.version]
    if variante is not None and variante != calage.variante:
        raise ValueError(f"variante {variante} contre un calage de la variante {calage.variante}")
    cfg = VARIANTES[calage.variante]
    _, r, _, eps = ecarts(sortie, calage)
    e = bout(choix["bout"], sortie, eps, calage.kappa)
    s = normaliser(sortie, r, e, calage.tau(choix["bout"]))
    s = remontee(choix["remontee"], s, sortie, APPELS)   # H lit les flèches de la fenêtre dans toutes les variantes (§6, J 1597-1599)
    sp, pointeur, racine = explication(choix["explication"], s, sortie, cfg["deps"])
    cles = sortie.cles()
    scores = {c: float(x) for c, x in zip(cles, sp)}
    haut = int(np.argmax(sp)) if len(sp) else None
    return scores, float(sp.max()) if len(sp) else 0.0, {
        "premier": cles[haut] if haut is not None else None,
        "pointeurs": {cles[a]: cles[b] for a, b in pointeur.items()},
        "racines": sorted({cles[b] for b in racine.values()})}


def rang_attendu(scores: dict, attendue: str | list[str], tous: list[str]) -> int:
    """Le rang de la réponse attendue (une clé ou plusieurs), égalités contre le GNN (juge.rang)."""
    return juge.rang([attendue] if isinstance(attendue, str) else list(attendue), scores, tous)


def base_en_tete(scores: dict, base: list[str], tous: list[str]) -> bool:
    """La base est-elle première, ex aequo compris ? Pour la garde G_val, une égalité
    compte contre le GNN (la base est alors désignée) ; juge.rang la compte déjà contre
    lui pour le top-1. Sous B3, la base partage son ε avec la source de sa flèche
    queries anormale : dc.premier (rang == 1) verrait « pas première »."""
    m = max(juge._val(scores.get(c)) for c in base)
    return m > -math.inf and not any(juge._val(scores.get(k)) > m for k in tous if k not in base)


def grille() -> list[dict]:
    """Les 30 combinaisons B/H/V, dans l'ordre de simplicité (V, puis H, puis B)."""
    return [{"bout": b, "remontee": h, "explication": v}
            for v in EXPLICATIONS for h in REMONTEES for b in BOUTS]


def simplicite(choix: dict) -> tuple[int, int, int]:
    """La clé de l'ordre de simplicité (§3.5) : V0 < V1, puis H0 < H1 < H2, puis B1 < … < B5."""
    return (EXPLICATIONS.index(choix["explication"]), REMONTEES.index(choix["remontee"]),
            BOUTS.index(choix["bout"]))


def nom_choix(choix: dict) -> str:
    return f"{choix['bout']}/{choix['remontee']}/{choix['explication']}"


# ------------------------------------------------------------------------------
# Les échelles hors pli, κ, τ
# ------------------------------------------------------------------------------
class Calage:
    """Médianes et échelles des résidus, κ_r et τ_k(B), sur des résidus TENUS hors pli.

    Version 1 : par (sorte, colonne) et (relation, colonne). Versions 2 et 3 (§11) :
    par (identité, colonne), l'identité du témoin 2 (temoin_noeud.identite : un pod de
    Deployment ramené à son service ; StatefulSet, file, machine par leur nom) et,
    pour une flèche, (relation, identité source, identité cible) comme le témoin
    des flèches ; médiane et échelle robustes de temoin_noeud.echelles, avec son
    plancher par (sorte, colonne) ou (relation, colonne) et son minimum de MIN_OBS
    résidus. Une identité (ou une de ses colonnes) sans normal retombe sur le calage
    par sorte ou par relation. L'identité ne cale que la sortie : le modèle ne la
    voit jamais."""

    def __init__(self, sorties: list[Sortie], variante: str, notees: list[str], version: str = VERSION):
        self.variante, self.notees, self.sorties = variante, list(notees), sorties
        self.version = version
        self.par_identite = VERSIONS[version]["identite"]
        self.med_n, self.ech_n, self.med_e, self.ech_e = {}, {}, {}, {}
        for k in SORTES:
            tout = np.concatenate([s.res_n[k] for s in sorties]) if sorties else np.zeros((0, 1))
            med, ech = [], []
            for c in range(tout.shape[1]):
                vals = tout[:, c][~np.isnan(tout[:, c])]
                med.append(float(np.median(vals)) if len(vals) else 0.0)
                ech.append(_echelle_robuste(vals))
            self.med_n[k], self.ech_n[k] = np.array(med), np.array(ech)
        for rel in self.notees:
            tout = np.concatenate([s.res_e[rel] for s in sorties])
            self.med_e[rel] = np.array([float(np.median(tout[:, c])) if len(tout) else 0.0
                                        for c in range(tout.shape[1])])
            self.ech_e[rel] = np.array([_echelle_robuste(tout[:, c]) for c in range(tout.shape[1])])
        self.ident_n: dict = {k: {} for k in SORTES}     # identité -> (médianes, échelles), repli compris
        self.ident_e: dict = {rel: {} for rel in self.notees}
        if self.par_identite:
            self._caler_identites(sorties)
        self._ecarts = [ecarts(s, self) for s in sorties]
        self.kappa = {}
        for rel in self.notees:
            tout = np.concatenate([ec[3][rel] for ec in self._ecarts])
            self.kappa[rel] = _q95(tout) if len(tout) else math.inf
        self._tau: dict[str, dict] = {}

    def _caler_identites(self, sorties: list[Sortie]) -> None:
        for k in SORTES:
            valeurs: dict = {}
            for s in sorties:
                ids = s.identites()[0][k]
                for ident, ligne in zip(ids, s.res_n[k].tolist()):
                    par = valeurs.setdefault(ident, {})
                    for c, v in enumerate(ligne):
                        if not math.isnan(v):
                            par.setdefault(c, []).append(v)
            stats = tn.echelles(valeurs, lambda ident: ident.split(":", 1)[0])
            for ident, par in stats.items():
                if not par:
                    continue                             # aucune colonne assez observée : le repli
                med, ech = self.med_n[k].copy(), self.ech_n[k].copy()
                for c, (m, e) in par.items():
                    med[c], ech[c] = m, e
                self.ident_n[k][ident] = (med, ech)
        for rel in self.notees:
            valeurs = {}
            for s in sorties:
                for ident, ligne in zip(s.identites()[1][rel], s.res_e[rel].tolist()):
                    par = valeurs.setdefault(ident, {})
                    for c, v in enumerate(ligne):
                        par.setdefault(c, []).append(v)
            stats = tn.echelles(valeurs, lambda cle: cle[0])
            for ident, par in stats.items():
                if not par:
                    continue
                med, ech = self.med_e[rel].copy(), self.ech_e[rel].copy()
                for c, (m, e) in par.items():
                    med[c], ech[c] = m, e
                self.ident_e[rel][ident] = (med, ech)

    def lignes(self, sortie: Sortie) -> tuple[dict, dict, dict, dict]:
        """(médianes, échelles) des nœuds par sorte, puis des flèches par relation notée :
        un vecteur par sorte (version 1, diffusé sur les lignes), ou une ligne par nœud et
        par flèche selon son identité, le repli par sorte pour une identité inconnue."""
        if not self.par_identite:
            return self.med_n, self.ech_n, self.med_e, self.ech_e
        noeuds, fleches = sortie.identites()
        med_n, ech_n, med_e, ech_e = {}, {}, {}, {}
        for k in SORTES:
            defaut = (self.med_n[k], self.ech_n[k])
            paires = [self.ident_n[k].get(i, defaut) for i in noeuds[k]]
            med_n[k] = np.array([m for m, _ in paires]).reshape(len(paires), len(defaut[0]))
            ech_n[k] = np.array([e for _, e in paires]).reshape(len(paires), len(defaut[0]))
        for rel in self.notees:
            defaut = (self.med_e[rel], self.ech_e[rel])
            paires = [self.ident_e[rel].get(i, defaut) for i in fleches[rel]]
            med_e[rel] = np.array([m for m, _ in paires]).reshape(len(paires), len(defaut[0]))
            ech_e[rel] = np.array([e for _, e in paires]).reshape(len(paires), len(defaut[0]))
        return med_n, ech_n, med_e, ech_e

    def connues(self, sortie: Sortie) -> tuple[int, int, int, int]:
        """(nœuds calés par leur identité, nœuds, flèches calées par leur identité, flèches notées)."""
        noeuds, fleches = sortie.identites()
        n = sum(1 for k in SORTES for i in noeuds[k] if i in self.ident_n[k])
        e = sum(1 for rel in self.notees for i in fleches[rel] if i in self.ident_e[rel])
        return n, sortie.total, e, sum(len(fleches[rel]) for rel in self.notees)

    def tau(self, b: str) -> dict:
        """τ_k : 95e centile des t = max(r, e) hors pli de la sorte k, pour le bout B."""
        if b not in self._tau:
            par = {k: [] for k in SORTES}
            for s, (_, r, _, eps) in zip(self.sorties, self._ecarts):
                t = np.maximum(r, bout(b, s, eps, self.kappa))
                for k in SORTES:
                    par[k] += t[s.decal[k]:s.decal[k] + s.n[k]].tolist()
            tau = {}
            for k in SORTES:
                v = _q95(par[k]) if par[k] else 1.0
                tau[k] = v if v > 1e-12 else 1.0
            self._tau[b] = tau
        return self._tau[b]


# ------------------------------------------------------------------------------
# L'étape 1 : le modèle final, les plis, les résidus tenus
# ------------------------------------------------------------------------------
def _taches(normales: list[dict], dims: dict, variante: str, graine: int, epoques: int,
            version: str = VERSION) -> list[tuple]:
    """Le modèle final (rang 0), puis un pli par campagne dans l'ordre trié (rang 1 à n)."""
    campagnes = sorted({f["campagne"] for f in normales})
    ids = lambda garde: tuple(id(f["donnees"]) for f in garde)
    out = [(ids(normales), dims, variante, graine, 0, epoques, version)]
    for rang, c in enumerate(campagnes, 1):
        out.append((ids([f for f in normales if f["campagne"] != c]), dims, variante, graine, rang, epoques, version))
    return out


def empreinte(etat: dict) -> str:
    """§8 : sha256 de torch.save en mémoire, sans rien d'autre, dans toutes les versions
    (--ouvrir la refait sur le state_dict). La version s'imprime à côté, dans l'en-tête."""
    return hashlib.sha256(_en_octets(etat)).hexdigest()


class Etape1:
    """
    Le modèle final, appris sur toutes les normales d'apprentissage, et un modèle par
    pli (une campagne mise de côté). Les résidus tenus : les normales de chaque
    campagne notées par le modèle appris sans elle. Le calage du modèle final vient
    de tous les résidus tenus ; celui qui note la campagne c, des résidus tenus des
    autres campagnes (§3.1).
    """

    def __init__(self, normales: list[dict], fige: dict, variante: str = "complet", graine: int = 0,
                 epoques: int = EPOQUES, etats: list[tuple[dict, dict]] | None = None, version: str = VERSION):
        if variante not in VARIANTES:
            raise ValueError(f"variante inconnue : {variante}")
        if version not in VERSIONS:
            raise ValueError(f"version inconnue : {version}")
        self.campagnes = sorted({f["campagne"] for f in normales})
        if len(self.campagnes) < 2:
            raise ValueError("il faut des fenêtres normales d'apprentissage dans au moins deux campagnes "
                             "(le seuil d'alarme se cale en en mettant une de côté)")
        self.variante, self.graine, self.epoques, self.version = variante, graine, epoques, version
        _un_fil()                    # notes reproductibles : un fil, algorithmes déterministes
        self.dims = dimensions(fige)
        if etats is None:
            asinh = VERSIONS[version]["asinh"]
            graphes = {id(f["donnees"]): convertir(f["donnees"], asinh) for f in normales}
            etats = entrainer_tous(_taches(normales, self.dims, variante, graine, epoques, version), graphes)
        self.infos = [i for _, i in etats]
        self.modele = charger(etats[0][0], self.dims, variante, version)
        self.plis = {c: charger(etats[r][0], self.dims, variante, version) for r, c in enumerate(self.campagnes, 1)}
        self.empreinte = empreinte(etats[0][0])   # §8 : sha256 de torch.save en mémoire
        self.tenues = {c: [(f["id"], residus(self.plis[c], f["donnees"])) for f in normales if f["campagne"] == c]
                       for c in self.campagnes}
        notees = self.modele.notees
        self.calage = Calage([s for c in self.campagnes for _, s in self.tenues[c]], variante, notees, version)
        self.calages_sans = {c: Calage([s for c2 in self.campagnes if c2 != c for _, s in self.tenues[c2]],
                                       variante, notees, version) for c in self.campagnes}
        self._sorties: dict[int, tuple[dict, Sortie]] = {}
        self._tenus: dict[tuple, list] = {}

    def sortie(self, donnees: dict) -> Sortie:
        """Les résidus du modèle final (gardés par objet ; une copie profonde est recalculée)."""
        cle = id(donnees)
        if cle not in self._sorties or self._sorties[cle][0] is not donnees:
            self._sorties[cle] = (donnees, residus(self.modele, donnees))
        return self._sorties[cle][1]

    def tenus(self, choix: dict | None = None) -> list[tuple[str, str, float]]:
        """(campagne, id, S) de chaque normale d'apprentissage, notée hors pli (J 1298-1299)."""
        choix = choix or CHOIX_VERSIONS[self.version]
        cle = tuple(sorted(choix.items()))
        if cle not in self._tenus:
            self._tenus[cle] = [(c, i, noter_noeuds(s, self.calages_sans[c], choix)[1])
                                for c in self.campagnes for i, s in self.tenues[c]]
        return self._tenus[cle]


_CACHE: dict[tuple, Etape1] = {}


def _cle_cache(normales: list[dict], variante: str, graine: int, epoques: int, version: str = VERSION) -> tuple:
    return (version, variante, graine, epoques, frozenset(f["id"] for f in normales))


def _normales(fen: list[dict]) -> list[dict]:
    return [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "normale"]


def etape1(fen: list[dict], fige: dict, variante: str = "complet", graine: int = 0,
           epoques: int = EPOQUES, version: str = VERSION) -> Etape1:
    """L'étape 1 apprise sur les normales d'apprentissage de `fen`, gardée en mémoire."""
    normales = _normales(fen)
    cle = _cle_cache(normales, variante, graine, epoques, version)
    if cle not in _CACHE:
        _CACHE[cle] = Etape1(normales, fige, variante, graine, epoques, version=version)
    return _CACHE[cle]


def preparer(fen: list[dict], fige: dict, graines: int = 5, variantes=tuple(VARIANTES),
             epoques: int = EPOQUES, version: str = VERSION) -> float:
    """Tous les entraînements manquants en une fois, en parallèle. Rend la durée (s)."""
    debut = time.perf_counter()
    normales = _normales(fen)
    graphes = {id(f["donnees"]): convertir(f["donnees"], VERSIONS[version]["asinh"]) for f in normales}
    dims = dimensions(fige)
    a_faire, taches = [], []
    for v in variantes:
        for g in range(graines):
            cle = _cle_cache(normales, v, g, epoques, version)
            if cle in _CACHE:
                continue
            t = _taches(normales, dims, v, g, epoques, version)
            a_faire.append((cle, v, g, len(taches), len(t)))
            taches += t
    etats = entrainer_tous(taches, graphes)
    for cle, v, g, debut_t, n in a_faire:
        _CACHE[cle] = Etape1(normales, fige, v, g, epoques, etats=etats[debut_t:debut_t + n], version=version)
    return time.perf_counter() - debut


# ------------------------------------------------------------------------------
# L'étape 2 et la réponse
# ------------------------------------------------------------------------------
def profil(sortie: Sortie, calage: Calage) -> list[float]:
    """Le profil d'une fenêtre, sans identité : pour chaque sorte et chaque colonne
    d'état (absents compris), puis chaque relation notée et chaque colonne, le plus
    grand et le plus petit z signé, compressés (tn._c)."""
    z_n, _, z_e, _ = ecarts(sortie, calage)
    out = []
    for k in SORTES:
        z = z_n[k]
        for c in range(len(calage.med_n[k])):
            vals = z[:, c][~np.isnan(z[:, c])] if len(z) else np.zeros(0)
            out += [tn._c(float(vals.max())), tn._c(float(vals.min()))] if len(vals) else [0.0, 0.0]
    for rel in calage.notees:
        z = z_e[rel]
        for c in range(len(calage.med_e[rel])):
            out += [tn._c(float(z[:, c].max())), tn._c(float(z[:, c].min()))] if len(z) else [0.0, 0.0]
    return out


def budget_mis_a_l_echelle(budget, n: int) -> int:
    """b sur n minutes pour un budget écrit sur 249 (un nom de BUDGETS, ou un nombre)."""
    b249 = BUDGETS[budget] if isinstance(budget, str) else int(budget)
    return int(math.floor(b249 * n / MINUTES_BUDGET + 0.5))


def seuil_budget(scores: list[float], b: int) -> float:
    """Le seuil qui fait sonner exactement b scores tenus s'il n'y a pas d'égalité."""
    s = sorted(scores, reverse=True)
    return s[b] if b < len(s) else -math.inf


class GNN:
    """
    La méthode, comme un témoin : fabriquée sur toutes les fenêtres (elle filtre
    elle-même l'apprentissage), elle répond fenêtre par fenêtre sur les seuls
    nombres, flèches et noms de la fenêtre.
    """

    def __init__(self, fen: list[dict], fige: dict, graine: int = 0, variante: str = "complet",
                 budget=None, reglage: str = "avec exemples", epoques: int = EPOQUES, choix: dict | None = None,
                 version: str = VERSION):
        if reglage not in tn.REGLAGES:
            raise ValueError(f"réglage inconnu : {reglage}")
        charger_echelle(fige)
        self.reglage, self.variante, self.budget, self.version = reglage, variante, budget, version
        self.choix = dict(choix or CHOIX_VERSIONS[version])
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        self.etape1 = etape1(fen, fige, variante, graine, epoques, version)

        # L'alarme : les scores tenus hors pli (gardés pour recaler à tout budget).
        self.tenus = self.etape1.tenus(self.choix)
        s = [x for _, _, x in self.tenus]
        self.seuil_propre = _q95(s)
        self.calage_propre = (sum(1 for x in s if x > self.seuil_propre), len(s))
        if budget is None:
            self.seuil = self.seuil_propre
            self.calage_alarme = self.calage_propre
        else:
            b = budget_mis_a_l_echelle(budget, len(s))
            self.seuil = seuil_budget(s, b)
            self.calage_alarme = (sum(1 for x in s if x > self.seuil), len(s))
            self.budget_b = b
            self.calage_budget = self.calage_alarme

        # L'étape 2 : prototypes sur les profils d'écart du modèle final, rejet par injection.
        self.prototypes, self.seuil_rejet, self.calage_rejet = None, math.inf, (0, 0)
        if reglage == "avec exemples" and pannes:
            cal = self.etape1.calage
            profils = {f["id"]: profil(self.etape1.sortie(f["donnees"]), cal) for f in pannes}
            self.prototypes = tn.Prototypes([profils[f["id"]] for f in pannes], [f["cause"] for f in pannes])
            bien = []
            injections = sorted({(f["campagne"], f["injection"]) for f in pannes})
            for g in injections:
                reste = [f for f in pannes if (f["campagne"], f["injection"]) != g]
                if not reste:
                    continue
                protos = tn.Prototypes([profils[f["id"]] for f in reste], [f["cause"] for f in reste])
                for f in (f for f in pannes if (f["campagne"], f["injection"]) == g):
                    cause, d = protos.plus_proche(profils[f["id"]])
                    if cause == f["cause"]:
                        bien.append(d)
            self.seuil_rejet = _q95(bien) if bien else math.inf
            self.calage_rejet = (len(injections), len(bien))

    def repondre(self, donnees: dict) -> dict:
        sortie = self.etape1.sortie(donnees)
        scores, s, diag = noter_noeuds(sortie, self.etape1.calage, self.choix)
        alarme = bool(s > self.seuil)
        brute = None
        if not alarme:
            cause = "normale"
        elif self.reglage == "sans exemples" or self.prototypes is None:
            cause = "inconnue"
        else:
            brute, d = self.prototypes.plus_proche(profil(sortie, self.etape1.calage))
            cause = brute if d <= self.seuil_rejet else "inconnue"
        return {"alarme": alarme, "cause": cause, "scores": scores, "_S": s, "_premier": diag["premier"],
                "_racine": diag["racines"], "_pointeurs": diag["pointeurs"], "_sans_rejet": brute}


def methodes(fige: dict, epoques: int = EPOQUES, version: str = VERSION) -> list[tuple[str, object, bool]]:
    """(nom, fabrique(fen, graine), tire au hasard) : noms commençant par « GNN »
    (decision_c.methodes). Seuil propre ; « budget de la règle » : θ_21."""
    out = [("GNN", lambda fen, g: GNN(fen, fige, graine=g, epoques=epoques, version=version), True),
           ("GNN, budget de la règle", lambda fen, g: GNN(fen, fige, graine=g, budget="règle", epoques=epoques,
                                                          version=version), True)]
    for v in VARIANTES:
        if v != "complet":
            out.append((f"GNN {v}", lambda fen, g, v=v: GNN(fen, fige, graine=g, variante=v, epoques=epoques,
                                                            version=version), True))
    return out


# ------------------------------------------------------------------------------
# Le scellé
# ------------------------------------------------------------------------------
def scelle_ouvert() -> bool:
    """L'étiquette gnn-fige existe-t-elle ? (lecture seule, comme decision_c._git)"""
    r = subprocess.run(["git", "-C", str(HERE.parent), "rev-parse", "-q", "--verify",
                        f"refs/tags/{ETIQUETTE_SCELLE}"], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def exiger_scelle() -> None:
    if not scelle_ouvert():
        raise juge.Refus(f"SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; le vrai test "
                         f"ne se lit qu'une fois le GNN figé (réglages sur juge.validation seulement).")


# ------------------------------------------------------------------------------
# --verifier : T1 à T4, T6, T7 (§8), T12, T13
# ------------------------------------------------------------------------------
def _propre(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


def _sans_fleches(donnees: dict) -> dict:
    d = copy.deepcopy(donnees)
    for e in d["edges"].values():
        e["source"], e["target"], e["X"] = [], [], []
    return d


def _nom_de_deploiement(nom: str, rnd: random.Random, pris: set) -> str | None:
    """Un autre nom de pod pour le même Deployment (même service, autre ReplicaSet et
    autre suffixe : même identité pour temoin_noeud.identite) ; None hors Deployment."""
    ident = tn.identite("instance", nom)
    if ident == f"instance:{nom}":
        return None
    while True:
        neuf = (ident.split(":", 1)[1] + "-" + "".join(rnd.choice("bcdf456789") for _ in range(10))
                + "-" + "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(5)))
        if neuf not in pris and tn.identite("instance", neuf) == ident:
            pris.add(neuf)
            return neuf


def _permuter(donnees: dict, graine: int, tout: bool = True) -> tuple[dict, dict]:
    """Les lignes de chaque sorte et les flèches permutées, les indices réécrits ; `tout` :
    tous les pods et toutes les machines renommés ; sinon (calage par identité, versions
    2 et 3) seuls les pods de Deployment, dans leur service (hachage et suffixe neufs) :
    renommer un StatefulSet ou une machine change son identité, donc son calage.
    (copie, {ancienne clé : nouvelle clé})."""
    rnd = random.Random(graine)
    d = copy.deepcopy(donnees)
    renomme = {}
    hotes = {h: (f"machine-{i:02d}-{rnd.randrange(10**6):06d}" if tout else h)
             for i, h in enumerate(d["nodes"]["host"]["names"])}
    nouvelle_place = {}
    for k in SORTES:
        b = d["nodes"][k]
        n = len(b["names"])
        perm = list(range(n))
        rnd.shuffle(perm)                                   # la place p reçoit l'ancienne ligne perm[p]
        nouvelle_place[k] = {ancien: p for p, ancien in enumerate(perm)}
        for champ in ("keys", "names", "hosts", "X"):
            if isinstance(b.get(champ), list) and len(b[champ]) == n:
                b[champ] = [b[champ][i] for i in perm]
        if k == "instance":
            if tout:
                nouveaux = [f"pod-{rnd.randrange(10**8):08d}-{i}" for i in range(n)]
            else:
                pris = set(b["names"])
                nouveaux = [_nom_de_deploiement(nom, rnd, pris) or nom for nom in b["names"]]
            for vieux, neuf in zip(b["names"], nouveaux):
                renomme[juge._cle(k, vieux)] = juge._cle(k, neuf)
            b["names"] = nouveaux
            b["keys"] = [f"uid-{i}" for i in range(n)]
        if k == "host":
            for vieux in b["names"]:
                renomme[juge._cle(k, vieux)] = juge._cle(k, hotes[vieux])
            b["names"] = [hotes[h] for h in b["names"]]
            b["keys"] = [f"host:{h}" for h in b["names"]]
        if k == "queue":
            for nom in b["names"]:
                renomme[juge._cle(k, nom)] = juge._cle(k, nom)
        if isinstance(b.get("hosts"), list):
            b["hosts"] = [hotes.get(h, h) if h is not None else None for h in b["hosts"]]
    for e in d["edges"].values():
        m = len(e["source"])
        perm = list(range(m))
        rnd.shuffle(perm)
        e["source"] = [nouvelle_place[e["source_kind"]][e["source"][i]] for i in perm]
        e["target"] = [nouvelle_place[e["target_kind"]][e["target"][i]] for i in perm]
        e["X"] = [e["X"][i] for i in perm]
    return d, renomme


def _petit_jeu(fen: list[dict]) -> list[dict]:
    """20 fenêtres de validation : 12 normales d'apprentissage (3 campagnes × 4), 4 pannes
    d'apprentissage (2 injections × 2, deux causes), 2 normales et 2 pannes du test."""
    app = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "normale"]
    par = {}
    for f in app:
        par.setdefault(f["campagne"], []).append(f)
    trois = sorted(par, key=lambda c: -len(par[c]))[:3]
    choisies = [x for c in trois for x in par[c][::max(1, len(par[c]) // 4)][:4]]
    pannes = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "panne"]
    injections, causes = [], set()
    for f in pannes:
        k = (f["campagne"], f["injection"])
        if f["cause"] not in causes and k not in injections:
            injections.append(k)
            causes.add(f["cause"])
        if len(injections) == 2:
            break
    for k in injections:
        choisies += [f for f in pannes if (f["campagne"], f["injection"]) == k][:2]
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    choisies += [f for f in test if f["etiquette"] == "normale"][:2] + [f for f in test if f["etiquette"] == "panne"][:2]
    return choisies


def verifier(campagnes: Path, runs: Path, version: str = VERSION) -> int:
    _un_fil()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    resultats = {}

    # T7 : l'empreinte de l'échelle est contrôlée.
    faux = copy.deepcopy(fige)
    faux["echelle"]["sha256"] = "0" * 64
    try:
        charger_echelle(faux)
        t7 = False
    except juge.Refus:
        t7 = True
    charger_echelle(fige)
    resultats["T7 sha256 de l'échelle contrôlé"] = (t7, "une fausse empreinte est refusée, la vraie acceptée")

    fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
    petit = _petit_jeu(fen)
    print(f"# version {version} : {VERSIONS[version]}")
    print(f"# petit jeu : {len(petit)} fenêtres de validation "
          f"({sum(1 for f in petit if f['jeu'] == 'apprentissage' and f['etiquette'] == 'normale')} normales "
          f"d'apprentissage sur {len({f['campagne'] for f in _normales(petit)})} campagnes), 2 époques")

    # T3 : deux entraînements à la même graine, identiques (dans ce processus et dans un autre).
    dims = dimensions(fige)
    asinh = VERSIONS[version]["asinh"]
    graphes = [convertir(f["donnees"], asinh) for f in _normales(petit)]
    a, info = entrainer(graphes, dims, "complet", 0, 0, 2, version)
    b, _ = entrainer(graphes, dims, "complet", 0, 0, 2, version)
    c, _ = entrainer(graphes, dims, "complet", 1, 0, 2, version)
    [(d_, _)] = entrainer_tous([(tuple(id(f["donnees"]) for f in _normales(petit)), dims, "complet", 0, 0, 2,
                                 version)],
                               {id(f["donnees"]): convertir(f["donnees"], asinh) for f in _normales(petit)})
    egal = lambda x, y: x.keys() == y.keys() and all(torch.equal(x[k], y[k]) for k in x)
    t3 = egal(a, b) and egal(a, d_) and not egal(a, c)
    resultats["T3 entraînement déterministe"] = (
        t3, f"même graine : identique ici {egal(a, b)}, dans un processus spawn {egal(a, d_)} ; "
            f"autre graine différente {not egal(a, c)} ; {info['parametres']} paramètres")

    # T1 : forme de la réponse, pour chaque variante et chaque fenêtre ; flèches vides.
    soucis = []
    preparer(petit, fige, graines=1, variantes=tuple(VARIANTES), epoques=2, version=version)
    modeles = {v: GNN(petit, fige, graine=0, variante=v, epoques=2, version=version) for v in VARIANTES}
    for v, m in modeles.items():
        for f in petit:
            rep = m.repondre(f["donnees"])
            try:
                juge.verifier(f, _propre(rep))
            except ValueError as e:
                soucis.append(f"{v} : {e}")
                continue
            if list(rep["scores"]) != juge.noeuds(f["donnees"]):
                soucis.append(f"{v} : {f['id']} : les clés ne sont pas tous les nœuds")
            if any(not math.isfinite(x) for x in rep["scores"].values()):
                soucis.append(f"{v} : {f['id']} : un score n'est pas fini")
            if not isinstance(rep["alarme"], bool):
                soucis.append(f"{v} : {f['id']} : alarme {type(rep['alarme']).__name__}")
        vide = {"id": "vide", "donnees": _sans_fleches(petit[0]["donnees"])}
        try:
            juge.verifier(vide, _propre(m.repondre(vide["donnees"])))
        except Exception as e:                                   # noqa: BLE001 — tout échec compte
            soucis.append(f"{v} : fenêtre sans flèche : {type(e).__name__} {e}")
    resultats["T1 forme de la réponse"] = (not soucis, f"{len(VARIANTES)} variantes × {len(petit)} fenêtres, "
                                                       f"plus une fenêtre sans aucune flèche"
                                           + (f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else ""))

    # T2 : renommer, permuter, réindexer ne change rien (toutes les combinaisons B/H/V).
    # Calage par identité (v2, v3) : seuls les pods de Deployment sont renommés (dans leur
    # service), et les résidus bruts du modèle doivent en plus être invariants quand TOUT
    # est renommé (pods, StatefulSet, machines) : aucun nom n'entre dans le modèle.
    tout = not VERSIONS[version]["identite"]
    pire, pire_res, cas = 0.0, 0.0, 0
    for v in ("complet", "sans aucune arête"):
        e1 = modeles[v].etape1
        for f in petit[-6:]:
            d2, renomme = _permuter(f["donnees"], 7, tout)
            s1, s2 = e1.sortie(f["donnees"]), e1.sortie(d2)
            for ch in grille():
                sc1, S1, _ = noter_noeuds(s1, e1.calage, ch)
                sc2, S2, _ = noter_noeuds(s2, e1.calage, ch)
                pire = max(pire, abs(S1 - S2), *(abs(sc1[k] - sc2[renomme[k]]) for k in sc1))
                cas += 1
            d3, renomme3 = _permuter(f["donnees"], 11, True)
            s3 = e1.sortie(d3)
            place1 = {c: i for i, c in enumerate(s1.cles())}
            place3 = {c: i for i, c in enumerate(s3.cles())}
            for k in SORTES:
                o1, o3 = s1.decal[k], s3.decal[k]
                for c, i in place1.items():
                    if c.startswith(k + ":"):
                        a1, a3 = s1.res_n[k][i - o1], s3.res_n[k][place3[renomme3[c]] - o3]
                        if not np.array_equal(np.isnan(a1), np.isnan(a3)):
                            pire_res = math.inf
                        else:
                            pire_res = max(pire_res, float(np.nanmax(np.abs(a1 - a3), initial=0.0)))
    renommage = ("tout renommé" if tout else
                 "pods de Deployment renommés dans leur service, StatefulSet et machines gardés")
    resultats["T2 aucun nom, invariance par permutation"] = (
        pire <= 1e-5 and pire_res <= 1e-5,
        f"{cas} cas (2 variantes × 6 fenêtres × 30 combinaisons, {renommage}) ; plus grand écart {pire:.2e} ; "
        f"résidus bruts du modèle, tout renommé : plus grand écart {pire_res:.2e}")

    # T12 : le calage de la sortie. v1 : par sorte, le nom ne compte pas. v2, v3 : par
    # identité (médiane et échelle recalculées ici à part), et repli par sorte pour une
    # identité inconnue (tsdb-mysql-0 et une machine renommées).
    e1 = modeles["complet"].etape1
    cal = e1.calage
    soucis12, n12 = [], 0
    for f in petit[-6:]:
        s1 = e1.sortie(f["donnees"])
        z1 = ecarts(s1, cal)[0]
        d4 = copy.deepcopy(f["donnees"])
        inst, hotes = d4["nodes"]["instance"], d4["nodes"]["host"]
        change = {}
        for i, nom in enumerate(inst["names"]):
            if tn.identite("instance", nom) == f"instance:{nom}":        # un StatefulSet
                inst["names"][i] = f"inconnu-{i}"
                change[("instance", i)] = True
        vieux = hotes["names"][0]
        hotes["names"][0] = "machine-inconnue"
        inst["hosts"] = ["machine-inconnue" if h == vieux else h for h in inst["hosts"]]
        change[("host", 0)] = True
        z4 = ecarts(e1.sortie(d4), cal)[0]
        noeuds = s1.identites()[0]
        for k in SORTES:
            for i in range(s1.n[k]):
                n12 += 1
                ident = noeuds[k][i]
                if not cal.par_identite or change.get((k, i)) or ident not in cal.ident_n[k]:
                    attendu = (s1.res_n[k][i] - cal.med_n[k]) / cal.ech_n[k]
                else:
                    vals = [s.res_n[k][j] for s in cal.sorties for j, x in enumerate(s.identites()[0][k]) if x == ident]
                    vals = np.array(vals)
                    attendu = s1.res_n[k][i].copy()
                    for c in range(vals.shape[1]):
                        col = vals[:, c][~np.isnan(vals[:, c])]
                        if len(col) >= tn.MIN_OBS:
                            med = float(np.median(col))
                            ech = cal.ident_n[k][ident][1][c]
                            if ech < tn.echelle(col.tolist()) - 1e-12:
                                soucis12.append(f"{ident} col {c} : échelle sous tn.echelle")
                            attendu[c] = (attendu[c] - med) / ech
                        else:
                            attendu[c] = (attendu[c] - cal.med_n[k][c]) / cal.ech_n[k][c]
                zi = z4[k][i] if change.get((k, i)) else z1[k][i]
                if not np.allclose(zi, attendu, equal_nan=True, atol=1e-9):
                    soucis12.append(f"{f['id']} {k} {i} ({ident})")
    connus = cal.connues(e1.sortie(petit[-1]["donnees"]))
    resultats["T12 calage de la sortie"] = (
        not soucis12, f"{n12} nœuds ({'par identité' if cal.par_identite else 'par sorte'} ; "
                      f"identités calées dans une fenêtre : {connus[0]}/{connus[1]} nœuds, "
                      f"{connus[2]}/{connus[3]} flèches ; StatefulSet et machine renommés : repli par sorte)"
        + (f" ; {len(soucis12)} soucis, dont {soucis12[0]}" if soucis12 else ""))

    # T13 : l'empreinte du modèle final est celle du §8 dans toutes les versions : le sha256
    # de torch.save en mémoire du state_dict, sans rien d'autre ; recalculée ici sur
    # l'entraînement `a` (même jeu, graine 0, rang 0, 2 époques : le modèle final de T1).
    tampon = io.BytesIO()
    torch.save(a, tampon)
    refaite = hashlib.sha256(tampon.getvalue()).hexdigest()
    resultats["T13 empreinte du §8"] = (
        e1.empreinte == refaite, f"version {version} : imprimée {e1.empreinte[:16]}, refaite sur torch.save "
                                 f"du state_dict {refaite[:16]}")

    # T4 : θ_b fait sonner exactement b scores tenus.
    m = modeles["complet"]
    s = [x for _, _, x in m.tenus]
    # Exactement b au-dessus quand il n'y a pas d'égalité à la limite ; jamais plus de b sinon.
    tries = sorted(s, reverse=True)
    libre = lambda b: b == 0 or b == len(s) or tries[b - 1] > tries[b]
    ecarts_b = [b for b in range(len(s) + 1)
                if (n_b := sum(1 for x in s if x > seuil_budget(s, b))) > b or (libre(b) and n_b != b)]
    budgets = {nom: budget_mis_a_l_echelle(nom, len(s)) for nom in BUDGETS}
    egalites = len(s) - len(set(s))
    ok4 = not ecarts_b
    resultats["T4 seuil au budget"] = (ok4, f"b = 0 à {len(s)} sur {len(s)} scores tenus ({egalites} égalités ; exact là où la "
                                            f"limite n'est pas une égalité, jamais plus de b ailleurs), "
                                            f"exacts sauf {ecarts_b or 'aucun'} ; budgets mis à l'échelle {budgets}")

    # T6 : le mode test est refusé sans gnn-fige.
    if scelle_ouvert():
        resultats["T6 test refusé sans gnn-fige"] = (True, "l'étiquette existe ici : refus non éprouvé")
    else:
        try:
            exiger_scelle()
            t6 = False
        except juge.Refus:
            t6 = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["gnn.py", "--test", "--graines", "1", "--epoques", "1", "--sans-temoins", "--version", version])
        resultats["T6 test refusé sans gnn-fige"] = (t6 and code == 1, f"exiger_scelle refuse : {t6} ; "
                                                                      f"--test rend le code {code}")

    print(f"# durée d'un entraînement de 2 époques sur {info['fenetres']} fenêtres : {info['duree']:.2f} s")
    echecs = 0
    for nom, (ok, detail) in sorted(resultats.items(), key=lambda x: int(x[0].split()[0][1:])):
        print(f"{nom:<44} {'réussi' if ok else 'ÉCHEC'}  ({detail})")
        echecs += not ok
    print("TOUT PASSE" if not echecs else f"{echecs} ÉCHEC(S)")
    return 0 if not echecs else 1


# ------------------------------------------------------------------------------
# --validation, --repetition, --test
# ------------------------------------------------------------------------------
def _reponses(t, fen: list[dict]) -> dict:
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    return {f["id"]: t.repondre(f["donnees"]) for f in test}


def _entrees(fige: dict, variantes, epoques: int, version: str = VERSION) -> list[tuple[str, object]]:
    ve = {"epoques": epoques, "version": version}
    out = [("GNN, avec exemples", lambda fen, g: GNN(fen, fige, graine=g, **ve)),
           ("GNN, sans exemples", lambda fen, g: GNN(fen, fige, graine=g, reglage="sans exemples", **ve)),
           ("GNN, budget de la règle", lambda fen, g: GNN(fen, fige, graine=g, budget="règle", **ve))]
    for v in variantes:
        out.append((f"GNN {v}", lambda fen, g, v=v: GNN(fen, fige, graine=g, variante=v, **ve)))
    return out


def _notes(fen: list[dict], fige: dict, graines: int, variantes, epoques: int, sans_temoins: bool,
           detail: dict | None = None, version: str = VERSION) -> dict:
    if sans_temoins:
        rep = juge.factices(fen)["a priori"]
        n = {"a priori (ne lit rien)": [(juge.noter(fen, rep)[1], rep)]}
    else:
        import temoins as temoins_module
        n = temoins_module.notes(fen, fige, graines)
    for nom, fabrique in _entrees(fige, variantes, epoques, version):
        n[nom] = []
        for g in range(graines):
            t = fabrique(fen, g)
            brutes = _reponses(t, fen)
            rep = {i: _propre(r) for i, r in brutes.items()}
            n[nom].append((juge.noter(fen, rep)[1], rep))
            if detail is not None and g == 0:
                detail[nom] = (t, brutes)
    return n


def _source_choix(choix: dict, version: str) -> str:
    """D'où vient le CHOIX écrit dans l'en-tête : le banc de la version, ou PROVISOIRE."""
    if CHOIX_SOURCES.get(version) and choix == CHOIX_VERSIONS[version]:
        return CHOIX_SOURCES[version]
    if choix == {"bout": "B1", "remontee": "H0", "explication": "V0"}:
        return "PROVISOIRE tant que le banc n'a pas tranché"
    return "choix passé à la main"


def _en_tete(t: GNN, variantes_infos: list) -> list[str]:
    e1 = t.etape1
    cal = e1.calage
    tau = cal.tau(t.choix["bout"])
    duree = [i["duree"] for i in e1.infos]
    out = [f"# étape 1 version {e1.version} ({e1.variante}, graine {e1.graine}) : {e1.infos[0]['parametres']} paramètres, "
           f"{e1.epoques} époques, {e1.infos[0]['fenetres']} normales d'apprentissage, "
           f"{len(e1.campagnes)} plis ; empreinte du modèle final {e1.empreinte[:16]}",
           f"#   durée d'un entraînement : modèle final {duree[0]:.1f} s, plis {min(duree[1:]):.1f}–"
           f"{max(duree[1:]):.1f} s (un fil chacun) ; perte du modèle final {e1.infos[0]['pertes'][0]:.3f} → "
           f"{e1.infos[0]['pertes'][-1]:.3f}",
           f"#   post-traitement {nom_choix(t.choix)} ({_source_choix(t.choix, e1.version)}) ; "
           f"κ : " + ", ".join(f"{r} {cal.kappa[r]:.2f}" for r in cal.notees)
           + " ; τ : " + ", ".join(f"{k} {tau[k]:.2f}" for k in SORTES),
           f"#   alarme au-dessus de {t.seuil_propre:.3f} (95e centile de {t.calage_propre[1]} scores tenus hors "
           f"pli ; {t.calage_propre[0]} au-dessus)"]
    if cal.par_identite:
        idn = sum(len(v) for v in cal.ident_n.values())
        ide = sum(len(v) for v in cal.ident_e.values())
        out.append(f"#   calage par identité (temoin_noeud.identite, temoin_noeud.echelles) : {idn} identités de nœud "
                   f"et {ide} de flèche ont leur normal ; les autres retombent sur le calage par sorte")
    n = len(t.tenus)
    s = [x for _, _, x in t.tenus]
    out.append("#   budgets mis à l'échelle (N = " + f"{n} au lieu de {MINUTES_BUDGET}) : "
               + ", ".join(f"{nom} {BUDGETS[nom]}/{MINUTES_BUDGET} → {budget_mis_a_l_echelle(nom, n)}/{n} "
                           f"(θ {seuil_budget(s, budget_mis_a_l_echelle(nom, n)):.3f})" for nom in BUDGETS))
    if t.prototypes is not None:
        out.append(f"#   étape 2 : {len(t.prototypes.moyennes)} prototypes ({', '.join(sorted(t.prototypes.moyennes))}) "
                   f"sur {len(t.prototypes.ecart)} dimensions ; rejet au-dessus de {t.seuil_rejet:.2f} "
                   f"({t.calage_rejet[0]} injections mises de côté, {t.calage_rejet[1]} fenêtres bien classées)")
    par = {}
    for c, _, x in t.tenus:
        par.setdefault(c, []).append(x > t.seuil_propre)
    out.append("#   scores tenus au-dessus du seuil, par campagne : "
               + ", ".join(f"{c} {sum(v)}/{len(v)}" for c, v in par.items()))
    out += variantes_infos
    return out


def repetition(noms: list[str], campagnes: Path, runs: Path, fige: dict, graines: int, variantes,
               epoques: int, sans_temoins: bool, validation: bool = True, version: str = VERSION) -> list[str]:
    """La boucle de temoins.repetition (l.181-200), recopiée, avec le GNN : chaque cause
    connue retirée de l'apprentissage (l'étape 1 est reprise : ses normales ne bougent pas)."""
    import temoins as temoins_module
    out = []
    for cause in temoins_module.REPETEES:
        fen = juge.lire(noms, campagnes, runs, jamais_vues=juge.JAMAIS_VUES | {cause})
        if validation:
            fen = juge.validation(fen)
        groupe = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "panne" and f["cause"] == cause]
        injections = len({(f["campagne"], f["injection"]) for f in groupe})
        out.append(f"\n{cause} retirée de l'apprentissage : {len(groupe)} fenêtres de test, {injections} injections")
        n = _notes(fen, fige, graines, variantes, epoques, sans_temoins, version=version)
        for nom, liste in n.items():
            cases = []
            for titre, cle in (("détection", f"detection jamais vue : {cause}"),
                               ("« inconnue »", f"cause jamais vue : {cause}"),
                               ("top-1", f"top-1 jamais vue : {cause}"),
                               ("top-3", f"top-3 jamais vue : {cause}")):
                v = [c[cle][0] for c, _ in liste if cle in c]
                if v:
                    cases.append(f"{titre} {temoins_module._case(v, liste[0][0][cle][1])}")
            if nom.startswith("règle"):
                cases = [x for x in cases if not x.startswith("« inconnue »")] + ["« inconnue » sans objet"]
            out.append(f"  {nom:<40}" + " ; ".join(cases))
    return out


def rapport(campagnes: Path, runs: Path, graines: int, epoques: int, sans_temoins: bool, variantes,
            validation: bool, avec_repetition: bool, tableau: bool = True, version: str = VERSION) -> int:
    import temoins as temoins_module
    _un_fil()
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    try:
        if not validation:
            exiger_scelle()
        charger_echelle(fige)
        noms = fautifs_module.SERIES
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    print("# Le GNN — écrit par graphe_en/gnn.py, ne pas éditer à la main.")
    cfg = VERSIONS[version]
    print(f"# version {version} de l'étape 1 (écart E-1, §11) : "
          f"{'masque' if cfg['masque'] else f'auto-encodeur sans masque, goulot {GOULOT}'}, "
          f"{'asinh' if cfg['asinh'] else 'sans asinh'}, calage {'par identité' if cfg['identite'] else 'par sorte'}")
    print(f"# graines 0 à {graines - 1} ; {epoques} époques ; variantes en plus du complet : "
          f"{', '.join(variantes) or 'aucune'} ; témoins {'NON recalculés' if sans_temoins else 'recalculés'}")
    duree = preparer(fen, fige, graines, ("complet",) + tuple(variantes), epoques, version)
    n_entr = graines * (1 + len(variantes)) * (1 + len(_etape_campagnes(fen)))
    print(f"# {n_entr} entraînements en {duree:.0f} s de temps réel ({PROCESSUS} processus au plus, un fil chacun)")
    if tableau:
        detail: dict = {}
        n = _notes(fen, fige, graines, variantes, epoques, sans_temoins, detail, version)
        t0 = detail["GNN, avec exemples"][0]
        tb = detail["GNN, budget de la règle"][0]
        infos = [f"#   GNN, budget de la règle : {tb.budget_b}/{len(tb.tenus)} → alarme au-dessus de {tb.seuil:.3f} "
                 f"({tb.calage_alarme[0]} scores tenus au-dessus)"]
        for v in variantes:
            tv = detail[f"GNN {v}"][0]
            sv = [x for _, _, x in tv.tenus]
            b21 = budget_mis_a_l_echelle("règle", len(sv))
            infos.append(f"#   {v} : alarme au-dessus de {tv.seuil_propre:.3f} (θ au budget de la règle, en "
                         f"diagnostic : {seuil_budget(sv, b21):.3f}) ; durée d'un entraînement "
                         f"{statistics.median(i['duree'] for i in tv.etape1.infos):.1f} s (médiane)")
        print("\n".join(_en_tete(t0, infos)))
        normales = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
        print(f"\n== 1. tableau de bord ({'validation' if validation else 'test'} ; fausses alertes sur "
              f"{sum(1 for f in normales if not f['vue'])} minutes normales non vues, puis sur "
              f"{sum(1 for f in normales if f['vue'])} de saine-09)")
        print("\n".join(temoins_module.tableau_de_bord(n)))
        print("\n== 2. fausses alertes au fil du temps (fenêtres normales du test ; médiane sur les graines)")
        print("\n".join(temoins_module.fil_du_temps(fen, n)))
        print("\n== note détaillée du GNN, avec exemples, graine 0")
        rep0 = {i: _propre(r) for i, r in detail["GNN, avec exemples"][1].items()}
        print("\n".join(juge.noter(fen, rep0, "GNN, avec exemples, graine 0")[0]))
        print("désigné en premier, par cause (fenêtres de panne du test)")
        print("\n".join(tn.premiers(fen, rep0)))
        if graines > 1:
            import temoin_tableau
            print(f"\n# GNN, avec exemples, sur {graines} graines : chaque nombre de la note")
            print("\n".join(temoin_tableau._resume_graines([c for c, _ in n["GNN, avec exemples"]])))
    if avec_repetition:
        print("\n== 3. répétition « panne jamais vue » (une cause connue retirée de l'apprentissage)")
        print("\n".join(repetition(fautifs_module.SERIES, campagnes, runs, fige, graines, variantes, epoques,
                                   sans_temoins, validation, version)))
    return 0


def nom_sortie(nom: str, version: str) -> str:
    """La version entre dans le nom des sorties : gnn-validation.txt (v1, inchangé),
    gnn-validation-v2.txt, gnn-banc-validation-v3.txt…"""
    return nom if version == "v1" else nom[:-len(".txt")] + f"-{version}.txt"


def _etape_campagnes(fen: list[dict]) -> set[str]:
    return {f["campagne"] for f in _normales(fen)}


def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    graines, epoques, sans_temoins, variantes = 5, EPOQUES, False, []
    mode, avec_repetition, version = None, False, VERSION
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--verifier":
                mode = "verifier"
            elif a == "--validation":
                mode = "validation" if mode != "test" else mode
            elif a == "--test":
                mode = "test"
            elif a == "--repetition":
                avec_repetition = True
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--epoques":
                epoques = int(args.pop(0))
                if epoques < 1:
                    raise ValueError
            elif a == "--sans-temoins":
                sans_temoins = True
            elif a == "--version":
                version = args.pop(0)
                if version not in VERSIONS:
                    raise ValueError
            elif a == "--variantes":
                v = args.pop(0)
                variantes = [x for x in VARIANTES if x != "complet"] if v == "toutes" else \
                    [x.strip() for x in v.split(",") if x.strip()]
                if any(x not in VARIANTES or x == "complet" for x in variantes):
                    raise ValueError
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible (variantes : "
              + ", ".join(v for v in VARIANTES if v != "complet") + " ; versions : " + ", ".join(VERSIONS) + ")",
              file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    if mode == "verifier":
        return verifier(campagnes, runs, version)
    if mode is None and avec_repetition:
        mode = "repetition"
    if mode is None:
        print(__doc__.strip())
        return 0
    validation = mode != "test"
    if mode == "test" and not scelle_ouvert():
        print(f"REFUS  SCELLÉ FERMÉ : l'étiquette « {ETIQUETTE_SCELLE} » n'existe pas ; --test est refusé.")
        return 1
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        print(f"# campagnes lues : {', '.join(fautifs_module.SERIES)}")
        code = rapport(campagnes, runs, graines, epoques, sans_temoins, variantes, validation,
                       avec_repetition, tableau=mode != "repetition", version=version)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        base = "gnn" if mode != "repetition" else "gnn-repetition"
        cible = campagnes / nom_sortie(juge.sortie(base, fautifs_module.SERIES, validation), version)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
