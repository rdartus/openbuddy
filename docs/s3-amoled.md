# Waveshare S3 AMOLED 1.64

## Materiel et limites

Profil : **Waveshare ESP32-S3-Touch-AMOLED-1.64**, ESP32-S3R8, flash 16 Mo,
PSRAM octale 8 Mo, AMOLED 280x456. Verifier cette reference sur la carte
ou sa fiche produit avant de flasher : le type de puce seul ne permet pas de
deviner le brochage. Le profil est choisi explicitement au deploiement et conserve
dans `openbuddy-board.txt`. Un deploiement sans `--board` conserve ce choix.

| Fonction | GPIO |
|---|---|
| AMOLED CLK / D0 / CS / RST | 10 / 11 / 9 / 21 |
| AMOLED D1 / D2 / D3 (pixels QSPI) | 12 / 13 / 14 |
| BOOT actif bas | 0 |
| SD CLK / MOSI / MISO / CS, bus separe | 41 / 39 / 40 / 38 |

Les anciennes demos Waveshare nomment le pilote **SH8601**, les nouvelles
**CO5300** ; elles partagent l'initialisation et le transport QSPI des pixels.
Ce changement de nom ne constitue pas une detection confirmee du silicium.
Le nom Python `co5300` est conserve pour les profils existants.

Le pilote exige le module C **`amoled_qspi` compile dans MicroPython** : registres
avec opcode `0x02`, pixels RGB565 BE avec opcode `0x32`, en-tete sur une ligne
et pixels sur quatre. Le `.bin` MicroPython officiel ne suffit pas, et `pc.deploy`
ne peut pas y ajouter ce module natif. SPI2 est reserve au module : ne pas creer
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
`os.statvfs`, pas simplement les 16 Mo annonces. Sur le S3 AMOLED, il privilegie
l'interne ; si insuffisant, il tente la SD. Sur le C6, il conserve la SD.
`--storage internal` interdit ce repli et renvoie une erreur si la flash ne suffit
pas. Les deux modes gardent 256 Kio de reserve avec marge d'allocation et de
metadonnees ; un remplacement exige conservativement la place d'un pack complet
supplementaire. Aucun formatage automatique ni nettoyage d'autres donnees.

Le lecteur cherche un pack valide dans `/openbuddy`, puis `/sd/openbuddy`, puis
utilise le robot integre. Un pack interne valide n'initialise pas le bus SD sur
le S3. Pour basculer volontairement vers la SD alors qu'un pack interne existe,
retirer ou renommer uniquement `/openbuddy/active.json` dans le REPL, programme
interrompu. `status` expose `assets: "internal"` ou `"sd"`, ainsi que `pet` et `sd`.

Les transferts verifies SHA-256 activent la selection en dernier. Une interruption
d'un remplacement du meme pack peut laisser ce pack incomplet : le lecteur revient
alors au robot ou a la SD. Reprendre avec `--replace`. Les cles BLE sont conservees.

## Installation Windows PowerShell

Prerequis : Windows 10/11, [uv](https://docs.astral.sh/uv/getting-started/installation/)
et un cable USB-C **de donnees**. Les commandes utilisent `uv run python`, sans
activation PowerShell ni installation globale de Python.

**Commencer par le [guide firmware S3 QSPI](s3-qspi-build.md#installation-windows-uv),
meme si MicroPython officiel est deja flashe.** Il centralise le telechargement
de l'artefact, la verification SHA-256, la sauvegarde et le reflashage, ainsi que
les fichiers Python du meme build. Ne pas telecharger de `.bin` officiel pour ce S3
et ne pas melanger les anciens fichiers SPI avec le firmware QSPI.

Suivre ensuite, dans ce guide, l'ordre obligatoire : verification de
`import amoled_qspi`, `pc.deploy --board waveshare-s3-amoled-164` avec son preflight
natif, execution de `tools/test_amoled.py`, puis `reset` meme si le test echoue.
Verifier rouge, vert, bleu, noir et blanc sur toute la dalle avant les animations.
En cas d'echec, conserver la sortie du terminal et ne pas poursuivre l'installation
des animations ni multiplier les effacements.

Pour les animations internes et l'integration OpenCode, poursuivre avec
[Windows apres flashage](windows-uv-apres-flash.md). Pour une mise a jour des seuls
fichiers Python sur un firmware natif compatible, relancer `pc.deploy` sans
effacement ; tout changement du module natif exige le reflashage du build
correspondant selon le guide QSPI. Le C6 conserve son firmware officiel.

## OpenCode

Le [guide Windows apres flashage](windows-uv-apres-flash.md#4-installer-le-plugin-opencode)
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
<https://www.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64>,
[datasheet CO5300, pages 20-24](https://files.waveshare.com/wiki/common/Co5300_Datasheet.pdf),
[demos Waveshare](https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64/ESP32-S3-Touch-AMOLED-1.64-Demo.zip)
(`ESP-IDF/06_LVGL_V9_Test/components/port_bsp/display_bsp.cpp`).
