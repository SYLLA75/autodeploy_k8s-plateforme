# Recommandations — état au 9 septembre 2026

> Tout ce qui a été relevé au cours de la mise en place de la chaîne de mesure.
> Chaque point indique s'il a été **constaté sur la grappe** ou s'il relève d'une
> **recherche externe non vérifiée**.
>
> Trois familles : ce qui touche tes **documents**, ce qui demande une
> **décision**, et ce qui reste à **faire**.

---

## 1. Défauts trouvés dans la formalisation

Constatés par lecture croisée du `.tex`, des sections 9 à 11 et de l'exemple
chiffré. Aucun ne demande de grappe pour être corrigé.

### 1.1 La flèche « déposer » est impossible sur un journal partitionné

La clé d'une file Kafka comporte trois morceaux, dont le groupe de consommateurs.
Or le producteur l'ignore : il dépose et s'en va. La fonction de résolution ne
peut donc jamais compléter la clé, et **toutes les flèches « déposer » sont
inconstructibles** sur cette famille.

**À décider** : tracer une flèche vers *chaque* groupe qui lit la destination.

### 1.2 Une même information est écrite à deux endroits — CORRIGÉ DANS LE CODE

Le débit de traitement figurait à la fois dans le vecteur de la copie de service
et sur la flèche « retirer » qui y mène.

**Conséquence** : l'ablation qui retire les flèches « retirer » ne pouvait pas
échouer, puisque l'information restait dans le vecteur. La prédiction falsifiable
de la section 10.7 était invalidée par la composition même du vecteur.

**Mesure faite depuis** — et elle est pire que le simple doublon. Les deux copies
ne portaient pas le même nombre : sur les 48 relevés de la campagne saine (12
fenêtres × 4 consommateurs), le vecteur annonçait **exactement le double** de la
flèche, rapport 2.00 partout. Le vecteur comptait des spans, la flèche comptait
des messages, et un message consommé émet deux spans.

**Correction appliquée à `graphe_en`** : la composante disparaît du vecteur, la
grandeur ne vit plus que sur la relation de consommation. Vérifié avant de
retirer : aucune copie n'avait un débit non nul sans flèche de consommation, donc
rien ne se perd. Un nœud qui a besoin du total somme ses flèches entrantes, ce
que fait de toute façon la propagation de messages.

**Découverte connexe, corrigée aussi** : les deux spans d'un message consommé ne
sont pas des copies l'un de l'autre. L'un décrit le courtier qui remet le message
sur le réseau, l'autre l'application qui le traite ; l'attribut
`network.peer.address` les sépare, 710 paires sur 710. Le temps de traitement
mélangeait les deux populations et annonçait une médiane de **0,283 ms** là où la
vraie médiane de traitement est **6,201 ms** — vingt-deux fois trop petit. Le
span de traitement est désormais seul retenu.

**Reste à faire dans le papier** : reprendre l'exemple chiffré, et corriger le
tableau des composantes.

**La chaîne française `graphe/` a été supprimée du dépôt** plutôt que corrigée :
elle portait les deux mêmes défauts et n'était plus utilisée. L'historique git la
conserve si besoin.

### 1.3 L'exemple chiffré se contredit d'un facteur dix

Le §4 pose 110 messages retirés comme un fait ; le §5.1 traite les mêmes
comptages comme échantillonnés au dixième. Les deux lectures sont incompatibles.
Avec la seconde, **l'écart entre débits vaut −16,33 msg/s** — négatif, alors que
la file accumule.

**À faire** : outiller ce contrôle de cohérence, il aurait révélé l'erreur.

### 1.4 La dimension du vecteur d'instance est tranchée

7×19 + 6 + 2×5 + 4×5 + 1 + 3 = **173**, le total annoncé. Avec 18, on obtient
166 et l'exemple devient faux.

**Cette décision disait « aucun argument formel ne pousse vers 18 ». Ce n'est
plus vrai.** Il en existe désormais deux, tous deux mesurés (§1.2) : la
composante est la même grandeur qu'une composante de relation, et la copie du
vecteur était fausse d'un facteur exactement 2. Garder 19 revient à publier une
valeur dont on sait qu'elle est double de la bonne.

