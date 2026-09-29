# Spécification d'implémentation de `graphe_en/gnn.py` et de son branchement

Sources lues : dépôt `~/autodeploy_k8s-phases`, commit d563964, branche plan-phases.

Abréviations :
- J = `notes/JOURNAL.md` ; AR = `notes/A_REPORTER.md`.
- tn = `temoin_noeud.py`, tf = `temoin_fleches.py`, tm = `temoin_machine.py`, dc = `decision_c.py`.

Ce que j'ai fait, et pas fait :
- Je n'ai écrit aucun fichier.
- Je n'ai lu ni `config.yaml`, ni `.env.secrets`, ni base-01, ni les essais réseau, ni les jumeaux.
- Sur vms0, en lecture seule, j'ai ouvert une seule fenêtre de saine-09 (`runs/20260926-033245/graph/window_0010.json`), pour les unités, et vérifié l'empreinte de `scaler.json` : 53b6728f…, identique à `fige["echelle"]["sha256"]`.
- vms0 a 8 cœurs et 31 Go, et un venv dans `graphe_en/.venv`.
- vms0 est à f5a6570, un commit de journal derrière d563964.

---

## 0. Trois décisions de cadrage, à écrire au journal AVANT d'écrire le code

1. **Aucune modification de `temoins.py`, `juge.py`, `temoin_*.py`.**
   - `controle_du_code` refuse `--ouvrir` si un fichier de `FIGES_TEMOINS` a changé (dc l.77, 192-194).
   - Il refuse aussi si `temoin_machine.py` a changé (l.200-211).
   - On ne touche qu'à deux fichiers :
     - `graphe_en/gnn.py`, nouveau ;
     - `decision_c.py`, qui doit de toute façon différer de `temoins-figes` (l.188-190).

2. **Un seul score et une seule alarme pour les deux réglages du GNN.**
   - Le classement vient toujours de l'étape 1 (J 1023-1024 ; tn l.76-77).
   - L'alarme ne vient que de l'étape 1 : c'est un seul signal, donc la question de l'union (J 1314) ne se pose pas.
   - « Sans exemples » et « avec exemples » ne diffèrent donc que par la cause.
   - Or la cause n'est pas un axe contre la règle (J 1259).
   - F, A, G, les minutes et les fausses alertes sont donc identiques pour les deux réglages. La décision 2 (J 1244-1257) porte sur une seule entrée, « GNN ».
   - Cela lève l'ambiguïté « quel réglage du GNN est comparé » (J 1234 contre `fautifs.py` l.49-54).

3. **La garde G ne sert jamais à choisir avant le gel.**
   - G se calcule sur le test (J 1235-1236 ; dc l.138-166). La condition « garder G » du banc (J 1594-1596) est donc remplacée par **G_val**, la même définition sur `juge.validation`.
   - La vraie G du GNN est calculée une fois, après `gnn-fige`, par dc.
   - Sinon ce serait le même défaut que la première version de temoin_machine (J 1623-1638), et une entorse à J 1321-1324.

---

## 1. Les données

### 1.1 Quelles fenêtres

- Le constructeur `GNN(fen, fige, graine=0, variante="complet", budget=None)` reçoit **toutes** les fenêtres des séries (dc `lire_c` l.290 et 296 lui passent `fen_series`). Il filtre lui-même, comme tn l.333 :

  ```
  garde    = [f for f in fen if f["jeu"] == "apprentissage" and f["etiquette"] not in juge.ECARTEES]
  normales = [f for f in garde if f["etiquette"] == "normale"]   # l'étape 1 ne voit QUE celles-ci (J 1297)
  pannes   = [f for f in garde if f["etiquette"] == "panne"]     # l'étape 2 seulement
  ```

- Les plis : `campagnes = sorted({f["campagne"] for f in normales})`. Il en faut au moins 2, sinon `ValueError`, comme tn l.336-338.
- Le GNN ne lit jamais `jeu == "test"`, ni `"hors"`, ni C, ni D (J 1319-1320).
- `gnn.py` n'appelle `juge.lire` qu'avec `fautifs.SERIES`.
- Le mode test (tableau de bord sur le vrai test) est **refusé** tant que l'étiquette `gnn-fige` n'existe pas (J 1321-1324, 1325). Ce contrôle se fait par `git rev-parse -q --verify refs/tags/gnn-fige`, comme dc `_git`.

### 1.2 La conversion

- La conversion se fait à la volée par `export_pyg.convert([donnees], scaler, "mask", False, "cpu")[0]`. Elle est identique à `graph.pt[i-1]`, vérifié sur 3 fenêtres par le second lecteur.
- `scaler.json` se charge une fois dans le module : `json.loads((HERE/"scaler.json").read_bytes())["scaler"]`. On refuse par `juge.Refus` si le sha256 diffère de `fige["echelle"]["sha256"]`. On ne recale jamais d'échelle (J 873-878, 891-895).
- `donnees` est partagé par des copies superficielles (`juge.validation` l.262) : il ne faut **jamais le modifier**. Le banc travaille sur des `copy.deepcopy`.
- Les fenêtres d'apprentissage converties sont gardées en cache dans un dictionnaire `{f["id"]: HeteroData}`.

### 1.3 Les colonnes (le graphe reste figé ; seul le rôle des colonnes est un choix de modèle)

- **Colonnes de contexte** : `memory_limit` et `cpu_quota` des instances.
  - Elles sont toujours en entrée, jamais masquées, jamais reconstruites, jamais notées.
  - Principe : la configuration est un contexte, pas un état.
  - À dire au rapport : elles distinguent les pods MySQL, c'est une quasi-identité (temoin_tableau l.63-65). Ce ne sont pas des noms, et elles se transportent (AR 31, l.288-296).
- **Colonnes d'état** : toutes les autres.
  - 16 pour les instances, 6 pour les files, 9 pour les machines.
  - Plus une pseudo-colonne `absents`, notée comme dans tn l.174-175 (voir 3.1).
- **Relations et colonnes des flèches** : les 5 relations du gel (`calls` 5, `queries` 5, `publishes` 1, `consumes` 1, `executes_on` 0).
  - Il n'y a jamais d'absent sur une flèche (export_pyg, docstring l.42-43).

### 1.4 La transformation interne au modèle (ne touche pas l'échelle figée)

- Après la mise à l'échelle figée, on applique `asinh(x)`, en entrée comme en cible, aux nœuds et aux flèches.
- Raison : en panne, certaines colonnes dépassent de 10² à 10³ fois l'écart-type de saine-09 (plancher 1,0, export_pyg l.130-152).
- `asinh` est monotone et sans plafond, donc ne crée pas d'égalités (le juge départage les égalités contre la méthode, juge l.337-348).

### 1.5 Aucune identité en entrée, et les pods renommés

- En entrée : les nombres, la sorte du nœud (un encodeur par sorte), le type de relation, la structure.
- `names`, `keys_` et `hosts` ne sont **jamais** des entrées.
- Les noms ne servent qu'à écrire les clés de sortie : `f"{kind}:{h[kind].names[i]}"`, comme `juge.noeuds` l.123-132.
- Conséquence : un renommage de pod ne change rien, et il n'y a rien à gérer (J 962-967, 1057, 1171-1175 ; AR 31).
- « Écart au normal du nœud » (AR 31) : le normal d'un nœud est **sa reconstruction à partir de son voisinage et de son contexte**. L'écart est le résidu (J 986-988). À dire au rapport : c'est ainsi que se concilient AR 31 et « aucun nom ».
- Test obligatoire T2 (voir §8).

