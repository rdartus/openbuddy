# Waveshare S3 AMOLED 1.64 et v2

## Materiel et limites

Carte : **Waveshare ESP32-S3-Touch-AMOLED-1.64 v2**, ESP32-S3R8, flash 16 Mo,
PSRAM octale 8 Mo, AMOLED 280x456. Verifier cette reference sur la carte
ou sa fiche produit avant de flasher : le type de puce seul ne permet pas de
deviner le brochage. Le profil est choisi explicitement au deploiement et conserve
dans `openbuddy-board.txt`. Un deploiement sans `--board` conserve ce choix ; sans
marqueur, le build dedie utilise le profil **`waveshare-s3-amoled-164-v2`**.
Un marqueur sauvegardé est prioritaire : sélectionner explicitement
`--board waveshare-s3-amoled-164-v2` si le profil enregistré est incorrect.

| Fonction | GPIO |
|---|---|
| AMOLED CLK / D0 / CS / RST, **v2** | 10 / 11 / **46** / 21 |
| AMOLED D1 / D2 / D3 (pixels QSPI) | 12 / 13 / 14 |
| BOOT actif bas | 0 |
| QMI8658 I²C SDA / SCL (partagé avec le tactile) | 47 / 48 |
| SD CLK / MOSI / MISO / CS, bus separe | 41 / 39 / 40 / 38 |

Le profil v2 utilise **CS GPIO46**, 40 MHz comme le constructeur. Le pet est
en flash interne par défaut, ou sur la TF FAT32 après sélection explicite ; le
firmware natif et les fichiers Python restent en flash.
Le choix du CS est transmis au module natif (`Bus(cs=...)`, API v4), y compris
pour liberer correctement la broche apres une erreur ou un reset logiciel.

Les anciennes demos Waveshare nomment le pilote **SH8601**, les nouvelles
**CO5300** ; elles partagent l'initialisation et le transport QSPI des pixels.
Ce changement de nom ne constitue pas une detection confirmee du silicium.
Le nom Python `co5300` est conserve.

Le pilote exige le module C **`amoled_qspi` compile dans MicroPython** : registres
avec opcode `0x02`, pixels RGB565 BE avec opcode `0x32`, en-tete sur une ligne
et pixels sur quatre. Le `.bin` MicroPython officiel ne suffit pas, et `pc.deploy`
ne peut pas y ajouter ce module natif. SPI2_HOST est reserve au module : ne pas creer
`machine.SPI(1)` en parallele ; la SD garde son bus separe. Deux buffers persistants
de 255 360 octets servent a la rotation et aux transferts alignes, avec conservation
des pixels voisins. Voir le [guide firmware QSPI](s3-qspi-build.md) pour la
configuration de compilation et les limites du transport.

L'interface reste exclusivement en **paysage 456x280**, sur toute la dalle.
La geometrie est definie par profil dans `board_config.py` : le C6 garde son
interface 320x172, le S3 utilise tout son panneau et agrandit le pet x2 au plus
proche voisin, sans changer le pack 96x104. Le tactile FT3168 (I²C 0x38 sur
SDA47/SCL48) sert à choisir une réponse OpenCode par glissement horizontal et
à la valider par un appui stable d'au moins une seconde **dans le cadre du choix**.
Un toucher bref, un glissement ou un appui commencé moins de 1,2 seconde après
un glissement ne valident rien. L'interface affiche la demande et le choix à droite
du pet, avec défilement du texte qui ne tient pas dans la zone. Dès que la
demande et les choix sont reçus, un appui maintenu valide le choix affiché sans attendre
la fin du défilement, y compris pour « Toujours autoriser ».
Le firmware 0.6.3 utilise les glissements verticaux pour changer de demande
représentable dans le projet courant, les horizontaux pour changer de choix.
La demande et le choix affiché défilent horizontalement de droite à gauche
quand ils sont trop longs, sans effacement de la ligne entre deux positions ni
compteurs de pages. Une demande non affichable
reste à traiter dans OpenCode.
Sans tactile fonctionnel, répondre depuis OpenCode. Aucune LED WS2812 n'est supposée, aucun GPIO de rétroéclairage
C6 n'est activé sur l'AMOLED.

