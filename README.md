# OpenBuddy

**L'activité d'OpenCode, visible en un coup d'œil.** Un compagnon physique pour
deux cartes ESP32 Waveshare : **C6-LCD-1.47** (écran paysage 320×172, halo RVB)
et **S3-Touch-AMOLED-1.64 v2** (écran paysage 456×280). Le pet animé et l'état
sont synchronisés en **Local USB** ou en **Bluetooth**.

Portage **Waveshare ESP32-S3-Touch-AMOLED-1.64 v2 (280x456, CS GPIO46, 16 Mo flash,
8 Mo PSRAM)** : pet **en flash interne par défaut ou sur TF FAT32 sélectionnée
explicitement**, sans repli automatique, avec un firmware
experimental integrant le module natif **`amoled_qspi`**, pas le `.bin` MicroPython
officiel. **[Installation Windows ESP32-S3 : suivre ce README](README-ESP32-S3-Windows.md).**
Le QMI8658 choisit automatiquement entre les deux sens paysage à 180°, sans mode
portrait. Ce portage reste a valider sur la carte reelle.

![Démonstration OpenBuddy : les événements OpenCode synchronisent les écrans et le pet Goku en Local USB ou Bluetooth.](docs/media/openbuddy-demo.gif)

*Scénario simulé, rendu par le vrai code d'affichage du firmware et les animations
RGB565 du pet installé. Ce n'est pas une capture d'une session OpenCode réelle.
[Aperçu fixe](docs/media/openbuddy-demo.png) · Pet « Super Saiyan Goku Combat » par
[datpham / Codex Pets](https://codex-pets.net/#/pets/super-saiyan-goku-combat).*

## Comment la synchronisation fonctionne

```text
OpenCode v2 → plugin d'événements → pont Python local → Local USB ou Bluetooth
                                                           ↓
                                                écran + animation + halo
```

Le plugin écoute les **événements OpenCode v2**, suit les sessions et les demandes
en attente, puis transmet un état au pont Python. Le pont envoie cet état au buddy ;
le firmware choisit l'écran, l'accent coloré (halo RVB sur C6) et l'animation
lue sur microSD C6, ou sur flash interne / TF S3 selon l'installation.
Les images ne sont pas envoyées en continu par le transport.

| Dans OpenCode | Sur OpenBuddy |
|---|---|
| Prêt, aucune exécution active | `READY` — pet au repos |
| L'agent réfléchit | `THINKING` — halo bleu |
| Un outil s'exécute ou une réponse s'écrit | `WORKING` — pet en action, halo turquoise |
| Une autorisation attend une validation | `PERMISSION` — halo orange |
| Une question attend une réponse | `QUESTION` — halo jaune |
| L'exécution a réussi | `DONE` — animation de succès, halo vert |
| L'exécution a échoué | `ERROR` — animation d'échec, halo rouge |
| Une nouvelle tentative est programmée | `RETRY` — animation d'attente, halo ambre |
| Plus de heartbeat du pont pendant 15 s | `OFFLINE` — pet au repos, halo atténué |

Les permissions et questions sont prioritaires, y compris avec plusieurs sessions.
Sur Windows, **sons et notifications visuelles** complètent le compagnon pour les
permissions, questions, succès et erreurs. `--mute` coupe seulement les sons ;
`--no-notifications` coupe seulement les notifications Windows.

Sur le **S3 v2 tactile**, une question à choix unique ou une permission complète
apparaît à droite du pet : glisser horizontalement pour changer de proposition,
toucher pour valider. Le texte trop long défile. Les autres formulaires restent
à traiter dans OpenCode. Pour une permission, les choix sont **Refuser**,
**Autoriser une fois** et **Toujours autoriser** ; le dernier enregistre une règle
persistante. Le C6 n'est pas tactile. Le texte de la demande et les choix sont
transmis localement au pont et au S3 seulement quand l'écran peut les afficher ;
aucun contenu d'outil ou prompt libre n'est envoyé.

## Deux modes, le même compagnon

| | Local USB | Bluetooth |
|---|---|---|
| Connexion | Câble USB-C **de données**, port série | Bluetooth LE : service GATT OpenBuddy + clavier HID |
| Démarrage du pont | `--serial auto` ou `--serial COMx` | Sans option de transport |
| Appairage | Aucun | BOOT long, vérification du code, puis **deuxième appui court** |
| Écran et pet (halo RVB sur C6) | Identiques pour une même carte | Identiques pour une même carte |
| Boutons et clavier | Pas de remontée de BOOT ni de HID ; tactile S3 disponible | BOOT sert à l'appairage (appui long, puis confirmation du code) ; tactile S3 disponible |

Le mode USB requiert le **firmware 0.3.0** ou plus (0.4.0 pour le quota,
0.5.0 pour les réponses tactiles S3). Le firmware conserve aussi le BLE :
le choix du transport se fait au lancement du pont. En USB, un seul outil peut
utiliser le port série à la fois. En Bluetooth, le buddy accepte un seul hôte à
la fois. Les autorisations USB/Bluetooth du système restent applicables.

## Premier setup de l'ESP32

Une carte neuve contient généralement une démonstration constructeur, **pas
MicroPython ni OpenBuddy**. `pc.deploy` copie les fichiers Python mais n'installe
pas MicroPython : il faut donc préparer la carte une première fois.

| Carte | Firmware requis | Profil `pc.deploy --board` |
|---|---|---|
| Waveshare ESP32-C6-LCD-1.47 non tactile | MicroPython officiel `ESP32_GENERIC_C6` 1.29.0 | `waveshare-c6-lcd-147` |
| Waveshare ESP32-S3-Touch-AMOLED-1.64 **v2** | Build OpenBuddy MicroPython 1.29.0 + `amoled_qspi` API v4, `OPENBUDDY_S3_AMOLED_V2`, PSRAM octale ([guide](docs/s3-qspi-build.md)) | `waveshare-s3-amoled-164-v2` |

**Ne pas utiliser le firmware C6 sur le S3**, ni la variante S3 sans PSRAM octale
pour cette carte S3R8. Vérifier la référence exacte du matériel avant de commencer.

Pour le **S3 AMOLED v2, avec ou sans microSD**, suivre uniquement le
**[README Windows ESP32-S3](README-ESP32-S3-Windows.md)** : preparation du PC,
telechargement du build, flashage, test ecran, pet en flash et lancement USB.
Ce parcours s'applique aussi si MicroPython officiel est deja flashe.
Les instructions C6 ci-dessous ne concernent pas le S3.

Pour le **C6**, depuis la racine du dépôt dans PowerShell :

```powershell
uv python install 3.13
uv venv --python 3.13
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt -r pc\requirements-assets.txt esptool
uv run python -m serial.tools.list_ports -v
$Port = "COM5" # Remplacer par le port detecte
```

Télécharger le `.bin` MicroPython 1.29.0 depuis
<https://micropython.org/download/ESP32_GENERIC_C6/> dans la racine du dépôt.
Pour entrer en bootloader : maintenir BOOT, appuyer puis relâcher RST, puis relâcher
BOOT. Utiliser un câble USB-C **de données** et vérifier le port après chaque changement
de mode. Fermer tout pont, moniteur série ou autre outil qui utilise ce port.

**Première installation uniquement : `erase-flash` efface la démonstration usine,
les fichiers et les appairages. Sauvegarder les données utiles avant.**

```powershell
uv run python -m esptool --chip esp32c6 --port $Port flash-id
uv run python -m esptool --chip esp32c6 --port $Port erase-flash
uv run python -m esptool --chip esp32c6 --port $Port --baud 460800 write-flash 0 ESP32_GENERIC_C6-20260824-v1.29.0.bin
```

Appuyer sur RST, relister les ports et ajuster `$Port` si nécessaire, puis :

```powershell
uv run python -m serial.tools.list_ports -v
uv run python -m pc.deploy --port $Port --board waveshare-c6-lcd-147
```

Le robot intégré doit apparaître, même sans pack d'animations. Pour installer le pet,
voir [les animations](docs/animations.md). Pour une mise à jour ultérieure, relancer
seulement `pc.deploy` : **ne pas refaire `erase-flash`**. Aucun besoin d'activer le
venv ni de modifier la politique d'exécution PowerShell avec ces commandes.

## Installer depuis le dépôt

Prérequis : **Windows 10/11, uv, OpenCode v2** en service
local géré. Le plugin et le pont tournent sur la même machine qu'OpenCode.
`uv` installe ici CPython 3.13 et gère les dépendances dans `.venv`.
Avec un kit contenant le plugin compilé, Node/npm n'est pas nécessaire pour
l'utiliser. Un clone des sources peut nécessiter sa reconstruction ci-dessous.
Si la carte est neuve, commencer par le [premier setup](#premier-setup-de-lesp32).

Depuis PowerShell :

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/) si nécessaire
(installation utilisateur, sans administrateur), puis rouvrir PowerShell :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

La politique d'exécution n'est contournée que pour ce processus d'installation,
pas modifiée globalement. Depuis la racine du dépôt, ou après clonage :

```powershell
git clone https://github.com/Nespouique/openbuddy.git
Set-Location openbuddy
uv python install 3.13
uv venv --python 3.13
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt
```

Si `.venv` est déjà préparé, ne pas le recréer. Les commandes utilisent
`uv run python`, sans activation PowerShell. Le premier setup
C6 utilise également uv ; installer uv avant de le suivre.

Si `integration\openbuddy\dist\index.js` est absent, installer Node.js avec npm,
puis générer le plugin :

```powershell
npm --prefix integration/openbuddy ci --ignore-scripts
npm --prefix integration/openbuddy run build
```

Installer ensuite le plugin :

```powershell
uv run python -m pc.install_plugin
```

Dans OpenCode, utiliser `/reload` si nécessaire. Pour mettre à jour une installation
du plugin existante, ajouter `--replace` : les fichiers remplacés sont sauvegardés,
sans modifier les configurations OpenCode ni les autres plugins.
Pour une copie du dépôt déjà présente, utiliser `git pull` au lieu de la cloner.

### Local USB

Brancher le câble de données, puis lancer depuis la racine du dépôt :

```powershell
uv run python -m pc.buddy --serial auto scan
uv run python -m pc.buddy --serial auto status
uv run python -m pc.opencode --serial auto
```

`auto` sélectionne l'unique port Espressif ; utiliser `--serial COMx` s'il y en a
plusieurs. **Garder le pont actif**. Les lanceurs `tools\openbuddy-usb.cmd` et
`tools\openbuddy-usb-stop.cmd` permettent aussi de le démarrer en arrière-plan et
de l'arrêter, sans démarrage automatique Windows.

Pour mettre a jour les fichiers Python, arreter d'abord le pont et les autres
outils serie, puis :

```powershell
uv pip install --python .venv\Scripts\python.exe -r pc\requirements-assets.txt
uv run python -m pc.deploy --port COMx
```

Remplacer `COMx` par le port détecté. Le déploiement ne formate pas la carte et
conserve la SD et les clés Bluetooth. [Guide USB détaillé](distribution/workplace/README-usb.md).
Sur S3, le firmware natif doit deja etre compatible ; `pc.deploy` ne le remplace
pas. Pour changer le module natif, suivre le [guide QSPI](docs/s3-qspi-build.md).

### Bluetooth

Alimenter le buddy, ouvrir l'ajout d'appareil Bluetooth dans Windows, puis maintenir
BOOT environ 3 s. Comparer les codes, confirmer dans Windows et faire un
**deuxième appui court sur BOOT**. Déconnecter tout ancien hôte à portée.

```powershell
uv run python -m pc.buddy scan
uv run python -m pc.buddy status
uv run python -m pc.opencode
```

Être reconnu comme clavier ne garantit pas l'accès au service GATT personnalisé.
[Guide Bluetooth détaillé](docs/ble-prototype.md).

### Diagnostic et arrêt

Dans un autre terminal, depuis la même racine :

```powershell
uv run python -m pc.opencode status
uv run python -m pc.opencode stop
```

`status` indique notamment `sources`, `usb_connected` / `ble_connected` et
`last_delivered`. `Ctrl+C` arrête aussi le pont lancé dans un terminal.
[Architecture et dépannage](docs/opencode-events.md).

## Pet et matériel

Le pet est lu sur la **microSD ou la flash interne**, en RGB565, avec un seul buffer d'image en RAM.
Sur le S3 AMOLED, l'installation peut se faire entièrement sans microSD ou
mettre le pet sur la TF en gardant les fichiers Python en flash.
Sans pack installé, un robot intégré prend le relais. Les sprites et les packs
du pet ne sont pas fournis dans le dépôt ou les kits : les visuels ci-dessus sont
une démonstration de l'affichage, pas un pack d'assets. Le bouton BOOT (appui court)
retourne l'affichage de 180° ; l'orientation choisie est mémorisée.
Sur le S3 v2, l'accéléromètre adapte aussi ce sens automatiquement, après 500 ms
de stabilité ; à plat ou en position verticale, la dernière vue est conservée.
BOOT apporte une correction de 180° au capteur jusqu'au redémarrage.

- [Préparer et installer une animation](docs/animations.md)
- [Afficher le quota du fournisseur (ex. GitHub Copilot)](docs/opencode-events.md#quota-du-fournisseur)
- [Matériel, brochage et précautions](docs/hardware.md)
- [Sources et attributions](THIRD_PARTY.md)

## Kits prêts à installer — optionnels

Pour installer sans cloner le dépôt, les [Releases](https://github.com/Nespouique/openbuddy/releases/latest)
proposent un **[kit Local USB](https://github.com/Nespouique/openbuddy/releases/latest/download/openbuddy-workplace-usb.zip)**
et un **[kit Bluetooth](https://github.com/Nespouique/openbuddy/releases/latest/download/openbuddy-workplace.zip)**,
avec les dépendances Windows x64 hors ligne et leur README. Les sources GitHub
ne contiennent pas le wheelhouse hors ligne.

Reconstruction locale des kits :

```powershell
uv run python tools/package_workplace.py --variant usb --download-wheels
uv run python tools/package_workplace.py --variant bluetooth --download-wheels
```

Un kit existant n'est remplacé qu'avec `--replace`.

## Fichiers

`device/` regroupe l'application MicroPython commune ; **le dossier du dépôt
n'est pas reproduit sur l'ESP32** : `pc.deploy` copie les modules directement
à la racine du système de fichiers de la carte. Le profil de `board_config.py`
sélectionne l'écran, les broches, l'orientation et le stockage. Le C6 utilise
MicroPython officiel ; `firmware/` contient le module C et la carte de build
du firmware S3 v2. Le `.bin` compilé est livré séparément dans `dist/s3-qspi/`.

| Chemin | Rôle |
|---|---|
| `device/board_config.py` | Broches et géométrie, source unique |
| `device/pet_format.py` | Fond noir et format du pack partagés entre PC, C6 et S3 |
| `device/main.py`, `companion.py` | Démarrage et boucle firmware |
| `device/buddy_ble.py` | HID, GATT, appairage et clés |
| `device/buddy_usb.py` | États et choix tactiles sur le port série USB |
| `device/ft3168.py`, `buddy_prompt.py` | Tactile et choix affichés sur le S3 v2 |
| `device/st7789.py`, `co5300.py` | Pilotes écran C6 et S3 (QSPI natif) |
| `device/buddy_ui.py` | Interface 320×172 C6 / 456×280 S3 ; halo RVB C6 |
| `device/buddy_protocol.py` | Protocole partagé PC / ESP32 |
| `device/shared_spi.py`, `sdcard_spi.py`, `storage.py` | Bus partagé et SD en lecture seule |
| `device/pet_player.py` | Lecteur RGB565, une image en RAM |
| `device/orientation_demo.py` | Ancienne démo conservée |
| `firmware/amoled_qspi/`, `firmware/boards/` | Module C et configuration du firmware S3 |
| `pc/buddy.py` | Diagnostic BLE et USB en Python |
| `pc/opencode.py` | Pont événements et choix tactiles → BLE/USB, authentifié localement |
| `pc/notifications.py` | Sons système Windows non bloquants |
| `pc/toasts.py` | Notifications Windows natives, sans données privées |
| `pc/install_plugin.py` | Installation globale/par projet sans modifier la configuration |
| `integration/openbuddy/dist/` | Plugin v2 autonome, prêt à installer |
| `integration/openbuddy/src/` | Sources et tests du plugin |
| `pc/pet.py` | Conversion et installation des packs |
| `pc/deploy.py` | Déploiement des seuls fichiers firmware |
| `tools/openbuddy-usb.cmd`, `openbuddy-usb-stop.cmd` | Lancement en arrière-plan et arrêt du pont USB |
| `tools/build_readme_demo.py` | Génération hors ligne du GIF à partir du firmware et d'un pack local |
| `docs/hardware.md` | Matériel, brochage et précautions |

## Développement

Installer aussi `pc/requirements-assets.txt` pour Pillow et les outils de déploiement.
Les tests n'accèdent pas au matériel et n'exigent pas les images Goku :

```powershell
uv pip install --python .venv\Scripts\python.exe -r pc\requirements-dev.txt
uv run python -m tools.check_micropython
uv run python -m unittest discover -s tests -v
npm --prefix integration/openbuddy test
npm --prefix integration/openbuddy run typecheck
```

Le contrôle MicroPython utilise obligatoirement `mpy-cross` **1.29.0** sur tous
les fichiers installés par `pc.deploy` ; un compilateur absent, une syntaxe
incompatible ou une API/importation Python non portable connue fait échouer les
tests. La CI Linux exécute aussi le protocole et les choix sur le port Unix de
MicroPython 1.29. Les mocks CPython ne suffisent
donc plus à faire passer ces régressions, mais ni ces contrôles ni le port Unix ne
remplacent les tests réels sur ESP32 (matériel, BLE, écran et module QSPI natif).

Node/npm est utilisé uniquement pour développer/reconstruire le plugin :
`npm --prefix integration/openbuddy ci`, puis `npm --prefix integration/openbuddy run build`.
Ne pas modifier le bundle compilé à la main.

Exception native S3 : la compilation C requiert ESP-IDF, hors environnement uv.
Le [guide QSPI](docs/s3-qspi-build.md#compilation-linux-sans-docker) centralise
la compilation Linux et les tests C sur hote. Ni ces tests ni les tests Python
simules ne valident l'affichage reel.

Pour régénérer le visuel du README depuis un pack déjà converti localement sur
fond noir (les anciens packs à fond sombre ne correspondent plus au firmware) :

```powershell
uv run python tools/build_readme_demo.py --pet-dir build/pets/super-saiyan-goku-combat-black
```

Le générateur utilise `BuddyUI`, `PetPlayer` et la police du firmware ; il ne se
connecte ni à OpenCode ni au buddy et ne télécharge aucun asset.
