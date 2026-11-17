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
| QMI8658 I²C SDA / SCL (partagé avec le tactile) | 47 / 48 |
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

L'interface reste exclusivement en **paysage 320x172**, centrée sans étirement
dans le panneau : des marges noires restent visibles. Le pet, le quota et les
instructions d'appairage conservent leur disposition actuelle. Le tactile FT3168
n'est pas utilisé. Aucune LED WS2812 n'est supposée, aucun GPIO de rétroéclairage
C6 n'est activé sur l'AMOLED.

### Orientation automatique (v2 uniquement)

Le QMI8658 (`WHO_AM_I = 0x05`, adresse `0x6B`) utilise I²C0 à 300 kHz, SDA=47,
SCL=48 comme la démo constructeur. Seul l'accéléromètre est activé : ±2 g,
62,5 Hz, lecture à 10 Hz, sans gyroscope, interruption ni accès au tactile.
L'écran choisit entre **les deux sens paysage à 180°**, après **500 ms de position
stable**. Il ne passe jamais en portrait. En position verticale, à plat, en
diagonale, en chute libre ou en forte accélération, il garde sa position
précédente. Les accès I²C ont un délai borné ; les erreurs n'arrêtent ni USB ni BLE.
Après trois erreurs consécutives, le capteur est libéré puis retenté après 30 s.

Les rotations automatiques **n'écrivent rien en flash**. BOOT court conserve la
rotation manuelle de 180° et ajoute une correction de 180° aux décisions du capteur
jusqu'au prochain redémarrage, sans être immédiatement annulé par l'automatisme.
Le choix manuel reste mémorisé comme orientation de démarrage/de secours, mais la
correction du capteur est volatile. BOOT long et la confirmation d'appairage sont
inchangés. Sans IMU, la rotation manuelle reste disponible. C6 et ancien S3 ne
créent aucun bus I²C et conservent les deux vues paysage manuelles.

`status` expose aussi `orientation` et `imu` (capteur lisible). Tester les deux
positions paysage sur la carte réelle, puis le passage à plat et le redémarrage : les
tests simulés ne prouvent pas le sens du montage physique du capteur. La
correspondance est centralisée dans `IMU_LANDSCAPE_AXIS` et `IMU_LANDSCAPE_SIGN` de
`board_config.py` (hypothèse initiale : axe X le long du petit côté de la dalle).
En cas d'inversion du montage sur une révision, ajuster ces deux constantes ; ne
pas modifier les broches QSPI ni le pilote d'écran pour compenser.

**Portage experimental, pas encore valide sur le materiel reel.** Une compilation
et des tests simules ne valident ni l'ecran, ni les couleurs, ni la rotation,
ni les redemarrages. Aucun appareil n'est flashe par les tests.

## Stockage sans microSD

Le programme Python est deja en flash interne dans le projet d'origine ; seuls
les assets d'animation exigeaient la SD. Le pack actuel contient 73 images,
soit **1 457 664 octets** de pixels, plus le manifeste et les metadonnees.
La PSRAM est volatile : elle n'est pas le stockage persistant des animations.

La flash de **16 Mio** laisse **14 Mio (14 680 064 octets)** au VFS après
`0x200000` ; le firmware natif dispose séparément de 1 984 Kio pour l'application.
Le pack de pixels occupe environ **1,39 Mio**, ou **1,50 Mio budgétés** avec le
manifeste maximal, les allocations et les métadonnées. Le build vérifie que les
fichiers Python, deux packs complets et 256 Kio de réserve tiennent ensemble ;
il publie les tailles exactes dans `BUILD.json` et le résumé de l'Action. Il reste
plus de 10 Mio de marge sur un VFS neuf avec le budget actuel. Les sources WebP et
la prévisualisation restent sur le PC, pas sur l'ESP32. Aucun pack n'est inclus
dans le `.bin` ou les artefacts publics.

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

Les acces REPL interrompent le programme : terminer par `reset`. Le journal
`openbuddy-error.txt` indique la phase (`Stage: imports`, `display`, `assets`,
`BLE`, `UI` ou `main loop`, notamment) et conserve l'exception Python initiale.
Les erreurs d'initialisation de l'ecran sont aussi journalisees, dans la mesure ou
la flash reste accessible. Le gestionnaire d'erreur ne tente plus de dessiner sur
un bus potentiellement en panne. L'ecran est explicitement ferme a la sortie,
y compris sur Ctrl+C ; une erreur de nettoyage n'empeche pas les autres fermetures.

Une panne d'initialisation BLE laisse le transport USB et la rotation BOOT actifs,
sans modifier les cles d'appairage. Le BLE n'est retente qu'au prochain demarrage.
Une panne fatale du compagnon rend la main au REPL apres nettoyage, sans boucle
automatique de redemarrage. Aucun journal n'est ecrit pour un simple Ctrl+C.

L'absence de journal ne prouve pas l'absence de panne : un blocage natif QSPI,
un reset materiel ou une flash inaccessible ne produisent pas necessairement
d'exception Python. Les traces serie `OpenBuddy startup: ...` aident alors a
identifier la derniere phase atteinte. Les attentes QSPI natives restent non
bornees : les timeouts des outils PC ne debloquent pas un transfert DMA sur la
carte. Voir le [depannage Windows](../README-ESP32-S3-Windows.md#si-ça-bloque)
pour les delais des outils et le reset manuel.

Il reste a verifier sur carte : couleurs, sens de rotation, debit, USB/BLE et
redemarrage a froid sans SD.

Sources constructeur :
le [depot v2 Waveshare](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.64-v2),
commit de reference `21b952243d306692774f3b5bfeb3eb5cff10f851` :
`ESP-IDF/06_LVGL_Test/main/main.c` et
`Arduino/examples/06_LVGL_Test/lcd_config.h` confirment CS=46, CLK=10, D0..D3=11..14,
RST=21, le decalage de 20 colonnes et les fenetres alignees sur 2 pixels.
La sequence d'initialisation existante correspond a celle du constructeur.
`ESP-IDF/02_I2C_QMI8658/components/i2c_bsp/i2c_bsp.c` et
`components/qmi8658c/qmi8658c.{c,h}` de cet exemple confirment les broches I²C,
la fréquence, l'adresse, l'identité et les registres de l'accéléromètre.
Le schema `schematic/ESP32-S3-Touch-AMOLED-1.64-Rev1.1.pdf` confirme egalement
GPIO46 pour LCD_CS ; GPIO9 est relie a l'interruption de l'IMU, pas au CS de l'ecran.

Autres references :
<https://www.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64>,
[datasheet CO5300, pages 20-24](https://files.waveshare.com/wiki/common/Co5300_Datasheet.pdf),
[demos Waveshare](https://files.waveshare.com/wiki/ESP32-S3-Touch-AMOLED-1.64/ESP32-S3-Touch-AMOLED-1.64-Demo.zip)
(`ESP-IDF/06_LVGL_V9_Test/components/port_bsp/display_bsp.cpp`).
