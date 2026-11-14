# Installer OpenBuddy sur l’ESP32-S3 AMOLED v2 — Windows

Pour la **Waveshare ESP32-S3-Touch-AMOLED-1.64 v2** : écran 280 × 456,
CS sur **GPIO46**, flash 16 Mo et PSRAM 8 Mo.
Le pet sera installé **dans la flash de l’ESP32**, sans carte TF/microSD.

**À prévoir :** Windows 10/11, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
OpenCode v2 et un câble USB-C **de données**. Pas besoin de compiler sur Windows,
ni d’installer Node.js/npm. Le portage reste à valider sur la carte réelle ;
le tactile et l’IMU ne sont pas utilisés.

> Toutes les commandes se lancent dans **PowerShell**, depuis le dossier `openbuddy`.
> **Arrêter à la première erreur.** Fermer Thonny, les moniteurs série et le pont
> OpenBuddy avant un flashage, un déploiement ou un transfert : un seul programme
> peut utiliser le port USB à la fois.

## 1. Préparer les fichiers et Python

Si tu n’as pas encore le dépôt :

```powershell
git clone --branch feat/esp32-s3-amoled-164 https://github.com/rdartus/openbuddy.git
Set-Location openbuddy
```

Si tu as déjà le dépôt, ouvre PowerShell dans son dossier et mets-le à jour :

```powershell
git status --short
git fetch origin
git switch feat/esp32-s3-amoled-164
git pull --ff-only origin feat/esp32-s3-amoled-164
```

Si Git affiche des modifications locales ou une divergence, ne les efface pas :
résous-les avant de poursuivre.

Préparer Python, sans activer de venv ni demander de droits administrateur :

```powershell
uv python install 3.13
if (-not (Test-Path .venv)) { uv venv --python 3.13 }
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt -r pc\requirements-assets.txt esptool
```

## 2. Télécharger le firmware compilé

