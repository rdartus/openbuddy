"""Read-only removable storage; failures never prevent the BLE companion booting."""

import time

import board_config as cfg
from sdcard_spi import ReadOnlySDCard


class Storage:
    def __init__(self, bus):
        self.bus = bus
        self.card = None
        self.mounted = False
        self.error = None

    def mount(self, attempts=3, delay_ms=400):
        """A cold card can need several hundred ms after power-up to answer."""
        import vfs

        if self.bus is None:
            from shared_spi import SharedSPI
            self.bus = SharedSPI(sd_only=True)

        for attempt in range(attempts):
            if attempt:
                time.sleep_ms(delay_ms)
            try:
                self.card = ReadOnlySDCard(self.bus, cfg.SD_SPI_BAUD)
                vfs.mount(self.card, cfg.SD_MOUNT, readonly=True)
                self.mounted = True
                self.error = None
                print("SD mounted read-only:", self.card.sectors * 512, "bytes")
                break
            except (OSError, ValueError) as error:
                self.card = None
                self.error = str(error)
                print("SD unavailable:", self.error)
            finally:
                self.bus.for_lcd()
        return self.mounted

    def load_player(self, lcd, attempts=3):
        """Use a valid local pack first, without probing an absent SD card."""
        from pet_player import PetPlayer

        for root in ("/openbuddy", cfg.SD_MOUNT + "/openbuddy"):
            if root.startswith(cfg.SD_MOUNT + "/"):
                if not self.mounted and not self.mount(attempts=attempts):
                    continue
            player = PetPlayer(lcd, directory=root + "/pets", selection=root + "/active.json")
            if player.available:
                player.source = "internal" if root == "/openbuddy" else "sd"
                return player
            player.close()
        return None

    def close(self):
        if self.mounted:
            import vfs

            try:
                vfs.umount(cfg.SD_MOUNT)
            finally:
                self.mounted = False
                self.bus.for_lcd()