---

## 2. L'étape 1 : le modèle et l'apprentissage

### 2.1 L'architecture : `class Reconstructeur(torch.nn.Module)`

C'est un R-GCN hétérogène avec un canal d'arête sur **toutes** les relations chiffrées :
- pas seulement `calls` (J 602-603), parce que la base ne se voit que par `queries` (J 1291-1293, 891-893) ;
- ce point est à noter au journal comme la lecture retenue de J 602.

Les dimensions :

```
H = 32, L = 2 couches, activation ReLU, LayerNorm, pas de dropout.
Relations de passage : les 5 du gel + leurs inverses "rev_<rel>", ajoutées DANS le modèle
  (graphe_fige.json : add_reverse_edges=false ; export_pyg l.54-58 : c'est un choix de modèle).
```

L'entrée d'un nœud de sorte k :

```
[ asinh(x_etat)·(1-m) , present_etat·(1-m) , asinh(x_ctx) , m ]
```

- `m` vaut 1 si le nœud est masqué. `present` vient de `data[k].present` ; un absent vaut 0.
- Les dimensions d'entrée : instance 16+16+2+1 = 35 ; file 6+6+0+1 = 13 ; machine 9+9+0+1 = 19.
- L'encodeur : `enc_k = Linear(in_k, H)`.

L'entrée d'une flèche de relation r chiffrée : `[asinh(e)·(1-m_e), m_e]`. Le canal d'arête :

```
φ_r = Linear(d_r+1, H) → ReLU → Linear(H, H)
```

Les poids de φ_r sont partagés entre r et rev_r. `executes_on` n'a pas de canal (colonnes vides, point ouvert 12 du premier lecteur).

Une couche l :

```
pour chaque sorte k : a_k = self_k^l(h_k)
pour chaque relation ρ (src→dst), directe ou inverse :
    msg = W_ρ^l( concat(h_src[e.src], φ_r(ê)) )   # sans φ si la relation n'a pas de colonnes
    a_dst += scatter(msg, e.dst, reduce="mean", dim_size=n_dst)   # torch_geometric.utils.scatter
h_k ← LayerNorm(h_k + ReLU(a_k))
```

- La moyenne rend le modèle insensible au degré : la base a 14 à 16 flèches `queries` entrantes.
- Un `edge_index` vide `[2,0]`, comme dans les fenêtres à 0 flèche de charge-03, doit passer sans erreur (test T1).

Les décodeurs :
- nœud : `dec_k = Linear(H,H) → ReLU → Linear(H, 2·d_etat_k)`, qui donne les valeurs et les logits de présence ;
- flèche : `dec_r = Linear(2H,H) → ReLU → Linear(H, d_r)` sur `concat(h_src, h_dst)`, pour `calls`, `queries`, `publishes` et `consumes`.

La taille : environ 70 000 paramètres. Les poids sont partagés par tous les nœuds d'une sorte et par toutes les flèches d'une relation (J 986-988 ; AR 4 l.69-71 : peu de paramètres).

### 2.2 La tâche : masquer puis reconstruire

**L'unité de masque est un nœud et toutes ses flèches entrantes, toutes relations confondues.**

Principe : on reconstruit un nœud et tout ce qui est mesuré en arrivant chez lui sans les voir.

Conséquences :
- Chaque flèche a exactement une cible, donc elle est masquée une fois par passage de notation.
- Toutes les `queries` vers la base sont masquées avec elle. Elles sont prédites d'après leurs sources seules, sans que les flèches voisines ralenties les « expliquent ».

**À l'apprentissage** :
- par graphe et par pas, chaque nœud est masqué avec p = 0,15, par un tirage `torch.Generator` graine ;
- la présence est codée « masqué → entrées d'état et bits de présence à 0, drapeau m = 1 » ;
- la perte porte sur les nœuds masqués :
  - Huber (δ = 1) sur les valeurs asinh des colonnes d'état présentes ;
  - plus 0,5 × BCE sur les logits de présence de toutes les colonnes d'état ;
- elle porte aussi sur les flèches masquées (Huber) ;
- la perte des nœuds est la moyenne des pertes par sorte, la perte des flèches la moyenne des pertes par relation, pour que les 2 files et les 8 machines pèsent autant que les 58 pods ;
- `L = L_noeuds + L_fleches`.

**L'optimisation** :
- Adam, lr = 3e-3, weight_decay = 1e-4, 150 époques ;
- lots de 16 graphes par `torch_geometric.loader.DataLoader`, mélange par un générateur graine ;
- pas d'arrêt précoce.

**Le déterminisme** (dc l.20-22 : `--ouvrir` réapprend) :
- `torch.manual_seed(graine*1009 + rang_du_pli)`, avec rang 0 pour le modèle final et 1 à 10 pour les plis dans l'ordre trié ;
- `torch.set_num_threads(1)` ;
- `torch.use_deterministic_algorithms(True)`.

**Le parallélisme** : les entraînements tournent sur 8 processus (`ProcessPoolExecutor`, contexte spawn), un fil chacun.
- Estimation : environ 10 s par entraînement.
- Par graine et par variante : 11 entraînements (un final et 10 plis).

### 2.3 La notation d'une fenêtre : `Reconstructeur.residus(data) -> Sortie`

- Il y a **un passage par nœud, en lot** : N copies de la fenêtre (N = 68 dans les séries), la copie i masquant le nœud i et ses flèches entrantes.
- Le lot passe en une seule fois, en environ 15 ms sur un cœur.
- Pour chaque nœud, on retient :
  - le résidu signé `x̃ − x̂` par colonne d'état présente ;
  - le résidu `absents` = Σ_c (present_c − σ(logit_c)), signé ;
- et, pour chaque flèche, le résidu signé par colonne, tiré de la copie de sa cible.
- Ce passage est invariant par permutation et ne dépend d'aucun nom (test T2).

La structure `Sortie`, pour une fenêtre :
- `res_n[k]` : un tableau `[n_k, d_etat_k+1]`, avec NaN si la colonne est absente ;
- `res_e[r]` : un tableau `[E_r, d_r]` ;
- `edges` : les `edge_index` par relation ;
- `hosts` : la liste de la machine de chaque instance, lue dans `donnees` et **seulement** pour le post-traitement du §3 ;
- `names` par sorte.

---

## 3. Le score par nœud : le principe général écrit, et la grille à trancher

**Principe P, à écrire mot pour mot au journal avant le banc** : « Une erreur partagée désigne le bout commun ; une anomalie qui s'explique par une dépendance anormale passe à cette dépendance, jusqu'au dernier composant anormal. »

C'est la définition du 24 sept. (tf l.6-8 : « la file → ses répliques → ce qu'elles appellent → le dernier composant anormal »). C'est aussi la « part des voisins » (J 1303, 1070-1075) et l'idée « machine » (J 1601-1621).

