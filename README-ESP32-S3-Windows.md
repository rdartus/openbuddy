# Installer OpenBuddy sur l’ESP32-S3 AMOLED v2 — Windows

Pour la **Waveshare ESP32-S3-Touch-AMOLED-1.64 v2** : écran 280 × 456,
CS sur **GPIO46**, flash 16 Mo et PSRAM 8 Mo.
Le pet peut être installé **dans la flash de l’ESP32 (par défaut)** ou sur une
**carte TF FAT32** ; le firmware personnalisé reste toujours en flash interne.

**À prévoir :** Windows 10/11, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
OpenCode v2 et un câble USB-C **de données**. Pas besoin de compiler sur Windows,
ni d'installer Node.js/npm. L'accéléromètre QMI8658 choisit automatiquement entre
les deux sens paysage à 180° ; aucun portrait. Le tactile FT3168 est utilisé pour
les réponses aux demandes OpenCode. L’axe Y et son signe ont
été mesurés sur une carte v2 ; vérifier le résultat visuel après déploiement.

> Toutes les commandes se lancent dans **PowerShell**, depuis le dossier `openbuddy`.
> **Arrêter à la première erreur.** Fermer Thonny, les moniteurs série et le pont
> OpenBuddy avant un flashage, un déploiement ou un transfert : un seul programme
> peut utiliser le port USB à la fois.

## 1. Préparer les fichiers et Python

Si tu n’as pas encore le dépôt :

```powershell
git clone --branch master https://github.com/rdartus/openbuddy.git
Set-Location openbuddy
```

Si tu as déjà le dépôt, ouvre PowerShell dans son dossier et mets-le à jour :

```powershell
git status --short
git fetch origin
git switch master
git pull --ff-only origin master
```

Si Git affiche des modifications locales ou une divergence, ne les efface pas :
résous-les avant de poursuivre. Pour un artefact issu d'une autre branche,
utilise **cette branche** à la place de `master` dans `clone`, `switch` et `pull` ;
ne change pas de branche après le téléchargement. Le **commit** local doit
toujours être celui inscrit dans l'artefact, comme vérifié à l'étape 2.

Préparer Python, sans activer de venv ni demander de droits administrateur :

```powershell
uv python install 3.13
if (-not (Test-Path .venv)) { uv venv --python 3.13 }
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt -r pc\requirements-assets.txt esptool
```

## 2. Télécharger le firmware compilé

