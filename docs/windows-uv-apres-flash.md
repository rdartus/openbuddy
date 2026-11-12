# Windows avec uv : apres le flashage

Procedure pour la **Waveshare ESP32-S3-Touch-AMOLED-1.64**, apres avoir flashe
MicroPython `ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin` avec succes.
**Ne pas refaire `erase-flash`.**

Executer les commandes dans PowerShell, depuis la racine du depot contenant
le portage AMOLED. uv et les dependances Python doivent deja etre installes.
Une microSD n'est pas necessaire pour cette procedure.

## 1. Verifier la carte

Appuyer sur **RST**, puis verifier le port : il peut avoir change apres le flashage.

```powershell
uv run python -m serial.tools.list_ports -v
$Port = "COM7" # Ajuster selon le port detecte
```

Verifier que MicroPython repond et afficher la memoire disponible :

```powershell
uv run python -m mpremote connect $Port exec "import os, gc; print(os.uname()); print('RAM libre:', gc.mem_free()); s=os.statvfs('/'); print('Flash filesystem total/libre:', s[0]*s[2], s[0]*s[4])"
```

## 2. Deployer OpenBuddy

Verifier que la copie du depot contient le portage AMOLED :

```powershell
Test-Path .\c6lcd\co5300.py
```

Le resultat doit etre `True`. Deployer le profil de la carte :

```powershell
uv run python -m pc.deploy --port $Port --board waveshare-s3-amoled-164
```

Le robot integre devrait apparaitre. **Si l'ecran reste noir, suivre le diagnostic
en fin de document avant de continuer.** Le portage n'a pas encore ete valide sur
le materiel reel ; le tactile et l'IMU ne sont pas utilises.

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

Le profil attendu est `waveshare-s3-amoled-164 co5300`. Si le fichier d'erreur
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
un probleme. Le [guide complet S3 AMOLED](s3-amoled.md) contient aussi le flashage
initial et les limites du portage.
