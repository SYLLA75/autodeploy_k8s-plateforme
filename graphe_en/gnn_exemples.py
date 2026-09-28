"""
Le GNN « avec exemples » : les mêmes droits que le témoin 2 (écart E-2).

    ./.venv/bin/python gnn_exemples.py --verifier [--version v12|v1|v2|v3]
    ./.venv/bin/python gnn_exemples.py --validation [--graines n] [--epoques e] [--version v]
                                       [--sans-temoins] [--sans-repetition] [--variantes a,b|toutes]
    ./.venv/bin/python gnn_exemples.py --test [mêmes options]   refusé sans l'étiquette gnn-fige

Phase E. Écrit d'après notes/GNN_SPEC.md, §12 (écart E-2, décidé par
l'utilisateur, écrit avant tout calcul), avec §5 (profils, prototypes, rejet) et
§11 (versions de l'étape 1). Importe gnn.py (l'étape 1, le post-traitement, les
prototypes et le rejet) et temoin_noeud.py (les réglages du témoin 2) sans les
modifier.

POURQUOI : le témoin 2 « avec exemples » apprend l'alarme (une forêt), le fautif
  (une régression logistique partagée) et la cause (des prototypes) sur les
  pannes d'apprentissage, et ne retombe sur l'écart seul que devant « inconnue ».
  Le GNN de gnn.py désignait TOUJOURS par son étape 1, apprise sur le normal
  seul. Ici le GNN reçoit la même information que le témoin, sur ce qu'il voit,
  SANS AUCUN NOM EN ENTRÉE.

CE QUE VOIT CHAQUE APPRENANT (jamais un nom de pod ni de machine)
  le profil d'une fenêtre   §5 : pour chaque sorte et chaque colonne d'état
                            (absents compris), puis chaque relation notée et chaque
                            colonne, le plus grand et le plus petit z signé,
                            compressés (gnn.profil) ; plus S, le score de fenêtre
                            de l'étape 1 (le plus haut score de nœud, CHOIX B/H/V)
  la ligne d'un nœud        sa sorte (trois drapeaux) ; puis un bloc par sorte, le
                            sien rempli, les autres à zéro, comme le témoin 2 :
                              ses z : part positive et part négative de chaque
                                écart, log1p (temoin_noeud.ligne_noeud) ;
                              ses flèches : pour chaque relation notée, le plus
                                grand ε des flèches qui entrent et de celles qui
                                sortent, puis ce qu'il reçoit par le bout B du
                                CHOIX et son score ŝ' de l'étape 1, log1p ;
                              son plongement : la sortie de la dernière couche du
                                Reconstructeur (dimension 32), lue par un crochet en
                                lecture (register_forward_hook) sur une passe SANS
                                masque du modèle final ; gnn.py n'est pas modifié
  Les z sont ceux de l'étape 1 : calés par sorte (v1) ou par identité (v2, v3,
  §11 : l'identité cale la SORTIE, jamais l'entrée du modèle).

LES QUATRE PIÈCES (réglages du témoin 2)
  alarme  une forêt aléatoire (temoin_noeud.ARBRES arbres, graine = graine) « panne
          ou non » sur le profil + S, apprise sur des vues CROISÉES : chaque fenêtre
          d'apprentissage vue par le modèle du pli de sa campagne (appris sans elle)
          et le calage des autres plis. Son seuil, DOUBLE CROISEMENT comme le témoin
          2 (§12.1 « calé comme le témoin 2 ») : chaque campagne c mise de côté à son
          tour, la forêt apprise sans elle sur des vues du « monde sans c » (une
          fenêtre de c' vue par un modèle appris sans c ni c', 45 entraînements de
          plus par graine pour 10 campagnes, et le calage des résidus tenus de ce
          monde) ; ses normales d'apprentissage vues par le pli c et le calage du
          monde sans c ; 95e centile de leurs probabilités. L'alarme sonne si la
          forêt OU l'étape 1 (son seuil propre, gnn.GNN) sonne, comme le témoin 2
          (detecte or alarme)
  fautif  une régression logistique partagée par tous les nœuds, un poids par sorte
          et par entrée (max_iter 5000, class_weight « balanced »), apprise sur les
          nœuds des fenêtres d'apprentissage (normales et pannes), fautifs ou non,
          vues par le modèle final. Elle classe par son logit (monotone de la
          probabilité, sans les égalités d'une probabilité saturée à 1)
  cause   prototypes (temoin_noeud.Prototypes) sur les profils du modèle final, puis
          le rejet (ci-dessous)
  repli   devant « inconnue » (rejet, ou seule l'étape 1 sonne) et devant
          « normale », le classement est celui de l'étape 1 (graphe, CHOIX B/H/V) :
          c'est le cas de C et D, causes jamais vues

LE REJET : ÉCART E-3 PROPOSÉ (à écrire dans la spécification par l'utilisateur)
  Constat (relecture du 28 sept., puis mesure sur les SEULES fenêtres
  d'apprentissage) : le rejet de §5 sur le profil du GNN ne rejette pas une cause
  jamais vue. Cause mise de côté à l'apprentissage, distance au prototype le plus
  proche / seuil de rejet : blocage 0,62, lenteur 0,68 en médiane (v1, graine 0),
  sous les fenêtres connues bien classées ; profil réduit aux nœuds : 0,61 et
  0,66. Le repli promis par §12.4 pour C et D n'avait donc pas lieu. La confiance
  de la régression du fautif, elle, sépare : logit maximal d'une fenêtre, injection
  mise de côté (cause connue) 3,4 à 7,7 (5e-95e centiles), cause mise de côté
  −6,0 à −0,1.
  « E-3 » (défaut)  la régression n'a le droit de désigner que si son logit
                    maximal atteint un seuil calé HORS PLI, sur l'apprentissage
                    seul, des deux côtés : connu, chaque injection d'apprentissage
                    (d'une cause à fautif) mise de côté à son tour, régression
                    apprise sans elle, 5e centile des logits maximaux de ses
                    fenêtres bien classées ; jamais vu, chaque cause mise de côté
                    à son tour, régression apprise sans ses pannes, 95e centile
                    des logits maximaux de ses fenêtres. Seuil au milieu (au 5e
                    centile des connues si les deux se chevauchent). Sous ce
                    seuil : cause « inconnue » et repli sur l'étape 1.
                    (Premier essai, 5e centile des connues seul, comme §5 :
                    validation v1, graine 0, 60 époques, seuil 4,13, TOUTE
                    l'injection connue blocage-03 rejetée, top-1 96/115 ; d'où le
                    milieu, décidé sur ce constat de validation.)
                    Une cause sans fautif appris (la charge) garde le rejet de §5
                    pour son nom ; son classement, sans objet pour le juge, est
                    celui de l'étape 1 quand la régression n'est pas sûre
  « §5 »            la spécification à la lettre (distance au prototype, seuil de
                    gnn.GNN) : donné à côté dans le tableau, pour comparaison

LE GNN COMBINÉ v12 (écart E-5, §15 ; la version par défaut de gnn.py) : les
  parties apprises (forêt, régression du fautif, prototypes) lisent les écarts et
  le plongement de l'exemplaire v2 (sous son choix B/H/V) ; le rejet est celui du
  logit (E-4, §14, « E-3 » ci-dessus) ; le repli est le classement de l'exemplaire
  v1 sous B5/H2/V0 ; l'alarme est la forêt OU l'alarme de l'exemplaire v2.

LE BUDGET DE LA RÈGLE (« GNN, avec exemples, budget de la règle », pour decision_c) :
  les deux alarmes calées ENSEMBLE sur les mêmes normales mises de côté (scores
  tenus de l'étape 1, probabilités du double croisement) : chacune à son k-ième
  score, le plus grand k tel que leur union sonne sur au plus b = 21/249 (mis à
  l'échelle) de ces normales. Les parties apprises ne changent pas.

LA PRODUCTION (§15, rapportée à part, ne change aucune décision) : l'alarme
  « persistante » (deux minutes de suite), pour chaque GNN et chaque témoin, sur le
  test de la validation : détection, retard de détection, fausses alertes par heure.

LE SCELLÉ : juge.lire n'est appelé qu'avec fautifs.SERIES ; tout se règle et se
  note sur juge.validation (jamais « hors ») ; --test est refusé tant que
  l'étiquette gnn-fige n'existe pas.

Options :
  --verifier             les contrôles X1 à X12 (forme, déterminisme, aucun nom,
                         repli, croisement, scellé, double croisement, aucun seuil
                         ne lit le test, v12 = parties v2 et repli v1, budget de
                         la règle, mesure de production), sur toute la validation
                         à 2 époques
  --validation           le tableau de bord sur juge.validation, avec les témoins
                         et la répétition « panne jamais vue » ; écrit
                         <campagnes>/gnn-exemples-validation.txt (-v2, -v3 selon la
                         version)
  --test                 le vrai test : refusé sans l'étiquette gnn-fige
  --graines <n>          graines 0 à n−1 (défaut 5)
  --epoques <e>          époques de l'étape 1 (défaut : celui de gnn.py)
  --version <v>          la version de l'étape 1 (gnn.VERSIONS ; défaut : celle de
                         gnn.py), transmise à gnn.py s'il la connaît
  --variantes <liste>    variantes de gnn.VARIANTES en plus du complet, ou « toutes »
  --rejet <r>            « E-3 » (défaut) ou « §5 » : le rejet de la méthode
                         principale ; l'autre est toujours donné à côté
  --sans-temoins         ne recalcule pas les témoins (seulement « a priori »)
  --sans-repetition      pas de répétition « panne jamais vue »
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --help                 ce texte

Code de sortie 0 ; 1 si une campagne est refusée, un contrôle échoue ou le scellé
est fermé ; 2 sur un mauvais argument.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch

import fautifs as fautifs_module
import gel
import gnn
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
SORTES = gnn.SORTES
NOM = "GNN, avec exemples"
FILS = 4                 # fils de la forêt (des fils, pas des processus ; sans effet sur le résultat)
PROCESSUS = 4            # entraînements de l'étape 1 en parallèle : au plus 6 processus avec celui-ci et le suivi des ressources
CAUSES_NON_APPRISES = ("normale", "inconnue")
REJETS = ("E-3", "§5")
RANG_PAIRES = 500        # rangs des modèles « sans c ni c' » : graine × 1009 + 500 + i, jamais celui d'un pli


# ------------------------------------------------------------------------------
# gnn.py change en ce moment (versions de l'étape 1) : on ne lui passe que ce qu'il connaît
# ------------------------------------------------------------------------------
def _kw(fonction, **kw) -> dict:
    """Les mots-clés (version, epoques) que `fonction` accepte ; une version autre que
    v1 demandée à un gnn.py qui ne la connaît pas est refusée."""
    params = inspect.signature(fonction).parameters
    out = {}
    for k, v in kw.items():
        if v is None:
            continue
        if k in params:
            out[k] = v
        elif k == "version" and v != "v1":
            raise ValueError(f"gnn.py ne connaît pas encore de version (demandée : {v})")
        elif k != "version":
            raise ValueError(f"gnn.{getattr(fonction, '__name__', fonction)} n'accepte pas {k}")
    return out


def _version(version: str | None) -> str:
    return version or getattr(gnn, "VERSION", "v1")


def _versions() -> tuple[str, ...]:
    return tuple(getattr(gnn, "TOUTES_VERSIONS", None) or getattr(gnn, "VERSIONS", {"v1": None}))


def _exemplaires(version: str | None) -> tuple[str, str]:
    """(version du modèle de l'alarme, du classement) : v12 (écart E-5, §15) : (v2, v1)."""
    v = _version(version)
    f = getattr(gnn, "exemplaires", None)
    return f(v) if f else (v, v)


def _asinh(modele) -> bool:
    versions = getattr(gnn, "VERSIONS", None)
    return versions[modele.version]["asinh"] if versions and hasattr(modele, "version") else True


def _par_identite(version: str) -> bool:
    """Un exemplaire au moins est-il calé par identité (v2, v3 ; v12 par son alarme v2) ?"""
    versions = getattr(gnn, "VERSIONS", None)
    return bool(versions and any(versions[v].get("identite") for v in _exemplaires(version)))


# ------------------------------------------------------------------------------
# Ce que l'étape 1 dit d'une fenêtre, sans aucun nom
# ------------------------------------------------------------------------------
def plongements(modele, donnees: dict) -> dict[str, np.ndarray]:
    """{sorte : [n, H]} : la sortie de la dernière couche du Reconstructeur, lue par un
    crochet en lecture sur une passe SANS masque (versions à masque : aucun nœud
    masqué ; version 3 : sa passe unique, avant le goulot). Le modèle n'est pas modifié."""
    g = gnn.convertir(donnees, _asinh(modele))
    pris: dict[str, torch.Tensor] = {}
    crochets = [modele.norme[-1][k].register_forward_hook(
        lambda _m, _e, sortie, k=k: pris.__setitem__(k, sortie.detach().clone())) for k in SORTES]
    try:
        m = {k: torch.zeros(g.n[k], dtype=torch.bool) for k in SORTES} if getattr(modele, "masque", True) else None
        with torch.no_grad():
            modele(g, m)
    finally:
        for c in crochets:
            c.remove()
    return {k: pris[k].numpy().astype(float) for k in SORTES}


def _log1p(x: np.ndarray) -> np.ndarray:
    return np.log1p(np.maximum(x, 0.0))


class Lecteur:
    """Les vues d'une étape 1 (un modèle final, ses plis, ses calages), gardées par fenêtre."""

    def __init__(self, e1, choix: dict):
        self.e1, self.choix = e1, dict(choix)
        self.tenues = {i: s for c in e1.campagnes for i, s in e1.tenues[c]}
        self._croisees: dict[str, tuple[list[float], float, bool]] = {}
        self._lignes: dict[str, tuple] = {}
        self._sans: dict[tuple, list[float]] = {}
        self.groupes: np.ndarray | None = None

    # --- la fenêtre entière ---
    def vue(self, sortie, calage) -> tuple[list[float], float]:
        """(profil + [S], S) : le profil d'écart (§5) et le score de fenêtre de l'étape 1."""
        _, s, _ = gnn.noter_noeuds(sortie, calage, self.choix)
        return gnn.profil(sortie, calage) + [s], s

    def croisee(self, f: dict) -> tuple[list[float], float, bool]:
        """La vue CROISÉE d'une fenêtre d'apprentissage : le modèle du pli de sa campagne
        (appris sans elle) et le calage des autres plis ; le modèle final si sa campagne
        n'a pas de pli (aucune normale d'apprentissage)."""
        if f["id"] not in self._croisees:
            c = f["campagne"]
            if c in self.e1.plis:
                sortie = self.tenues.get(f["id"])
                if sortie is None:
                    sortie = gnn.residus(self.e1.plis[c], f["donnees"])
                v, s = self.vue(sortie, self.e1.calages_sans[c])
                self._croisees[f["id"]] = (v, s, True)
            else:
                v, s = self.vue(self.e1.sortie(f["donnees"]), self.e1.calage)
                self._croisees[f["id"]] = (v, s, False)
        return self._croisees[f["id"]]

    # --- le monde sans c (double croisement du seuil de la forêt) ---
    def vue_sans(self, c: str, f: dict, pp: Paires) -> list[float]:
        """La vue de f (campagne c' ≠ c) dans le monde sans c, pour apprendre la forêt sans c :
        le modèle sans c ni c' et le calage qui note c' dans ce monde ; le pli c et le calage
        du monde si c' n'a pas de normale d'apprentissage (pas de pli)."""
        cle = (c, f["id"])
        if cle not in self._sans:
            final, sans = pp.monde(c)
            if f["campagne"] in sans:
                self._sans[cle] = self.vue(pp.residus(c, f), sans[f["campagne"]])[0]
            else:
                self._sans[cle] = self.vue(gnn.residus(self.e1.plis[c], f["donnees"]), final)[0]
        return self._sans[cle]

    def vue_tenue(self, c: str, f: dict, pp: Paires) -> list[float]:
        """Une normale d'apprentissage de c vue comme du nouveau par le monde sans c : le pli c
        (appris sans elle) et le calage des résidus tenus de ce monde."""
        cle = (c, f["id"], "tenue")
        if cle not in self._sans:
            sortie = self.tenues.get(f["id"])
            if sortie is None:
                sortie = gnn.residus(self.e1.plis[c], f["donnees"])
            self._sans[cle] = self.vue(sortie, pp.monde(c)[0])[0]
        return self._sans[cle]

    # --- les nœuds ---
    def lignes(self, donnees: dict) -> tuple[list[str], np.ndarray, dict, float, list[float]]:
        """(clés, lignes des nœuds pour la régression, scores ŝ' de l'étape 1, S, profil + [S]),
        par le modèle final. Aucun nom n'entre dans une ligne : les clés ne servent qu'à la
        réponse."""
        e1, cal = self.e1, self.e1.calage
        sortie = e1.sortie(donnees)
        z_n, _, _, eps = gnn.ecarts(sortie, cal)
        scores1, s, _ = gnn.noter_noeuds(sortie, cal, self.choix)
        cles = sortie.cles()
        sp = np.array([scores1[c] for c in cles], dtype=float)
        recu = gnn.bout(self.choix["bout"], sortie, eps, cal.kappa)
        entre, sort = {}, {}
        for rel in gnn.CHIFFREES:
            entre[rel], sort[rel] = np.zeros(sortie.total), np.zeros(sortie.total)
            if rel in eps and len(eps[rel]):
                src, dst = sortie.globaux(rel)
                np.maximum.at(entre[rel], dst, eps[rel])
                np.maximum.at(sort[rel], src, eps[rel])
        fl = np.stack([_log1p(entre[r]) if j == 0 else _log1p(sort[r])
                       for r in gnn.CHIFFREES for j in (0, 1)] + [_log1p(recu), _log1p(sp)], 1)
        emb = plongements(e1.modele, donnees)
        largeur_z = {k: z_n[k].shape[1] for k in SORTES}
        largeur_e = {k: emb[k].shape[1] for k in SORTES}
        blocs = []
        for k in SORTES:
            o, n = sortie.decal[k], sortie.n[k]
            ligne = [np.full((n, 1), 1.0 if kk == k else 0.0) for kk in SORTES]
            for kk in SORTES:                                     # les z, part positive et négative
                if kk == k:
                    z = np.nan_to_num(z_n[k], nan=0.0)
                    pn = np.empty((n, 2 * largeur_z[k]))
                    pn[:, 0::2], pn[:, 1::2] = _log1p(z), _log1p(-z)
                    ligne.append(pn)
                else:
                    ligne.append(np.zeros((n, 2 * largeur_z[kk])))
            for kk in SORTES:                                     # les flèches et l'étape 1
                ligne.append(fl[o:o + n] if kk == k else np.zeros((n, fl.shape[1])))
            for kk in SORTES:                                     # le plongement
                ligne.append(emb[k] if kk == k else np.zeros((n, largeur_e[kk])))
            blocs.append(np.concatenate(ligne, 1))
        x = np.concatenate(blocs, 0)
        if self.groupes is None:                                  # le nom de chaque colonne, pour l'ablation
            nf = fl.shape[1] - 1
            self.groupes = np.array(["sorte"] * len(SORTES)
                                    + [g for kk in SORTES for g in ["z"] * (2 * largeur_z[kk])]
                                    + [g for kk in SORTES for g in ["flèches"] * nf + ["étape 1"]]
                                    + [g for kk in SORTES for g in ["plongement"] * largeur_e[kk]])
        return cles, x, scores1, s, gnn.profil(sortie, cal) + [s]

    def lignes_de(self, f: dict) -> tuple:
        if f["id"] not in self._lignes:
            self._lignes[f["id"]] = self.lignes(f["donnees"])
        return self._lignes[f["id"]]


_LECTEURS: dict[tuple, Lecteur] = {}


def lecteur(e1, choix: dict) -> Lecteur:
    """Un lecteur par (étape 1, CHOIX) : les graines d'une même étape 1 partagent ses vues.
    Les étapes 1 restent dans gnn._CACHE, leur id ne se réemploie pas."""
    cle = (id(e1), tuple(sorted(choix.items())))
    if cle not in _LECTEURS:
        _LECTEURS[cle] = Lecteur(e1, choix)
    return _LECTEURS[cle]


# ------------------------------------------------------------------------------
# Le double croisement du seuil de la forêt (comme temoin_noeud : normaux.sans(c', c))
# ------------------------------------------------------------------------------
_ETATS_PAIRES: dict[tuple, dict] = {}      # clé de l'étape 1 -> {(c, c') : state_dict}
_PAIRES: dict[tuple, "Paires"] = {}


def _cle_e1(e1, normales: list[dict]) -> tuple:
    return (e1.version, e1.variante, e1.graine, e1.epoques, frozenset(f["id"] for f in normales))


def _paires_de(e1) -> list[tuple[str, str]]:
    cs = e1.campagnes
    return [(a, b) for i, a in enumerate(cs) for b in cs[i + 1:]]


def _taches_paires(e1, normales: list[dict]) -> list[tuple]:
    """Une tâche de gnn.entrainer_tous par paire {c, c'} : les normales sans c ni c', même
    recette que les plis de gnn.py (variante, graine, époques, version), rang RANG_PAIRES + i."""
    modele = gnn._taches(normales, e1.dims, e1.variante, e1.graine, e1.epoques,
                         **_kw(gnn._taches, version=e1.version))[0]
    out = []
    for i, (a, b) in enumerate(_paires_de(e1)):
        t = list(modele)
        t[0] = tuple(id(f["donnees"]) for f in normales if f["campagne"] not in (a, b))
        t[4] = RANG_PAIRES + i
        out.append(tuple(t))
    return out


def preparer_paires(fen: list[dict], fige: dict, graines: int, variantes, epoques: int, version) -> float:
    """Tous les modèles « sans c ni c' » manquants, en une fois (après gnn.preparer)."""
    debut = time.perf_counter()
    normales = gnn._normales(fen)
    taches, a_faire = [], []
    va = _exemplaires(version)[0]         # les parties apprises lisent l'exemplaire de l'alarme
    for v in variantes:
        for g in range(graines):
            e1 = gnn.etape1(fen, fige, v, g, epoques, **_kw(gnn.etape1, version=va))
            cle = _cle_e1(e1, normales)
            if cle in _ETATS_PAIRES:
                continue
            t = _taches_paires(e1, normales)
            a_faire.append((cle, e1, len(taches), len(t)))
            taches += t
    if taches:
        asinh = _asinh(a_faire[0][1].modele)
        graphes = {id(f["donnees"]): gnn.convertir(f["donnees"], asinh) for f in normales}
        etats = gnn.entrainer_tous(taches, graphes)
        for cle, e1, d, n in a_faire:
            _ETATS_PAIRES[cle] = {p: etats[d + i][0] for i, p in enumerate(_paires_de(e1))}
    return time.perf_counter() - debut


class Paires:
    """Le « monde sans c » de chaque campagne c : son modèle final est le pli c de
    l'étape 1 ; ses plis, les modèles appris sans c ni c' ; ses résidus tenus, les
    normales de c' notées par le modèle sans c ni c'. Le calage du monde sans c vient
    de tous ses résidus tenus ; celui qui note c', des résidus tenus des autres."""

    def __init__(self, e1, normales: list[dict]):
        self.e1, self.normales = e1, normales
        cle = _cle_e1(e1, normales)
        if cle not in _ETATS_PAIRES:
            etats = gnn.entrainer_tous(_taches_paires(e1, normales),
                                       {id(f["donnees"]): gnn.convertir(f["donnees"], _asinh(e1.modele))
                                        for f in normales})
            _ETATS_PAIRES[cle] = {p: etats[i][0] for i, p in enumerate(_paires_de(e1))}
        kw = _kw(gnn.charger, version=e1.version)
        self.modeles = {p: gnn.charger(etat, e1.dims, e1.variante, **kw) for p, etat in _ETATS_PAIRES[cle].items()}
        # Pour --verifier : les campagnes vues par chaque modèle de paire.
        self.vues_par = {(a, b): {f["campagne"] for f in normales if f["campagne"] not in (a, b)}
                         for a, b in _paires_de(e1)}
        self._mondes: dict[str, tuple] = {}
        self._residus: dict[tuple, object] = {}

    def modele(self, c: str, c2: str):
        return self.modeles[(c, c2) if (c, c2) in self.modeles else (c2, c)]

    def residus(self, c: str, f: dict):
        """Les résidus de f (de la campagne c' ≠ c, qui a un pli) dans le monde sans c."""
        cle = (c, f["id"])
        if cle not in self._residus:
            self._residus[cle] = gnn.residus(self.modele(c, f["campagne"]), f["donnees"])
        return self._residus[cle]

    def monde(self, c: str) -> tuple:
        """(calage du monde sans c, {c' : calage qui note c' dans ce monde})."""
        if c not in self._mondes:
            e1 = self.e1
            tenues = {c2: [self.residus(c, f) for f in self.normales if f["campagne"] == c2]
                      for c2 in e1.campagnes if c2 != c}
            kw = _kw(gnn.Calage, version=e1.version)
            notees = e1.modele.notees
            final = gnn.Calage([s for v in tenues.values() for s in v], e1.variante, notees, **kw)
            sans = {c2: gnn.Calage([s for c3, v in tenues.items() if c3 != c2 for s in v], e1.variante, notees, **kw)
                    for c2 in tenues}
            self._mondes[c] = (final, sans)
        return self._mondes[c]


def paires(e1, normales: list[dict]) -> Paires:
    cle = _cle_e1(e1, normales)
    if cle not in _PAIRES:
        _PAIRES[cle] = Paires(e1, normales)
    return _PAIRES[cle]


# ------------------------------------------------------------------------------
# La méthode
# ------------------------------------------------------------------------------
class GNNExemples:
    """
    Le GNN « avec exemples » (§12) : l'étape 1 de gnn.py, puis une alarme, un fautif et
    une cause appris sur les pannes d'apprentissage, comme le témoin 2 ; repli sur le
    classement de l'étape 1 devant « inconnue » et « normale ».
    """

    def __init__(self, fen: list[dict], fige: dict, graine: int = 0, version: str | None = None,
                 variante: str = "complet", epoques: int | None = None, rejet: str = "E-3"):
        import numpy as np_
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        if rejet not in REJETS:
            raise ValueError(f"rejet inconnu : {rejet}")
        self.graine, self.variante, self.version, self.rejet = graine, variante, _version(version), rejet
        self.base = gnn.GNN(fen, fige, graine=graine, variante=variante, reglage="avec exemples",
                            **_kw(gnn.GNN, version=version, epoques=epoques))
        # Les parties apprises lisent l'exemplaire de l'ALARME (v12 : v2, sous son choix) ; le
        # repli est le classement de la méthode sans exemples (v12 : l'exemplaire v1, B5/H2/V0).
        self.e1 = getattr(self.base, "etape1_alarme", self.base.etape1)
        self.choix = getattr(self.base, "choix_alarme", self.base.choix)
        self.combinee = bool(getattr(self.base, "combinee", False))
        self.lecteur = lecteur(self.e1, self.choix)
        garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
        normales = [f for f in garde if f["etiquette"] == "normale"]
        pannes = [f for f in garde if f["etiquette"] == "panne"]
        panne = {f["id"]: 1 if f["etiquette"] == "panne" else 0 for f in garde}
        if len(set(panne.values())) < 2:
            raise ValueError("avec exemples : aucune fenêtre de panne à l'apprentissage")
        self.apprises = sorted({f["cause"] for f in pannes})
        foret = lambda: RandomForestClassifier(n_estimators=tn.ARBRES, random_state=graine, n_jobs=FILS)

        # 1. L'alarme apprise : une forêt sur des vues croisées.
        vues = {f["id"]: self.lecteur.croisee(f) for f in garde}
        self.croisees = (sum(1 for v in vues.values() if v[2]), len(vues))

        def detecteur(fenetres: list[dict]):
            y = [panne[f["id"]] for f in fenetres]
            if len(set(y)) < 2:
                return None
            return foret().fit(np_.array([vues[f["id"]][0] for f in fenetres]), y)

        self.detecteur = detecteur(garde)
        # Son seuil, double croisement comme le témoin 2 : chaque campagne c mise de côté,
        # la forêt apprise sans elle sur les vues du monde sans c, ses normales vues comme
        # du nouveau par ce monde.
        self.paires = paires(self.e1, gnn._normales(fen))
        probas = []
        for c in self.e1.campagnes:
            reste = [f for f in garde if f["campagne"] != c]
            y = [panne[f["id"]] for f in reste]
            ici = [f for f in normales if f["campagne"] == c]
            if len(set(y)) < 2 or not ici:
                continue
            d = foret().fit(np_.array([self.lecteur.vue_sans(c, f, self.paires) for f in reste]), y)
            p = d.predict_proba(np_.array([self.lecteur.vue_tenue(c, f, self.paires) for f in ici]))
            probas += [(f["id"], float(x)) for f, x in zip(ici, p[:, list(d.classes_).index(1)])]
        self.probas = probas                 # (id, probabilité) des normales mises de côté : les budgets
        self.seuil_detecteur = tn._q([p for _, p in probas], 1 - tn.CENTILE / 100) if probas else 1.0
        # Ce que coûtent les deux alarmes ensemble, sur les mêmes fenêtres mises de côté.
        tenu = {i: s for _, i, s in self.base.tenus}
        self.calage_detecteur = (sum(1 for _, p in probas if p > self.seuil_detecteur), len(probas))
        self.calage_union = (sum(1 for i, p in probas if p > self.seuil_detecteur or tenu.get(i, -math.inf)
                                 > self.base.seuil), len(probas))

        # 2. Le fautif appris : une régression partagée par tous les nœuds.
        def regression(fenetres: list[dict]):
            xs, ys = [], []
            for f in fenetres:
                cles, x, _, _, _ = self.lecteur.lignes_de(f)
                xs.append(x)
                ys += [1 if c in f["fautifs"] else 0 for c in cles]
            r = LogisticRegression(max_iter=5000, class_weight="balanced").fit(np_.concatenate(xs), ys) \
                if 0 < sum(ys) < len(ys) else None
            return r, sum(ys), len(ys), (xs[0].shape[1] if xs else 0)

        self.fautif, self.fautifs_appris, self.lignes_apprises, self.largeur = regression(garde)
        self.apprises_ids = sorted(f["id"] for f in garde)

        # 3. La cause : prototypes et rejet de §5, ceux de gnn.GNN (profils du modèle final).
        self.prototypes, self.seuil_rejet = self.base.prototypes, self.base.seuil_rejet

        # 4. Écart E-3 : la confiance de la régression, calée hors pli, des deux côtés.
        # Connu : chaque injection d'apprentissage d'une cause à fautif mise de côté à son
        # tour, la régression apprise sans ses fenêtres ; 5e centile du logit maximal de ses
        # fenêtres bien classées (fautif en tête). Jamais vu : chaque cause apprise mise de
        # côté à son tour, la régression apprise sans ses pannes ; 95e centile du logit
        # maximal de ses fenêtres. Seuil au milieu des deux ; au 5e centile des connues si
        # les deux se chevauchent (ou s'il n'y a qu'une cause).
        self.causes_a_fautif = sorted({f["cause"] for f in pannes if f["fautifs"]})
        confiances, injections = [], sorted({(f["campagne"], f["injection"]) for f in pannes if f["fautifs"]})
        for g in injections:
            r, _, _, _ = regression([f for f in garde if f["etiquette"] != "panne"
                                     or (f["campagne"], f["injection"]) != g])
            if r is None:
                continue
            for f in (f for f in pannes if (f["campagne"], f["injection"]) == g and f["fautifs"]):
                cles, x, _, _, _ = self.lecteur.lignes_de(f)
                lg = r.decision_function(x)
                if cles[int(np_.argmax(lg))] in f["fautifs"]:
                    confiances.append(float(lg.max()))
        inconnues = []
        for c in self.apprises:
            r, _, _, _ = regression([f for f in garde if f["etiquette"] != "panne" or f["cause"] != c])
            if r is None:
                continue
            inconnues += [float(r.decision_function(self.lecteur.lignes_de(f)[1]).max())
                          for f in pannes if f["cause"] == c]
        self.q_connues = tn._q(confiances, tn.CENTILE / 100) if confiances else math.inf
        self.q_inconnues = tn._q(inconnues, 1 - tn.CENTILE / 100) if inconnues else -math.inf
        separees = bool(inconnues) and self.q_inconnues < self.q_connues
        self.seuil_confiance = (self.q_connues + self.q_inconnues) / 2 if separees else self.q_connues
        self.calage_confiance = (len(injections), len(confiances))
        self.calage_inconnues = (len(self.apprises), len(inconnues), separees)

    def seuils_au_budget(self, budget) -> tuple[float, float, int, int, int]:
        """Les deux alarmes (étape 1, forêt) calées ENSEMBLE à un budget (un nom de
        gnn.BUDGETS, sur 249 minutes, mis à l'échelle) : sur les mêmes normales mises de
        côté (scores tenus de l'étape 1, probabilités du double croisement), chacune à son
        k-ième score, le plus grand k tel que leur union sonne sur au plus b d'entre elles.
        Rend (seuil de l'étape 1, seuil de la forêt, k, union, b)."""
        tenu = {i: x for _, i, x in self.base.tenus}
        proba = dict(self.probas)
        ids = sorted(set(tenu) & set(proba))
        if len(ids) != len(tenu) or len(ids) != len(proba):
            raise ValueError("les normales mises de côté de l'étape 1 et de la forêt ne sont pas les mêmes")
        b = gnn.budget_mis_a_l_echelle(budget, len(ids))
        for k in range(b, -1, -1):
            s1 = gnn.seuil_budget([tenu[i] for i in ids], k)
            sf = gnn.seuil_budget([proba[i] for i in ids], k)
            union = sum(1 for i in ids if tenu[i] > s1 or proba[i] > sf)
            if union <= b:
                return s1, sf, k, union, b
        raise AssertionError("k = 0 fait toujours tenir le budget")

    def classement(self, donnees: dict, scores1: dict) -> dict:
        """Le classement du repli : celui de la méthode sans exemples (gnn.GNN) ; pour une
        version simple, ce sont les scores de l'étape 1 que lit la régression (scores1)."""
        if not self.combinee:
            return dict(scores1)
        return self.base.classement(donnees)[0]

    def repondre(self, donnees: dict, rejet: str | None = None, seuils: tuple[float, float] | None = None) -> dict:
        """La réponse ; `rejet` (« E-3 » ou « §5 ») remplace celui de la méthode, `seuils`
        (étape 1, forêt) ses seuils d'alarme, sans rien réapprendre : le tableau donne les
        autres réglages sur les mêmes apprentissages."""
        rejet = rejet or self.rejet
        seuil1, seuil_f = seuils or (self.base.seuil, self.seuil_detecteur)
        cles, x, scores1, s, vue = self.lecteur.lignes(donnees)
        alarme1 = bool(s > seuil1)
        proba = 0.0
        if self.detecteur is not None:
            proba = float(self.detecteur.predict_proba(np.array([vue]))[0][list(self.detecteur.classes_).index(1)])
        detecte = proba > seuil_f
        logit = self.fautif.decision_function(x) if self.fautif is not None and len(cles) else None
        confiance = float(logit.max()) if logit is not None else -math.inf
        sur = confiance >= self.seuil_confiance
        cause, brute = "normale", None
        if detecte and self.prototypes is not None:
            brute, d = self.prototypes.plus_proche(gnn.profil(self.e1.sortie(donnees), self.e1.calage))
            if rejet == "E-3" and brute in self.causes_a_fautif:
                cause = brute if sur else "inconnue"
            else:
                cause = brute if d <= self.seuil_rejet else "inconnue"
        elif detecte or alarme1:
            cause = "inconnue"
        if cause not in CAUSES_NON_APPRISES and logit is not None and (rejet == "§5" or sur):
            scores, repli = {c: float(v) for c, v in zip(cles, logit)}, False
        else:
            scores, repli = self.classement(donnees, scores1), True
        return {"alarme": bool(detecte or alarme1), "cause": cause, "scores": scores,
                "_repli": repli, "_p": proba, "_S": s, "_alarme_etape1": alarme1, "_detecte": bool(detecte),
                "_sans_rejet": brute, "_confiance": confiance, "_sur": sur}


class _AutreReglage:
    """La même méthode apprise (mêmes forêt, régression, prototypes), avec un autre rejet
    ou d'autres seuils d'alarme (un budget : GNNExemples.seuils_au_budget)."""

    def __init__(self, t: GNNExemples, rejet: str, budget=None):
        self.t, self.rejet, self.budget = t, rejet, budget
        self.seuils = None
        if budget is not None:
            s1, sf, self.k, self.union, self.b = t.seuils_au_budget(budget)
            self.seuils = (s1, sf)

    def repondre(self, donnees: dict) -> dict:
        return self.t.repondre(donnees, self.rejet, self.seuils)


_FAITS: dict[tuple, tuple] = {}


def _fabrique(fen, fige, g, version, variante, epoques, rejet, budget=None):
    """Une méthode par (fenêtres, graine, version, variante, époques) : les entrées « autre
    rejet » et « budget de la règle » du tableau reprennent celle de la méthode principale
    au lieu de la réapprendre."""
    cle = (id(fen), g, version, variante, epoques)
    if cle not in _FAITS or _FAITS[cle][0] is not fen:
        _FAITS[cle] = (fen, GNNExemples(fen, fige, graine=g, version=version, variante=variante, epoques=epoques,
                                        rejet=rejet))
    t = _FAITS[cle][1]
    return t if t.rejet == rejet and budget is None else _AutreReglage(t, rejet, budget)


NOM_BUDGET = f"{NOM}, budget de la règle"


def methodes(fige: dict, epoques: int | None = None, version: str | None = None,
             variantes=(), rejet: str = "E-3", budgets: bool = False) -> list[tuple[str, object, bool]]:
    """(nom, fabrique(fen, graine), tire au hasard) : noms commençant par « GNN »
    (decision_c.methodes) ; `budgets` : aussi « GNN, avec exemples, budget de la règle »
    (les deux alarmes calées ensemble à 21/249) ; une variante de gnn.VARIANTES :
    « GNN <variante>, avec exemples »."""
    out = [(NOM, lambda fen, g: _fabrique(fen, fige, g, version, "complet", epoques, rejet), True)]
    if budgets:
        out.append((NOM_BUDGET, lambda fen, g: _fabrique(fen, fige, g, version, "complet", epoques, rejet, "règle"),
                    True))
    for v in variantes:
        if v != "complet":
            out.append((f"GNN {v}, avec exemples",
                        lambda fen, g, v=v: _fabrique(fen, fige, g, version, v, epoques, rejet), True))
    return out


def nom_autre(rejet: str) -> str:
    autre = REJETS[1] if rejet == REJETS[0] else REJETS[0]
    return f"{NOM}, rejet {autre}" + (" (spec)" if autre == "§5" else " (proposé)")


# ------------------------------------------------------------------------------
# --verifier
# ------------------------------------------------------------------------------
def _propre(rep: dict) -> dict:
    return {k: v for k, v in rep.items() if not k.startswith("_")}


def _test(fen: list[dict]) -> list[dict]:
    return [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]


def _echantillon(fen: list[dict]) -> list[dict]:
    """Deux fenêtres de panne du test par cause, et quatre normales du test."""
    test = _test(fen)
    out, par = [], Counter()
    for f in test:
        if f["etiquette"] == "panne" and par[f["cause"]] < 2:
            out.append(f)
            par[f["cause"]] += 1
    return out + [f for f in test if f["etiquette"] == "normale"][:4]


def verifier(campagnes: Path, runs: Path, version: str | None) -> int:
    gnn._un_fil()
    gnn.PROCESSUS = min(gnn.PROCESSUS, PROCESSUS)
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    gnn.charger_echelle(fige)
    v = _version(version)
    fen = juge.validation(juge.lire(fautifs_module.SERIES, campagnes, runs))
    epo = 2
    debut = time.perf_counter()
    gnn.preparer(fen, fige, graines=2, variantes=("complet",), epoques=epo,
                 **_kw(gnn.preparer, version=version))
    a = GNNExemples(fen, fige, graine=0, version=version, epoques=epo)
    print(f"# version {v} de l'étape 1 ; toute la validation, {epo} époques ; étape 1 et méthode en "
          f"{time.perf_counter() - debut:.0f} s ; {a.largeur} entrées par nœud ; "
          f"{a.croisees[0]}/{a.croisees[1]} vues croisées")
    test = _test(fen)
    resultats = {}

    # X1 : la forme de chaque réponse (juge.verifier, toutes les clés, nombres finis).
    soucis, reps = [], {}
    for f in test:
        rep = a.repondre(f["donnees"])
        reps[f["id"]] = rep
        try:
            juge.verifier(f, _propre(rep))
        except ValueError as e:
            soucis.append(str(e))
            continue
        if list(rep["scores"]) != juge.noeuds(f["donnees"]):
            soucis.append(f"{f['id']} : les clés ne sont pas tous les nœuds")
        if any(x is None or not math.isfinite(x) for x in rep["scores"].values()):
            soucis.append(f"{f['id']} : un score manque ou n'est pas fini")
        if not isinstance(rep["alarme"], bool):
            soucis.append(f"{f['id']} : alarme {type(rep['alarme']).__name__}")
        if rep["cause"] not in set(CAUSES_NON_APPRISES) | set(a.apprises):
            soucis.append(f"{f['id']} : cause {rep['cause']}")
    resultats["X1 forme des réponses"] = (not soucis, f"{len(test)} fenêtres du test de validation"
                                          + (f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else ""))

    # X2 : le déterminisme par graine.
    b = GNNExemples(fen, fige, graine=0, version=version, epoques=epo)
    c = GNNExemples(fen, fige, graine=1, version=version, epoques=epo)
    ech = _echantillon(fen)
    meme = all(b.repondre(f["donnees"]) == reps[f["id"]] for f in test)
    autre = any(c.repondre(f["donnees"])["_p"] != reps[f["id"]]["_p"] for f in ech)
    memes_seuils = (b.seuil_detecteur, b.seuil_confiance) == (a.seuil_detecteur, a.seuil_confiance)
    resultats["X2 déterminisme par graine"] = (
        meme and autre and memes_seuils,
        f"graine 0 refaite : réponses identiques {meme} ({len(test)} fenêtres), seuils du détecteur et de "
        f"confiance identiques {memes_seuils} ; graine 1 : autre probabilité {autre}")

    # X3 : aucune entrée nominative. Pods de Deployment renommés (autre hachage, autre
    # suffixe) et lignes permutées : mêmes réponses par clé. v1 (calage par sorte) : TOUT
    # renommé (pods, StatefulSet, machines). Et, pour toute version, les plongements
    # (sortie du modèle) sont les mêmes quand tout est renommé.
    tout = not _par_identite(v)
    pire, pire_emb, diff = 0.0, 0.0, []
    for f in ech:
        d2, renomme = gnn._permuter(f["donnees"], 7, tout)
        r1, r2 = a.repondre(f["donnees"]), a.repondre(d2)
        if (r1["alarme"], r1["cause"], r1["_repli"]) != (r2["alarme"], r2["cause"], r2["_repli"]):
            diff.append(f["id"])
        pire = max(pire, abs(r1["_p"] - r2["_p"]), *(abs(r1["scores"][k] - r2["scores"][renomme[k]])
                                                    for k in r1["scores"]))
        d3, renomme3 = gnn._permuter(f["donnees"], 11, True)
        e1_, e3 = plongements(a.e1.modele, f["donnees"]), plongements(a.e1.modele, d3)
        for k in SORTES:
            n1 = list(f["donnees"]["nodes"][k]["names"])
            n3 = list(d3["nodes"][k]["names"])
            place3 = {nom: i for i, nom in enumerate(n3)}
            for i, nom in enumerate(n1):
                j = place3[renomme3[juge._cle(k, nom)].split(":", 1)[1]]
                pire_emb = max(pire_emb, float(np.abs(e1_[k][i] - e3[k][j]).max()))
    renommage = "tout renommé" if tout else "pods de Deployment renommés dans leur service"
    resultats["X3 aucune entrée nominative"] = (
        not diff and pire <= 1e-4 and pire_emb <= 1e-5,
        f"{len(ech)} fenêtres ({renommage}, lignes et flèches permutées) : alarme, cause, repli identiques "
        f"{not diff} ; plus grand écart de score ou de probabilité {pire:.2e} ; plongements, tout renommé : "
        f"{pire_emb:.2e}")

    # X4 : le repli. Cause « normale » ou « inconnue », ou (E-3) régression pas sûre : les
    # scores de l'étape 1, à l'identique ; sinon le logit de la régression. Et, en E-3, une
    # cause à fautif n'est nommée que si la régression est sûre.
    mauvais, n_repli, n_appris = [], 0, 0
    for f in test:
        rep = reps[f["id"]]
        cles, x, scores1, _, _ = a.lecteur.lignes(f["donnees"])
        classement = a.base.classement(f["donnees"])[0] if hasattr(a.base, "classement") else scores1
        if rep["cause"] in a.causes_a_fautif and not rep["_sur"]:
            mauvais.append(f["id"])
        if rep["cause"] in CAUSES_NON_APPRISES or not rep["_sur"]:
            n_repli += 1
            if rep["scores"] != classement or not rep["_repli"]:
                mauvais.append(f["id"])
        else:
            n_appris += 1
            logit = a.fautif.decision_function(x)
            if rep["_repli"] or any(rep["scores"][k] != float(l) for k, l in zip(cles, logit)):
                mauvais.append(f["id"])
    resultats["X4 repli sur l'étape 1"] = (not mauvais, f"{n_repli} réponses « normale », « inconnue » ou pas "
                                                         f"sûres classées par l'étape 1 (exemplaire "
                                                         f"{a.base.etape1.version}, {gnn.nom_choix(a.base.choix)}), "
                                                         f"{n_appris} par la régression "
                                                         f"(seuil de confiance {a.seuil_confiance:.2f})"
                                           + (f" ; {len(mauvais)} fausses, dont {mauvais[0]}" if mauvais else ""))

    # X5 : le croisement. Les normales vues croisées ont le score tenu de gnn.GNN.
    tenu = {i: s for _, i, s in a.base.tenus}
    normales = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] == "normale"]
    ecart = max(abs(a.lecteur.croisee(f)[1] - tenu[f["id"]]) for f in normales)
    resultats["X5 vues croisées"] = (ecart == 0.0, f"{len(normales)} normales d'apprentissage : S croisé = S tenu "
                                                   f"de l'étape 1 (plus grand écart {ecart:.1e})")

    # X6 : alarme = forêt ou étape 1 ; la cause ne vient des prototypes que sous la forêt.
    incoherent = [i for i, r in reps.items()
                  if r["alarme"] != (r["_detecte"] or r["_alarme_etape1"])
                  or (r["cause"] in a.apprises and not r["_detecte"])
                  or (r["cause"] == "normale") == r["alarme"]]
    resultats["X6 alarme et cause"] = (not incoherent, f"{len(reps)} réponses"
                                       + (f" ; {len(incoherent)} incohérentes, dont {incoherent[0]}"
                                          if incoherent else ""))

    # X8 : le double croisement. Chaque modèle de paire apprend sur toutes les normales
    # d'apprentissage sauf celles de c et c', et son germe n'est celui d'aucun pli.
    normales_app = gnn._normales(fen)
    par_id = {id(f["donnees"]): f["campagne"] for f in normales_app}
    taches = _taches_paires(a.e1, normales_app)
    faux = []
    for (c1, c2), t in zip(_paires_de(a.e1), taches):
        vues_ici = {par_id[i] for i in t[0]}
        if vues_ici & {c1, c2} or vues_ici != set(a.e1.campagnes) - {c1, c2}:
            faux.append(f"{c1}+{c2}")
    germes_plis = {g * 1009 + r for g in range(5) for r in range(len(a.e1.campagnes) + 1)}
    germes_paires = {g * 1009 + t[4] for g in range(5) for t in taches}
    resultats["X8 double croisement"] = (
        not faux and not germes_plis & germes_paires and len(taches) == len(a.paires.modeles),
        f"{len(taches)} modèles « sans c ni c' » ; normales vues exactement les autres campagnes "
        f"{not faux} ; germes distincts de ceux des plis {not germes_plis & germes_paires} ; seuil du détecteur "
        f"{a.seuil_detecteur:.3f} ({a.calage_detecteur[0]}/{a.calage_detecteur[1]} au-dessus)"
        + (f" ; paires fausses : {', '.join(faux[:3])}" if faux else ""))

    # X9 : aucun seuil ne lit le test. Les fenêtres de test retirées, la méthode refaite
    # donne les mêmes seuils (détecteur, confiance, rejet) et la même régression.
    sans_test = [f for f in fen if f["jeu"] != "test"]
    d = GNNExemples(sans_test, fige, graine=0, version=version, epoques=epo)
    memes = ((d.seuil_detecteur, d.seuil_confiance, d.seuil_rejet) == (a.seuil_detecteur, a.seuil_confiance,
                                                                        a.seuil_rejet)
             and np.array_equal(d.fautif.coef_, a.fautif.coef_))
    resultats["X9 seuils sans le test"] = (memes, f"fenêtres de test retirées ({len(fen) - len(sans_test)}) : "
                                                  f"seuils et régression identiques {memes} ; confiance : "
                                                  f"{_calage_confiance(a)}")

    # X10 (v12, écart E-5, §15) : les parties apprises sont celles de l'exemplaire de
    # l'alarme (v2) — mêmes seuils, même régression, même forêt, mêmes réponses hors repli
    # que le GNN avec exemples de la version v2 — et le repli est le classement de
    # l'exemplaire v1 sous B5/H2/V0 (les scores de gnn.GNN en version v1).
    va, vc = _exemplaires(version)
    if va != vc:
        e2 = GNNExemples(fen, fige, graine=0, version=va, epoques=epo)
        c1 = gnn.GNN(fen, fige, graine=0, reglage="sans exemples", epoques=epo, version=vc)
        memes_parts = ((e2.seuil_detecteur, e2.seuil_confiance, e2.seuil_rejet) ==
                       (a.seuil_detecteur, a.seuil_confiance, a.seuil_rejet)
                       and np.array_equal(e2.fautif.coef_, a.fautif.coef_) and a.e1 is e2.e1)
        soucis10 = []
        for f in test:
            r12, r2 = reps[f["id"]], e2.repondre(f["donnees"])
            for k in ("alarme", "cause", "_p", "_S", "_alarme_etape1", "_detecte", "_confiance", "_sur", "_repli"):
                if r12[k] != r2[k]:
                    soucis10.append(f"{f['id']} : {k}")
            attendu = c1.repondre(f["donnees"])["scores"] if r12["_repli"] else r2["scores"]
            if r12["scores"] != attendu:
                soucis10.append(f"{f['id']} : scores ({'repli' if r12['_repli'] else 'régression'})")
        n_repli = sum(1 for r in reps.values() if r["_repli"])
        resultats["X10 v12 = parties apprises v2, repli v1"] = (
            memes_parts and not soucis10,
            f"seuils, régression et lecteur identiques à {va} {memes_parts} ; {len(test)} réponses : alarme, cause, "
            f"probabilité, confiance identiques à {va}, scores = régression ou, au repli ({n_repli}), ceux de "
            f"{vc} {gnn.nom_choix(c1.choix)}" + (f" ; {len(soucis10)} soucis, dont {soucis10[0]}" if soucis10 else ""))

    # X11 : le budget de la règle. Les deux alarmes calées ensemble sonnent sur au plus b des
    # normales mises de côté, et k est le plus grand qui tient ; les réponses ne diffèrent
    # de la méthode que par l'alarme (et la cause qui en dépend).
    s1, sf, k, union, b = a.seuils_au_budget("règle")
    tenu = {i: x for _, i, x in a.base.tenus}
    proba = dict(a.probas)
    recompte = sum(1 for i in tenu if tenu[i] > s1 or proba[i] > sf)
    plus = k + 1
    trop = sum(1 for i in tenu if tenu[i] > gnn.seuil_budget(list(tenu.values()), plus)
               or proba[i] > gnn.seuil_budget(list(proba.values()), plus)) > b if plus <= b else True
    ab = _AutreReglage(a, a.rejet, "règle")
    diff11 = []
    for f in test:
        rb, r0 = ab.repondre(f["donnees"]), reps[f["id"]]
        if (rb["_p"], rb["_S"], rb["_confiance"]) != (r0["_p"], r0["_S"], r0["_confiance"]) \
                or rb["alarme"] != (rb["_S"] > s1 or rb["_p"] > sf):
            diff11.append(f["id"])
    resultats["X11 budget de la règle"] = (
        recompte == union <= b and trop and not diff11,
        f"b = {b}/{len(tenu)} ; k = {k} ; les deux alarmes ensemble sur {union} normales mises de côté ; k + 1 "
        f"dépasserait {trop} ; seuils étape 1 {s1:.3f}, forêt {sf:.3f} ; {len(test)} réponses : ne diffèrent que "
        f"par l'alarme {not diff11}" + (f" ; fausses : {diff11[:3]}" if diff11 else ""))

    # X7 : le mode test est refusé sans gnn-fige.
    if gnn.scelle_ouvert():
        resultats["X7 test refusé sans gnn-fige"] = (True, "l'étiquette existe ici : refus non éprouvé")
    else:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["gnn_exemples.py", "--test", "--graines", "1", "--epoques", "1"])
        resultats["X7 test refusé sans gnn-fige"] = (code == 1, f"--test rend le code {code}")

    # X12 : la mesure de production (§15). Deux alarmes fabriquées, sans modèle : A sonne sur
    # les fenêtres de panne seules, B aussi sur la minute à cheval du début. Le retard se compte
    # depuis le début de l'injection : A 1 minute = 1 si l'injection a une minute à cheval, sinon
    # 0 ; B 1 minute = 0 ; la persistante d'une alarme qui ne sonne sur aucune minute normale
    # arrive une minute après celle d'une minute, pour chaque injection.
    tr = terrain_production(fen)
    soucis = []
    for nom_a, sonne in (("A", lambda f: f["etiquette"] == "panne"),
                         ("B", lambda f: f["etiquette"] == "panne" or any(f is fs[0] and f["etiquette"] == "a_cheval"
                                                                          for fs in tr["debuts"].values()))):
        a1 = {f["id"]: sonne(f) for f in tr["tous"]}
        r1 = retards_par_injection(a1, tr)
        rp = retards_par_injection(persistante(a1, tr["avant"]), tr)
        for cle, fs in tr["debuts"].items():
            attendu = 1 if nom_a == "A" and fs[0]["etiquette"] == "a_cheval" else 0
            if r1[cle] != attendu or rp[cle] != attendu + 1:
                soucis.append(f"{nom_a} {cle} : {r1[cle]} et {rp[cle]} au lieu de {attendu} et {attendu + 1}")
    sans_prec = sorted({f["campagne"] for f in tr["nv"] if tr["avant"][f["id"]] is None})
    resultats["X12 mesure de production"] = (
        not soucis, f"{len(tr['debuts'])} injections dont {tr['a_cheval']} commencent sur une minute à cheval ; "
                    f"retards de deux alarmes fabriquées comme prévu (persistante = 1 minute + 1) ; "
                    f"{len(tr['nv']) - len(tr['nv_p'])} minutes normales non vues sans précédente "
                    f"({', '.join(sans_prec)})" + (f" ; {len(soucis)} soucis, dont {soucis[0]}" if soucis else ""))

    echecs = 0
    for nom, (ok, detail) in sorted(resultats.items(), key=lambda x: int(x[0].split()[0][1:])):
        print(f"{nom:<32} {'réussi' if ok else 'ÉCHEC'}  ({detail})")
        echecs += not ok
    print("TOUT PASSE" if not echecs else f"{echecs} ÉCHEC(S)")
    return 0 if not echecs else 1


