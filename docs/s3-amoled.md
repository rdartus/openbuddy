# Waveshare S3 AMOLED 1.64 et v2

## Materiel et limites

Carte : **Waveshare ESP32-S3-Touch-AMOLED-1.64 v2**, ESP32-S3R8, flash 16 Mo,
PSRAM octale 8 Mo, AMOLED 280x456. Verifier cette reference sur la carte
ou sa fiche produit avant de flasher : le type de puce seul ne permet pas de
deviner le brochage. Le profil est choisi explicitement au deploiement et conserve
dans `openbuddy-board.txt`. Un deploiement sans `--board` conserve ce choix ; sans
marqueur, le build dedie utilise le profil **`waveshare-s3-amoled-164-v2`**.
Un ancien marqueur n'est jamais remplace automatiquement : choisir explicitement
`--board waveshare-s3-amoled-164-v2` lors de la migration.

| Fonction | GPIO |
|---|---|
| AMOLED CLK / D0 / CS / RST, **v2** | 10 / 11 / **46** / 21 |
| AMOLED D1 / D2 / D3 (pixels QSPI) | 12 / 13 / 14 |
| BOOT actif bas | 0 |
| SD CLK / MOSI / MISO / CS, bus separe | 41 / 39 / 40 / 38 |

**Ne pas confondre les revisions** : l'ancien profil `waveshare-s3-amoled-164`
conserve CS=GPIO9 et son comportement SD optionnel. Le profil **v2 utilise GPIO46**,
40 MHz comme le constructeur, et le pet exclusivement en flash interne.
Le choix du CS est transmis au module natif (`Bus(cs=...)`, API v2), y compris
pour liberer correctement la broche apres une erreur ou un reset logiciel.

Les anciennes demos Waveshare nomment le pilote **SH8601**, les nouvelles
**CO5300** ; elles partagent l'initialisation et le transport QSPI des pixels.
Ce changement de nom ne constitue pas une detection confirmee du silicium.
Le nom Python `co5300` est conserve pour les profils existants.

Le pilote exige le module C **`amoled_qspi` compile dans MicroPython** : registres
avec opcode `0x02`, pixels RGB565 BE avec opcode `0x32`, en-tete sur une ligne
et pixels sur quatre. Le `.bin` MicroPython officiel ne suffit pas, et `pc.deploy`
ne peut pas y ajouter ce module natif. SPI2_HOST est reserve au module : ne pas creer
`machine.SPI(1)` en parallele ; la SD garde son bus separe. Deux buffers persistants
de 255 360 octets servent a la rotation et aux transferts alignes, avec conservation
des pixels voisins. Voir le [guide firmware QSPI](s3-qspi-build.md) pour la
configuration de compilation et les limites du transport.

L'interface paysage existante **320x172 est centree sans etirement** dans le panneau
utilise en paysage 456x280. Des marges noires restent donc visibles. BOOT court
retourne l'affichage a 180 degres ; BOOT long conserve l'appairage BLE. Le tactile
FT3168 et l'IMU QMI8658 ne sont pas utilises. Aucune LED WS2812 n'est supposee,
aucun GPIO de retroeclairage C6 n'est active sur l'AMOLED.

**Portage experimental, pas encore valide sur le materiel reel.** Une compilation
et des tests simules ne valident ni l'ecran, ni les couleurs, ni la rotation,
ni les redemarrages. Aucun appareil n'est flashe par les tests.

## Stockage sans microSD

Le programme Python est deja en flash interne dans le projet d'origine ; seuls
les assets d'animation exigeaient la SD. Le pack actuel contient 73 images,
soit **1 457 664 octets** de pixels, plus le manifeste et les metadonnees.
La PSRAM est volatile : elle n'est pas le stockage persistant des animations.

`--storage auto` consulte le profil et l'espace **effectivement disponible** via
`os.statvfs`, pas simplement les 16 Mo annonces. **Sur la v2, il impose la flash
interne et echoue si elle est insuffisante ; aucun repli sur la TF et
`--storage sd` est refuse.** Sur l'ancien profil S3, il privilegie l'interne puis
la SD si necessaire. Sur le C6, il conserve la SD.
`--storage internal` interdit ce repli et renvoie une erreur si la flash ne suffit
pas. Les deux modes gardent 256 Kio de reserve avec marge d'allocation et de
metadonnees ; un remplacement exige conservativement la place d'un pack complet
supplementaire. Aucun formatage automatique ni nettoyage d'autres donnees.

