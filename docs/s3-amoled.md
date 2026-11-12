# Waveshare S3 AMOLED 1.64

## Materiel et limites

Profil : **Waveshare ESP32-S3-Touch-AMOLED-1.64**, ESP32-S3R8, flash 16 Mo,
PSRAM octale 8 Mo, AMOLED CO5300 280x456. Verifier cette reference sur la carte
ou sa fiche produit avant de flasher : le type de puce seul ne permet pas de
deviner le brochage. Le profil est choisi explicitement au deploiement et conserve
dans `openbuddy-board.txt`. Un deploiement sans `--board` conserve ce choix.

| Fonction | GPIO |
|---|---|
| AMOLED CLK / D0 / CS / RST | 10 / 11 / 9 / 21 |
| AMOLED D1 / D2 / D3 (inutilises par ce pilote) | 12 / 13 / 14 |
| BOOT actif bas | 0 |
| SD CLK / MOSI / MISO / CS, bus separe | 41 / 39 / 40 / 38 |

Le pilote utilise le **mode SPI simple documente du CO5300**, pas un faux QSPI
via `machine.SPI` : instruction `0x02`, adresse `00 CMD 00`, pixels RGB565 BE.
Cela permet d'utiliser MicroPython officiel sans compilation C. Horloge prudente
10 MHz, decalage de 20 colonnes, initialisation Waveshare, luminosite 128/255.
Les mises a jour sont alignees sur des coordonnees paires, avec conservation des
pixels voisins. Un buffer de 255 360 octets permet la rotation logicielle.

L'interface paysage existante **320x172 est centree sans etirement** dans le panneau
utilise en paysage 456x280. Des marges noires restent donc visibles. BOOT court
retourne l'affichage a 180 degres ; BOOT long conserve l'appairage BLE. Le tactile
FT3168 et l'IMU QMI8658 ne sont pas utilises. Aucune LED WS2812 n'est supposee,
aucun GPIO de retroeclairage C6 n'est active sur l'AMOLED.

**Portage couvert par tests simules, pas encore valide sur le materiel reel.**
Le debit SPI simple et la rotation Python ne visent pas les performances QSPI/LVGL
des demos constructeur. Aucun appareil n'est flashe par les tests.

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

Prerequis : Windows 10/11, **uv**, un cable USB-C **de donnees**.
uv installe Python 3.13 : une installation Python prealable n'est pas necessaire.
Ouvrir PowerShell dans la racine de la copie contenant ce portage (branche
`feat/esp32-s3-amoled-164`). Ces modifications doivent etre presentes sur le PC
Windows : un clone de la branche principale ne les contient pas necessairement.
Aucun besoin d'activer le venv ni de droits administrateur : on appelle directement
l'interpreteur de l'environnement gere par uv.

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/) si absent :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cette option concerne uniquement le processus d'installation, sans changer la
politique globale. Rouvrir PowerShell apres installation pour actualiser le PATH,
puis revenir dans la racine du depot :

```powershell
uv --version
uv python install 3.13
uv venv --python 3.13
uv pip install --python .venv\Scripts\python.exe -r pc\requirements-assets.txt -r pc\requirements.txt esptool
.\.venv\Scripts\python.exe -m serial.tools.list_ports -v
```

Si `.venv` existe deja avec un Python compatible (3.11-3.14 x64), sauter
`uv venv` et installer seulement les dependances. Les commandes Python ci-dessous
utilisent toutes ce meme environnement uv, y compris les sous-processus de
`pc.deploy` et `pc.pet` ; inutile d'installer mpremote ou esptool globalement.

Telecharger le **`.bin` ESP32_GENERIC_S3-SPIRAM_OCT 1.29.0** depuis
<https://micropython.org/download/ESP32_GENERIC_S3/> (section Octal-SPIRAM).
Le nom exact est `ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin`.
Telechargement direct dans la racine du depot :

```powershell
Invoke-WebRequest -Uri "https://micropython.org/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin" -OutFile "ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin"
$Port = "COM5" # Remplacer par le port detecte
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 --port $Port flash-id
```

