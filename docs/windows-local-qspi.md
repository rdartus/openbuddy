# PC Windows : recuperer et installer le firmware QSPI

Procedure PowerShell pour une carte **Waveshare ESP32-S3-Touch-AMOLED-1.64**
deja flashee avec MicroPython officiel. Aucun besoin de compiler sur Windows,
de WSL ou de microSD. Le nouveau firmware reste experimental : tester les couleurs
avant les animations. Utiliser un cable USB-C de donnees.

## 1. Recuperer les commits

Les commits doivent d'abord etre **pousses depuis Coder**. Un commit local dans
Coder n'est pas accessible depuis le PC et ne declenche pas GitHub Actions.
Depuis la copie Windows existante du depot :

```powershell
git status --short
git fetch origin
git switch feat/esp32-s3-amoled-164
git pull --ff-only origin feat/esp32-s3-amoled-164
git log -2 --oneline
```

Si Git signale des modifications locales ou une divergence, s'arreter et les
examiner : ne pas utiliser de reset force. Si la branche locale n'existe pas encore,
`git switch --track origin/feat/esp32-s3-amoled-164` permet de la creer.

## 2. Preparer uv

Si uv est absent, suivre son [installation officielle](https://docs.astral.sh/uv/getting-started/installation/).
Depuis la racine du depot :

```powershell
uv --version
uv python install 3.13
```

Seulement si `.venv` n'existe pas :

```powershell
uv venv --python 3.13
```

Installer les dependances dans cet environnement :

```powershell
uv pip install --python .venv\Scripts\python.exe -r pc\requirements.txt -r pc\requirements-assets.txt esptool
```

Pas besoin d'activer le venv. Toutes les commandes suivantes utilisent `uv run python`.

## 3. Recuperer le build GitHub Actions

Le `.bin` est un artefact de compilation, **pas un fichier suivi par Git** :
`git pull` seul ne le telecharge pas. Le push sur la branche declenche le workflow
**Build S3 AMOLED QSPI firmware**. Attendre la reussite de tous ses jobs.

Dans le navigateur : ouvrir <https://github.com/rdartus/openbuddy/actions>, choisir
ce workflow et l'execution correspondant au dernier commit recupere, puis telecharger
l'artefact **openbuddy-s3-amoled-qspi**. Une connexion GitHub peut etre necessaire.
Extraire le ZIP de l'artefact dans `dist\s3-qspi` a la racine du depot.
Ne pas confondre ce ZIP avec `openbuddy-s3-qspi-files.zip` contenu dedans.

Alternative avec GitHub CLI deja installe et authentifie :

```powershell
gh auth status
gh run list --repo rdartus/openbuddy --workflow s3-qspi.yml --branch feat/esp32-s3-amoled-164 --limit 5
$RunId = Read-Host "Numero ID de l'execution correspondant au commit local"
gh run watch $RunId --repo rdartus/openbuddy --exit-status
if ($LASTEXITCODE -ne 0) { throw "La compilation GitHub a echoue" }
gh run download $RunId --repo rdartus/openbuddy --name openbuddy-s3-amoled-qspi --dir dist/s3-qspi
if ($LASTEXITCODE -ne 0) { throw "Le telechargement a echoue" }
```

Utiliser un dossier de destination vide pour ne pas melanger plusieurs builds.
Si aucune execution n'apparait, verifier que les commits et le workflow ont bien
ete pousses. En cas d'echec CI, ouvrir les logs ; ne pas flasher un ancien artefact.

## 4. Verifier le firmware et le commit

```powershell
$Build = Get-Content .\dist\s3-qspi\BUILD.json -Raw | ConvertFrom-Json
$Commit = (git rev-parse HEAD).Trim()
if ($Build.openbuddy_commit -ne $Commit) { throw "Firmware et checkout ne correspondent pas" }
if ($Build.openbuddy_dirty) { throw "Cet artefact ne provient pas d'un checkout propre" }
$Hash = (Get-FileHash .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Hash -ne $Build.firmware_sha256) { throw "Empreinte du firmware incorrecte" }
$Build | Format-List
```

Ces controles verifient la coherence du telechargement. Sa provenance doit rester
votre depot GitHub et la bonne execution, pas un artefact fourni par un tiers.

## 5. Flasher le nouveau firmware

Arreter le pont avec Ctrl+C et fermer Thonny, les REPL et les moniteurs serie.
Sauvegarder les donnees importantes de la carte avant le flashage. Pour remplacer
MicroPython officiel **v1.29.0 SPIRAM_OCT** par ce build de meme partitionnement,
**ne pas faire `erase-flash`**. La preservation du stockage n'est pas garantie pour
un autre firmware ou partitionnement ; voir le [guide detaille](s3-qspi-build.md).

```powershell
uv run python -m serial.tools.list_ports -v
$Port = "COM7" # Ajuster selon le port detecte
uv run python -m esptool --chip esp32s3 --port $Port --baud 460800 write-flash 0 .\dist\s3-qspi\openbuddy-s3-amoled-qspi.bin
```

Ne continuer que si le flashage reussit et son hash est valide. Si besoin, entrer
en bootloader : maintenir BOOT, appuyer puis relacher RST, relacher BOOT. En cas
d'echec de transfert, essayer sans `--baud 460800`.

Appuyer sur RST, relister les ports et ajuster `$Port` s'il a change :

```powershell
uv run python -m serial.tools.list_ports -v
uv run python -m mpremote connect $Port exec "import amoled_qspi; print(amoled_qspi.Bus)"
```

L'import doit reussir. Sinon le firmware natif n'est pas installe correctement.

## 6. Deployer et tester l'ecran

```powershell
uv run python -m pc.deploy --port $Port --board waveshare-s3-amoled-164
uv run python -m mpremote connect $Port run tools/test_amoled.py
uv run python -m mpremote connect $Port reset
```

La dalle entiere doit afficher **rouge, vert, bleu, noir, blanc**, 1,5 seconde par
couleur. Faire le `reset` meme si le test echoue. Si l'ecran reste noir, conserver
les messages du terminal et ne pas poursuivre avec les animations.

## 7. Animations en flash interne

Si le pack existe deja et fonctionne, le conserver et passer au statut.
Sinon, convertir puis installer :

```powershell
uv run python -m pc.pet convert
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal
```

Pour reconvertir un pack local existant, ajouter `--force` a `convert`. Pour
remplacer un pack deja present sur la carte, ajouter `--replace` a `install`.

```powershell
uv run python -m pc.buddy --serial $Port status
uv run python -m pc.buddy --serial $Port demo
```

Le statut doit indiquer `"assets": "internal"` et l'identifiant du personnage
dans `"pet"`. Aucune microSD n'est necessaire.

## 8. Plugin et pont OpenCode

Avec Node.js et npm disponibles, reconstruire le plugin correspondant aux sources :

```powershell
npm --prefix integration/openbuddy ci --ignore-scripts
npm --prefix integration/openbuddy run build
uv run python -m pc.install_plugin
```

Si le plugin est deja installe et doit etre mis a jour, utiliser a la place :

```powershell
uv run python -m pc.install_plugin --replace
```

Ne pas charger deux copies du plugin. Utiliser `/reload` dans OpenCode si necessaire.
Lancer ensuite le pont et laisser ce terminal ouvert :

```powershell
uv run python -m pc.opencode --serial $Port
```

Ctrl+C arrete le pont. Un seul outil peut ouvrir le port serie : toujours arreter
le pont avant les diagnostics ou transferts. Dans un nouveau terminal, revenir
dans la racine du depot et redefinir `$Port`.

## Diagnostic

Avec le pont arrete :

```powershell
uv run python -m mpremote connect $Port fs cat :openbuddy-error.txt
uv run python -m mpremote connect $Port exec "import board_config as c; print(c.BOARD_MODEL, c.DISPLAY_DRIVER)"
uv run python -m mpremote connect $Port reset
```

L'absence de journal n'exclut pas une erreur avant l'initialisation de l'ecran.
Le profil attendu est `waveshare-s3-amoled-164 co5300`, avec le transport natif QSPI.
Pour observer le demarrage : `uv run python -m mpremote connect $Port repl`,
Ctrl+D pour redemarrer et Ctrl+] pour quitter.
