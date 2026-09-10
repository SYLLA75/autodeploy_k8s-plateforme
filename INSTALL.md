# Mise en route sur une machine neuve

> De rien à des figures. Compter 1 h 30, dont une heure d'attente pendant
> laquelle la machine travaille seule.

Chaque étape indique **où** elle se fait : sur votre poste, ou sur le nœud de
contrôle de la grappe.

---

## Étape 0 — Ce que la machine doit avoir

**Où** : sur votre poste · **Durée** : 5 minutes

Ubuntu 22.04 ou 24.04 — poste de travail, serveur, ou machine virtuelle.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip openssh-client curl
python3 --version      # 3.10 minimum ; 3.12 recommandé
```

C'est tout. En particulier, **ne sont PAS nécessaires sur votre poste** :

| outil | pourquoi |
|-------|----------|
| `kubectl` | tous les appels passent par `ssh master "kubectl …"` |
| `helm` | installé sur le nœud de contrôle par `deploy.sh` |
| Ansible | installé dans `kubespray/venv-kubespray/` par le script |
| Docker | les images sont tirées par les machines, pas par vous |
| `rsync` | `scp` suffit |

`python3-venv` est vérifié explicitement au démarrage : sans lui, Kubespray ne
peut pas créer son environnement, et le script s'arrête avec la commande à taper.

### Place disque

| | |
|---|---|
| `kubespray/` + son environnement | ~ 600 Mo |
| environnement Python du constructeur de graphe | ~ 1,2 Go (PyTorch) |
| une campagne rapatriée | 200 Mo à 1 Go |
| **prévoir** | **5 Go confortables** |

Sans l'export PyTorch (`pytorch_geometric: false`), l'environnement du
constructeur tombe à ~ 80 Mo.

### Flux réseau sortants

Depuis votre poste :

| destination | pourquoi |
|-------------|----------|
| `bastion2.slices-be.eu:22` | seul accès aux machines — elles n'ont pas d'adresse publique |
| API SLICES (HTTPS) | réservation des machines |
| `github.com` (HTTPS) | clonage de Kubespray |
| PyPI (HTTPS) | installation des bibliothèques Python |
| votre magasin d'objets (HTTPS) | rapatriement des mesures |

Les machines réservées ont leurs propres accès sortants — dépôts Helm, Maven
Central, registres d'images. Vous n'avez rien à ouvrir pour elles.

> Si `deploy.sh` échoue en annonçant que les machines sont injoignables, la
> cause la plus fréquente est un filtrage sortant sur le port 22, ou une adresse
> IP publique non déclarée auprès de SLICES.

---

## Étape 1 — Une clé SSH connue de SLICES

**Où** : sur votre poste · **Durée** : 5 minutes

SLICES enregistre votre clé **publique** sur chaque machine créée. Le script se
connecte ensuite avec la clé **privée**. Il faut donc les deux.

```bash
ls ~/.ssh/id_rsa ~/.ssh/id_rsa.pub 2>/dev/null \
    || ssh-keygen -t ed25519 -f ~/.ssh/id_rsa -N ""