# ------------------------------------------------------------------------------
# --validation
# ------------------------------------------------------------------------------
def _entrees(fige: dict, epoques, version, variantes, rejet: str = "E-3") -> list[tuple[str, object]]:
    kw = _kw(gnn.GNN, version=version, epoques=epoques)
    autre = REJETS[1] if rejet == REJETS[0] else REJETS[0]
    out = [(nom, fab) for nom, fab, _ in methodes(fige, epoques, version, variantes, rejet, budgets=True)]
    out.insert(2, (nom_autre(rejet), lambda fen, g: _fabrique(fen, fige, g, version, "complet", epoques, autre)))
    out.insert(3, ("GNN, sans exemples", lambda fen, g: gnn.GNN(fen, fige, graine=g, reglage="sans exemples", **kw)))
    out.insert(4, ("GNN, sans exemples, budget de la règle",
                   lambda fen, g: gnn.GNN(fen, fige, graine=g, reglage="sans exemples", budget="règle", **kw)))
    out.insert(5, ("GNN, étape 1 + prototypes (avant E-2)", lambda fen, g: gnn.GNN(fen, fige, graine=g, **kw)))
    return out


def _notes(fen, fige, graines, epoques, version, variantes, sans_temoins, brutes: dict, rejet: str = "E-3") -> dict:
    import temoins as temoins_module
    n = {}
    test = _test(fen)
    for nom, fabrique in _entrees(fige, epoques, version, variantes, rejet):
        n[nom] = []
        brutes[nom] = []
        for g in range(graines):
            t = fabrique(fen, g)
            b = {f["id"]: t.repondre(f["donnees"]) for f in test}
            rep = {i: _propre(r) for i, r in b.items()}
            n[nom].append((juge.noter(fen, rep)[1], rep))
            brutes[nom].append((t, b))
    if not sans_temoins:
        # temoins.notes recopié, en gardant chaque témoin appris (pour la production, §15).
        for nom, fabrique, hasard in temoins_module.temoins(fige):
            n[nom], brutes[nom] = [], []
            for g in range(graines if hasard else 1):
                t = fabrique(fen, g)
                rep = temoins_module.repondre(t, fen)
                n[nom].append((juge.noter(fen, rep)[1], rep))
                brutes[nom].append((t, rep))
    rep = juge.factices(fen)["a priori"]
    n["a priori (ne lit rien)"] = [(juge.noter(fen, rep)[1], rep)]
    return n


