# openbuddy

Petit appareil physique (ESP32) qui rend OpenCode interactif dans le monde réel : il signale quand OpenCode attend une réponse et affiche son état (pet animé depuis la microSD ou la flash interne sur S3). Sur S3, seuls les choix de formulaires et permissions representables peuvent etre valides depuis l'appareil ; le C6 reste un indicateur.

Lire d'abord `docs/hardware.md` (matériel, brochage, pièges), `docs/opencode-events.md` et `docs/animations.md` avant de modifier le firmware ou l'intégration.
Pour le S3 AMOLED, lire aussi [le guide firmware QSPI](docs/s3-qspi-build.md), reference technique pour les versions, artefacts, compilation et tests natifs. Le [README Windows S3](README-ESP32-S3-Windows.md) est le parcours unique d'installation, verification des hashes et reflashage ; les anciens guides Windows y renvoient. Ne pas dupliquer ces procedures dans les autres guides.

## Conventions

- Réponses et documentation en français. Code, noms, commentaires et messages de commit en anglais.
- Ne pas supposer de droits administrateur sur le PC (Windows) : utiliser uv et `.venv`, aucun `.msi`. Commandes Python Windows : `uv run python`, sans activation PowerShell.
- Firmware en **MicroPython**. Le C6 conserve MicroPython officiel, sans toolchain C. Exception S3 AMOLED : module C `amoled_qspi` compile dans un firmware personnalise avec PSRAM octale ; le `.bin` officiel ne suffit pas et `pc.deploy` ne peut pas installer ce module. Compiler exige la toolchain ESP-IDF sous Linux, hors environnement uv ; utiliser un artefact construit ne l'exige pas sur le PC Windows.
- Ne pas utiliser `$_` dans un `powershell -Command` lancé depuis bash : passer par un fichier `.ps1`.
- Tests matériels toujours mockés en CI : ne pas flasher d'appareil ni jouer de notification bureau depuis les tests unitaires.
- Ne jamais committer : clés d'appairage BLE, jetons de découverte du pont, adresses d'appareil réelles, ports série ou chemins personnels, packs du pet, caches, environnements virtuels, `node_modules`. Ce fichier est publié : il ne doit contenir aucune de ces informations.

## Structure

