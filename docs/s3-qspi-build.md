# Firmware S3 AMOLED v2 QSPI experimental

## Pourquoi un nouveau firmware

Le SPI simple du premier portage a laisse l'ecran noir lors du test utilisateur.
Les anciennes demos Waveshare nomment le pilote SH8601 et les nouvelles CO5300 ;
elles utilisent la meme initialisation et surtout le **QSPI pour les pixels**.
Le nom du controleur seul ne permet donc pas d'attribuer la panne.

Le module C `amoled_qspi` reproduit le transport constructeur : registres avec
opcode `0x02`, pixels avec opcode `0x32`, en-tete sur une ligne, pixels sur quatre.
Il est compile dans MicroPython : un simple `pc.deploy` sur le `.bin` officiel
ne suffit plus. Le C6 n'est pas concerne et conserve son firmware officiel.

Le depot constructeur **v2** utilise **CS=GPIO46**. Selectionner
`waveshare-s3-amoled-164-v2` : le nom du pilote SH8601/CO5300 ne permet pas
de choisir le brochage.

Configuration : MicroPython **v1.29.0**, ESP-IDF **v5.5.2**, carte dediee
`OPENBUDDY_S3_AMOLED_V2`, derivee de `ESP32_GENERIC_S3` / `SPIRAM_OCT`, flash
**16 Mio**, PSRAM octale **8 Mio**. SPI2 appartient exclusivement au
module natif (GPIO CS=46 sur v2, CLK=10, D0..D3=11..14). Ne pas creer `machine.SPI(1)`
en parallele. La SD conserve son bus separe. Les transferts sont synchrones,
avec un tampon DMA interne de 4092 octets. L'affichage utilise deux buffers
persistants de 255360 octets en memoire accessible au heap MicroPython.
Le partitionnement MicroPython standard est conserve : application avant
`0x200000`, puis VFS dynamique jusqu'a la fin de la flash, soit **14 Mio** sur
une carte 16 Mio. Les animations resident dans ce VFS persistant, pas dans la PSRAM.

Le build v2 impose l'USB **Serial/JTAG materiel** (`303a:1001`), sans bascule du PHY
vers USB OTG/TinyUSB CDC. Le REPL et le protocole JSON utilisent ce meme port ; les
messages de demarrage/panic ESP-IDF sont aussi actives sur cette console secondaire.
L'ancien build heritait du CDC TinyUSB de `ESP32_GENERIC_S3` (`303a:4001`), ce qui
remplacait le peripherique USB apres flashage et rendait son fonctionnement lie au
traitement logiciel de TinyUSB. Ce changement est une piste pour un port qui
disparait au redemarrage, pas une preuve d'absence de panne de boot ou de PSRAM.
Un firmware Serial/JTAG exige une **recompilation et un reflashage du `.bin`** :
`pc.deploy` seul n'y change rien. Le packaging controle les symboles USB reellement
compiles dans `micropython.map`, refuse TinyUSB/OTG et publie le backend/VID/PID
dans `BUILD.json`. Le retablissement reel du port reste a valider sur la carte.

Le packaging contrôle la table de partitions réellement compilée, la taille de
`micropython.bin` dans sa partition et l'absence de débordement du `.bin` combiné
sur le VFS. Il refuse aussi un budget VFS insuffisant pour les fichiers Python,
**deux packs v2 de 73 images** (pour permettre un remplacement), les allocations,
les métadonnées et une réserve de 256 Kio. Ce contrôle ne remplace pas `statvfs`
à l'installation sur une carte déjà occupée. Le détail est dans `BUILD.json`.

**Experimental : une compilation et des tests simules ne valident pas l'ecran
reel, les couleurs, la rotation ou les redemarrages.** Le QMI8658 choisit entre les
deux sens paysage sur le profil v2 ; son axe Y et son signe ont été mesurés sur une
carte, mais la rotation corrigée reste à vérifier visuellement après déploiement.
Le tactile FT3168 est utilisé par l'application Python pour les demandes OpenCode ;
il ne fait pas partie du module natif QSPI. Aucune animation proprietaire n'est
distribuee avec le firmware.

## GitHub Actions

Le workflow **Build S3 AMOLED v2 QSPI firmware** compile sur les pushes vers `master`
ou `feat/esp32-s3-amoled-164`, ainsi que sur la branche `orientation`, et les pull
requests modifiant les sources concernees.
Il peut aussi etre lance manuellement
une fois disponible sur la branche par defaut. Il produit un artefact
`openbuddy-s3-amoled-qspi` conserve 30 jours :

- `openbuddy-s3-amoled-qspi.bin` : MicroPython avec le module natif **API v4**, sans
  application Python. L'identite par defaut v2 est figee dans `openbuddy_build`.
- `openbuddy-s3-qspi-files.zip` : fichiers Python correspondants, diagnostic et licences.
- `BUILD.json` : commits, etat sale/propre, empreintes, profil v2, CS=46,
  flash 16 Mio, `pet_storage: "internal"`, `orientation_sensor: "qmi8658"` et
  `flash_budget` (application, VFS, fichiers Python, packs et marges).