```

La clé privée est le fichier **sans** `.pub`. C'est la confusion la plus
fréquente : un dossier `~/.ssh/` qui ne contient que des `.pub` n'a pas de clé
privée, et le déploiement s'arrête dès la première étape.

Ces chemins iront dans `.env` :

```
SSH_SOURCE_PRIV_KEY="/home/VOTRE_NOM/.ssh/id_rsa"
SSH_SOURCE_PUB_KEY="/home/VOTRE_NOM/.ssh/id_rsa.pub"
```

Rien n'oblige à réutiliser la clé d'une autre machine : une paire neuve, créée
là où vous lancez le déploiement, convient parfaitement. C'est même préférable —
une clé privée ne se recopie pas de machine en machine.

> Le script travaille sur une **copie** de la clé, en `chmod 600`, dans
> `~/.ssh/id_rsa_slices`. OpenSSH refuse une clé privée dont les droits sont
> trop ouverts ; la copie garantit les bons droits sans toucher à l'originale.

---

## Étape 2 — La CLI SLICES

**Où** : sur votre poste · **Durée** : 5 minutes

Elle réserve les machines. Elle vit dans son propre environnement Python pour ne
rien imposer au système.

```bash
python3 -m venv ~/slices-venv
~/slices-venv/bin/pip install --upgrade pip
~/slices-venv/bin/pip install slices-cli slices-cli-bi
export PATH="$HOME/slices-venv/bin:$PATH"
```

Ajoutez cette dernière ligne à votre `~/.bashrc` pour ne pas la retaper.

**Authentification**, une fois :

```bash
slices auth login
```

**Vérification** — elle doit lister les gabarits disponibles :

```bash
slices bi --site-id be-gent1-bi-vm1 flavor list
```

Si cette commande échoue, rien de ce qui suit ne fonctionnera : l'accès au banc
d'essai est le premier prérequis.

---

## Étape 3 — Récupérer le dépôt

**Où** : sur votre poste · **Durée** : 1 minute

```bash
cd ~
git clone <URL_DU_DEPOT> autodeploy_k8s
cd autodeploy_k8s
```

> Le dossier doit s'appeler `autodeploy_k8s` : la documentation y fait référence
> par ce nom. Un autre nom fonctionne, mais les commandes des autres fichiers
> seront à adapter.

---

## Étape 4 — Configurer

**Où** : sur votre poste · **Durée** : 10 minutes

Trois fichiers, aucun n'est versionné.

### 4a. `.env` — la grappe

```bash
cp .env.example .env
$EDITOR .env
```

Ce qu'il faut adapter :

| variable | pourquoi |
|----------|----------|
| `EXPERIMENT_NAME` | un nom à vous ; elle est créée automatiquement si elle n'existe pas |
| `SSH_SOURCE_PRIV_KEY` / `_PUB_KEY` | les chemins des clés de l'étape 1 |
| `SITE_ID` | le site SLICES où vous avez des droits |
| `DURATION` | `3h` pour un essai, `3d` pour une campagne |

Laissez `PROFILE_TT_WORKERS=7` et `OBS_DEDICATED_NODE="workers6"` : six machines
pour l'application, une réservée à la mesure. Descendre en dessous sature les
machines — mesuré à 96-98 % de mémoire sur quatre workers, avec des pannes
applicatives à la clé.

### 4b. `.env.secrets` — le magasin d'objets

Ce fichier n'a pas de modèle : il ne contient que des identifiants.

```bash
cat > .env.secrets <<'EOF'
OBS_S3_ENDPOINT="https://s3.exemple.eu"
OBS_S3_BUCKET="votre-bucket"
OBS_S3_PREFIX="otel-data"
OBS_S3_REGION="us-east-1"
OBS_S3_ACCESS_KEY="..."
OBS_S3_SECRET_KEY="..."
EOF
chmod 600 .env.secrets
```

### 4c. `graphe_en/config.yaml` — la construction du graphe

```bash
cp graphe_en/config.example.yaml graphe_en/config.yaml
chmod 600 graphe_en/config.yaml
```

Laissez `access_key` et `secret_key` vides : ils seront lus dans
l'environnement, ce qui évite d'écrire un secret dans un fichier de
configuration. La plage de dates se remplit plus tard, à l'étape 8.

---

## Étape 5 — Déployer la grappe et l'application

**Où** : sur votre poste · **Durée** : 45 à 60 minutes, sans intervention

```bash
./deploy.sh --app train-ticket
```

Cette commande réserve les machines, installe Kubernetes, prépare le stockage,
**réserve le nœud de mesure**, puis déploie les 56 pods de train-ticket.

**Ce que vous devez voir à la fin** : un récapitulatif avec l'adresse du nœud de
contrôle et les URLs de l'application.

**Vérification** :

```bash
ssh master 'kubectl get nodes'
ssh master 'kubectl get pods -n train-ticket --no-headers | wc -l'
```

Huit machines, et 56 pods.

> Le script est rejouable : en cas d'échec, relancez-le. Il réutilise ce qui
> existe déjà et reprend là où il s'était arrêté.

---

## Étape 6 — Poser la chaîne de mesure

**Où** : sur votre poste, puis sur le nœud de contrôle · **Durée** : 15 minutes

Suivre **PROCEDURE.md**, étapes 2 à 8 :

```
  2   envoyer .env.secrets sur le nœud de contrôle
  3   installer la chaîne de mesure
  4   vérifier la réservation du nœud de mesure
  5   instrumenter les 46 services
  6   trois copies du consommateur
  7   lancer le générateur de trafic
  8   vérifier que chaque grandeur est mesurable