**Premiere installation uniquement : l'effacement suivant detruit le programme
usine, les fichiers et les appairages deja presents.** Faire une sauvegarde si
necessaire. Pour entrer en bootloader : maintenir BOOT, appuyer puis relacher RST,
relacher BOOT. Le port peut changer entre bootloader et MicroPython.

```powershell
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 --port $Port erase-flash
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
```

Appuyer sur RST, verifier de nouveau le port et ajuster `$Port` si necessaire.
Controler la memoire disponible et le filesystem avant de deployer ; avec la
variante octale, le heap doit beneficier de la PSRAM :

```powershell
.\.venv\Scripts\python.exe -m serial.tools.list_ports -v
# Si le port a change, redefinir $Port avant de continuer.
.\.venv\Scripts\python.exe -m mpremote connect $Port exec "import os, gc; print(os.uname()); print('heap free:', gc.mem_free()); s=os.statvfs('/'); print('filesystem total/free:', s[0]*s[2], s[0]*s[4])"
.\.venv\Scripts\python.exe -m pc.deploy --port $Port --board waveshare-s3-amoled-164
```

Le robot doit apparaitre meme sans microSD. Installer ensuite le pet :

```powershell
.\.venv\Scripts\python.exe -m pc.pet convert
.\.venv\Scripts\python.exe -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal
.\.venv\Scripts\python.exe -m pc.buddy --serial $Port status
.\.venv\Scripts\python.exe -m pc.buddy --serial $Port demo
```

Pour laisser l'installateur choisir : remplacer `--storage internal` par
`--storage auto`. Pour une mise a jour, ajouter `--replace`. Pour les seuls fichiers
Python, relancer `pc.deploy` : **ne pas refaire erase-flash**.

En cas d'echec du flashage, essayer sans `--baud 460800`. Si aucun port ne s'affiche,
verifier le cable, le Gestionnaire de peripheriques Windows et le mode BOOT.
Fermer les moniteurs serie, Thonny et les autres programmes utilisant le port.
Les broches fournies n'ont pas besoin d'etre soudees pour ce setup USB.

Exemple de mise a jour, sans effacement :

```powershell
.\.venv\Scripts\python.exe -m pc.deploy --port $Port --board waveshare-s3-amoled-164
.\.venv\Scripts\python.exe -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal --replace
```

## OpenCode

Le pont USB fonctionne sans appairage, sans microSD, et doit rester actif :

```powershell
.\.venv\Scripts\python.exe -m pc.opencode --serial $Port
```

Un seul programme peut ouvrir le port. Arreter le pont avec Ctrl+C avant tout
diagnostic, deploiement, transfert ou REPL. Pour installer le plugin OpenCode depuis
les sources, dans un autre terminal et avec Node/npm disponibles :

```powershell
npm --prefix integration/openbuddy ci --ignore-scripts
npm --prefix integration/openbuddy run build
.\.venv\Scripts\python.exe -m pc.install_plugin
```

Ne pas charger deux copies du plugin. Cette commande installe seulement le plugin
OpenBuddy ; elle ne change pas la configuration JSON d'OpenCode. Voir
[evenements OpenCode](opencode-events.md) pour les contraintes de version.
Si le plugin est deja installe et doit etre mis a jour, ajouter `--replace`.
Utiliser `/reload` dans OpenCode si necessaire. Les nouveaux terminaux doivent
etre ouverts dans la racine du depot ; y redefinir `$Port` avant de lancer le pont.

## Diagnostic

Ecran noir : verifier d'abord la reference exacte et le profil, puis lire l'erreur :

```powershell
.\.venv\Scripts\python.exe -m mpremote connect $Port fs cat :openbuddy-error.txt
.\.venv\Scripts\python.exe -m mpremote connect $Port exec "import board_config as c; print(c.BOARD_MODEL, c.DISPLAY_DRIVER)"
.\.venv\Scripts\python.exe -m mpremote connect $Port reset
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