À dire honnêtement au rapport : ce post-traitement est écrit à la main ; le modèle appris fournit « qui est anormal, et de combien, sans nom ». La variante « sans aucune arête » en mesure la part (J 1597-1599).

### 3.1 Des résidus aux écarts (les échelles « dans le pli », J 1300-1301)

- Pour chaque couple (sorte, colonne), et pour chaque couple (relation, colonne), on calcule sur les résidus tenus hors pli :
  - la médiane ;
  - l'échelle `tn.echelle`, avec le plancher de `tn.echelles` l.202-216 : 0,1 × pstdev, ou 1 si l'échelle est ≤ 1e-12.
- On en tire `z = (res − médiane) / échelle`.
- Erreur d'un nœud : `r_v = max_c |z_vc|` sur ses colonnes présentes, `absents` compris.
- Erreur d'une flèche : `ε_e = max_c |z_ec|`.
- « Tenus hors pli » veut dire :
  - pour noter les normales de la campagne c (calage), on prend les résidus du modèle du pli c′ sur les normales de c′, pour tout c′ ≠ c ;
  - pour le modèle final, les résidus hors pli de tous les plis (validation croisée).

### 3.2 Le bout des flèches B, et la réunion

- Seules les flèches **anormales** comptent : `ε_e > κ_r`, où κ_r est le 95e centile des ε hors pli de la relation r. Sinon une somme grandirait avec le degré.
- `e_v` est l'agrégat reçu par v. On prend `t_v = max(r_v, e_v)`.
- Les cinq candidats :
  - **B1 « cible-max »** : `e_v = max` des ε des flèches anormales qui entrent en v.
  - **B2 « source-max »** : la même règle pour les flèches qui sortent de v.
  - **B3 « deux-max »** : les deux bouts reçoivent ε, réunies par le maximum.
  - **B4 « cible-somme »** : la somme des ε des flèches anormales qui entrent en v.
  - **B5 « part »** :
    - pour une flèche anormale u→v de relation r, `fin(v)` est la part des flèches entrantes r de v qui sont anormales, et `fout(u)` la part des flèches sortantes r de u qui sont anormales ;
    - v reçoit `ε·fin/(fin+fout)` et u reçoit `ε·fout/(fin+fout)` ;
    - réunion par la somme.
    - Calcul à la main : lenteur (3 flèches sur 15 vers la base), la base reçoit environ 0,5ε ; C (15 sur 15), environ 7,5ε.
- La normalisation par sorte : `ŝ_v = t_v / τ_k`, où τ_k est le 95e centile des t hors pli de la sorte k. On a donc « 1 = l'extrême normal de sa sorte », ce qui rend les pods, les files et les machines comparables (J 1300-1301 ; juge l.117-118 : la machine se classe contre les pods).
- « Anormal » veut dire ŝ > 1.

### 3.3 La remontée pods → machine H (J 1304-1305, 1580-1582)

On lit la machine d'un pod dans `hosts`, identique à `executes_on` (tf l.244-246). On lit `hosts` dans **toutes** les variantes, comme l'exige J 1597-1599.

A_h désigne les pods de h avec ŝ > 1. Trois candidats :

- **H0** : pas de remontée.
- **H1 « somme à seuil »** : si |A_h| ≥ 2, alors `R_h = Σ_{p∈A_h} ŝ_p`, sinon 0.
  - Avec au moins deux pods, le cas R (la réplique seule) ne fait jamais monter la machine.
  - La somme permet à X de passer devant sa réplique (+5d) dans le cas M, ce que ni un maximum ni un 2e plus grand ne font.
- **H2 « concentrée »** : H1, et en plus :
  - une majorité stricte des pods **actifs** de h est anormale ;
  - au plus la moitié des pods actifs ailleurs, hors de l'amont de h, est anormale.
  - Actif : un pod source d'une flèche `calls` ou `queries` vers une autre machine (même définition que `tm._actifs`, l.82-86).
  - Amont : les pods qui atteignent un pod de h en suivant les flèches `calls` et `queries` **de la fenêtre**, sans nom ; c'est la seule différence avec tm l.150-156.
  - C'est l'idée de tm l.158-173, transposée.
- Dans tous les cas : `ŝ_h ← max(ŝ_h, R_h)`.

### 3.4 L'explication par les dépendances V (la victime, point ouvert 4)

**Les dépendances** D(v), lues dans la fenêtre :
- une file dépend de ses consommateurs (`consumes`) et de ses producteurs (`publishes`) ;
- une instance dépend des cibles de ses `calls` et de ses `queries` sortantes, et de sa machine (`hosts`) ;
- une machine ne dépend de rien.

**Les candidats** :
- **V0** : pas d'explication.
- **V1 « héritage »** :

  ```
  Anorm = {v : ŝ_v > 1} ; graphe G_A = arcs v→u pour u ∈ D(v) ∩ Anorm, v ∈ Anorm
  SCC = scipy.sparse.csgraph.connected_components(G_A, connection="strong")
  pour v ∈ Anorm : cand = [u ∈ D(v)∩Anorm, scc(u) ≠ scc(v)]
      si cand : pointeur(v) = argmax_{u∈cand} ŝ_u  (égalité : le plus haut ŝ puis l'indice ; jamais le nom)
  racine(v) = pointeur suivi jusqu'à un nœud sans pointeur (le graphe condensé est acyclique)
  pour chaque v expliqué : ŝ'_v = 1 − exp(−ŝ_v)   (< 1, monotone : pas d'égalités)
  pour chaque racine r : ŝ'_r = max(ŝ_r, max{ŝ_v : racine(v)=r})
  les autres : ŝ'_v = ŝ_v
  ```

**Propriétés** :
- `max_v ŝ'_v = max_v ŝ_v` : l'alarme ne change pas avec V, seul le classement change.
- On garde « score de fenêtre = le plus haut score de nœud, le même qui sert au classement » (J 1300).

**Ce qu'on attend, à la main** :
- C : file → répliques → base. La base est la racine si B lui donne ŝ > 1.
- D : la réplique de X pointe vers le plus haut de la base et de X ; H fait monter X.
- Lenteur : les répliques sont racines **seulement si** la base reste sous 1. Sinon G tombe : c'est ce que G_val contrôle.
- Limite connue : dans le blocage, la flèche `consumes` de la réplique gelée disparaît, donc la file reste racine. V ne répare pas le blocage : à écrire.

### 3.5 Le choix dans la grille (J 1301-1311, 1594-1596), à écrire au journal avant le calcul

La grille : B ∈ {B1…B5}, H ∈ {H0, H1, H2}, V ∈ {V0, V1}, soit 30 combinaisons.

C'est du post-traitement : les résidus de l'étape 1 sont calculés une fois, et les 30 combinaisons coûtent peu.

Le terrain :
- la validation (`juge.validation`) : modèles appris sur ses normales d'apprentissage, graines 0 à 4 ;
- le banc (§7).

Les critères, dans l'ordre :

1. **Admissible si G_val tient pour les 5 graines.**
   - Sur les 8 injections `jeu=="test"` de la validation, causes connues : blocage-02, blocage-03, lenteur-01, lenteur-02, hote-01, hote-02, charge-03, charge-04.
   - G_val tient si `instance:tsdb-mysql-0` n'est premier dans une majorité stricte des fenêtres d'aucune de ces injections.
   - On utilise `dc.premier`, `dc.par_injection` et `dc.majorite`.