**Décision révisée** : 18 dans le code. Le papier doit passer son total annoncé
de 173 à 166 et refaire l'exemple, ou bien assumer par écrit que la dix-neuvième
composante est une redite d'une composante de relation — auquel cas l'ablation
de la §10.7 doit être retirée, car elle ne peut pas échouer.

### 1.5 L'incrément est faux au moment précis qu'on veut détecter

Un compteur repart de zéro au redémarrage du conteneur. La définition suppose
qu'il ne décroît jamais. Or **la composante 15 compte justement les
redémarrages** : le formalisme attend des redémarrages tout en supposant qu'ils
n'arrivent pas. À la même fenêtre, six autres composantes deviennent absurdes.

**À faire** : réécrire l'opérateur en somme d'accroissements positifs, par série,
avant toute agrégation. Ajouter un taux de qualité comptant les remises à zéro.

### 1.6 Le taux par seconde est biaisé

On mesure entre le premier et le dernier relevé de la fenêtre, mais on divise par
la largeur entière. Le biais vaut `1 − (cadence / largeur)`, soit **−17 % à
10 secondes de cadence pour une fenêtre d'une minute**.

### 1.7 La pente est exprimée « par fenêtre », pas « par seconde »

Le dénominateur porte sur des indices entiers. Tant que le pas de glissement égale
la largeur, cela coïncide ; dès qu'ils diffèrent, deux campagnes ne sont plus
comparables.

**Contrainte jamais énoncée** : le pas de glissement doit être supérieur ou égal à
la cadence de relevé, sinon deux fenêtres consécutives partagent leur dernier
relevé et la pente dégénère.

### 1.8 Le quantile est appliqué à un histogramme

`http.server.request.duration` est un histogramme à bornes fixes plafonnées à
dix secondes, alors que le quantile est défini sur une distribution de durées
observées. Contradiction de définition — et surtout, **au-delà de dix secondes
le quantile haut n'est plus majoré**, c'est-à-dire précisément dans le régime
étudié.

**À faire** : renommer en « durée des spans de type serveur » et imposer les
durées brutes.

### 1.9 Une contrainte de charge n'est jamais posée

Le quantile 0,99 est exigé **par arête**. Pour qu'il soit défini il faut au moins
cent observations par fenêtre, et de l'ordre du millier pour qu'il soit stable.
Avec une cinquantaine d'arêtes d'appel et une fenêtre d'une minute, cela impose
**plusieurs centaines de notes par seconde**. C'est ce paramètre qui fixe la
charge à générer, pas le stockage.

### 1.10 Deux des quatre points ouverts se ferment

**Migration en cours de fenêtre** : l'identité repose sur l'identifiant unique du
pod, et un pod ne se déplace pas — il est recréé avec un identifiant neuf, donc
un nœud neuf. La proposition tient par construction. Il suffit de l'écrire, et
d'ajouter une assertion qui lève si un identifiant voit deux machines.

**Débit consommé d'une file classique** : *constaté sur la grappe* — le courtier
n'expose **pas** ce compteur par file. Les compteurs de flux existent, mais pour
tout le courtier. La reconstruction depuis les notes n'est donc pas un choix,
c'est la seule voie. À déclarer comme tel.

**Fonctionnelle de dispersion** : le code peut refuser de trancher, puisqu'elle
n'entre dans aucune matrice. Émettre les quatre candidates et décider sur données.

---

## 2. Corrections au protocole de vérification

Points établis en exécutant le protocole sur la grappe.

**V1 — répondu.** Point d'accès `/metrics/per-object` sur le port 15692, préfixe
`rabbitmq_` et non `rabbitmq_detailed_`. Le point d'accès `/metrics/detailed`
**n'existe pas** sur la version déployée : il n'apparaît qu'en 3.11. L'étape 3 du
protocole est donc inexécutable telle qu'écrite.

**V3 — répondu.** Les compteurs de pression du noyau répondent sur les sept
machines. La solution de repli, décrite comme un discriminant plus faible, **n'aura
pas à être employée**.

**V4 — à compléter.** Ajouter le couple `messaging.destination.name = "<default>"`
face au nom réel de la file. Sans le réglage de stabilité des conventions, les
deux files fusionnent en un seul nœud, **sans aucun message d'erreur**.

