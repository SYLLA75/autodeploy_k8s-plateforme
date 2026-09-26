# Versions des témoins déjà notées sur le test, puis changées

Gardées pour la transparence (phase B, 26 sept. 2026). Chaque fichier est la
sortie telle qu'elle a été vue ; le journal (notes/JOURNAL.md) dit ce qui a
changé ensuite et pourquoi. Depuis, tout choix de réglage se fait sur la
validation (juge.validation), jamais sur le test.

| fichier | version | ce qui a changé après |
|---|---|---|
| temoin_tableau-974ba15.txt | témoin 1, commit 974ba15 (fautif appris case par case, rejet d'un seul côté, graine 0) | forêt partagée pour le fautif, résumés des flèches, rejet des deux côtés, 5 graines (relecture B.3) |
| temoin_noeud-4ca7001.txt | témoin 2, commit 4ca7001 (détecteur forêt, plancher par sorte) | plancher, écarts croisés, repli du fautif, prototypes mis à l'échelle (deux relectures, vérifiés sur la validation) |
| temoin_fleches-v1.txt | témoin 3, première version (jamais commitée : une limite d'alarme commune, charge nommée par le dépôt, sortie « file pleine inexpliquée → inconnue », plancher de l'ancien témoin 2) | deux limites, charge par élimination, puis relectures |

Non gardées en fichier, chiffres dans le journal : le tableau avec le rejet calé
« hors sac » (cause 33 %) ; le témoin 2 avec l'échelle par écart interquartile
seul (seuil d'alarme 138) et avec le détecteur en régression logistique (seuil
0,043, 33/120 fausses alertes au test).

Nombre de regards sur le test avant la version finale : tableau 3 (hors sac,
974ba15, 96d2622 final de B.3) ; score par nœud 4 (échelle interquartile,
logistique, 4ca7001, final) ; règle 2 (v1, final). Chaque changement a été fait
dans le sens qui renforce le témoin, ce qui rend une victoire du GNN plus
difficile, pas plus facile.