Le fond de l'interface est noir RGB `(0,0,0)` sur **C6 et S3** ; sur l'AMOLED,
cela éteint les pixels inoccupés, mais pas le rétroéclairage PWM du C6. Le pack
doit être converti sur **le même fond**, y compris les bords à alpha partiel ;
les anciens packs à fond `(8,12,20)` sont refusés sur les deux profils pour
éviter un rectangle sombre autour du pet. Suivre uniquement le [README Windows S3](../README-ESP32-S3-Windows.md)
pour la conversion et le remplacement du pack ; le `.bin` API v4 existant ne
doit pas être reflashé pour ce changement Python/assets.

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
inchangés. Sans IMU, la rotation manuelle reste disponible. Le C6 ne crée pas
de bus I²C et conserve les deux vues paysage manuelles.

`status` expose aussi `orientation` et `imu` (capteur lisible). Mesures sur une
carte v2 tenue debout, écran face à soi : **USB-C à gauche** donne Y ≈ +16 200,
X ≈ −1 250 ; **USB-C à droite** donne Y ≈ −16 100, X ≈ +1 200 (1 g = 16 384).
Le choix initial de X faisait donc réagir l'automatisme en portrait plutôt qu'en
paysage. `IMU_LANDSCAPE_AXIS = 1` et `IMU_LANDSCAPE_SIGN = -1` correspondent à ces
mesures. Les deux sens paysage doivent encore être validés visuellement après
déploiement, ainsi que la position à plat et le redémarrage. Sur une autre révision,
utiliser le diagnostic du [README Windows S3](../README-ESP32-S3-Windows.md)
avant de changer ces constantes dans `board_config.py` ; ne pas modifier les
broches QSPI ni le pilote d'écran pour compenser.

**Portage experimental.** L'axe de l'IMU a été mesuré sur une carte v2 ; cela
ne valide pas encore le rendu, la rotation automatique après correction ni les
redémarrages. Aucun appareil n'est flashé par les tests.

## Stockage : flash interne ou carte TF

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

Sur la v2, `--storage auto` suit la préférence mémorisée : **flash interne par
défaut**, TF après une installation explicite avec `--storage sd`. L'installateur
utilise `os.statvfs` sur la destination choisie (pas simplement les 16 Mo
annoncés) et conserve 256 Kio de réserve avec marge d'allocation et de
métadonnées. Une flash insuffisante n'entraîne aucun repli automatique sur la
TF : choisir `--storage sd` avec une carte FAT32 insérée. Un remplacement exige
conservativement la place d'un pack complet supplémentaire. Aucun formatage ni
nettoyage d'autres données. Même en mode TF, il faut 32 Kio disponibles en flash
pour enregistrer atomiquement la préférence ; ce point est vérifié avant le transfert.

Le choix vérifié est mémorisé dans `openbuddy-storage.txt` sur le S3 **après**
les SHA-256 et la sélection du pack actif. En mode flash, le lecteur ne crée
aucun bus TF, même si le pack manque. En mode TF, il monte `/sd` **en lecture
seule** sur le bus SPI séparé sans toucher au CS QSPI, lit uniquement
`/sd/openbuddy` et retente le montage si la carte manque ; il affiche alors le
robot plutôt qu'un ancien pack interne. Une réinstallation avec
`--storage internal` restaure le choix initial sans supprimer la TF.
`status` expose `assets: "internal"` ou `"sd"`, `sd` et `pet`.

Les transferts verifies SHA-256 activent la selection en dernier. Une interruption
d'un remplacement du meme pack peut laisser ce pack incomplet : le lecteur revient
alors au robot. Reprendre avec
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
complet. Le pont fonctionne sans appairage et sans microSD en mode flash interne ;
il doit rester actif.
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

Il reste a verifier sur carte : couleurs, sens de rotation, debit, USB/BLE,
lecture et rechargement du pet sur TF, et redemarrage a froid avec/sans TF.

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