2. **Et, pour chaque dimension non minimale**, le top-1 de validation, sans alarme, par fenêtre et en médiane des graines, doit être au moins égal à celui de la même combinaison avec cette dimension ramenée au plus simple. C'est la lecture de « validation au moins aussi bonne » : l'option ne coûte rien sur la validation.
3. **Parmi les admissibles**, on prend le maximum de la médiane des graines du nombre de cas du banc où la réponse attendue est au rang 1 (`juge.rang == 1`, égalités contre la méthode).
4. **À égalité, le plus simple.**
   - Ordre lexicographique : V0 < V1, puis H0 < H1 < H2, puis B1 < B2 < B3 < B4 < B5.
   - Si aucune combinaison n'est admissible : B1/H0/V0, dit au journal.

Le résultat est codé en dur dans `gnn.py` : `CHOIX = {"bout": "...", "remontee": "...", "explication": "..."}`. On commite aussi la sortie `campagnes/gnn-banc-validation.txt` avant `gnn-fige`.

---

## 4. L'alarme, les budgets, le classement (J 1312-1316)

- **Les scores tenus hors pli** : pour chaque campagne c, le modèle du pli c, appris sans c avec les mêmes réglages et la même graine (J 1298-1299), note les normales d'apprentissage de c. On obtient `S_c(w) = max_v ŝ'_v`. Les 249 valeurs sont gardées dans `self.tenus`, une liste de (campagne, id, S).
- **Le seuil propre** : `θ = tn._q(S_tenus, 0.95)`, comme tn l.343-347. Il donne environ 13/249.
- **Le budget d'une autre méthode** (J 1312-1313, 1248-1251) :
  - `θ_b = sorted(S_tenus, reverse=True)[b]`, pour qu'exactement b scores tenus dépassent le seuil s'il n'y a pas d'égalité ; on garde le compte réel, `self.calage_budget = (n_dessus, N)` ;
  - les budgets sont ceux de J 1165-1169 : `BUDGETS = {"tableau": 13, "score par nœud, sans": 13, "score par nœud, avec": 25, "règle": 21}` sur 249 ;
  - les versions « machine » gardent le budget de la règle (J 1611 : « même alarme, même budget ») ;
  - si N ≠ 249 (validation), `b = round(b249 · N / 249)`, dit dans l'en-tête.
- **Le modèle final** (J 1315-1316) : appris sur toutes les normales d'apprentissage, avec les échelles, τ et κ de tous les plis (§3.1).
  - Le risque (point ouvert 5) est mesuré : les fausses alertes du modèle final sur les normales `test` de la validation, contre le budget.
- **La réponse** :

  ```python
  {"alarme": bool(S > θ_budget), "cause": ..., "scores": {cle: float(ŝ'_v) for chaque cle de juge.noeuds(donnees)},
   "_S": S, "_racine": ..., "_pointeurs": {...}}
  ```

  - Les clés `_` sont retirées par temoins l.85 et dc l.102.
  - Jamais de `None` : chaque nœud a un résidu.
  - Test T1 : `juge.verifier` passe.

---

## 5. L'étape 2 : prototypes et rejet (J 600-605, 1317-1318)

- **Le profil d'une fenêtre, sans identité** : on prend les z **signés** du modèle final (§3.1).
  - Pour chaque sorte et chaque colonne d'état, plus `absents` : `tn._c(max_v z)` et `tn._c(min_v z)`.
  - Pour chaque relation chiffrée et chaque colonne : `_c(max_e z)` et `_c(min_e z)`.
  - Environ 90 dimensions, 0 si un bloc est vide.
  - Ce sont des écarts au normal du nœud, donc transportables (AR 31).
- **Les prototypes** : `tn.Prototypes(profils, causes)`, sur les fenêtres de panne d'apprentissage. On l'importe sans le modifier : même distance réduite que le témoin 2.
  - L'étape 1 n'a jamais vu de panne, donc son modèle final peut noter ces fenêtres sans croisement. C'est l'apprentissage « en deux temps ».
- **Le rejet** : chaque injection d'apprentissage est mise de côté à son tour ; seuil au 95e centile des distances de ses fenêtres bien classées. On copie tn l.395-411.
- **La cause** :
  - `réglage="avec exemples"`, la valeur par défaut : `"normale"` sans alarme ; sinon le prototype le plus proche si `d ≤ seuil_rejet`, et `"inconnue"` au-delà ;
  - `"sans exemples"` : `"inconnue"` si l'alarme sonne, sinon `"normale"`. Seulement au tableau de bord ; le score et l'alarme sont identiques (§0.2).
- **La répétition « jamais vue »** : seules les pannes bougent (juge l.214-217), donc l'étape 1 est reprise du cache. L'étape 2 est réapprise sur 3 causes.

---

## 6. Graines, variantes, noms

- **Graines 0 à 4**, chacune avec son calage (J 1315-1316). Note détaillée de la graine 0, puis minimum, médiane et maximum (`fautifs.py` l.74-76).
- **Le cache** : un dictionnaire de module, `_CACHE[(variante, graine, frozenset(ids des normales))] = Etape1`.
  - Le même modèle sert à toutes les entrées de budget, à `garde()` et à `lire_c()`.
- **Préchargement** : `gnn.preparer(fen, fige, graines=5, variantes=VARIANTES)` lance tous les entraînements en parallèle (§2.2). À appeler avant les boucles.
- **Les variantes** (J 1291-1294, 1262 ; AR 27j), dans `VARIANTES` :

| variante | message passant | flèches notées (§3.2) | dépendances de V | remontée H |
|---|---|---|---|---|
| `complet` | 5 relations + inverses, canal | oui | oui | `hosts` |
| `sans aucune arête` | aucune (self seul) | non | `hosts` seul | `hosts` (J 1597-1599) |
| `sans queries` / `sans calls` / `sans publishes` / `sans consumes` | la relation (et son inverse) retirée | sans elle | sans elle | `hosts` |
| `sans executes_on` | executes_on retiré | idem complet | idem complet | `hosts` (post-traitement écrit à la main : à dire) |
| `sans canal d'arête` | 5 relations, φ retiré | non | oui | `hosts` |
| `un seul type sans canal` | un seul W lié pour toutes les relations, sans φ | non | oui | `hosts` |

- Le CHOIX (B, H, V) est celui du complet, repris tel quel par les variantes.
- Chaque variante a ses propres seuils.
- **Les noms dans `dc.methodes`**, qui commencent tous par « GNN » (dc l.111-112) :
  - `"GNN"` (complet, seuil propre) ;
  - `"GNN, budget de la règle"` (complet, θ_21) ;
  - `"GNN sans aucune arête"`, et `"GNN sans queries"`, … pour chaque variante (seuil propre, et θ_21 calculé en diagnostic).
- `gnn.methodes(fige)` rend ces triplets `(nom, fabrique(fen, g), True)`.

---

## 7. Le banc de pannes fabriquées (J 1584-1599, avec la signature de l'écart 3 J 1989-1996)

**Les fenêtres** : les normales de `jeu=="test"` de `juge.validation(juge.lire(SERIES))`. Jamais `"hors"`, jamais C, D ou leurs essais (J 1532-1535). Les modèles sont ceux de la validation, graines 0 à 4.

**Le générateur** : `fabriquer(donnees, cas, X, d, Y=None) -> donnees′`, sur une copie profonde. Le générateur **peut** lire les noms : ce n'est pas le modèle. Unités en ms, vérifiées : la réplique a un p50 d'environ 846 ms et sa flèche `queries` environ 141 ms.

1. **Signature M (machine X, retard d)** :
   - la réplique `ts-delivery-service-*` de X : `process_time_p50/95/99 += 5d` ; ses `queries` sortantes `latency_p50/95/99 += d` ; sa flèche `consumes` : `rate = min(rate, 1000/(p50_avant + 6d))` ;
   - les autres pods de X **sources de `queries`** : latences de ces flèches `+= d`, et leurs `process_time_*` et `request_time_*` `+= d`, une borne basse, puisque J ne chiffre pas les requêtes par appel ;
   - le ricochet (« preserve », non chiffré au J, borne basse) : les flèches `calls` qui entrent chez ces pods : `latency_* += d` ; leur source : `process_time_*`, `request_time_* += d` ;
   - inchangés : les `calls` qui sortent de X, le trafic entre pods de X hors réplique, les nombres de la machine X, les appelants de la base hors de X ;
   - la file est rendue pleine (J 1647) : la ligne `food_delivery` est copiée de la i-ème fenêtre de panne `lenteur` de l'apprentissage de la validation, avec i = rang de la fenêtre modulo n.
2. **Les cas** :
   - **M** : la signature M ; réponse attendue `host:X` ;
   - **R** : la réplique seule (sa partie de M), file pleine ; réponse attendue la réplique ;
   - **M+Y** : M, et les colonnes `cpu_pressure`, `memory_pressure`, `io_pressure` de Y portées aux médianes de la machine fautive des pannes `hote` d'apprentissage ; réponse attendue X ;
   - **Y** : Y seul, file inchangée ; réponse attendue `host:Y` (fautifs.py l.16-19).
   - Les X : workers0, workers2 et workers5. Cela couvre les deux couples de D (J 2041-2044).
   - Y = workers1, le leurre donné par `couples_d.py`, lu dans le code et pas dans D.
   - Les retards : d ∈ {75, 150, 300}. 400 ms (J 2004) est **donné à part, hors critère**, car la grille est écrite (J 1586).
3. **Les familles de J 1308-1310** :
   - « entrant dans T » : T est chaque instance cible de flèches venant d'au moins 3 pods sources distincts ; toutes ses flèches entrantes `+= d` ; les `process_time` et `request_time` de ses sources `+= d` (+5d pour une réplique) ; file pleine si les répliques sont parmi les sources ; réponse attendue T ;
   - « sortant de T » : T est chaque réplique ; toutes ses flèches sortantes `+= d`, `process_time += 5d`, file pleine ; réponse attendue T.
   - Au rapport : la famille « entrant » contient la base. Le J l'autorise (J 1308) ; il faut le dire.

**Ce qu'on mesure** :
- pour chaque (famille, cas, X, d, graine) et chaque combinaison du §3.5 : le nombre de fenêtres où la réponse attendue est au rang 1 ;
- plus, par cas, la réponse la plus souvent première ;
- le total entre dans le critère 3 du §3.5.

---

## 8. Ordre de travail, contrôles, temps (3 h demandées : voir le dépassement en fin)

**0. Journal « écrit avant », 15 min.** Le principe P, la grille B/H/V, l'ordre de simplicité, les critères du §3.5 (G_val à la place de G), les budgets, les variantes, le banc. Commit.

**1. `gnn.py` : données, modèle, entraînement, notation, 60 min.** Signatures :

```
charger_echelle(fige) -> dict ; convertir(donnees) -> HeteroData(asinh, ctx séparé)
class Reconstructeur(nn.Module); entrainer(normales_donnees, variante, graine, rang_pli) -> state_dict
class Etape1: plis, residus tenus, echelles(par pli), kappa, tau ; sortie(donnees) -> Sortie
noter_noeuds(sortie, calib, CHOIX, variante) -> (s_prime: dict, S: float, diag)
class GNN: __init__(fen, fige, graine=0, variante="complet", budget=None, reglage="avec exemples"); repondre(donnees)
methodes(fige) ; preparer(fen, fige, graines, variantes)
```

**2. Calage, post-traitement, étape 2, 45 min.**

**3. Tests `gnn.py --verifier`, 15 min, sur vms0.** Données limitées à 20 fenêtres de validation, 2 époques.
- T1 : forme de la réponse ; `juge.verifier` sur chaque fenêtre ; `edge_index` vide accepté.
- T2 : renommer tous les pods, puis permuter les lignes et réindexer les flèches, donne les mêmes scores par clé à 1e-5 près.
- T3 : deux entraînements à la même graine donnent un `state_dict` identique (`torch.equal`).
- T4 : `θ_b` fait sonner exactement b scores tenus (sans égalité).
- T5 : `fabriquer` ne change que les cellules prévues ; réplique de X = avant + 5d.
- T6 : le mode test est refusé sans `gnn-fige`.
- T7 : `sha256` de l'échelle contrôlé.

**4. `--banc`, 30 min.**

**5. Runs sur vms0, 25 min de temps réel.** On pousse depuis le poste, puis :

```
ssh vms0 ; cd ~/autodeploy_k8s-plateforme && git pull && cd graphe_en
./.venv/bin/python gnn.py --verifier
./.venv/bin/python gnn.py --validation --graines 5            # → ../campagnes/gnn-validation.txt (juge.sortie("gnn", SERIES, True))
./.venv/bin/python gnn.py --banc --graines 5                  # → ../campagnes/gnn-banc-validation.txt, la table des 30 combinaisons + CHOIX
./.venv/bin/python gnn.py --validation --repetition           # la boucle de temoins l.181-200 recopiée, avec le GNN
```

- En développement, `--graines 1 --epoques 60`.
- `--validation` affiche `temoins.tableau_de_bord(n)` et `temoins.fil_du_temps(fen, n)`, avec `n = temoins.notes(fen, fige, g)` augmenté des entrées GNN. On peut ajouter `--sans-temoins`.

**6. CHOIX codé, run de validation refait, relecture.** Deux agents indépendants, constats revérifiés, selon la règle de la mémoire. Environ 45 min.

**7. `decision_c.py`, 30 min pour le GNN.**
- `methodes(fige, machine=False, gnn=False)` : si `gnn`, `out += gnn.methodes(fige)`, avec un import paresseux.
- `rapport` :
  - `gnn = (mode == "ouvrir") or etiquette_existe("gnn-fige")`, pour qu'aucun `--garde` ne regarde le test avec le GNN avant le gel ;
  - puis `gnn.preparer(...)` avant `garde()`.
- `lire_c` :
  - `sans_structure` inclut les noms qui commencent par `"GNN sans aucune arête"` (J 1262-1263) ;
  - on garde par méthode et par graine `n_f`, `minutes`, et **`fa_test`** = alarmes sur les 120 normales `jeu=="test"` et `not vue` des séries (axe a, J 1252-1253 ; aujourd'hui l.302 ne compte que C).
- Le verdict de la décision 2 (J 1244-1251, 1690-1695) :

  ```
  pour chaque version R de la règle qui TROUVE :
     ax = comparer(fa_test["GNN, budget de la règle"], fa_test[R][0], minutes["GNN, budget…"], minutes[R][0],
                   n_f["GNN"], n_f[R][0], comptent)
     assez = median(n_f GNN) ≥ n_f R ; image_assez = n_f R ≥ median(n_f GNN)
     gagne_R = TROUVE[GNN] et assez et "gagné" ∈ ax et "perdu" ∉ ax
     image_R = image_assez et "perdu" ∈ ax et "gagné" ∉ ax
  verdict = "perdu" si ∃R image_R ; "gagné" si ∀R gagne_R ; sinon "égal"
  décision 3 : "gagné" si TROUVE["GNN"]
  ```

- **L'extension à D, exigée avant `gnn-fige` (J 1538-1540), est un morceau à part d'environ 60 min, plus une relecture :**
  - `--ouvrir <C> --jumeaux <D>` dans la même lecture ;
  - F_D et A_D avec X = `f["fautifs"][0]` ;
  - G_D pour chaque X, par `garde()` paramétrée par la clé de X, avec l'exception de l'injection hote dont X serait le fautif ;
  - le plancher « a priori » restreint aux machines ;
  - « compte » + NotReady + fenêtre sans X ou sans réplique ;
  - la table de l'axe (d) (J 1697-1713) ;
  - `methodes(machine=True, gnn=True)`.

**8. Le gel.**
- On commite `gnn.py`, `decision_c.py` et les sorties de validation et du banc.
- On note au journal le hachage des `state_dict` par graine (sha256 de `torch.save` en mémoire), que `--ouvrir` recalcule et compare.
- On pose l'étiquette `gnn-fige` seulement après.
- `--ouvrir` refuse un `.py` non suivi ou un `graphe_en/` changé (dc l.212-217).

**Le temps** :
- `gnn.py` et le banc font environ 3 h 30 (étapes 0 à 6).
- `decision_c` avec le GNN ajoute 30 min, et l'extension à D encore 1 h.
- Si les 3 h tiennent : étapes 0 à 5 et le branchement de `methodes` d'abord. Les variantes ne coûtent que des drapeaux. Le gel attend la relecture et l'extension à D.

---

## 9. Les risques, et ce qui est laissé simple exprès

**Les risques** :
1. **La victime.** Dans le blocage, la file reste racine (§3.4) : le top-1 blocage de la validation sera faible, comme pour le témoin 2 (J 1140-1142). C n'est pas touché si les répliques consomment encore.
2. **G_val et lenteur.** Si B donne ŝ > 1 à la base dans la lenteur, V1 la met en tête et G tombe. Le critère l'écarte, mais le choix peut alors être « V0 », qui désigne la file dans C.
3. **L'explication par les voisins.** Un modèle appris sur le normal extrapole mal, et des voisins anormaux peuvent réduire un résidu. Le masque « nœud et ses flèches entrantes » limite l'effet pour la base ; la famille « entrant » du banc le mesure.
4. **La part écrite à la main** (B, H, V). À dire au rapport. La variante « sans aucune arête » et les retraits en donnent la mesure. H2 est l'idée de la règle « machine » : l'écart sur D ne viendra pas du principe (J 1685-1688).
5. **L'échelle du modèle final** contre les échelles des plis : l'alarme peut dévier. C'est mesuré sur la validation, pas corrigé sur le test.
6. **La signature du banc**. Les `+d` sont des bornes basses, preserve est approché, 400 ms est hors critère, et G_val n'est pas G.
7. **La quasi-identité** par `memory_limit` et `cpu_quota` : à dire.
8. **Le temps** : l'extension de dc à D est une condition du gel.

**Volontairement simple** :
- pas de recherche d'hyperparamètres (valeurs par défaut figées ; un seul essai de rechange au plus, sur la validation, noté) ;
- pas d'attention ni de contexte temporel (chaque fenêtre est jugée seule, tn l.14-15) ;
- des prototypes sur des profils d'écart plutôt qu'une tête apprise ;
- pas de moyenne des graines (chacune notée à part) ;
- un seul signal d'alarme ;
- aucune entrée nouvelle au graphe figé.
---

## 10. Amendements après lecture de etat.txt et de rapport.tex (28 sept., avant tout code)

1. **DOMINANT n'est ni un adversaire ni une ligne de base** (décision de l'utilisateur, J 1194-1196). L'étape 1
   s'en inspire (auto-encodeur de graphe appris sur le normal) ; à dire ainsi au rapport. Les lignes du rapport
   qui promettent DOMINANT comme témoin de désignation (R:866-870) sont à corriger en phase F.
2. **Pas de décodeur de structure** (etat.txt le proposait) : les flèches d'une fenêtre sont observées, pas
   prédites ; on reconstruit les nombres des nœuds et des flèches. Choix de simplicité, à dire.
3. **Canal d'arête sur toutes les relations chiffrées** (calls, queries, publishes, consumes ; executes_on sans
   canal). Le rapport ne le nomme que pour `calls` (R:824-825), qui n'avait pas encore `queries` : la base ne
   se voit que par `queries`, d'où l'extension.
4. **Relations inverses dans le modèle** (le graphe figé reste à un sens) : sans elles, la machine ne renvoie rien
   à ses pods et la file rien à ses consommateurs (etat.txt « et retour », E:27).
5. **Prototypes sur les profils d'écart** et non sur la moyenne des plongements (R:830-831) : un encodeur appris
   sur le seul normal ne sépare pas les causes ; les écarts au normal, eux, se transportent (AR 31). À dire.
6. **Rejet par la distance seule** (R:832-833), calé en mettant de côté chaque injection (J 1317-1318).
7. **Contradiction à écrire** : etat.txt justifie le GNN par la cause « machine saturée » ; les mesures du rapport
   montrent qu'elle n'atteint pas la file et que le tableau plat la trouve (R:607-617). Le terrain du GNN est C
   (propagation vers la base) et D (réseau d'une machine), comme au plan.

---

## 11. Écart E-1 (28 sept., écrit AVANT tout calcul des versions 2 et 3) : trois versions de l'étape 1

**Constat sur la validation (version 1 = §1–§6, graine 0, 60 et 150 époques ; `--sans-temoins`).** Détection 4/153
fenêtres de panne (le score par nœud sans exemples, même idée sans graphe : 151/153) ; top-1 37/115 (témoin : 40/115) ;
lenteur : tsdb-mysql-0 premier 19 fois sur 38. Causes diagnostiquées par l'agent (sans regarder le test) : (1) le
calage des écarts PAR SORTE laisse quelques nœuds naturellement bruyants (tcp_retrans_ratio du master et de workers1,
memory_pressure de workers6, cpu_throttle_ratio, memory_slope) fixer la queue des scores normaux, donc le seuil ;
(2) asinh appliqué après une échelle déjà logarithmique écrase le signal (lenteur : résidu du p99 de la réplique 0,39) ;
(3) hypothèse : la reconstruction d'un nœud masqué à partir de ses voisins « explique » une anomalie qui touche tout
un voisinage (file + répliques + base).

**Écart à §9 (« un seul essai de rechange ») : trois versions, fixées ici avant tout calcul, toutes rapportées.**
- **v1** : la spec telle quelle (masque, calage par sorte, asinh).
- **v2** : masque gardé ; PAS d'asinh ; calage des résidus PAR IDENTITÉ, comme le témoin 2 (`temoin_noeud.identite` :
  pod ramené à son service, répliques regroupées ; StatefulSet, file, machine par leur nom), médiane et échelle
  robustes par (identité, colonne) sur les résidus tenus hors pli, avec le plancher par sorte du témoin 2 ; une
  identité sans normal retombe sur le calage par sorte. L'identité ne sert qu'à caler la SORTIE (comme le témoin 2),
  jamais en entrée du modèle (AR 31 tenu : le modèle ne voit aucun nom ; en production, ce calage se refait sur
  des minutes normales, sans étiquettes).
- **v3** : v2, mais l'étape 1 est l'auto-encodeur du rapport (R:828-829, etat.txt E:61) : SANS masque, goulot de
  dimension 8 en sortie de l'encodeur (les décodeurs ne lisent que le plongement final), une seule passe par fenêtre.
- Chaque version passe le banc (§7) qui fixe SON propre CHOIX B/H/V selon §3.5.

**Règle de choix entre v1, v2, v3 (validation seule, graine 0 à 4, 150 époques), dans l'ordre :**
1. G_val tient pour les 5 graines (avec le CHOIX de la version) ;
2. la plus grande détection (fenêtres de panne) au budget de la règle (21/249 mis à l'échelle), médiane des graines ;
3. à ±5 fenêtres près, le plus grand top-1 sans alarme (causes apprises), médiane des graines ;
4. à égalité, la plus simple : v1 < v2 < v3.
Si aucune ne passe 1 : v2 avec B1/H0/V0 serait inacceptable → arrêt, décision avec l'utilisateur.

---

## 12. Écart E-2 (28 sept., décidé par l'utilisateur, écrit AVANT tout calcul) : le GNN « avec exemples » a les mêmes droits que les témoins

**Constat.** J 1023-1024 et §0.2 font désigner le fautif TOUJOURS par l'étape 1 (apprise sur le normal seul), même
devant une cause connue ; le témoin 2 « avec exemples », lui, apprend l'alarme (forêt), le fautif (régression
logistique partagée) et la cause (prototypes) sur les pannes d'apprentissage, et ne retombe sur l'écart seul que
devant « inconnue » (J 1018-1024) : 114/115 au top-1 de validation. Le GNN courait avec un handicap que le témoin n'a
pas. L'utilisateur exige que le GNN égale les témoins sur les 4 causes connues : on lui donne la même information.

**Ce qui change (réglage « avec exemples » du GNN seulement ; « sans exemples » inchangé = étape 1 seule).**
Même recette que `temoin_noeud` « avec exemples », mais sur ce que voit le GNN (sans aucun nom en entrée) :
1. **Alarme apprise** : une forêt (mêmes réglages que le témoin 2 : 200 arbres, graines 0–4) sur le profil d'écart du
   GNN (§5 : extrêmes signés des z par sorte/colonne et par relation/colonne) + le score de fenêtre de l'étape 1 ;
   seuil calé comme le témoin 2 (mêmes minutes normales tenues hors pli, même budget).
2. **Fautif appris** : une régression logistique PARTAGÉE par sorte de nœud (mêmes réglages que le témoin 2), dont
   les entrées pour un nœud sont ses z (nœud) et l'agrégat de ses flèches (B), plus son plongement de l'étape 1
   (dimension 32, sans nom) : la probabilité d'être le fautif classe les nœuds.
3. **Cause** : prototypes et rejet de §5, inchangés.
4. **Repli** : si la cause est « inconnue » (rejet) ou si l'alarme apprise ne sonne pas mais que l'alarme de l'étape 1
   sonne, le classement est celui de l'étape 1 (graphe, CHOIX B/H/V) — c'est le cas de C et D, causes jamais vues.
5. Tout se règle sur `juge.validation` ; aucune fenêtre de test des séries, ni C, ni D. La répétition « panne jamais
   vue » (validation) mesure le repli.

**Comparaison.** Le GNN « avec exemples » est comparé aux témoins « avec exemples » (même information), le GNN « sans
exemples » aux témoins « sans exemples ». Les décisions de C et D (J 1244-1257) restent écrites comme avant ; sur C et D,
la cause étant nouvelle, c'est le repli (étape 1) qui désigne, pour les deux réglages.

---

## 13. Écart E-3 (28 sept., écrit AVANT tout nouveau calcul) : un choix B/H/V ÉQUILIBRÉ entre les familles du banc

**Constat.** §3.5 (critère 3 : le plus de cas du banc au rang 1, TOUTES familles additionnées) a retenu pour v2
B2/H0/V1, qui trouve la réplique fabriquée mais presque jamais la base fabriquée (« entrant dans tsdb-mysql-0 » : 0 à
1/128) ni la machine fabriquée sur workers5 (0 à 2/128). Le banc existe pour éprouver ces choix sur les pannes de type
C et D (J 1301-1311) ; la somme laissait la famille la plus nombreuse (réplique) décider. Défaut de la spec écrite ce
jour, pas du journal. Aucune donnée de C ni de D n'a été lue.

**Nouvelle règle, pour chaque version, parmi les combinaisons dont G_val tient pour les 5 graines :**
- familles (médiane des graines, part au rang 1) : **F_C** = « entrant dans tsdb-mysql-0 », d ∈ {75, 150, 300} ;
  **F_D** = cas M et M+Y, X ∈ {workers0, workers2, workers5}, d ∈ {75, 150, 300} ; **F_R** = cas R et « sortant »
  (la réplique) ; (Y, « entrant » ts-order-service et 400 ms : rapportés, hors critère) ;
- on retient le plus grand **min(F_C, F_D, F_R)** ; à 0,05 près, le plus grand top-1 de validation ; puis le plus simple.
**Choix de la version (remplace la règle de §11) :** (1) G_val ; (2) détection au budget de la règle ; (3) le plus
grand min(F_C, F_D, F_R) de la version (à 0,05 près) ; (4) top-1 de validation (à ±5) ; (5) la plus simple.
**Arrêt :** si aucune version n'atteint min(F_C, F_D, F_R) ≥ 0,5, on ne fige pas : décision avec l'utilisateur.

---

## 14. Écart E-4 (28 sept., décidé par l'utilisateur, avant l'ouverture de C et D) : rejet « inconnue » par le logit

Remplace §12.3 (« rejet inchangé ») pour le GNN « avec exemples » : la régression du fautif ne désigne que si son logit
maximal atteint un seuil calé sur l'APPRENTISSAGE seul, au milieu entre le 5e centile des causes connues (chaque
injection mise de côté) et le 95e centile des causes retirées (chaque cause mise de côté) ; en dessous : cause
« inconnue » et classement de l'étape 1. Motif : le rejet de §5 ne reconnaissait presque jamais une cause retirée
(répétition : 0/76 pour blocage et lenteur), si bien que le repli prévu pour C et D ne se serait pas déclenché.
À dire : ce seuil a connu deux essais, le premier (5e centile seul) vu sur la validation. Le rejet de §5 reste affiché
à côté dans les sorties. Consigne de l'utilisateur : favoriser le GNN par tout réglage légitime AVANT l'ouverture de C
et D, sur la validation et le banc seulement ; rien n'est réglé après l'ouverture, aucun résultat n'est caché.