**À ajouter au protocole** : vérifier qu'un appel de test produit un résultat
**non vide**, pas seulement un code 200. Constaté : l'application répondait
`{"status":1,"msg":"Success","data":[]}` avec de mauvais noms de champs.

**Nouvelle fiche à écrire** : la présence d'un nom ne suffit pas. Relever aussi
le **nombre de relevés distincts par fenêtre** et le **nombre de notes par
arête**. Un nom peut exister et sa série n'avoir que deux points par fenêtre.

---

## 3. Positionnement et originalité

⚠️ **Cette section repose sur une recherche mono-source, non vérifiée
contradictoirement.** À re-vérifier avant toute rédaction.

**À cesser de revendiquer** : la fenêtre glissante comme unité d'analyse
(plusieurs travaux la précèdent), le graphe hétérogène typé, les types instance
et machine, la granularité instance, le constat de rupture de causalité (acté par
la spécification elle-même), la mesure du retard (produit commercial depuis 2023),
et « la file comme objet de premier ordre » (trois produits le font déjà).

**Retournement à opérer** : présenter la fenêtre non comme une trouvaille mais
comme une **conséquence forcée** — la grandeur cherchée n'existe pas sur un
message isolé. Le même fait devient alors une force au lieu d'une survente.

**Ce qui reste défendable**, par ordre de solidité :
1. l'identité de file **polymorphe**, dont l'arité change selon la famille de
   courtier, avec un schéma commun à six composantes ;
2. la sélection des anomalies par capacité, et l'ablation dont chaque branche est
   une prédiction d'échec réfutable ;
3. les taux de résolution publiés comme indicateur de complétude, distincts de
   toute performance de modèle ;
4. les exclusions assumées : matrice d'arêtes vide, dispersion hors features,
   séparation des clés.

**Preuve d'absence la moins chère** : la revue de référence du domaine ne contient
aucune occurrence de « message queue », « Kafka », « RabbitMQ », « broker »,
« event-driven ».

**Risque non levé** : deux produits commerciaux revendiquent une analyse causale.
Impossible de vérifier s'ils traversent une frontière producteur-consommateur.
C'est le point faible du dossier.

**Faiblesse à déclarer avant qu'on ne la trouve** : sur une file classique, une
composante sur six n'est pas directement observable et un discriminant est perdu.

---

## 4. Décisions qui t'appartiennent

| Sujet | Options |
|---|---|
| Filtre des compteurs exportés | garder les 21 noms, élargir la liste, ou tout exporter |
| Relation « appeler » | les appels internes d'otel-demo sont en gRPC, pas en HTTP — ajouter une instanciation, ou déclarer que cette cause n'est étudiée que sur train-ticket |
| Couples parent-enfant | exclure explicitement ceux qui franchissent une frontière asynchrone, sinon une flèche « appeler » fantôme apparaît |
| Branches d'ablation | quatre par capacité (§9.4) ou une par élément (§10.7) — les deux sections se contredisent |
| Nombre de répliques | la quatrième cause exige au moins trois copies du consommateur ; il y en a une |
| Parcours du générateur | trois retenus ; chaque parcours en plus ajoute du bruit à la référence |

---

## 5. Ce qui reste à faire

### Immédiat, sans grappe

- `git rm --cached .env` — le fichier est suivi dans un dépôt public
- corriger les neuf défauts de la section 1
- écrire le faux jeu de données et le test des 173 nombres

### Sur la grappe

- **retrouver une source de journal partitionné** — otel-demo a été supprimé, il
  ne reste qu'une famille de courtier sur deux
- porter le service consommateur à trois répliques
- une surveillance de l'export : **rien ne prévient si le magasin devient
  injoignable**, et le tampon local ne couvre qu'environ deux heures
- vérifier la stationnarité de la charge : sur soixante fenêtres, la pente du
  débit doit être non significative et le coefficient de variation sous 10 %

### Le gros œuvre

- le constructeur de graphe lui-même — aucune ligne n'existe
- l'injection de fautes, calibrée pour rester dans le régime précurseur
- l'étiquetage, avec période de garde et validation « la faute a bien produit
  l'effet attendu »
- les deux points de comparaison imposés : un seuil univarié sur la pente, et un
  modèle non relationnel