```

L'étape 8 parcourt chaque grandeur dont le graphe a besoin et répond `PRESENT`
ou `ABSENT`. N'allez pas plus loin tant qu'il reste des `ABSENT`.

---

## Étape 7 — Laisser tourner

**Où** : sur le nœud de contrôle · **Durée** : 30 à 60 minutes

La grandeur centrale du travail est une pente : elle demande des dizaines de
minutes de trafic régulier.

```bash
ssh master
bash ~/autodeploy/apps/collecte.sh etat
```

Entre deux expériences, on arrête d'enregistrer sans détruire la grappe :

```bash
bash ~/autodeploy/apps/collecte.sh arreter     # plus rien n'est enregistré
bash ~/autodeploy/apps/collecte.sh demarrer    # on réenregistre
```

L'application, elle, continue de tourner et reste instrumentée.

---

## Étape 8 — Construire le graphe et les figures

**Où** : sur votre poste · **Durée** : 5 minutes

Demandez d'abord la plage exacte à traiter — **en heure UTC**, celle du magasin
et non celle de votre poste :

```bash
ssh master 'bash ~/autodeploy/apps/collecte.sh fenetre'
```

Elle rend un bloc à recopier tel quel dans `graphe_en/config.yaml` :

```yaml
range:
  date:       2026-09-10
  from:       "01:32"
  to:         "02:03"
```

Puis :

```bash
cd graphe_en
python3 -m venv .venv
set -a; . ../.env.secrets; set +a
./.venv/bin/python run.py
```

Les bibliothèques manquantes s'installent seules, dans cet environnement
virtuel uniquement. Sur un interpréteur système, le script refuse et affiche la
commande à taper — installer des paquets dans le Python du système casserait les
outils de la machine.

**Ce que vous obtenez** :

```
runs/<horodatage>/
    run.log                 tout ce que le terminal a affiché
    raw/                    les archives rapatriées, et leur provenance
    graph/  manifest.json   réglages, provenance, dimensions, écarts au papier
            window_*.json   un cliché par fenêtre
            graph.pt        les tenseurs PyTorch Geometric
    figures/                deux vues SVG par fenêtre
```

Pour refaire les figures sans retélécharger :

```bash
./.venv/bin/python run.py --render-only runs/<horodatage>
```

---

## Étape 9 — Libérer les machines

**Où** : sur votre poste

```bash
./destroy.sh --yes
```

Détruit les machines SLICES et nettoie le poste. **Rapatriez vos données
avant** : elles sont dans le magasin d'objets, mais les archives locales du
nœud de contrôle disparaissent avec lui.

---

## Si quelque chose ne va pas

| symptôme | cause la plus fréquente |
|----------|------------------------|
| `Impossible de lister les ressources` | l'expérience n'existe pas ; `deploy.sh` la crée maintenant tout seul |
| `Connection timed out` sur le nœud de contrôle | le bastion n'est pas utilisé — vérifier que `inventory.ini` existe |
| `nacos-0 Init:Error` en boucle | élection MySQL bloquée ; voir RECOMMANDATIONS.md, correctif 1 |
| pods `Pending`, `Insufficient memory` | trop peu de workers ; `PROFILE_TT_WORKERS` doit valoir 7 |
| `0 publishes, 0 consumes` dans les figures | la plage précède le démarrage du trafic ; utiliser `collecte.sh fenetre` |
| un pod `Pending` avec `PersistentVolume's node affinity` | un volume local est resté sur un nœud interdit ; voir RECOMMANDATIONS.md, correctifs 4 et 5 |

**RECOMMANDATIONS.md** recense les huit défauts rencontrés et corrigés, avec ce
qui a été observé pour chacun.