PERSISTANCE = 2          # minutes de suite (§15, etat.txt E:81)


def terrain_production(fen: list[dict]) -> dict:
    """Les minutes du test de la validation pour la mesure de production : la minute
    précédente de chacune (même campagne, dans le test ; None sinon), les fenêtres de
    panne par injection, et le DÉBUT de chaque injection : la minute à cheval juste avant
    sa première fenêtre de panne, s'il y en a une (l'injection y commence), sinon la
    première fenêtre de panne."""
    tous = [f for f in fen if f["jeu"] == "test"]
    place = {(f["campagne"], f["numero"]): f for f in tous}
    avant = {f["id"]: place.get((f["campagne"], f["numero"] - 1)) for f in tous}
    pannes = [f for f in tous if f["etiquette"] == "panne"]
    nv = [f for f in tous if f["etiquette"] == "normale" and not f["vue"]]
    injections: dict = {}
    for f in pannes:
        injections.setdefault((f["campagne"], f["injection"]), []).append(f)
    debuts, a_cheval = {}, 0
    for cle, fs in injections.items():
        fs.sort(key=lambda f: f["numero"])
        v = avant[fs[0]["id"]]
        if v is not None and v["etiquette"] == "a_cheval":
            debuts[cle] = [v] + fs
            a_cheval += 1
        else:
            debuts[cle] = fs
    return {"tous": tous, "avant": avant, "pannes": pannes, "nv": nv,
            "nv_p": [f for f in nv if avant[f["id"]] is not None],
            "vues": [f for f in tous if f["etiquette"] == "normale" and f["vue"]],
            "injections": injections, "debuts": debuts, "a_cheval": a_cheval}