---

## 6. Trois leçons transversales

**Un succès n'est pas une preuve.** L'application répondait « succès » avec une
liste vide ; Helm rapportait « upgraded » sans avoir rien appliqué ; les pods
tournaient pendant que la cadence était trois fois trop lente. Vérifier l'état
effectif, jamais le message.

**Une limite déclarée n'est pas une limite appliquée.** Un volume de 20 Gio est
un répertoire sur un disque : rien n'empêche d'y écrire davantage. Une limite de
mémoire ne protège pas le nœud voisin.

**Un symptôme ne dit pas sa cause.** Un réglage non appliqué a été attribué à une
mauvaise clé de configuration, alors que le script n'atteignait jamais cette
ligne. Une solution juste a été remplacée par une fausse.

---

## Six correctifs apportés au déploiement (2026-09-10)

Trouvés en débloquant un déploiement arrêté sur `nacos-0 Init:Error`. Tous sont
dans le code, aucun ne demande d'intervention manuelle au prochain lancement.

### 1. MySQL inaccessible en IPv6 — le correctif ne tenait pas

`apps/train-ticket.sh`. Le sidecar xenon de RadonDB se connecte à
`localhost:3306` ; glibc préfère IPv6, MySQL voit donc `root@::1`, un compte que
le chart ne crée pas. Sans lui : pas d'élection, pas de label `role=leader`,
service `*-mysql-leader` sans adresse, init de Nacos en boucle.

Le correctif existait mais marquait chaque pod « fait » après un seul succès.
Constaté : appliqué aux trois pods au démarrage, il avait disparu de deux d'entre
eux une heure plus tard — l'entrée en service de RadonDB réécrit sa table de
comptes après le premier démarrage. **La boucle vérifie maintenant l'existence du
compte à chaque passage** au lieu de faire confiance à un premier succès.

Constaté sur le cluster : 21 019 tentatives d'authentification refusées, nœud 1
CANDIDAT depuis 1 392 élections. Correctif posé → élection en 15 secondes.

### 2. La boucle s'arrêtait à la première base

Même fichier. Elle sortait dès qu'*un* service leader avait une adresse. Or Train
Ticket en a **deux** — `nacosdb` et `tsdb` — déployés à plusieurs minutes
d'écart. Résultat : nacosdb corrigé, tsdb laissé sans correctif, et les 41
services sans base de données. Elle attend maintenant que **tous** les services
`*-mysql-leader` soient adressés.

### 3. `--apps-only` ne passait pas par le bastion

`deploy.sh`. `SSH_JUMP` n'est renseigné qu'en mode complet, à partir de la sortie
de la CLI SLICES. En mode `--apps-only` il restait vide : « Connection timed
out » sur un master pourtant joignable. Le bastion est maintenant repris de
`inventory.ini`, qui le porte déjà.

### 4. `isolate` expulsait des pods qui ne peuvent pas bouger

`apps/observability.sh`. Le stockage local-path attache un volume à **une
machine**. Expulser un pod dont le volume est sur le nœud qu'on vient d'interdire
le laisse Pending indéfiniment — constaté sur `nacosdb-mysql-0`, débloqué
seulement en supprimant son volume. Ces pods sont maintenant **laissés en place**,
avec une tolérance posée sur leur contrôleur, et la liste est affichée.

### 5. `install` épinglait avant d'étiqueter

Même fichier. Avec `OBS_DEDICATED_NODE`, les composants sont déployés avec
`nodeSelector: role=observability` alors que l'étiquette n'est posée que par
`isolate`. Leurs volumes local-path se créaient donc là où le planificateur les
posait par défaut, et l'épinglage ultérieur devenait contradictoire. Constaté sur
Jaeger : volume sur workers3, pod exigé sur workers1, Pending définitif.
**Le nœud est maintenant étiqueté avant toute installation.** L'étiquette seule
n'interdit rien — c'est le marquage `dedicated` de `isolate` qui écarte les
autres pods.

### 6. Profil de dimensionnement périmé

`.env` : `PROFILE_TT_WORKERS` valait 4, dimensionné pour train-ticket **seul**.
Depuis, la plateforme ajoute la chaîne de mesure, un nœud entier réservé, l'agent
Java sur 46 services (~150 Mio de tas chacun) et trois copies du consommateur.