- `device/` : application **MicroPython commune** aux ESP32 C6-LCD-1.47 et S3 AMOLED 1.64 v2, déployée à la racine de la carte. `board_config.py` = identité, broches et géométrie par profil (source unique), `st7789.py` = pilote C6, `main.py`/`companion.py` = boucle principale, `buddy_ble.py` = HID/GATT/appairage, `buddy_ui.py` = écran et halo C6, `buddy_protocol.py` = protocole partagé PC/carte. `firmware/` contient les sources compilées et la configuration de build S3 ; le `.bin` résultant est dans `dist/s3-qspi/`.
- `device/co5300.py` : pilote S3 AMOLED utilisant `amoled_qspi` natif (sources dans `firmware/`). Demos Waveshare : SH8601 ou CO5300, sans detection confirmee du silicium. Registres sur une ligne, pixels sur quatre ; SPI2_HOST est reserve au module natif comme dans la demo v2, ne pas creer `machine.SPI(1)` en parallele. SD sur bus separe.
- `device/buddy_usb.py` : transport USB série, même protocole JSON que BLE, sans HID ni remontée de BOOT. Le tactile S3 remonte les choix par USB ou BLE ; USB prend l'affichage tant que sa lease est active, sauf appairage BLE prioritaire.
- `device/orientation_demo.py` : ancienne démo conservée.
- `device/qmi8658.py`, `buddy_orientation.py` : accéléromètre I²C QMI8658 v2 uniquement (SDA47/SCL48, 0x6B), ±2 g/62,5 Hz, polling 100 ms et stabilité 500 ms. Deux sens paysage à 180° seulement, jamais de portrait ; pas d'écriture flash automatique, aucune initialisation I²C sur C6. Axe/signe dans `board_config.py`, montage physique encore à valider.
- `device/ft3168.py`, `buddy_prompt.py` : tactile S3 v2, FT3168 à 0x38 sur le bus de l'IMU ; swipe horizontal = choix, vertical = demande. Validation uniquement par appui stable ≥ 1 s dans le cadre du choix, 1,2 s de garde après glissement, aucune validation sur tap bref. Réponse possible dès que la demande et les choix sont reçus, même si le texte défile encore ; `Refuser` est initial, `Toujours autoriser` est persistant. Formulaires à un seul champ de choix uniquement ; validation par ID de demande via l'API v2, jamais par HID.
- `device/shared_spi.py`, `sdcard_spi.py`, `storage.py`, `pet_player.py` : bus écran/SD partagé, carte en lecture seule, lecteur RGB565 à un buffer.
- `pc/buddy.py` : diagnostic BLE Python/Bleak, `uv run python -m pc.buddy` depuis la racine.
- `device/pet_format.py` : fond noir et dimensions du pack communs au convertisseur PC et aux profils C6/S3. Un seul pack RGB565 `build/pets/<id>-black/` sert aux deux cartes ; seules l'échelle d'affichage et la destination (SD/interne) changent.
- `pc/pet.py` : conversion Codex Pets et installation USB vérifiée ; `pc/deploy.py` : déploiement firmware sans effacement.
- `pc/opencode.py` : pont événements → carte, démarrage `uv run python -m pc.opencode`, diagnostic/arrêt avec `status`/`stop`.
- Mode USB : `uv run python -m pc.opencode --serial auto` (ou un port explicite), diagnostic `uv run python -m pc.buddy --serial auto status`. Un seul outil sur le port série, DTR/RTS bas. Arrêter le pont avant `pc.deploy`, `pc.pet` ou `mpremote`.
- `integration/openbuddy/dist/` : plugin v2 autonome généré, hors autochargement ; sources dans `integration/openbuddy/src/`, métadonnées/licence dans `assets/`, build `npm --prefix integration/openbuddy run build`. Ne pas éditer `index.js` à la main. Installation globale avec `uv run python -m pc.install_plugin`.
- `pc/quota.py` : texte `utilisé / limite` du fournisseur (ex. `0 / 200`) via une commande configurée dans `%APPDATA%\openbuddy\quota.json`, envoyé au firmware dans le champ optionnel `info` de la commande `state` et affiché à la place de `PET / MICROSD` ; rafraîchi toutes les 600 s et à l'entrée dans les états de `refresh_on` (`success` par défaut, 10 s minimum entre deux appels) ; `--no-quota` ou `--quota-config`. Les tests ne doivent jamais lancer la vraie commande (voir `setUpModule` de `tests/test_opencode_bridge.py`).
- `pc/notifications.py` : sons système Windows, option `--mute`. `pc/toasts.py` : notifications Windows WinRT natives, texte générique, toast silencieux, option `--no-notifications`, aucun bouton de validation.
- `pc/install_plugin.py` : installateur du plugin (global par défaut, projet en option), sauvegarde avant `--replace`, aucun changement des configs JSON.
- `tools/package_workplace.py` : ZIP de transfert par liste blanche, wheels hors ligne ; README du kit dans `distribution/workplace/README.md`, variante USB avec `--variant usb` et `README-usb.md`.
- `tools/prepare_publication.py` : liste blanche de publication. `AGENTS.md`, la doc publique et les sources en font partie ; `docs/hardware-notes.md`, packs du pet et clés n'en font jamais partie.
- `tools/build_readme_demo.py` : démo README sans matériel (Pillow). Seuls `docs/media/openbuddy-demo.gif` et `.png` peuvent illustrer le pet ; packs/sprites bruts toujours exclus des sources et kits.
- `docs/ble-prototype.md` : installation, appairage (appui long puis appui court de confirmation), protocole et commandes de test.

## État