def persistante(alarme: dict, avant: dict) -> dict:
    """{id : l'alarme sonne à cette minute ET à la précédente} (PERSISTANCE = 2)."""
    return {i: alarme[i] and avant[i] is not None and alarme[avant[i]["id"]] for i in alarme}


def retards_par_injection(a: dict, tr: dict) -> dict:
    """{injection : minutes depuis son début jusqu'à la première alarme (None : jamais)}."""
    return {cle: next((f["numero"] - fs[0]["numero"] for f in fs if a[f["id"]]), None)
            for cle, fs in tr["debuts"].items()}


def production(fen: list[dict], brutes: dict) -> list[str]:
    """
    §15, rapporté à part (ne change aucune décision) : l'alarme « persistante » sonne à
    la minute i si l'alarme sonne aux minutes i et i − 1 de la même campagne (fenêtres
    d'une minute, contiguës). Sur le test de la validation ; les minutes écartées du
    juge (à cheval, vidange) sont aussi répondues, pour ne pas couper la suite. Pour
    chaque méthode, graine par graine, médiane [min–max] : détection (fenêtres de panne,
    injections), retard de détection, fausses alertes (minutes normales non vues ;
    épisodes et par heure ; saine-09 à part). La même chose pour l'alarme d'une minute.
    Le retard se compte depuis le DÉBUT de l'injection : la minute à cheval où elle
    commence quand il y en a une (juge : « a_cheval » juste avant la première fenêtre de
    panne), sinon la première fenêtre de panne ; une alarme sur la minute à cheval compte,
    pour l'alarme d'une minute comme pour la persistante (sans quoi la persistante
    paraîtrait aussi rapide que l'autre alors qu'elle sonne au moins une minute après
    elle). Les minutes normales non vues sans minute précédente dans le test ne peuvent
    pas donner d'alarme persistante : les fausses alertes sont aussi données sur les
    seules minutes qui ont une précédente, pour les deux alarmes.
    """
    tr = terrain_production(fen)
    tous, avant, pannes, nv, nv_p, vues = (tr[k] for k in ("tous", "avant", "pannes", "nv", "nv_p", "vues"))
    injections, a_cheval = tr["injections"], tr["a_cheval"]
    heures = len(nv) / 60
    m = statistics.median

    def case(v: list, total=None, fmt="{:g}") -> str:
        t = fmt.format(m(v)) + (f"/{total}" if total is not None else "")
        return t + (f" [{fmt.format(min(v))}–{fmt.format(max(v))}]" if min(v) != max(v) else "")

    out = [f"# {len(pannes)} fenêtres de panne, {len(injections)} injections ; {len(nv)} minutes normales non vues "
           f"({heures:.2f} h ; {len(nv_p)} ont une minute précédente dans le test, les {len(nv) - len(nv_p)} autres ne "
           f"peuvent pas donner d'alarme persistante), {len(vues)} de saine-09 ; persistante = {PERSISTANCE} minutes "
           f"de suite ; retard en minutes depuis le début de l'injection, la minute à cheval où elle commence "
           f"({a_cheval} injections sur {len(injections)}) ou sinon la première fenêtre de panne (0 : l'alarme sonne "
           f"dès cette minute ; la persistante ne peut sonner qu'à partir de la minute suivante, sauf si la minute "
           f"d'avant, normale, avait déjà sonné) ; « jamais » : injections non détectées"]
    for nom, liste in brutes.items():
        res = {"1": [], "p": []}
        for t, rep in liste:
            alarme = {}
            for f in tous:
                r = rep.get(f["id"])
                alarme[f["id"]] = bool((r if r is not None else t.repondre(f["donnees"]))["alarme"])
            for cle, a in (("1", alarme), ("p", persistante(alarme, avant))):
                par_inj = retards_par_injection(a, tr)
                retards = [x for x in par_inj.values() if x is not None]
                jamais = len(par_inj) - len(retards)
                episodes = sum(1 for f in nv if a[f["id"]] and not (avant[f["id"]] is not None
                                                                     and avant[f["id"]]["etiquette"] == "normale"
                                                                     and not avant[f["id"]]["vue"]
                                                                     and a[avant[f["id"]]["id"]]))
                res[cle].append({"det": sum(1 for f in pannes if a[f["id"]]), "inj": len(injections) - jamais,
                                 "retard": m(retards) if retards else math.inf, "jamais": jamais,
                                 "fa": sum(1 for f in nv if a[f["id"]]), "ep": episodes,
                                 "fa_p": sum(1 for f in nv_p if a[f["id"]]),
                                 "fa_vues": sum(1 for f in vues if a[f["id"]])})
        out.append(f"{nom}  ({len(liste)} graine{'s' if len(liste) > 1 else ''})")
        for cle, titre in (("1", "1 minute   "), ("p", "persistante")):
            r = res[cle]
            g = lambda k: [x[k] for x in r]
            ret = [x for x in g("retard") if math.isfinite(x)]
            out.append(f"    {titre} détection {case(g('det'), len(pannes))} ; injections {case(g('inj'), len(injections))}"
                       f" ; retard médian {case(ret, fmt='{:g}') + ' min' if ret else 'jamais'} ; fausses alertes "
                       f"{case(g('fa'), len(nv))} min ({case(g('fa_p'), len(nv_p))} sur celles qui ont une "
                       f"précédente), {case(g('ep'))} épisodes, "
                       f"{case([x / heures for x in g('ep')], fmt='{:.1f}')} par heure ; saine-09 "
                       f"{case(g('fa_vues'), len(vues))}")
    return out