---

## 15. Écart E-5 (28 sept., décidé par l'utilisateur, écrit AVANT tout calcul) : le GNN combiné

**Constat (§13, confirmé par un recompte indépendant).** Aucune version n'atteint min(F_C, F_D, F_R) ≥ 0,5. v1
(B5/H2/V0) : F_C 0,77 [0,12–0,99], F_D 0,87, F_R 0,05, G_val tient, mais alarme cassée (11/153 au budget). v2 et v3 :
alarme réparée (153/153) mais F_C ≤ 0,10 et F_D ≤ 0,10 ; en M+Y, le leurre passe premier (calage par identité : un
nœud d'habitude calme paraît énorme). Aucune combinaison d'aucune version ne trouve à la fois la base et la réplique.

**Le GNN combiné (nom de version « v12 »)** : deux exemplaires du même modèle, entraînés à part sur les mêmes normales,
mêmes graines, chacun dans son réglage :
- **alarme** : l'exemplaire v2 (score de fenêtre, seuil propre et budgets comme §4) ;
- **classement du fautif** : l'exemplaire v1 et le CHOIX B5/H2/V0 (celui que §13 donne à v1) ;
- **GNN avec exemples** : ses parties apprises (forêt d'alarme, régression du fautif, prototypes) sur les écarts et
  le plongement de l'exemplaire v2 ; rejet par le logit (E-4, §14) ; repli : le classement de l'exemplaire v1 (B5/H2/V0) ;
  alarme = forêt OU alarme de l'exemplaire v2 ;
- aucune identité en entrée d'aucun modèle ; empreintes des deux exemplaires notées au gel.

**Critères pour figer (validation et banc seulement, 5 graines, 150 époques), tous requis :**
1. G_val tient pour les 5 graines ;
2. détection au budget de la règle ≥ 150/153 (médiane) ;
3. banc : F_C ≥ 0,5 et F_D ≥ 0,5 (médianes) ; F_R rapporté (faiblesse connue, dite) ;
4. GNN avec exemples : top-1 ≥ 114/115 et détection ≥ 150/153 (médianes) ; répétition « jamais vue » : « inconnue »
   dans une majorité des fenêtres de chaque cause retirée.
Si un critère manque : pas de gel, décision avec l'utilisateur.

**Pour la production (rapporté à part, ne change aucune décision)** : alarme « persistante » (2 minutes de suite),
mesurée sur la validation (fausses alertes par heure, détection, retard de détection), comme etat.txt le propose
(E:81). Consigne de l'utilisateur : rendre le GNN le plus performant possible honnêtement avant le gel, et le meilleur
possible en production.

---

## 16. Compléments écrits avant le gel (29 sept.) : ce que le code du GNN combiné fait et que §14–§15 ne disaient pas

Constats des relecteurs d'E.7 : le code applique déjà ces choix ; ils sont écrits ici, avant tout gel, pour que rien
de ce qui décide ne reste hors de la spec. Aucun n'a été réglé sur C, D ou le vrai test.
1. **Rejet E-4, deux règles de plus** : (a) si les logits des causes connues et ceux des causes retirées se
   chevauchent, le seuil retombe au 5e centile des causes connues (mises de côté injection par injection) ;
   (b) la cause « charge » (sans fautif) garde le rejet de §5. Coût mesuré (répétition) : charge retirée → blocage
   top-1 32/38 [22–38] au lieu de 38/38 ; blocage retiré → lenteur 37/38 [31–38].
2. **« GNN, avec exemples, budget de la règle »** : les deux alarmes (forêt et exemplaire v2) sont calées ensemble,
   chacune à son k-ième score tenu, avec le plus grand k qui tient 10/121 (budget de la règle mis à l'échelle).
3. **Mesure de production** (§15, hors décision) : alarme sur 2 minutes de suite ; le retard se compte depuis le
   début de l'injection ; la mesure répond aussi sur les minutes que le juge écarte (à cheval, vidange), pour ne pas
   couper la suite des minutes ; 4 minutes normales sans minute précédente sont signalées.
4. **Variantes** (« GNN sans aucune arête », retrait de chaque relation…) : rendues par `methodes()` en réglage sans
   exemples, pour le retrait des flèches.
5. **Ce que coûte le classement v1** (à dire au rapport) : sans exemples, l'exemplaire v2 seul trouvait 76/115 fautifs
   au top-1 de validation (lenteur 37/38) ; v12 en trouve 38/115 (lenteur 0/38). C'est le prix de F_C 0,77 et F_D 0,87.
   Les critères 3 et 4 de §15 ne tiennent qu'à la MÉDIANE des graines (une graine : F_C 0,12 ; une autre : top-1 113/115).

---

## 17. Variante pré-enregistrée « GNN unique » (29 sept., décidée par l'utilisateur, écrite AVANT tout calcul et AVANT tout regard sur la première ouverture)

**Pourquoi.** v12 utilise deux exemplaires entraînés à part (v2 pour l'alarme, v1 pour le fautif). La différence qui
compte pour le fautif est surtout le CALAGE des résidus (par sorte contre par identité), qui se fait après le modèle.
Question à trancher par la mesure : un seul modèle suffit-il ?
**La variante « u » (GNN unique)** : UN exemplaire, celui de v2 (masque, sans asinh, mêmes normales, mêmes graines) ; ses
résidus sont calés deux fois : par identité → alarme (exactement comme v12) ; PAR SORTE → classement du fautif avec les
règles B5/H2/V0 (comme l'exemplaire v1 de v12). Réglage « avec exemples » : parties apprises sur les écarts par identité
et le plongement de ce même modèle, rejet E-4, repli sur son classement par sorte. Aucun autre changement.
**Critères** : exactement ceux de §15 (G_val 5 graines ; détection au budget de la règle ≥ 150/153 ; banc F_C ≥ 0,5 et
F_D ≥ 0,5 ; avec exemples top-1 ≥ 114/115, détection ≥ 150/153, « inconnue » majoritaire par cause retirée), rapportés
quel que soit le résultat.
**Lecture de C et D.** Personne ne regarde les résultats de la première ouverture (v12, tmux « ouverture » sur vms0) avant
l'étiquette gnn-fige-2 (variante u figée). Exception écrite ici à « C et D lus une seule fois » : une seconde lecture, pour
la seule variante u, figée avant tout regard sur la première. v12, figée en premier, reste la variante de référence des
décisions pré-enregistrées ; les verdicts de u sont rapportés à côté, avec les mêmes règles. Calculs lourds sur une
machine dédiée (vms1, SLICES), de la validation jusqu'à sa lecture de C et D (empreintes reproductibles sur la même machine).
