# Matériel OpenBuddy

La Waveshare **ESP32-S3-Touch-AMOLED-1.64 v2** dispose aussi d'un profil dedie,
d'un pilote Python `co5300` et du stockage des animations en flash interne.
Elle exige un firmware MicroPython personnalise avec **`amoled_qspi` natif** :
le `.bin` officiel et un simple `pc.deploy` ne suffisent pas. Les anciennes demos
Waveshare nomment le pilote SH8601, les nouvelles CO5300 ; cela ne confirme pas
une detection du silicium. Les pixels passent en QSPI sur D0..D3, pas en SPI simple.
SPI2_HOST est reserve au module natif : ne pas creer `machine.SPI(1)` en parallele ;
la SD utilise un bus separe. Voir le [guide S3 AMOLED](s3-amoled.md) pour le brochage
et le stockage, et le [guide firmware QSPI](s3-qspi-build.md) pour l'artefact,
son hash, le reflashage et le test plein ecran suivi d'un reset avant les animations.
Ce portage est experimental et reste a valider sur materiel. Les regles C6
ci-dessous ne changent pas : son firmware reste officiel.
Attention aux revisions : **v2 = CS GPIO46**, ancien profil = GPIO9. Le build v2
utilise la flash interne pour le pet, sans acces TF ni repli SD ; voir le guide S3.
Sur la v2, le QMI8658 utilise SDA=47, SCL=48, adresse `0x6B` et choisit entre les
deux sens paysage à 180° avec filtrage, sans mode portrait. Le sens physique de
l'axe reste à valider sur carte ; le C6 n'est pas modifié.

## Carte principale

**Waveshare ESP32-C6-LCD-1.47, version non tactile**, écran ST7789 172×320,
LED RVB WS2812 et emplacement microSD. Ne pas confondre avec la variante Touch.
Le projet utilise MicroPython `ESP32_GENERIC_C6` 1.29.0, sans compilation C.

Orientation retenue : **landscape 320×172, USB-C à gauche**.

| Fonction | GPIO |
|---|---|
| LCD/SD MOSI | 6 |
| LCD/SD SCLK | 7 |
| LCD CS / DC / RST | 14 / 15 / 21 |
| Rétroéclairage LCD | 22 |
| WS2812 RVB | 8 |
| Bouton BOOT, actif bas | 9 |
| SD CS / MISO | 4 / 5 |

## Contraintes impératives

- Rétroéclairage : **PWM ≤ 50 %**, jamais GPIO22 en sortie simple.
- ST7789 : `INVON`, offset de **34 px** sur l'axe court, RGB565 **octet fort en
  premier** et effacement de toute la RAM 240×320 au changement d'orientation.
- LED : ordre **GRB**, chaque composante reste **< 40**.
- Écran/SD : un seul `machine.SPI`, CS relevés avant changement de fréquence.
  LCD 40 MHz ; SD 100 kHz à l'initialisation puis 8 MHz.
- SD **FAT32**, lecture seule pendant l'animation. Ne jamais reformater une carte
  automatiquement. Le pilote SD natif est utilisé seulement pour l'installation
  USB, firmware interrompu et contrôleur SPI écran libéré.
- Aucun buzzer ou haut-parleur intégré : les sons et notifications sont sur le PC.

Le firmware fonctionne aussi sans assets SD, avec un robot intégré de secours.
Une image 96×104 RGB565 occupe 19 968 octets ; les animations ne sont pas envoyées
en continu depuis le PC.

## Déploiement

Les numéros de port série changent selon le PC :

```powershell
uv run python -m serial.tools.list_ports -v
uv run python -m pc.deploy --port COMX
```

Remplacer `COMX` par le port détecté. L'outil copie les fichiers du firmware sans
effacer les clés Bluetooth ou la SD, puis redémarre la carte. Pour les animations,
voir [animations](animations.md).

## Bluetooth

Le device expose un clavier HID et un service GATT OpenBuddy. L'appairage exige
un appui long BOOT 3 s, la vérification du code, puis un **deuxième appui court**.
Un seul hôte BLE est accepté à la fois. Windows peut conserver la connexion HID
après l'arrêt du pont Python : déconnecter l'ancien hôte avant un nouvel appairage.

## USB série

Le firmware **0.3.0** accepte également les états par le port USB-Serial/JTAG
intégré, sans appairage Bluetooth. Le pont se lance avec
`uv run python -m pc.opencode --serial auto` (ou `--serial COMx`).
Les boutons et le clavier HID ne sont pas exposés par ce transport. Un seul outil
peut ouvrir le port série à la fois : arrêter le pont avant un déploiement, un
transfert d'assets ou une session REPL. L'USB doit être autorisé sur le poste.

Ce mode conserve le brochage, les limites de luminosité et la SD en lecture seule.
Le firmware conserve aussi son transport BLE ; seul le pont lancé avec `--serial`
n'utilise pas Bluetooth. Voir le [guide USB](../distribution/workplace/README-usb.md).

Les identifiants de carte, ports personnels et journaux de diagnostic ne font
pas partie du dépôt public. L'adresse BLE réelle se découvre avec `pc.buddy scan`.

Référence : <https://www.waveshare.com/wiki/ESP32-C6-LCD-1.47>.