def _repli(fen: list[dict], brutes: list[tuple], cause: str | None = None) -> str:
    """Sur les fenêtres de panne du test (d'une cause) : combien sont classées par le
    repli (l'étape 1), et le top-1 du repli et de la régression ; médiane des graines."""
    groupe = [f for f in _test(fen) if f["etiquette"] == "panne" and (cause is None or f["cause"] == cause)]
    avec = [f for f in groupe if f["fautifs"]]
    rep_n, top_r, n_r, top_a, n_a = [], [], [], [], []
    for _, b in brutes:
        rep_n.append(sum(1 for f in groupe if b[f["id"]]["_repli"]))
        r = [f for f in avec if b[f["id"]]["_repli"]]
        a = [f for f in avec if not b[f["id"]]["_repli"]]
        un = lambda f: juge.rang(f["fautifs"], b[f["id"]]["scores"], juge.noeuds(f["donnees"])) == 1
        n_r.append(len(r))
        top_r.append(sum(1 for f in r if un(f)))
        n_a.append(len(a))
        top_a.append(sum(1 for f in a if un(f)))
    m = statistics.median
    return (f"repli (classement de l'étape 1) sur {m(rep_n):g}/{len(groupe)} fenêtres de panne ; "
            f"top-1 {m(top_r):g}/{m(n_r):g} par le repli, {m(top_a):g}/{m(n_a):g} par la régression")


