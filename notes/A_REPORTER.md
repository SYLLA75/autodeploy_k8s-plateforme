# À reporter : dans les trois projets, et dans le rapport CSI

Tenu à jour à chaque étape du plan (phases A à F). Deux listes :
ce qu'il faudra **porter dans le code** des trois projets refondus, et ce qu'il
faudra **réécrire dans le rapport CSI**. Le détail de chaque étape (mesures,
chiffres, vérifications) est dans `notes/JOURNAL.md` ; ici, seulement quoi
changer et où.

Point de départ de tout le travail : commit `95ad49b` (lignes de base du
18 sept.). Tout ce qui a changé depuis, en une commande :

```bash
git diff 95ad49b..plan-phases -- apps/ campagne.sh PROCEDURE.md graphe_en/
```

---

## 1. Code à porter dans les trois projets

Projets : `~/coordination-fault-bench`, `~/banc-fautes-coordination`,
`~/coordination-fault-bench-web`. Ce ne sont pas des dépôts git et leurs
fichiers sont renommés (`campaign.sh`, `graphe/`…) : porter **par le sens**,
pas en appliquant le diff tel quel. Décidé le 26 sept. : en une seule fois,
à la fin, « une fois qu'on aura quelque chose de propre ».

| étape | quoi | fichiers | commits |
|---|---|---|---|
| A.2 | relation `queries` : appelant → pod de la base (spans CLIENT `db.system`), 5 nombres mesurés chez l'appelant ; adresse → pod par `graph.databases` | `graphe_en/edges.py`, `settings.py`, `config.example.yaml` | 89881ed, 0907f77 |
| A.4 | 4 nombres réseau pour l'hôte (`net_rx_rate`, `net_tx_rate`, `net_drop_rate`, `tcp_retrans_ratio`), carte physique seulement ; hôte 5 → 9 nombres ; métriques gardées par la collecte | `graphe_en/features.py`, `apps/metrics-keep.txt` | 0426a09, 5e3f0bd |
| série 2 | cibles tournantes : `--cible x,y,z`, une cible par injection, vérifiées avant le départ (`panne.sh verifier`) | `campagne.sh`, `apps/panne.sh`, `PROCEDURE.md` | 58c9691 |
| A.7 | les figures dessinent `queries` et le réseau des hôtes | `graphe_en/render.py`, `README.md` | a87bb6a |
| A.8 | **flèches mises à l'échelle** comme les nœuds (même référence saine) ; le manifest dit quel code a construit le run, quelle base, quelle mise à l'échelle ; `run.py` affiche la raison d'un refus ; écart 4 du manifest corrigé | `graphe_en/export_pyg.py`, `snapshot.py`, `run.py` | 440e8af |
| A.8 | le gel : ce qui est figé et sa vérification | `graphe_en/graphe_fige.json`, `gel.py` (nouveaux), `LEXIQUE.md`, `README.md` | 440e8af, 100945c, étiquette `graphe-fige` |
| B.1 | le fautif de chaque injection et les règles de jugement, écrits avant tout calcul | `graphe_en/fautifs.py` (nouveau) | e338da4, 3c5aa84 |

| B.2 | le juge commun : lecture des graphes figés, étiquette des minutes, coupure, notation, essais du juge | `graphe_en/juge.py` (nouveau), `fautifs.py` | 5 commits jusqu'à 519c686 |

| B.3 | témoin 1, le tableau équitable : cases + résumés sans identité, 2 forêts, rejet des deux côtés, 5 graines ; juge : cause jamais vue à part | `graphe_en/temoin_tableau.py` (nouveau), `juge.py`, `fautifs.py` | jusqu'à 96d2622 |

**Encore à coder, pas encore fait :**
- avant la prochaine campagne (début de C) : `campagne.sh` écrit le
  placement des pods (pod → machine) dans le compte rendu de chaque campagne.

**À ne jamais porter :** `graphe_en/config.yaml` (identifiants),
`scaler.json` (propre à une référence saine), `runs/` (données).

---

## 2. Rapport CSI à réécrire

