# Windows avec uv : après le flashage

Suivre le **[README Windows ESP32-S3 AMOLED v2](../README-ESP32-S3-Windows.md)**.
Il remplace les anciens parcours Windows pour éviter des instructions divergentes.

Si le bon firmware natif v2 est déjà flashé :

1. Préparer le dépôt et Python avec l’[étape 1](../README-ESP32-S3-Windows.md#1-préparer-les-fichiers-et-python).
2. Reprendre à l’[étape 4 : déploiement et test écran](../README-ESP32-S3-Windows.md#4-déployer-openbuddy-et-tester-lécran).
3. Continuer avec le pet en flash et le plugin, dans le même README.

Un ancien build sans `amoled_qspi` API v3 exige d’abord le reflashage décrit dans
ce README. Un simple déploiement Python ne suffit pas.