def _par_cause(n: dict) -> list[str]:
    """top-1 / top-3 par cause, et par injection, médiane des graines."""
    causes = ("blocage", "hote", "lenteur")
    tete = f"{'':<42}" + "".join(f"{c:>15}" for c in causes) + f"{'injections':>15}"
    out = [tete, f"{'':<42}" + "".join(f"{'top-1 / top-3':>15}" for _ in range(len(causes) + 1))]
    for nom, liste in n.items():
        cases = []
        for c in causes:
            t1 = [ch[f"top-1 {c}"][0] for ch, _ in liste if f"top-1 {c}" in ch]
            t3 = [ch[f"top-3 {c}"][0] for ch, _ in liste if f"top-3 {c}" in ch]
            tot = liste[0][0].get(f"top-1 {c}", (0, 0))[1]
            cases.append(f"{statistics.median(t1):g}/{statistics.median(t3):g} sur {tot}" if t1 else "—")
        inj = liste[0][0]["injections"]
        k1 = "top-1 (causes apprises)" if "top-1 (causes apprises)" in inj else "top-1" if "top-1" in inj else None
        k3 = "top-3 (causes apprises)" if "top-3 (causes apprises)" in inj else "top-3" if "top-3" in inj else None
        if k1 and k3:
            t1 = statistics.median(ch["injections"][k1][0] for ch, _ in liste)
            t3 = statistics.median(ch["injections"][k3][0] for ch, _ in liste)
            cases.append(f"{t1:g}/{t3:g} sur {inj[k1][1]}")
        else:
            cases.append("—")
        out.append(f"{nom[:41]:<42}" + "".join(f"{x:>15}" for x in cases))
    return out