Fichier : `~/CSI_REPORT_2026/rapport/rapport.tex`. Les numéros de ligne datent
du 24 sept. : chercher la phrase. À appliquer seulement quand tu le décides,
en respectant tes règles de prose. Vérifier aussi les diapositives qui
reprennent la perspective (19 et 20 de la version allégée, 16 de la plénière).

### Faux ou contradictoire
1. l. 836, section 7, « conçues pour que ce tableau échoue » : contredit 3.3.
   Dire : pannes réelles dont la marque tombe loin de la file.
2. l. 841-842, « les quatre mêmes causes » avec la base lente : la base lente
   appelle une autre équipe, c'est une **5e cause** (décidé le 24 sept.).
3. l. 843, « toujours du côté du consommateur » : faux pour la cause 1.
4. l. 820-824, raisons R-GCN contre HGT : HGT a aussi des poids par relation ;
   retirer une relation marche avec tout modèle ; garder le petit nombre de
   paramètres (« très peu d'injections »).
5. l. 634-636, 5.3, « la réplique gelée se noierait » : faux (706 contre
   1 081 ms, 3 → 2 lecteurs). Dire : on saurait qu'une réplique décroche,
   sans savoir laquelle.

### Affirmé sans preuve, à adoucir
6. l. 829 « signale et localise », l. 838 « fournit directement » : les
   victimes d'une panne qui se propage s'écartent aussi.
7. l. 809 « découle d'un état de l'art » : l'état de l'art justifie le graphe,
   pas le GNN ; dire qu'il sera comparé à une règle qui suit les flèches.
8. l. 348, 4.1, `executes on` sert la cause 3 : les nombres de l'hôte ont
   suffi ; la flèche ne sert que si plusieurs hôtes sont chargés.
9. l. 853, 5e relation « vers la base » : fait (A.2), vers le pod leader
   `tsdb-mysql-0`, depuis l'adresse donnée par l'appelant.
10. l. 404, 4.2, « aucune source ne l'expose » : « aucune des sources
    collectées sur la plateforme ».

### Précisions
11. l. 152, H1 : « une méthode qui lit cette représentation, flèches
    comprises » ; scinder H1 (file comme nœud, relations).
12. l. 710 et 779, « sans aucune relation » : « sans les flèches, mais
    construit en les suivant à la main ».
13. l. 791 : ce sont les relations qui doivent faire leurs preuves, face à une
    règle qui les suit et à un modèle appris.
14. l. 862-866, lignes de base : ajouter le tableau équitable et la règle qui
    suit les flèches, écrits avant la base lente (phase B).
15. l. 861 : l'hôte n'avait aucun compteur réseau (tableau 3) ; il en a quatre
    depuis A.4.

### Le graphe (A.2, A.4, A.7, A.8)
16. Relation `queries` : équation (1) de 4.1 (une méta-relation de plus),
    « cinq sortes d'arêtes », figure 1, tableau 3, comptes d'arêtes en 5.3,
    diapos et schémas du graphe. Le 150/150 ne change pas.
17. Hôte à 9 nombres : tableau 3 ; ils n'existent pas dans la première série
    (absents, jamais 0).
18. **Le graphe est figé avant la base lente** (étiquette `graphe-fige`) :
    colonnes, relations, fenêtres, mise à l'échelle. Pourquoi : un graphe
    retouché après avoir vu la panne serait taillé pour la réponse.
    `gel.py` le prouve pour chaque graphe utilisé.
19. **Les flèches sont mises à l'échelle** comme les nœuds, sur la même
    référence saine, décidé au gel : c'est par elles que la base lente se
    verra. Moyennes communes à toutes les flèches d'une relation.

### Les campagnes (seconde série)
20. Décrire la seconde série et chaque raison : refaire les 5 campagnes
    (compteurs réseau absents de la première, ne pas mélanger) ; normale de
    120 min à paliers 10/25/20/15 ; cibles tournantes pour qu'aucun modèle
    n'apprenne un nom ; mêmes intensités et même plan ; pas d'exportateur
    MySQL ; `purger --redemarrer` avant chaque campagne.
21. Cause 2 « dégradation du consommateur » (tableau 2, 3.3) : le retard est
    posé sur le chemin répliques → base, mais seul ce chemin ralentit, la base
    répond vite aux douze autres appelants. C'est bien le consommateur ; la
    base lente (cause 5) ralentit tous les appelants.
22. Section 6, lignes de base : écrites **après** avoir vu la première série
    (« avant toute modélisation » est vrai, « avant d'avoir vu les données »
    serait faux). Ajouter le test à l'aveugle de la seconde série : 162/162
    pour le tableau plat et les règles, 142/162 pour la file seule.
23. Section 6, « la saturation d'hôte n'atteint pas la file » : dépend de ce
    que l'hôte porte. hote-02, 3e injection : workers0 portait aussi
    ts-order-service (replacé par un redémarrage), le dépôt tombe de 3,6 à
    0,94 msg/s. Le placement des pods est une condition d'expérience.
24. Temps de traitement des répliques selon le trafic : 706 ms à ≥ 0,95 msg/s
    par réplique, 846 ms à ≤ 0,70 (saine-09). La limite de 883–894 ms des
    lignes de base est proche de 846.
25. Flux commandes → base : grossit avec l'âge de la purge (quelques dizaines
    de ko/s à plusieurs Mo/s), vu grâce aux compteurs réseau. Même dérive
    d'une campagne à l'autre.

