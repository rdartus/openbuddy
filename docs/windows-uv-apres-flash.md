# Windows avec uv : apres le flashage

Procedure pour la **Waveshare ESP32-S3-Touch-AMOLED-1.64**, apres installation du
firmware experimental OpenBuddy avec le module natif **`amoled_qspi`**.
**Si vous avez deja flashe MicroPython officiel, commencer par le
[guide firmware S3 QSPI](s3-qspi-build.md#installation-windows-uv)** : il centralise
le telechargement de l'artefact, la verification SHA-256, la sauvegarde et le
reflashage. Ne plus telecharger de `.bin` officiel pour ce S3. Ne pas lancer
`erase-flash` par reflexe ; suivre les conditions de preservation du guide.

Executer les commandes dans PowerShell, depuis la racine du depot contenant
le portage AMOLED du meme build que le firmware. uv et les dependances Python
doivent deja etre installes. Pour le plugin et le pont, utiliser le depot complet
au commit indique dans `BUILD.json`, pas seulement le ZIP des fichiers firmware.
Une microSD n'est pas necessaire pour cette procedure. Le C6 n'est pas concerne
et conserve son firmware officiel.

## 1. Verifier la carte

Appuyer sur **RST**, puis verifier le port : il peut avoir change apres le flashage.

```powershell
uv run python -m serial.tools.list_ports -v
$Port = "COM7" # Ajuster selon le port detecte
```

Verifier le module natif avant tout deploiement :

```powershell
uv run python -m mpremote connect $Port exec "import amoled_qspi; print(amoled_qspi.Bus)"
```

Si l'import echoue, revenir au [guide firmware QSPI](s3-qspi-build.md) : copier
un fichier Python ne peut pas installer ce module C.

## 2. Deployer et tester l'ecran

Deployer le profil de la carte. `pc.deploy` effectue un preflight du module natif
avant de copier les fichiers. Tester ensuite la dalle sans BLE ni SD :

```powershell
uv run python -m pc.deploy --port $Port --board waveshare-s3-amoled-164
uv run python -m mpremote connect $Port run tools/test_amoled.py
uv run python -m mpremote connect $Port reset
```

Le test doit afficher **rouge, vert, bleu, noir, blanc**, sur toute la dalle,
1,5 seconde par couleur. **Terminer par `reset` meme si le test echoue.** Si l'ecran
reste noir ou si le test echoue, conserver la sortie et suivre le diagnostic
avant de continuer : ne pas installer les animations. Le portage est experimental ;
compilation et tests simules ne valident pas le materiel reel. Le tactile et l'IMU
ne sont pas utilises. Si cette sequence a deja reussi dans le guide QSPI, passer
directement aux animations.

## 3. Installer les animations sans microSD

Telecharger et convertir le personnage :

```powershell
uv run python -m pc.pet convert
```

Installer les animations en flash interne :

```powershell
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal
```

Verifier le statut, puis lancer la demonstration :

```powershell
uv run python -m pc.buddy --serial $Port status
uv run python -m pc.buddy --serial $Port demo
```

Le statut devrait indiquer `"assets": "internal"` et l'identifiant du personnage
dans `"pet"`. Si le pack est deja installe, son remplacement exige `--replace` :

```powershell
uv run python -m pc.pet install build/pets/super-saiyan-goku-combat --port $Port --storage internal --replace
```

## 4. Installer le plugin OpenCode

Si le plugin n'a pas encore ete construit, avec Node.js et npm disponibles :

```powershell
npm --prefix integration/openbuddy ci --ignore-scripts
npm --prefix integration/openbuddy run build
```

Installer le plugin :

```powershell
uv run python -m pc.install_plugin
```

Si une ancienne version existe et doit etre remplacee :

```powershell
uv run python -m pc.install_plugin --replace
```

Utiliser `/reload` dans OpenCode si necessaire. Ne pas charger deux copies du
plugin. Cette integration cible OpenCode v2 en service local gere ; voir
[les details de l'integration](opencode-events.md).

## 5. Demarrer le pont USB

```powershell
uv run python -m pc.opencode --serial $Port
```

Laisser ce terminal ouvert. **Ctrl+C** arrete le pont.
**Arreter le pont avant tout diagnostic, transfert ou deploiement : un seul
programme peut utiliser le port serie a la fois.**

Dans un nouveau terminal, revenir a la racine du depot et redefinir `$Port` avant
d'utiliser les commandes. La variable n'est pas partagee entre les terminaux.

## Diagnostic : ecran noir

Executer ces commandes avec le pont arrete :

```powershell
uv run python -m mpremote connect $Port fs cat :openbuddy-error.txt
uv run python -m mpremote connect $Port exec "import board_config as c; print(c.BOARD_MODEL, c.DISPLAY_DRIVER)"
uv run python -m mpremote connect $Port reset
```

Le profil attendu est `waveshare-s3-amoled-164 co5300`. Le nom `co5300` reste celui
du profil : les anciennes demos constructeur disent SH8601, les nouvelles CO5300,
sans detection confirmee du silicium. Si le fichier d'erreur
n'existe pas, ce n'est pas necessairement anormal : une erreur d'initialisation
ecran peut survenir avant la creation du journal.

Pour observer le demarrage directement :

```powershell
uv run python -m mpremote connect $Port repl
```

Appuyer sur **Ctrl+D** pour redemarrer MicroPython et observer les messages,
puis **Ctrl+]** pour quitter le REPL. Les acces REPL peuvent interrompre le
programme ; terminer les diagnostics par un `reset` si necessaire.

Conserver les sorties des commandes et noter ce que montre l'ecran pour diagnostiquer
un probleme. Le [guide firmware QSPI](s3-qspi-build.md) fait reference pour le
reflashage et le test ; le [guide S3 AMOLED](s3-amoled.md) decrit le materiel,
le stockage et les limites du portage.