1. Ouvrir les [GitHub Actions du dépôt](https://github.com/rdartus/openbuddy/actions/workflows/s3-qspi.yml).
2. Choisir **Build S3 AMOLED v2 QSPI firmware**, sur `master` ou la branche
   utilisée à l'étape 1, pour **le même commit que ton dépôt**
   (`git rev-parse HEAD`). Les builds de pull request utilisent le commit de
   la branche proposée, pas le commit de fusion temporaire de GitHub.
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
if ($Build.board -ne "waveshare-s3-amoled-164-v2" -or $Build.lcd_cs -ne 46 -or $Build.flash_bytes -ne 16777216 -or $Build.pet_storage -ne "internal" -or (@($Build.pet_storage_options) -join ',') -ne "internal,sd" -or $Build.qspi_api_version -ne 4) { throw "Mauvais firmware S3 v2" }
if ($Build.orientation_sensor -ne "qmi8658" -or $Build.flash_budget.vfs_bytes -ne 14680064 -or $Build.flash_budget.spare_vfs_bytes -le 0) { throw "Build sans orientation ou budget flash verifie" }
if ($Build.usb_backend -ne "usb-serial-jtag" -or $Build.usb_vid -ne 0x303A -or $Build.usb_pid -ne 0x1001) { throw "Ancien build USB : telecharger le firmware Serial/JTAG corrige" }
$Hash = (Get-FileHash .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Hash -ne $Build.firmware_sha256) { throw "Empreinte du firmware incorrecte" }
```

**Ne pas continuer si une vérification échoue.** Télécharger un build ne change
rien sur la carte : le flashage se fait à l’étape suivante.

## 3. Flasher l’ESP32-S3

**Sauvegarder les fichiers importants de la carte avant de flasher.**
Ne pas lancer `erase-flash` dans la procédure normale. Le build conserve le
partitionnement MicroPython v1.29.0 SPIRAM_OCT ; la conservation des données
n’est pas garantie depuis un firmware constructeur, Arduino ou un autre
partitionnement.

Brancher la carte, repérer son port dans la liste et le saisir :

```powershell
uv run python -m serial.tools.list_ports -v
$Port = Read-Host "Port de la carte (COM suivi de son numero)"
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin
if ($LASTEXITCODE -ne 0) { throw "Flashage en echec : ne pas poursuivre" }
```

Si la connexion échoue : maintenir **BOOT**, appuyer puis relâcher **RST**,
relâcher BOOT, relister les ports et réessayer avec le bon `$Port`.

Après un flashage réussi, appuyer sur **RST**, puis relister les ports :

```powershell
uv run python -m serial.tools.list_ports -v
$Port = Read-Host "Port actuel de la carte"
```

Le build corrigé conserve l’USB **Serial/JTAG matériel** d’Espressif
(`VID:PID 303A:1001`), comme le mode de téléchargement ROM. Une brève déconnexion
pendant le reset reste possible ; le port doit ensuite être de nouveau détectable.
L’ancien build utilisait **TinyUSB CDC (`303A:4001`)** et changeait le périphérique
USB au démarrage. Sur cette carte, ne pas confondre ce changement ou une disparition
USB avec un port occupé par un programme PC. L’USB matériel ne garantit pas que
MicroPython ait fini de démarrer : un éventuel crash reste à diagnostiquer.

**Si le port disparaît avec l’ancien `.bin` :** maintenir BOOT, appuyer puis
relâcher RST, puis relâcher BOOT pour retrouver le port ROM. Reprendre le flashage
avec le build corrigé vérifié à l’étape 2, sans effacement de la flash. Une simple
mise à jour des fichiers Python ne peut pas corriger le backend USB du `.bin`.

## 4. Déployer OpenBuddy et tester l’écran

**Utiliser exactement le profil ci-dessous, avec le suffixe `-v2`.**
Le déploiement vérifie le module natif avant de copier les fichiers.
Cette commande sélectionne explicitement le profil de la carte S3 v2.
Le pilote accéléré exige **`amoled_qspi.API_VERSION >= 4`** : reflasher d’abord
le nouveau `.bin` vérifié, sans effacer la flash, puis déployer les fichiers
Python du même commit. Les `.bin` API v2/v3 et ces fichiers ne sont pas compatibles.

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
L'interface suivante doit occuper les **456 × 280 pixels en paysage** ; une fois
installé à l'étape 5, le pet est agrandi en ×2 sans nouvelle conversion du pack.
La petite interface 320 × 172 ne doit plus rester au milieu de l'écran :
les dispositions sont choisies par le profil dans
`board_config.py`.
Sur S3 comme sur C6, la barre colorée supérieure **et le séparateur horizontal
inférieur** s'étendent d'un bord à l'autre en paysage.
**Si l’écran reste noir ou affiche mal les couleurs, arrêter ici et conserver
la sortie du terminal.** Ne pas installer le pet ni multiplier les effacements.

Après le reset, tenir la carte successivement dans les deux sens paysage et
attendre au moins une seconde dans chacun : l’interface doit rester lisible en
paysage. Posée à plat ou tenue verticalement, la carte conserve la dernière
orientation. BOOT court retourne toujours la vue à 180° (correction du capteur
jusqu’au redémarrage), BOOT long conserve l’appairage. En cas de capteur absent,
la rotation manuelle reste utilisable. La mesure de l'axe ne remplace pas cet
essai visuel de rotation.

### Si le système de fichiers est corrompu

Si `pc.deploy` échoue avec **`The filesystem appears to be corrupted`** puis
`could not enter raw repl`, le port USB peut être visible mais MicroPython ne
peut pas accéder à son système de fichiers. Relancer `pc.deploy` ou changer de
port ne répare pas ce problème. Ce cas peut notamment survenir après un flash
depuis un firmware au partitionnement différent ; ne pas en déduire la cause
exacte sans diagnostic.

**Si la carte contient des fichiers ou des clés d’appairage à conserver, arrêter
ici et sauvegarder sa flash avant toute remise à zéro.** Sur une carte dont tout
le contenu peut être perdu, vérifier à nouveau le port et le `.bin` comme aux
étapes 2–3, puis seulement effectuer la récupération suivante :

```powershell
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 erase-flash
if ($LASTEXITCODE -ne 0) { throw "Effacement en echec : ne pas poursuivre" }
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin
if ($LASTEXITCODE -ne 0) { throw "Reflashage en echec : ne pas poursuivre" }
```

**Cette opération efface le pet, les clés BLE et tous les autres fichiers de la
carte.** Appuyer sur RST, relister les ports comme à l’étape 3, puis reprendre
le déploiement et le test écran de l’étape 4. Un port occupé ou un simple délai
de réponse USB ne justifie pas un effacement.

## 5. Installer le pet en flash interne ou sur la carte TF

Uniquement après un test écran réussi, convertir le pack commun aux deux cartes :

```powershell
uv run python -m pc.pet convert
```

**Sans carte TF**, installer dans la flash interne (choix par défaut) :

```powershell
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat-black --port $Port --storage internal
uv run python -m pc.buddy --serial $Port status
```

**Avec carte TF FAT32 insérée**, pour conserver la place en flash sur une
installation neuve, choisir explicitement la TF :

```powershell
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat-black --port $Port --storage sd
uv run python -m pc.buddy --serial $Port status
```

Le transfert contrôle la place libre sur la destination (dont 256 Kio de réserve
pour le pack et **32 Kio disponibles en flash** pour mémoriser le choix TF),
relit les fichiers et vérifie les SHA-256 avant de mémoriser le choix dans
`openbuddy-storage.txt` sur la flash. **Aucune carte n'est formatée** ; le bus TF
du S3 est distinct du QSPI de l'écran. Une installation ultérieure avec
`--storage internal` rebascule sur la flash après vérification, sans effacer le
pack sur la TF, et inversement. `--storage auto` suit ensuite le dernier choix
validé ; sur un S3 neuf ou sans marqueur, il choisit la flash et ne bascule pas
silencieusement sur la TF si la flash est pleine. Si la TF sélectionnée est
absente ou pleine, l'installation échoue plutôt que de changer de destination.
Un ancien pack dans l'autre destination n'est jamais supprimé automatiquement.
La lecture de la TF en fonctionnement normal est **en lecture seule**.

Le pack noir `build/pets/super-saiyan-goku-combat-black` est **le même pour C6
et S3** : les zones transparentes et les bords semi-transparents sont composités
sur le fond RGB `(0,0,0)` dès la conversion. Seuls son agrandissement à l'écran
et sa destination (flash interne ou TF sur S3, microSD sur C6) changent. Les
anciens packs à fond `(8,12,20)` sont refusés sur les **deux** profils afin
d'éviter un rectangle visible autour du pet.
Un ancien pack déjà installé doit être remplacé explicitement en ajoutant
`--replace` à la commande `install` ci-dessus ; garder tout ancien pack local intact.
Si le dossier noir existe déjà, le réutiliser sans relancer `convert`, ou utiliser
`--force` pour le reconvertir volontairement. Un pack noir déjà créé avec un autre
nom de dossier reste compatible : donner son chemin à `install`, sans le recopier.
Le changement de fond sur un firmware déjà en **API v4** ne demande **pas de
nouveau `.bin`** : lors
d'une mise à jour, après installation du pack noir, redéployer les fichiers
Python de l'étape 4.

Résultat attendu : **`"assets": "internal", "sd": false`** sans TF, ou
**`"assets": "sd", "sd": true`** avec TF, et un identifiant dans `"pet"`.
Si la TF sélectionnée manque au démarrage, le robot remplace le pet et le
firmware retente périodiquement son montage : il ne lit pas un éventuel ancien
pack interne à la place. Le pet n’est pas inclus dans le `.bin`.

**Le mode sans TF tient dans la flash de 16 Mio** sur une installation neuve :
14 Mio sont réservés aux fichiers. Le pet représente 1 457 664 octets de pixels
(environ 1,50 Mio avec les marges). Le build contrôle les tailles du firmware, des fichiers
Python et de deux packs complets pour permettre le remplacement, plus 256 Kio de
réserve. Les chiffres exacts sont dans `$Build.flash_budget` et le résumé de
l’Action. Ce budget conservateur s'applique même si le pet est placé sur TF.
L’installateur vérifie aussi la place réellement libre sur la destination choisie ;
il refuse un transfert trop gros sans effacer d’autres fichiers.

Le `status` doit aussi montrer `"imu": true` et l’`"orientation"` courante
après initialisation du capteur ; au tout début, `"imu": false` peut encore
apparaître. Si les sens sont incorrects, voir les constantes d’axes et les
limites de validation dans le [guide S3](docs/s3-amoled.md#orientation-automatique-v2-uniquement).

### Si la rotation réagit au portrait plutôt qu'au paysage

Une ancienne version utilisait l'axe **X** du QMI8658. Sur une carte v2 mesurée,
la gravité en paysage est sur **Y** : environ +16 200 avec USB-C à gauche et
−16 100 avec USB-C à droite (1 g = 16 384). Le profil corrigé utilise Y avec
le signe négatif ; en portrait il conserve la dernière orientation paysage.

Si le firmware natif installé est déjà en **API v4** et que seul le code Python
change, arrêter le pont puis redéployer les fichiers du dépôt mis à jour avec
la commande de l'étape 4. **Pas besoin de reflasher le `.bin` ni d'effacer la
flash.** Le précontrôle de `pc.deploy` refuse un firmware natif incompatible.
Après le déploiement, vérifier les deux sens et relancer le pont (étape 6).

Pour mesurer les axes sur une autre révision, tenir la carte debout, écran face
à soi, dans un sens paysage, puis répéter dans l'autre sens. Le pont doit être
arrêté avant chaque accès au port. Depuis la racine du dépôt :

```powershell
uv run python -m pc.opencode stop
try {
    uv run python -m mpremote connect $Port run tools/test_orientation.py
} finally {
    uv run python -m mpremote connect $Port reset
}
```

Le diagnostic affiche dix mesures X/Y/Z en une seconde, sans modifier la
flash ; le `reset` relance le compagnon. Répéter pour l'autre sens et relancer
ensuite le pont (étape 6). Le signe de l'axe mesuré peut varier sur une autre
révision : ne pas le supposer d'après le nom du capteur.

Si un ancien pack existe sur la carte, suivre les consignes de remplacement de
l'étape 5 plutôt que de conserver son ancien fond sombre.

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
Le build **API v2** souffre d’une lenteur de rendu qui bloque parfois la boucle
USB pendant plusieurs secondes. Le build API v4 reprend l'accélération native
de l'API v3 et ajoute l'interface plein écran et le pet ×2 ; sa réactivité
reste à valider sur matériel. Si le pont
affiche `USB unavailable: TimeoutError - retrying`, conserver sa sortie ; ne
pas effacer la flash ni simplement augmenter le timeout. Voir les
[mesures et le correctif](docs/s3-qspi-build.md#performance-du-rendu-et-timeouts-usb).

Les fois suivantes, ouvrir PowerShell dans `openbuddy` et relancer **uniquement
cette dernière commande**. Ne pas reflasher ni réinstaller le pet à chaque démarrage.
Sans événement d’OpenCode, l’état `OFFLINE` est normal.

### Si ça bloque

- **Port disparu après le flash du `.bin`** : suivre la récupération BOOT/RST de
  l’étape 3 et vérifier `usb_backend: "usb-serial-jtag"` dans `BUILD.json`.
- **Port occupé** : arrêter le pont avec `Ctrl+C` et fermer les autres outils série.
- **`status` expire alors que le port est visible** : vérifier d’abord que le
  nouveau build est en API v4. Sur l’ancien build API v2, le rendu peut bloquer
  la boucle USB bien après le démarrage. Ce message seul ne démontre ni un
  port occupé ni une flash corrompue.
- **Déploiement ou transfert bloqué** : les outils arrêtent leur processus `mpremote`
  après 30 s pour le précontrôle, 180 s pour le déploiement ou 600 s pour le pet,
  puis tentent un reset limité à 20 s. `--timeout SECONDES` ajuste la durée du
  transfert dans `pc.deploy` et `pc.pet install`. Si le reset échoue, appuyer sur
  **RST** ; l’erreur initiale reste affichée. Un pack interrompu se reprend avec
  `--replace`, sans effacer la flash.
- **Module `amoled_qspi` absent ou trop ancien** : reflasher le `.bin` de l’étape 2 ;
  `pc.deploy` seul ne peut pas installer le module C.
- **Écran noir ou interface encore petite au centre** : vérifier le profil
  **`waveshare-s3-amoled-164-v2`**, l'API v4 et le commit identique pour le `.bin`
  et les fichiers Python, puis le test de l’étape 4. Les anciennes marges autour
  de l'interface 320 × 172 ne sont plus attendues.
- **Pas de pet** : vérifier `assets` et `sd` dans `status`, la destination choisie
  à l'étape 5 et, en mode TF, l'insertion et le format FAT32 de la carte. Ne pas
  reformater la carte automatiquement ni effacer la flash pour ce diagnostic.
- **BLE indisponible au démarrage** : le compagnon reste utilisable par USB et
  BOOT court conserve la rotation. Le détail est dans `openbuddy-error.txt`, avec
  `Stage: BLE` ; le BLE sera retenté au prochain démarrage.
- **Problème persistant** : conserver les erreurs et consulter le
  [guide matériel S3](docs/s3-amoled.md#diagnostic).

Les détails de compilation et de transport sont dans le
[guide technique QSPI](docs/s3-qspi-build.md).