- `BUILD.json` contient aussi `usb_backend: "usb-serial-jtag"`, `usb_vid: 12346`
  et `usb_pid: 4097` (les identifiants `303a:1001` en decimal).
- `SHA256SUMS.txt` : empreintes des fichiers livres.
- `INSTALL.md` : le README Windows S3, également inclus dans le ZIP des sources.

Un tag pousse **`s3-qspi-*`** publie automatiquement une **prerelease**, uniquement
apres la compilation reussie. Le workflow n'ecrase pas une release existante.
Un push de branche ne publie pas de release. Un commit local ne lance aucune CI.
Les pull requests n'ont pas de droit d'ecriture dans les releases.
Le résumé GitHub Actions affiche aussi le budget flash vérifié, sans télécharger
ni redistribuer de sprites du pet.

## Installation Windows uv

Suivre uniquement le **[README Windows ESP32-S3 AMOLED v2](../README-ESP32-S3-Windows.md)**.
Il centralise le téléchargement de l’artefact, le contrôle du commit et du hash,
le flashage, le test écran avec reset, les animations internes et le lancement USB.
Le dépôt complet du même commit est nécessaire pour le pont et le plugin.

Le VFS commence à `0x200000`. Le `.bin` combiné réécrit la table de partitions ;
MicroPython recrée l’entrée VFS au démarrage. La conservation des données depuis
MicroPython v1.29.0 SPIRAM_OCT ne remplace pas une sauvegarde et ne s’applique pas
à un firmware ayant un autre partitionnement. Ne pas effacer la flash par réflexe.

## Performance du rendu et timeouts USB

Mesures sur carte S3 v2 avec l’ancien build QSPI API v2, sans pont sur le port série :
pour un rectangle de **172 × 320 pixels** (110 080 octets), la copie des lignes
dans `co5300.py::_flush` prend environ **3 943 ms**, contre **8 ms** pour la
commande QSPI native qui envoie les mêmes pixels. `co5300.py::blit` prend environ
**1 750 ms** pour un sprite de 96 × 104 pixels ; un premier dessin de l’interface
sans pet a pris environ **37 s**. Ces durées sont des observations, pas des
objectifs de performance.

La démo constructeur `Arduino/examples/06_LVGL_Test/lcd_bsp.c` utilise des
buffers DMA et dessine avec LVGL en C. OpenBuddy transmet aussi les pixels en
QSPI natif, mais **transpose chaque pixel et compacte chaque ligne en boucles
MicroPython**, puis ne traite l’USB que lorsque `BuddyUI.draw()` rend la main.
Le panneau ne prend pas en charge `swap_xy` selon le pilote constructeur :
basculer simplement un registre de rotation n’est pas un correctif établi.
Augmenter le timeout du pont ne rendrait pas les animations ou les états réactifs.

Le correctif **API v3** a déplacé dans `amoled_qspi` la rotation RGB565, le
remplissage des rectangles et l’extraction des lignes depuis le buffer physique.
Le transport QSPI et son tampon DMA de 4 092 octets ne changent pas. Les mises
à jour conservent l’alignement pair, les voisins via le buffer d’ombre, le gap
de 20 colonnes et les deux sens paysage ; un effacement plein écran envoie
directement le buffer contigu. L'**API v4** transmet aussi la taille du canevas
et le facteur d'agrandissement (×2) au code natif : le profil S3 utilise les
456×280 pixels de la dalle, sans reconvertir le pet 96×104. Le C6 conserve son
interface 320×172. `co5300.py` refuse l’API v2/v3, et le précontrôle
de `pc.deploy` bloque un déploiement Python incompatible avant toute copie.
**Cela nécessite un nouveau `.bin` API v4** et les fichiers Python du même commit.
Les tests simulés ne suffisent pas : mesurer sur carte le temps par image, la
latence USB, les couleurs et les deux orientations après compilation GitHub
Actions. Ne pas déduire un gain matériel avant cet essai.

## Compilation Linux sans Docker

Installer les prerequis Linux documentes par ESP-IDF (compilateur C hote, make,
CMake, Ninja, Git, Python avec venv, libusb). Dans un dossier de travail :

```bash
git clone --branch v5.5.2 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git
git clone --branch v1.29.0 --depth 1 https://github.com/micropython/micropython.git
cd esp-idf
./install.sh esp32s3
. ./export.sh
cd /path/to/openbuddy
bash tools/build_s3_qspi.sh /path/to/micropython
```

Le script controle les commits MicroPython et ESP-IDF attendus, compile puis
produit `dist/s3-qspi/`. La definition de carte et le manifeste frozen sont dans
`firmware/boards/OPENBUDDY_S3_AMOLED_V2/` ; le dossier de compilation est
`ports/esp32/build-OPENBUDDY_S3_AMOLED_V2`. Aucune connexion USB n'est necessaire pour compiler.
La compilation C utilise l'environnement ESP-IDF, pas l'environnement uv du PC.

Tests du module C sur ordinateur (pas une validation electrique) :

```bash
make -f tests/native_qspi/Makefile MICROPYTHON=/path/to/micropython
```