Mesuré sur 4 workers : après isolement il n'en restait que 3 pour 56 pods,
saturés à **96-98 % de mémoire réservée**. Un pod de Nacos ne trouvait plus de
place, l'annuaire devenait incomplet, et les services qui s'y enregistrent
tombaient en boucle avec :

```
Nacos cluster is running with 1.X mode, can't accept gRPC request temporarily
```

Un manque de place qui se présente comme une panne applicative. Le profil est
passé à **6 workers**, ce que PROCEDURE.md annonçait déjà (« sept machines »).

### 7. Le correcteur mourait avant la seconde base

`apps/train-ticket.sh`. Il était arrêté dès que le script amont rendait la main.
Or l'amont rend la main dès que ses `rollout status` sont satisfaits — et un pod
RadonDB devient Ready **sans que l'élection Raft ait abouti** : sa sonde
interroge MySQL, pas Raft.

Enchaînement constaté sur un déploiement à 6 workers, mémoire saine :

```
  nacosdb   corrigé pendant le déploiement          leader élu     OK
  tsdb      table de comptes réécrite APRÈS le retour du script amont
            correcteur déjà tué, aucun chef élu
            → 13 services sur 56 en CrashLoopBackOff pendant les
              trente minutes d'attente qui suivent
```

Le correcteur couvre maintenant **le déploiement ET l'attente** qui le suit ; sa
fenêtre vaut `TT_DEPLOY_TIMEOUT + TT_READY_TIMEOUT`. Il s'arrête de lui-même dès
que tous les services `*-mysql-leader` sont adressés.

Correctif posé à chaud sur le cluster : chef élu en 15 secondes, 56/56 pods
prêts cinq minutes plus tard.

### 8. La sortie anticipée annulait le correctif n°2

Même fichier. La boucle s'arrêtait dès que **tous les services leader connus**
étaient adressés. Piège : à l'étape 1/3 seul `nacosdb` existe, il est élu, la
condition « tous » est satisfaite **avec un seul**, et le correcteur meurt.
`tsdb` est créé à l'étape 2/3, sans personne pour le corriger.

Le nombre de bases ne peut pas être connu avant qu'elles ne soient déployées. Le
correcteur tourne donc **jusqu'au bout de sa fenêtre** ; c'est `install_app` qui
l'arrête quand l'application est prête. Un contrôle toutes les dix secondes ne
coûte rien.

**Vérifié sur cluster réel**, les deux bases déjà élues :

```
  correctif IPv6 appliqué à nacosdb-mysql-2 (compte root@::1 créé)
  élection MySQL aboutie sur 2 base(s) — surveillance maintenue.
  la fonction a rendu la main après 97 s (fenêtre = 90 s)
```

Trois faits d'un coup : un compte avait **de nouveau** été effacé et a été
reposé — la réécriture n'est donc pas un incident isolé ; le correcteur n'a pas
quitté malgré les deux bases élues ; il a tenu toute sa fenêtre.

### Bruit sans conséquence : `sed -i ""` du script amont

`hack/deploy/gen-mysql-secret.sh` du dépôt train-ticket contient :

```bash
if [ "$(uname)"="Darwin" ]; then      # pas d'espaces autour du =
```

Sans espaces, bash n'évalue aucune comparaison : il teste la chaîne
`"Linux=Darwin"`, non vide, donc toujours vraie. La branche macOS s'exécute
systématiquement, d'où `sed -i ""` que GNU sed refuse :

```
sed: can't read s/nacos/nacos/g: No such file or directory
```

**Sans conséquence** : la substitution remplace « nacos » par « nacos ». Elle ne
change rien, qu'elle aboutisse ou non. Bug amont, à ne pas confondre avec une
panne de déploiement.

### Ce qui n'a pas été vérifié

La chaîne complète jusqu'aux figures **n'a pas été exercée** sur ce cluster : il
a saturé à l'étape 6, avant le générateur de charge. Les étapes 1 à 5 sont
validées, le déploiement a atteint 56/56 pods. Les étapes 7 à 10 et la
génération des figures restent à confirmer sur un cluster à 6 workers.