- Cible : C6-LCD-1.47, MicroPython 1.29, écran **landscape 320×172** (USB-C à gauche par défaut), BLE HID + GATT et USB série, appairage authentifié avec clés persistantes.
- Portage S3-Touch-AMOLED-1.64 experimental : firmware natif obligatoire, installation sans microSD possible. Meme apres un flash officiel reussi, commencer par le guide QSPI, puis `import amoled_qspi`, preflight de `pc.deploy`, `tools/test_amoled.py` et `reset` meme en cas d'echec, avant les animations. Conserver les sorties si le test echoue ; ne pas multiplier les effacements.
- Revision S3 AMOLED **v2** : profil `waveshare-s3-amoled-164-v2`, CS=GPIO46, 40 MHz, pet exclusivement interne (`PET_STORAGE = "internal"`), aucun montage TF meme sans pack. Build dedie `firmware/boards/OPENBUDDY_S3_AMOLED_V2`, flash 16 Mio, PSRAM octale, identite frozen ; module natif API v4 et CS configurable obligatoires. Un marqueur existant reste prioritaire : le corriger avec `pc.deploy --board waveshare-s3-amoled-164-v2`.
- USB du build S3 v2 : Serial/JTAG materiel `303a:1001`, TinyUSB/OTG desactive pour ne pas remplacer le peripherique USB apres flashage. Le packaging controle les symboles compiles et publie `usb_backend`, `usb_vid`, `usb_pid` dans `BUILD.json`. Ce correctif exige un nouveau `.bin`, pas seulement `pc.deploy` ; retour du port encore a valider sur carte.
- Microprogramme **0.6.3** (kits publiés en 1.2.0 : firmware 0.3.0). Pet lu depuis une microSD FAT32 partagée avec l'écran C6 (un buffer de 19 968 octets).
- Plugin `openbuddy.events` autonome (SDK 2.2.5 embarqué, sans Node/npm), réservé au service OpenCode local géré. Éviter de charger en même temps les copies globale et projet (`Duplicate plugin ID`).
- Pont Python 3.11+, sons et toasts Windows indépendants du BLE. Utiliser le runtime WinRT 4.1.0 ; ne pas installer Windows-Toasts 1.3.1 (impose un runtime 3.x incompatible).
- BOOT : appui court = rotation 180° (`landscape`/`landscape_inv`, mémorisée dans `openbuddy-orientation.txt`), appui long 3 s = fenêtre d'appairage BLE, appui court pendant une comparaison de code = confirmation. Plus d'événement `button` ni de F13 sur appui court.
- S3 v2 : rotation automatique entre les deux sens paysage par gravité, sans portrait ; à plat/verticale/en mouvement, garder la vue précédente. BOOT court corrige le capteur de 180° jusqu'au redémarrage ; orientation manuelle mémorisée seulement pour démarrage/secours. Après panne IMU, BOOT/USB/BLE restent utilisables et l'IMU est retentée après 30 s. Le build et `BUILD.json` contrôlent le budget flash (Python + deux packs v2 + réserve), l'installateur conserve le contrôle réel `statvfs`.
- Pet : 9 animations (73 images). `thinking` = `look` (lignes de regards 9-10 de l'atlas v2), `retry` = `running-left` puis `running-right`, `question` = `waving`, appairage = `waiting`. Le pack se régénère avec `pc.pet`, puis `pc.pet install --replace`.
- Montage SD : 3 essais au démarrage, puis rechargement du pet toutes les 3 s (30 s après 20 essais) si la carte n'était pas prête.
- Non validé sur matériel : nouveau pack d'animations, affichage du quota, rotation BOOT, rechargement du pet après démarrage à froid, touche HID F13 réelle.
- Sous Windows, normaliser avec `.resolve()` avant de comparer des chemins (formes courtes/longues).

## Règles matérielles critiques (C6-LCD-1.47)

- Rétroéclairage GPIO22 : PWM ≤ 50 %, jamais en sortie simple (risque d'ombres permanentes).
- Écran ST7789 : offset 34 px sur l'axe court, `INVON` obligatoire, RGB565 envoyé octet de poids fort d'abord, effacer toute la RAM (240×320) à chaque changement d'orientation.
- Orientations valides : `portrait`, `landscape`, `portrait_inv`, `landscape_inv` (voir `board_config.py`). L'interface n'est dessinée que pour les deux orientations paysage.
- LED RVB WS2812 GPIO8 : ordre GRB, garder les valeurs < 40.
- Un seul `machine.SPI` pour écran/SD. Ne jamais utiliser `machine.SDCard` natif en parallèle du LCD ; le natif est réservé à l'installateur USB, programme interrompu. Ne pas toucher aux clés `openbuddy-bonds.json`.

## Vérifications

Après toute modification de `device/`, installer `pc/requirements-dev.txt` dans
`.venv` puis exécuter **obligatoirement** le contrôle MicroPython 1.29 avant de
conclure que le firmware passe les tests. Les mocks CPython seuls ne suffisent pas.

```text
uv pip install --python .venv\Scripts\python.exe -r pc\requirements-dev.txt
uv run python -m tools.check_micropython
uv run python -m unittest discover -s tests -v
npm --prefix integration/openbuddy test
npm --prefix integration/openbuddy run typecheck
```

La CI compile les fichiers de `pc.deploy` avec `mpy-cross` 1.29 et exécute un
smoke test du protocole et de l'USB sur le port Unix MicroPython 1.29.
Ces tests ne compilent pas le module C. La compilation Linux et
les tests C sur hote sont decrits dans le [guide QSPI](docs/s3-qspi-build.md#compilation-linux-sans-docker).
Un build reussi et des tests simules ne valident ni le transport electrique,
ni les couleurs, ni la rotation, ni les redemarrages sur la carte reelle.
`tools/test_amoled.py` est un diagnostic materiel manuel, pas un test CI :
il affiche les cinq couleurs plein ecran sans BLE ni SD, puis exige un reset.

## Prochaines étapes

1. Valider sur matériel la rotation BOOT et le rechargement du pet.
2. Valider le rendu visuel du pet et ajuster les animations si nécessaire.
3. Étendre l'intégration **OpenCode v2** si nécessaire ; vérifier la doc v2 et le contrat API avant toute modification.
4. Valider sur carte les réponses aux questions et permissions (notamment « Toujours autoriser ») avant de les considérer fiables.