### Évaluation (phase B)
26. **Le fautif de chaque cause, écrit avant tout calcul** (B.1) : blocage =
    la réplique gelée ; hôte = la machine ; lenteur = les 3 répliques ;
    **charge = aucun fautif**, jugée sur la cause seulement (rien n'est cassé,
    il y a plus de voyageurs) ; base lente = le pod de la base ; jumeaux = la
    machine au réseau dégradé, jamais le leurre. Juste au rang k si un fautif
    est parmi les k premiers.
    Règles de jugement, écrites aussi avant : chaque méthode rend une alarme,
    une cause et un classement ; fausses alertes au fil du temps ; top-k sans
    et avec l'alarme ; égalités départagées contre la méthode ; mesures par
    minute ET par injection ; une panne jamais vue a pour bonne cause
    « panne inconnue » (c'est là que sert le rejet du classifieur à
    prototypes).

27b. **Le plancher « a priori »** (B.2) : une méthode qui ne lit aucune donnée,
    et classe les nœuds par le nombre de fois qu'ils ont été fautifs à
    l'apprentissage, a déjà 100 % en top-1 sur la lenteur et 100 % en top-3
    sur le blocage (toujours les trois mêmes répliques), 0 sur l'hôte. Donner
    ce plancher à côté de chaque méthode ; les mesures qui départagent sont le
    top-1 du blocage et de l'hôte, et la base lente (fautif jamais vu).

27c. **Le tableau équitable** (B.3) : tous les nombres, aucune structure de
    flèche ; 8/8 causes, 6/6 fautifs, 8–10 fausses alertes sur 120 (5 graines).
    Dire les deux versions écartées et pourquoi (chaque fois pour le
    renforcer). Répétition « panne jamais vue » : il détecte la nouveauté
    (blocage, lenteur : 100 % « inconnue ») mais ne désigne jamais le fautif
    (0 %), et ne voit pas l'hôte (3 %). Argument central pour l'écart au
    normal nœud par nœud (témoin 2, première étape du GNN).

### Limites à écrire honnêtement
27. **Dérive** : toute méthode qui apprend le « normal » se trompe si le normal
    bouge (nouvelles versions, trafic, données). Réponse : recaler la
    référence saine avec la même recette ; l'étape 1 du GNN n'a besoin que de
    données normales, sans étiquettes. Mesuré en phase B : fausses alertes sur
    les minutes normales au fil du temps.
28. **Peu d'injections** : 3 par cause et par campagne, une seule application,
    une seule file. Les résultats en minutes (162/162) sont à donner aussi par
    injection.
