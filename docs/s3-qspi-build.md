# Firmware S3 AMOLED QSPI experimental

## Pourquoi un nouveau firmware

Le SPI simple du premier portage a laisse l'ecran noir lors du test utilisateur.
Les anciennes demos Waveshare nomment le pilote SH8601 et les nouvelles CO5300 ;
elles utilisent la meme initialisation et surtout le **QSPI pour les pixels**.
Le nom du controleur seul ne permet donc pas d'attribuer la panne.

Le module C `amoled_qspi` reproduit le transport constructeur : registres avec
opcode `0x02`, pixels avec opcode `0x32`, en-tete sur une ligne, pixels sur quatre.
Il est compile dans MicroPython : un simple `pc.deploy` sur le `.bin` officiel
ne suffit plus. Le C6 n'est pas concerne et conserve son firmware officiel.

Configuration : MicroPython **v1.29.0**, ESP-IDF **v5.5.2**, carte
`ESP32_GENERIC_S3`, variante `SPIRAM_OCT`. SPI3_HOST appartient exclusivement au
module natif (GPIO CS=9, CLK=10, D0..D3=11..14). Ne pas creer `machine.SPI(2)`
en parallele. La SD conserve son bus separe. Les transferts sont synchrones,
avec un tampon DMA interne de 4092 octets. L'affichage utilise deux buffers
persistants de 255360 octets en memoire accessible au heap MicroPython.

**Experimental : une compilation et des tests simules ne valident pas l'ecran
reel, les couleurs, la rotation ou les redemarrages.** Le tactile et l'IMU ne sont
pas utilises. Aucune animation proprietaire n'est distribuee avec le firmware.

## GitHub Actions

Le workflow **Build S3 AMOLED QSPI firmware** compile sur les pushes vers `master`
ou `feat/esp32-s3-amoled-164` et les pull requests modifiant les sources concernees.
Il peut aussi etre lance manuellement
une fois disponible sur la branche par defaut. Il produit un artefact
`openbuddy-s3-amoled-qspi` conserve 30 jours :

- `openbuddy-s3-amoled-qspi.bin` : MicroPython avec le module natif, sans application Python.
- `openbuddy-s3-qspi-files.zip` : fichiers Python correspondants, diagnostic et licences.
- `BUILD.json` : commits des sources, etat sale/propre et empreintes des fichiers.
- `SHA256SUMS.txt` : empreintes des fichiers livres.
- `INSTALL.md` : ce guide.

Un tag pousse **`s3-qspi-*`** publie automatiquement une **prerelease**, uniquement
apres la compilation reussie. Le workflow n'ecrase pas une release existante.
Un push de branche ne publie pas de release. Un commit local ne lance aucune CI.
Les pull requests n'ont pas de droit d'ecriture dans les releases.

## Installation Windows uv

Arreter le pont et tout outil serie. Recuperer l'artefact de la bonne execution
GitHub (ou les fichiers de la prerelease), et extraire l'artefact dans un dossier
local. Conserver le `.bin` et `SHA256SUMS.txt` ensemble. Verifier son empreinte :

```powershell
Get-FileHash .\openbuddy-s3-amoled-qspi.bin -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Comparer l'empreinte a la ligne du `.bin` avant de continuer. Utiliser uniquement
un artefact provenant de votre depot et du commit attendu.

Extraire `openbuddy-s3-qspi-files.zip` dans un dossier distinct et utiliser ses
fichiers, ou utiliser le checkout du commit indique dans `BUILD.json`. Ne pas
melanger l'ancien pilote SPI et le nouveau firmware QSPI.

Depuis la racine des fichiers Python correspondants :

```powershell
uv python install 3.13
uv venv --python 3.13
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt -r pc\requirements-assets.txt esptool
uv run python -m serial.tools.list_ports -v
$Port = "COM7" # Ajuster selon le port detecte
```

Si `.venv` existe deja, ne pas le recreer. Le chemin du `.bin` ci-dessous est a
adapter a son dossier de telechargement.

**Sauvegarder les fichiers importants avant tout flashage.** Pour remplacer le
MicroPython officiel v1.29.0 SPIRAM_OCT par ce build de meme configuration,
ne pas lancer `erase-flash`. Le VFS commence a `0x200000` ; le `.bin` combine
reecrit cependant la table de partitions. Au demarrage, MicroPython recree
l'entree VFS si necessaire. Cette preservation ne remplace pas une sauvegarde
et ne s'applique pas a un ancien firmware au partitionnement different.

```powershell
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 .\openbuddy-s3-amoled-qspi.bin
```

Si necessaire : maintenir BOOT, appuyer puis relacher RST, relacher BOOT.
Apres flashage, appuyer sur RST, relister les ports et ajuster `$Port`.

```powershell
uv run python -m serial.tools.list_ports -v
uv run python -m mpremote connect $Port exec "import amoled_qspi; print(amoled_qspi.Bus)"
uv run python -m pc.deploy --port $Port --board waveshare-s3-amoled-164
uv run python -m mpremote connect $Port run tools/test_amoled.py
uv run python -m mpremote connect $Port reset
```

Le test doit afficher **rouge, vert, bleu, noir, blanc**, sur toute la dalle,
pendant 1,5 seconde par couleur. Terminer par `reset` meme si le test echoue.
Le test n'initialise ni BLE ni SD. S'il echoue ou si l'ecran reste noir, conserver
la sortie du terminal avant de poursuivre ; ne pas multiplier les effacements.

Si le test est concluant, installer les animations (ou garder celles deja presentes) :

```powershell
uv run python -m pc.pet convert
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal
uv run python -m pc.buddy --serial $Port status
```

Ajouter `--replace` uniquement si un pack existe deja et doit etre remplace.
Pour l'integration OpenCode, utiliser le depot complet et le guide
`docs/windows-uv-apres-flash.md` : le ZIP firmware ne contient pas le pont OpenCode
ni le bundle du plugin. Les fichiers d'assets restent independants du `.bin`.

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
produit `dist/s3-qspi/`. Aucune connexion USB n'est necessaire pour compiler.
La compilation C utilise l'environnement ESP-IDF, pas l'environnement uv du PC.

Tests du module C sur ordinateur (pas une validation electrique) :

```bash
make -f tests/native_qspi/Makefile MICROPYTHON=/path/to/micropython
```