Sur la v2, le lecteur cherche uniquement dans `/openbuddy`, puis utilise le robot
integre si le pack manque ou est invalide. Meme les nouvelles tentatives de
chargement ne creent aucun bus SD et ne montent aucune carte TF.
Sur l'ancien profil, il cherche aussi dans `/sd/openbuddy`. Un pack interne valide
n'initialise pas le bus SD. Pour basculer volontairement vers la SD sur cet ancien profil,
retirer ou renommer uniquement `/openbuddy/active.json` dans le REPL, programme
interrompu. `status` expose `assets: "internal"` ou `"sd"`, ainsi que `pet` et `sd`.

Les transferts verifies SHA-256 activent la selection en dernier. Une interruption
d'un remplacement du meme pack peut laisser ce pack incomplet : le lecteur revient
alors au robot (ou a la SD sur l'ancien profil uniquement). Reprendre avec
`--replace`. Les cles BLE sont conservees.

## Installation Windows PowerShell

Prerequis : Windows 10/11, [uv](https://docs.astral.sh/uv/getting-started/installation/)
et un cable USB-C **de donnees**. Les commandes utilisent `uv run python`, sans
activation PowerShell ni installation globale de Python.

**Suivre le [README Windows ESP32-S3 AMOLED v2](../README-ESP32-S3-Windows.md)**,
même si MicroPython officiel est déjà flashé. Ce parcours unique va du
téléchargement du firmware au lancement du pont, avec test écran avant le pet.
Tout changement du module natif exige de reflasher le build correspondant ;
une mise à jour des seuls fichiers Python utilise `pc.deploy`, sans effacement.

## OpenCode

Le [README Windows S3](../README-ESP32-S3-Windows.md#6-installer-le-plugin-et-lancer-openbuddy)
centralise l'installation du plugin et le lancement du pont USB depuis le depot
complet. Le pont fonctionne sans appairage ni microSD et doit rester actif.
Un seul programme peut ouvrir le port : arreter le pont avant tout diagnostic,
deploiement, transfert ou REPL. Voir aussi les
[evenements OpenCode](opencode-events.md) pour les contraintes de version.

## Diagnostic

Ecran noir : verifier d'abord le firmware natif et effectuer le
[test plein ecran du guide QSPI](s3-qspi-build.md#installation-windows-uv).
Verifier aussi la reference exacte et le profil, puis lire l'erreur :

```powershell
uv run python -m mpremote connect $Port fs cat :openbuddy-error.txt
uv run python -m mpremote connect $Port exec "import board_config as c; print(c.BOARD_MODEL, c.DISPLAY_DRIVER)"
uv run python -m mpremote connect $Port reset
```

Les acces REPL interrompent le programme : terminer par `reset`. L'absence de fichier
d'erreur n'est pas anormale. Un probleme d'initialisation ecran peut survenir avant
la creation de ce journal ; utiliser alors `mpremote repl`, Ctrl+D pour observer
le demarrage. Il reste a verifier sur carte : couleurs, sens de rotation, debit,
USB/BLE et redemarrage a froid sans SD.

Sources constructeur :
le [depot v2 Waveshare](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.64-v2),
commit de reference `21b952243d306692774f3b5bfeb3eb5cff10f851` :
`ESP-IDF/06_LVGL_Test/main/main.c` et
`Arduino/examples/06_LVGL_Test/lcd_config.h` confirment CS=46, CLK=10, D0..D3=11..14,
RST=21, le decalage de 20 colonnes et les fenetres alignees sur 2 pixels.
La sequence d'initialisation existante correspond a celle du constructeur.
Le schema `schematic/ESP32-S3-Touch-AMOLED-1.64-Rev1.1.pdf` confirme egalement
GPIO46 pour LCD_CS ; GPIO9 est relie a l'interruption de l'IMU, pas au CS de l'ecran.

Autres references :
<https://www.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64>,
[datasheet CO5300, pages 20-24](https://files.waveshare.com/wiki/common/Co5300_Datasheet.pdf),
[demos Waveshare](https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64/ESP32-S3-Touch-AMOLED-1.64-Demo.zip)
(`ESP-IDF/06_LVGL_V9_Test/components/port_bsp/display_bsp.cpp`).