def _en_tete(t: GNNExemples) -> list[str]:
    b, e1 = t.base, t.e1
    n = len(b.tenus)
    b25 = gnn.budget_mis_a_l_echelle("score par nœud, avec", n) if hasattr(gnn, "budget_mis_a_l_echelle") else None
    s1, sf, k, union, b21 = t.seuils_au_budget("règle")
    lignes = [
        f"# version {t.version} ; exemplaire de l'alarme et des parties apprises : étape 1 version {e1.version} "
        f"({e1.variante}, graine {e1.graine}) : {e1.epoques} époques, {len(e1.campagnes)} plis ; empreinte "
        f"{e1.empreinte[:16]} ; post-traitement {gnn.nom_choix(t.choix)} (celui de gnn.py pour cette version)"]
    if t.combinee:
        c = b.etape1
        lignes.append(f"#   exemplaire du classement (le repli) : étape 1 version {c.version} ; empreinte "
                      f"{c.empreinte[:16]} ; post-traitement {gnn.nom_choix(b.choix)} (écart E-5, §15)")
    return lignes + [
        f"#   budget de la règle ({b21}/{n}) : les deux alarmes calées ensemble, chacune à son {k}e score tenu "
        f"(étape 1 au-dessus de {s1:.3f}, forêt au-dessus de {sf:.3f}) ; elles sonnent ensemble sur {union}/{n} "
        f"normales mises de côté",
        f"#   alarme de l'étape 1 au-dessus de {b.seuil:.3f} ({b.calage_alarme[0]}/{b.calage_alarme[1]} scores tenus "
        f"au-dessus)",
        f"#   détecteur : forêt de {tn.ARBRES} arbres sur le profil + S ({t.croisees[0]}/{t.croisees[1]} fenêtres "
        f"d'apprentissage vues croisées) ; alarme au-dessus de {t.seuil_detecteur:.3f} (95e centile, "
        f"{len(e1.campagnes)} campagnes mises de côté ; {t.calage_detecteur[0]}/{t.calage_detecteur[1]} au-dessus)",
        f"#   les deux alarmes ensemble sonnent sur {t.calage_union[0]}/{t.calage_union[1]} normales mises de côté"
        + (f" (budget du témoin 2 « avec exemples » : 25/249, soit {b25}/{n})" if b25 is not None else ""),
        f"#   fautif : régression logistique partagée, {t.largeur} entrées par nœud, {t.fautifs_appris} lignes "
        f"fautives sur {t.lignes_apprises}",
        f"#   cause : {len(t.prototypes.moyennes) if t.prototypes else 0} prototypes "
        f"({', '.join(sorted(t.prototypes.moyennes)) if t.prototypes else '—'}) ; rejet §5 au-dessus de "
        f"{t.seuil_rejet:.2f} ({b.calage_rejet[0]} injections mises de côté, {b.calage_rejet[1]} fenêtres bien "
        f"classées)",
        f"#   rejet E-3 (proposé) : la régression désigne si son logit maximal atteint {t.seuil_confiance:.2f}, sinon "
        f"« inconnue » et repli ; " + _calage_confiance(t) + f" ; causes à fautif "
        f"{', '.join(t.causes_a_fautif) or '—'}, les autres gardent le rejet §5 ; méthode principale : rejet {t.rejet}",
    ]


def _calage_confiance(t: GNNExemples) -> str:
    return (f"connues {t.q_connues:.2f} (5e centile, {t.calage_confiance[0]} injections à fautif mises de côté, "
            f"{t.calage_confiance[1]} fenêtres bien classées), jamais vues {t.q_inconnues:.2f} (95e centile, "
            f"{t.calage_inconnues[0]} causes mises de côté, {t.calage_inconnues[1]} fenêtres), "
            + ("seuil au milieu" if t.calage_inconnues[2] else "CHEVAUCHEMENT : seuil au 5e centile des connues"))