1. Ouvrir les [GitHub Actions du dépôt](https://github.com/rdartus/openbuddy/actions/workflows/s3-qspi.yml).
2. Choisir **Build S3 AMOLED v2 QSPI firmware**, sur la branche
   `feat/esp32-s3-amoled-164`, pour **le même commit que ton dépôt** (`git rev-parse HEAD`).
3. Attendre la réussite de l’exécution, puis télécharger l’artefact
   **`openbuddy-s3-amoled-qspi`** en bas de sa page. Se connecter à GitHub si nécessaire.
4. Extraire son contenu dans **`dist\s3-qspi`**, à la racine du dépôt.

Tu dois notamment avoir `dist\s3-qspi\openbuddy-s3-amoled-qspi.bin` et
`dist\s3-qspi\BUILD.json`, directement dans ce dossier, sans sous-dossier supplémentaire.
`git pull` **ne télécharge pas le `.bin`**. Ne pas utiliser un firmware MicroPython officiel.
Le ZIP `openbuddy-s3-qspi-files.zip` contient les fichiers correspondants ; il n’est
pas nécessaire de l’extraire ici puisque tu utilises le dépôt complet du même commit.

Vérifier le commit, le profil et l’empreinte avant de flasher :

```powershell
$Build = Get-Content .\dist\s3-qspi\BUILD.json -Raw | ConvertFrom-Json
if ($Build.openbuddy_commit -ne (git rev-parse HEAD).Trim() -or $Build.openbuddy_dirty) { throw "Le build ne correspond pas au depot propre" }
if ($Build.board -ne "waveshare-s3-amoled-164-v2" -or $Build.lcd_cs -ne 46 -or $Build.flash_bytes -ne 16777216 -or $Build.pet_storage -ne "internal" -or $Build.qspi_api_version -ne 2) { throw "Mauvais firmware S3 v2" }
$Hash = (Get-FileHash .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Hash -ne $Build.firmware_sha256) { throw "Empreinte du firmware incorrecte" }
```

**Ne pas continuer si une vérification échoue.** Télécharger un build ne change
rien sur la carte : le flashage se fait à l’étape suivante.

## 3. Flasher l’ESP32-S3

**Sauvegarder les fichiers importants de la carte avant de flasher.**
Ne pas lancer `erase-flash`. Le build conserve le partitionnement MicroPython
v1.29.0 SPIRAM_OCT ; la conservation des données n’est pas garantie depuis un
firmware constructeur, Arduino ou un autre partitionnement.

Brancher la carte, repérer son port dans la liste et le saisir :

```powershell
uv run python -m serial.tools.list_ports -v
$Port = Read-Host "Port de la carte (COM suivi de son numero)"
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin
if ($LASTEXITCODE -ne 0) { throw "Flashage en echec : ne pas poursuivre" }
```

Si la connexion échoue : maintenir **BOOT**, appuyer puis relâcher **RST**,
relâcher BOOT, relister les ports et réessayer avec le bon `$Port`.

Après un flashage réussi, appuyer sur **RST**. Le port peut changer :

```powershell
uv run python -m serial.tools.list_ports -v
$Port = Read-Host "Port actuel de la carte"
```

## 4. Déployer OpenBuddy et tester l’écran

**Utiliser exactement le profil ci-dessous, avec le suffixe `-v2`.**
Le déploiement vérifie le module natif avant de copier les fichiers.
Même si tu avais déjà déployé OpenBuddy, cette commande corrige l’ancien profil GPIO9.

```powershell
uv run python -m pc.deploy --port $Port --board waveshare-s3-amoled-164-v2
if ($LASTEXITCODE -ne 0) { throw "Deploiement en echec : verifier le firmware natif" }
try {
    uv run python -m mpremote connect $Port run tools/test_amoled.py
    if ($LASTEXITCODE -ne 0) { throw "Test ecran en echec" }
} finally {
    uv run python -m mpremote connect $Port reset
}
```

La dalle entière doit afficher **rouge, vert, bleu, noir, blanc**, 1,5 seconde par
couleur. Le `reset` relance OpenBuddy, même si le test échoue.
**Si l’écran reste noir ou affiche mal les couleurs, arrêter ici et conserver
la sortie du terminal.** Ne pas installer le pet ni multiplier les effacements.

## 5. Installer le pet en flash interne

Uniquement après un test écran réussi :

```powershell
uv run python -m pc.pet convert
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal
uv run python -m pc.buddy --serial $Port status
```

Résultat attendu : **`"assets": "internal"`**, **`"sd": false`** et un identifiant
dans `"pet"`. Le pet n’est pas inclus dans le `.bin` : cette étape le copie en flash
et vérifie les fichiers. Sur ce profil, aucune carte TF n’est utilisée, même si la
flash est pleine ou si le pack manque.

Si la conversion existe déjà, la conserver ; utiliser `convert --force` seulement
pour la refaire. Si le pack est déjà sur la carte, le conserver ou ajouter
**`--replace`** à la commande `install` pour le remplacer.

## 6. Installer le plugin et lancer OpenBuddy

Installer le plugin déjà fourni dans le dépôt, sans Node.js/npm :

```powershell
uv run python -m pc.install_plugin --source plugin/openbuddy
```

Si une ancienne installation doit être mise à jour, relancer avec `--replace` :
l’installateur sauvegarde l’ancienne copie. Utiliser **`/reload`** dans OpenCode si
nécessaire. Ne pas charger une deuxième copie du plugin dans un projet.

Lancer ensuite le pont USB :

```powershell
uv run python -m pc.opencode --serial auto
```

**Laisser ce terminal ouvert.** `Ctrl+C` arrête le pont. Aucun appairage Bluetooth
n’est nécessaire. `auto` exige une seule carte Espressif branchée ; sinon utiliser
`--serial` avec son port explicite.

Les fois suivantes, ouvrir PowerShell dans `openbuddy` et relancer **uniquement
cette dernière commande**. Ne pas reflasher ni réinstaller le pet à chaque démarrage.
Sans événement d’OpenCode, l’état `OFFLINE` est normal.

### Si ça bloque

- **Port occupé** : arrêter le pont avec `Ctrl+C` et fermer les autres outils série.
- **Module `amoled_qspi` absent ou trop ancien** : reflasher le `.bin` de l’étape 2 ;
  `pc.deploy` seul ne peut pas installer le module C.
- **Écran noir** : vérifier le profil **`waveshare-s3-amoled-164-v2`**, puis le test
  de l’étape 4. Les marges noires autour de l’interface centrée sont normales.
- **Pas de pet** : vérifier le résultat de l’étape 5, sans ajouter de carte TF.
- **Problème persistant** : conserver les erreurs et consulter le
  [guide matériel S3](docs/s3-amoled.md#diagnostic).

Les détails de compilation et de transport sont dans le
[guide technique QSPI](docs/s3-qspi-build.md).