def _ablation(fen: list[dict], t: GNNExemples) -> str:
    """Défaut relevé le 28 sept. : ce que chaque groupe d'entrées apporte au fautif. La
    régression refaite sur les mêmes lignes d'apprentissage, sous-ensembles de colonnes ;
    top-1 sur les fenêtres de panne du test (avec un fautif), sans l'alarme ni la cause."""
    from sklearn.linear_model import LogisticRegression
    garde = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
    avec = [f for f in _test(fen) if f["etiquette"] == "panne" and f["fautifs"]]
    lignes = [t.lecteur.lignes_de(f) for f in garde]
    x = np.concatenate([l[1] for l in lignes])
    y = [1 if c in f["fautifs"] else 0 for f, l in zip(garde, lignes) for c in l[0]]
    tests = [(f, t.lecteur.lignes(f["donnees"])) for f in avec]
    grp = t.lecteur.groupes
    out = []
    for nom, garder in (("toutes les entrées", None), ("z seuls (comme le témoin 2)", {"sorte", "z"}),
                        ("sans le plongement", {"sorte", "z", "flèches", "étape 1"}),
                        ("plongement seul", {"sorte", "plongement"}), ("ŝ' de l'étape 1 seul", {"sorte", "étape 1"})):
        m = np.ones(len(grp), bool) if garder is None else np.isin(grp, list(garder))
        r = LogisticRegression(max_iter=5000, class_weight="balanced").fit(x[:, m], y)
        par = Counter()
        for f, (cles, xt, *_ ) in tests:
            sc = dict(zip(cles, map(float, r.decision_function(xt[:, m]))))
            par[f["cause"]] += juge.rang(f["fautifs"], sc, juge.noeuds(f["donnees"])) == 1
        out.append(f"{nom} {sum(par.values())}/{len(avec)} ("
                   + ", ".join(f"{c} {par[c]}" for c in sorted({f['cause'] for f in avec})) + ")")
    return "; ".join(out)


def rapport(campagnes: Path, runs: Path, graines: int, epoques, version, variantes, sans_temoins: bool,
            avec_repetition: bool, validation: bool = True, rejet: str = "E-3") -> int:
    import temoins as temoins_module
    gnn._un_fil()
    gnn.PROCESSUS = min(gnn.PROCESSUS, PROCESSUS)
    fige, ecarts_ref, _ = gel.reference()
    if ecarts_ref:
        print(f"REFUS  {ecarts_ref[0]}")
        return 1
    try:
        if not validation:
            gnn.exiger_scelle()
        gnn.charger_echelle(fige)
        fen = juge.lire(fautifs_module.SERIES, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    v = _version(version)
    epo = epoques if epoques is not None else gnn.EPOQUES
    print("# Le GNN avec exemples (écart E-2, §12) — écrit par graphe_en/gnn_exemples.py, ne pas éditer à la main.")
    print(f"# version {v} de l'étape 1 ; graines 0 à {graines - 1} ; {epo} époques ; variantes en plus du "
          f"complet : {', '.join(variantes) or 'aucune'} ; témoins {'NON recalculés' if sans_temoins else 'recalculés'}")
    debut = time.perf_counter()
    gnn.preparer(fen, fige, graines, ("complet",) + tuple(variantes), epo, **_kw(gnn.preparer, version=version))
    d_paires = preparer_paires(fen, fige, graines, ("complet",) + tuple(variantes), epo, version)
    print(f"# étapes 1 apprises en {time.perf_counter() - debut:.0f} s, dont {d_paires:.0f} s pour les modèles "
          f"« sans c ni c' » du double croisement ({gnn.PROCESSUS} processus au plus)")
    debut = time.perf_counter()
    brutes: dict = {}
    n = _notes(fen, fige, graines, epoques, version, variantes, sans_temoins, brutes, rejet)
    t0 = brutes[NOM][0][0]
    print("\n".join(_en_tete(t0)))
    print(f"# notes en {time.perf_counter() - debut:.0f} s")
    normales = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
    print(f"\n== 1. tableau de bord ({'validation' if validation else 'test'} ; fausses alertes sur "
          f"{sum(1 for f in normales if not f['vue'])} minutes normales non vues, puis sur "
          f"{sum(1 for f in normales if f['vue'])} de saine-09)")
    print("\n".join(temoins_module.tableau_de_bord(n)))
    print("\n== 2. fautif par cause et par injection (top-1 / top-3, médiane des graines)")
    print("\n".join(_par_cause(n)))
    print(f"\n{NOM} : " + _repli(fen, brutes[NOM]))
    print("\n== 3. fausses alertes au fil du temps (fenêtres normales du test ; médiane sur les graines)")
    print("\n".join(temoins_module.fil_du_temps(fen, n)))
    print(f"\n== 4. note détaillée : {NOM}, graine 0")
    rep0 = n[NOM][0][1]
    print("\n".join(juge.noter(fen, rep0, f"{NOM}, graine 0")[0]))
    print("désigné en premier, par cause (fenêtres de panne du test)")
    print("\n".join(tn.premiers(fen, rep0)))
    b0 = brutes[NOM][0][1]
    pannes = [f for f in _test(fen) if f["etiquette"] == "panne"]
    print(f"# cause sans le rejet : {sum(1 for f in pannes if b0[f['id']]['_sans_rejet'] == f['attendue'])}/"
          f"{len(pannes)} ; alarme par la forêt seule : {sum(1 for f in pannes if b0[f['id']]['_detecte'])}/"
          f"{len(pannes)}, par l'étape 1 seule : {sum(1 for f in pannes if b0[f['id']]['_alarme_etape1'])}/"
          f"{len(pannes)} ; régression sûre (E-3) : {sum(1 for f in pannes if b0[f['id']]['_sur'])}/{len(pannes)}")
    nv = [f for f in normales if not f["vue"]]
    print(f"# fausses alertes non vues : forêt seule {sum(1 for f in nv if b0[f['id']]['_detecte'] and not b0[f['id']]['_alarme_etape1'])}, "
          f"étape 1 seule {sum(1 for f in nv if b0[f['id']]['_alarme_etape1'] and not b0[f['id']]['_detecte'])}, "
          f"les deux {sum(1 for f in nv if b0[f['id']]['_alarme_etape1'] and b0[f['id']]['_detecte'])} (sur {len(nv)})")
    print("# ablation du fautif appris (graine 0), top-1 : " + _ablation(fen, t0))
    if graines > 1:
        import temoin_tableau
        print(f"\n# {NOM}, sur {graines} graines : chaque nombre de la note")
        print("\n".join(temoin_tableau._resume_graines([c for c, _ in n[NOM]])))
    print("\n== 4 bis. production (§15, rapporté à part, ne change aucune décision) : alarme persistante, "
          f"{PERSISTANCE} minutes de suite, sur le test de la validation")
    print("\n".join(production(fen, {k: v for k, v in brutes.items() if k != nom_autre(rejet)})))
    if avec_repetition:
        print("\n== 5. répétition « panne jamais vue » (une cause connue retirée de l'apprentissage ; "
              "le repli doit s'y voir)")
        for cause in temoins_module.REPETEES:
            fen_c = juge.lire(fautifs_module.SERIES, campagnes, runs, jamais_vues=juge.JAMAIS_VUES | {cause})
            if validation:
                fen_c = juge.validation(fen_c)
            groupe = [f for f in fen_c if f["jeu"] == "test" and f["etiquette"] == "panne" and f["cause"] == cause]
            injections = len({(f["campagne"], f["injection"]) for f in groupe})
            print(f"\n{cause} retirée de l'apprentissage : {len(groupe)} fenêtres de test, {injections} injections")
            gnn.preparer(fen_c, fige, graines, ("complet",) + tuple(variantes), epo,
                         **_kw(gnn.preparer, version=version))
            preparer_paires(fen_c, fige, graines, ("complet",) + tuple(variantes), epo, version)
            br: dict = {}
            n_c = _notes(fen_c, fige, graines, epoques, version, variantes, sans_temoins, br, rejet)
            restantes = [c for c in ("blocage", "hote", "lenteur") if c != cause]
            for nom, liste in n_c.items():
                cases = []
                for titre, cle in (("détection", f"detection jamais vue : {cause}"),
                                   ("« inconnue »", f"cause jamais vue : {cause}"),
                                   ("top-1", f"top-1 jamais vue : {cause}"),
                                   ("top-3", f"top-3 jamais vue : {cause}")):
                    val = [c[cle][0] for c, _ in liste if cle in c]
                    if val:
                        cases.append(f"{titre} {temoins_module._case(val, liste[0][0][cle][1])}")
                if nom.startswith("règle"):
                    cases = [x for x in cases if not x.startswith("« inconnue »")] + ["« inconnue » sans objet"]
                # Les causes restantes (apprises) : ce que le retrait coûte sur ce que la méthode connaît.
                cases += [f"{c} top-1 {temoins_module._case([ch[f'top-1 {c}'][0] for ch, _ in liste], liste[0][0][f'top-1 {c}'][1])}"
                          for c in restantes if f"top-1 {c}" in liste[0][0]]
                print(f"  {nom[:41]:<42}" + " ; ".join(cases))
            print(f"  {NOM} : " + _repli(fen_c, br[NOM], cause))
            t_c = br[NOM][0][0]
            print(f"  {NOM}, graine 0 : seuil de confiance {t_c.seuil_confiance:.2f} ({_calage_confiance(t_c)}) ; "
                  f"rejet §5 {t_c.seuil_rejet:.2f} ; seuil du détecteur {t_c.seuil_detecteur:.3f}")
    return 0


def nom_sortie(version: str, validation: bool) -> str:
    base = juge.sortie("gnn-exemples", fautifs_module.SERIES, validation)
    return gnn.nom_sortie(base, version) if hasattr(gnn, "nom_sortie") else base


def main(argv: list[str]) -> int:
    campagnes, runs = HERE.parent / "campagnes", HERE / "runs"
    graines, epoques, version, variantes = 5, None, None, []
    mode, sans_temoins, avec_repetition, rejet = None, False, True, "E-3"
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
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--epoques":
                epoques = int(args.pop(0))
                if epoques < 1:
                    raise ValueError
            elif a == "--version":
                version = args.pop(0)
                if version not in _versions():
                    raise ValueError
            elif a == "--variantes":
                x = args.pop(0)
                variantes = [v for v in gnn.VARIANTES if v != "complet"] if x == "toutes" else \
                    [v.strip() for v in x.split(",") if v.strip()]
                if any(v not in gnn.VARIANTES or v == "complet" for v in variantes):
                    raise ValueError
            elif a == "--sans-temoins":
                sans_temoins = True
            elif a == "--sans-repetition":
                avec_repetition = False
            elif a == "--rejet":
                rejet = args.pop(0)
                if rejet not in REJETS:
                    raise ValueError
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible (versions : " + ", ".join(_versions()) + ")", file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    if mode == "verifier":
        return verifier(campagnes, runs, version)
    if mode is None:
        print(__doc__.strip())
        return 0
    if mode == "test" and not gnn.scelle_ouvert():
        print(f"REFUS  SCELLÉ FERMÉ : l'étiquette « {gnn.ETIQUETTE_SCELLE} » n'existe pas ; --test est refusé.")
        return 1
    validation = mode != "test"
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        print(f"# campagnes lues : {', '.join(fautifs_module.SERIES)}")
        code = rapport(campagnes, runs, graines, epoques, version, variantes, sans_temoins, avec_repetition,
                       validation, rejet)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / nom_sortie(_version(version), validation)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
