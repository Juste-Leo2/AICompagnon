# SPDX-FileCopyrightText: 2023-2024 The Trustees of Massachusetts Institute of Technology
#
# SPDX-License-Identifier: MIT

"""
ili9488_lib.py

Driver for the ILI9488 LCD display using Adafruit Blinka.
Includes Pillow integration for image display and differential updates.
"""

import time
import digitalio
import busio
from PIL import Image # Import Pillow, ImageOps n'est plus directement utilisé ici

# --- Définitions de commandes ILI9488 (en hexadécimal) ---
ILI9488_NOP     = 0x00
ILI9488_SWRESET = 0x01
ILI9488_RDDID   = 0x04
ILI9488_RDDST   = 0x09

ILI9488_SLPIN   = 0x10
ILI9488_SLPOUT  = 0x11
ILI9488_PTLON   = 0x12
ILI9488_NORON   = 0x13

ILI9488_RDMODE  = 0x0A
ILI9488_RDMADCTL  = 0x0B
ILI9488_RDPIXFMT  = 0x0C
ILI9488_RDIMGFMT  = 0x0D
ILI9488_RDSELFDIAG  = 0x0F

ILI9488_INVOFF  = 0x20
ILI9488_INVON   = 0x21
ILI9488_GAMMASET = 0x26
ILI9488_DISPOFF = 0x28
ILI9488_DISPON  = 0x29

ILI9488_CASET   = 0x2A
ILI9488_PASET   = 0x2B
ILI9488_RAMWR   = 0x2C
ILI9488_RAMRD   = 0x2E

ILI9488_PTLAR   = 0x30
ILI9488_MADCTL  = 0x36
ILI9488_PIXFMT  = 0x3A

ILI9488_FRMCTR1 = 0xB1
ILI9488_FRMCTR2 = 0xB2
ILI9488_FRMCTR3 = 0xB3
ILI9488_INVCTR  = 0xB4
ILI9488_DFUNCTR = 0xB6

ILI9488_PWCTR1  = 0xC0
ILI9488_PWCTR2  = 0xC1
ILI9488_PWCTR3  = 0xC2
ILI9488_PWCTR4  = 0xC3
ILI9488_PWCTR5  = 0xC4
ILI9488_VMCTR1  = 0xC5
ILI9488_VMCTR2  = 0xC7

ILI9488_RDID1   = 0xDA
ILI9488_RDID2   = 0xDB
ILI9488_RDID3   = 0xDC
ILI9488_RDID4   = 0xDD

ILI9488_GMCTRP1 = 0xE0
ILI9488_GMCTRN1 = 0xE1

ILI9488_IFMODE_CTL     = 0xB0
ILI9488_ENTRY_MODE_SET = 0xB7
ILI9488_IMAGE_FUNC_SET = 0xE9
ILI9488_SET_BRIGHTNESS = 0x51
ILI9488_ADJUST_CTL3    = 0xF7

# Dimensions par défaut de l'écran (peuvent être surchargées à l'init)
ILI9488_DEFAULT_TFTWIDTH  = 320
ILI9488_DEFAULT_TFTHEIGHT = 480

# Modes MADCTL
MADCTL_MY  = 0x80  # Row Address Order
MADCTL_MX  = 0x40  # Column Address Order
MADCTL_MV  = 0x20  # Row/Column Exchange
MADCTL_ML  = 0x10  # Vertical Refresh Order
MADCTL_BGR = 0x08  # BGR-RGB Order (1 = BGR, 0 = RGB)
MADCTL_MH  = 0x04  # Horizontal Refresh Order

# Couleurs prédéfinies (format 24 bits 0xRRGGBB)
COLOR_BLACK   = 0x000000
COLOR_WHITE   = 0xFFFFFF
COLOR_RED     = 0xFF0000
COLOR_GREEN   = 0x00FF00
COLOR_BLUE    = 0x0000FF
COLOR_YELLOW  = 0xFFFF00
COLOR_CYAN    = 0x00FFFF
COLOR_MAGENTA = 0xFF00FF

# --- Configuration ---
DEFAULT_SPI_BAUDRATE = 24000000 # 24 MHz, un bon point de départ, à ajuster.

class ILI9488:
    def __init__(self, spi: busio.SPI, cs: digitalio.DigitalInOut, dc: digitalio.DigitalInOut,
                 rst: digitalio.DigitalInOut, bl, # bl peut être DigitalInOut ou PWMOut
                 width: int = ILI9488_DEFAULT_TFTWIDTH,
                 height: int = ILI9488_DEFAULT_TFTHEIGHT):
        self._spi = spi
        self._cs = cs
        self._dc = dc
        self._rst = rst
        self._bl = bl

        self._native_width = width
        self._native_height = height
        self._width = width
        self._height = height
        self._rotation = 0

        self._cs.direction = digitalio.Direction.OUTPUT
        self._dc.direction = digitalio.Direction.OUTPUT
        self._rst.direction = digitalio.Direction.OUTPUT
        if isinstance(self._bl, digitalio.DigitalInOut):
            self._bl.direction = digitalio.Direction.OUTPUT
        # Si c'est un objet PWM, sa direction est gérée par le module PWM.

        self._cs.value = True # Désélectionner par défaut
        # self.backlight_off() # Peut être appelé par l'utilisateur après begin()

        self._is_spi_locked = False

        self._last_frame_buffer_pil: Image.Image | None = None
        self._force_full_refresh = True

    def _write_command(self, command: int, data: bytes | None = None):
        needs_lock_management = not self._is_spi_locked
        if needs_lock_management:
            if not self._spi.try_lock():
                raise RuntimeError(f"Impossible de verrouiller le bus SPI pour la commande 0x{command:02X}")
            self._is_spi_locked = True

        try:
            self._dc.value = False
            self._cs.value = False
            self._spi.write(bytes([command]))
            # Pour la plupart des commandes, CS peut remonter après la commande elle-même.
            # Si des données suivent immédiatement, on le garde bas dans certains cas.
            # Cependant, la pratique courante avec ces drivers est de remonter CS entre cmd et data
            # sauf pour RAMWR.
            self._cs.value = True

            if data is not None:
                self._dc.value = True
                self._cs.value = False
                self._spi.write(data)
                self._cs.value = True
        finally:
            if needs_lock_management and self._is_spi_locked:
                self._spi.unlock()
                self._is_spi_locked = False

    def _write_command_ramwr_mode(self, command: int):
        # L'appelant DOIT gérer le verrouillage SPI et le CS.value = True à la fin.
        if not self._is_spi_locked:
            raise RuntimeError("SPI non verrouillé pour _write_command_ramwr_mode")

        self._dc.value = False
        self._cs.value = False # RESTE BAS
        self._spi.write(bytes([command]))
        # DC sera mis à True par l'appelant pour envoyer les données pixels.

    def begin(self, spi_baudrate: int = DEFAULT_SPI_BAUDRATE):
        print("Initialisation de l'écran ILI9488...")
        self._rst.value = False
        time.sleep(0.02)
        self._rst.value = True
        time.sleep(0.150)

        if not self._spi.try_lock():
             raise RuntimeError("Impossible de verrouiller le bus SPI pour l'initialisation.")
        self._is_spi_locked = True

        try:
            self._spi.configure(baudrate=spi_baudrate, polarity=0, phase=0)
            print(f"Bus SPI configuré (baudrate={spi_baudrate}). Fréquence réelle: {self._spi.frequency} Hz")
        except Exception as e:
            print(f"ATTENTION: Erreur lors de la configuration du bus SPI: {e}")

        self._write_command(ILI9488_SWRESET)
        time.sleep(0.120)

        self._write_command(ILI9488_DISPOFF)

        self._write_command(ILI9488_IFMODE_CTL, bytes([0x00]))
        self._write_command(ILI9488_FRMCTR1, bytes([0xA0]))
        self._write_command(ILI9488_INVCTR, bytes([0x02]))
        self._write_command(ILI9488_DFUNCTR, bytes([0x02, 0x02, 0x3B]))
        self._write_command(ILI9488_ENTRY_MODE_SET, bytes([0xC6]))

        self._write_command(ILI9488_PWCTR1, bytes([0x17, 0x15]))
        self._write_command(ILI9488_PWCTR2, bytes([0x41]))
        self._write_command(ILI9488_VMCTR1, bytes([0x00, 0x12, 0x80]))

        self._write_command(ILI9488_PIXFMT, bytes([0x66])) # 18-bit/pixel (RGB666)

        gamma_p = bytes([0x00,0x03,0x09,0x08,0x16,0x0A,0x3F,0x78,0x4C,0x09,0x0A,0x08,0x16,0x1A,0x0F])
        self._write_command(ILI9488_GMCTRP1, gamma_p)
        gamma_n = bytes([0x00,0X16,0X19,0x03,0x0F,0x05,0x32,0x45,0x46,0x04,0x0E,0x0D,0x35,0x37,0x0F])
        self._write_command(ILI9488_GMCTRN1, gamma_n)

        self._write_command(ILI9488_IMAGE_FUNC_SET, bytes([0x00]))
        self._write_command(ILI9488_SET_BRIGHTNESS, bytes([0xFF]))
        self._write_command(ILI9488_ADJUST_CTL3, bytes([0xA9, 0x51, 0x2C, 0x82]))

        self._write_command(ILI9488_SLPOUT)
        time.sleep(0.150)

        self._write_command(ILI9488_DISPON)
        time.sleep(0.020)

        if self._is_spi_locked:
            self._spi.unlock()
            self._is_spi_locked = False

        self.setRotation(self._rotation)
        self._force_full_refresh = True
        print("Initialisation de l'écran ILI9488 terminée.")

    def setAddrWindow(self, x0: int, y0: int, x1: int, y1: int):
        if not self._is_spi_locked:
             raise RuntimeError("SPI non verrouillé pour setAddrWindow")

        x_data = bytes([ (x0 >> 8) & 0xFF, x0 & 0xFF, (x1 >> 8) & 0xFF, x1 & 0xFF ])
        self._write_command(ILI9488_CASET, x_data)

        y_data = bytes([ (y0 >> 8) & 0xFF, y0 & 0xFF, (y1 >> 8) & 0xFF, y1 & 0xFF ])
        self._write_command(ILI9488_PASET, y_data)

        self._write_command_ramwr_mode(ILI9488_RAMWR)


    def _convert_color_to_18bit_bytes(self, color: int) -> bytes:
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        return bytes([r & 0xFC, g & 0xFC, b & 0xFC])

    def fillRect(self, x: int, y: int, w: int, h: int, color: int):
        if x >= self._width or y >= self._height or w <= 0 or h <= 0: return
        x2 = min(self._width, x + w)
        y2 = min(self._height, y + h)
        x = max(0, x)
        y = max(0, y)
        w = x2 - x
        h = y2 - y
        if w <= 0 or h <= 0: return

        if not self._spi.try_lock():
            raise RuntimeError(f"Impossible de verrouiller le bus SPI pour fillRect.")
        self._is_spi_locked = True

        try:
            self.setAddrWindow(x, y, x + w - 1, y + h - 1)

            pixel_bytes_tpl = self._convert_color_to_18bit_bytes(color)
            num_pixels = w * h

            # Envoyer par blocs pour une meilleure gestion de la mémoire et des performances SPI
            # Taille de bloc en nombre de pixels. 512 pixels * 3 bytes/pixel = 1536 bytes.
            # Adapter cette taille si nécessaire.
            chunk_size_pixels = 512

            self._dc.value = True # Mode données (CS est déjà bas depuis setAddrWindow/RAMWR)

            num_full_chunks = num_pixels // chunk_size_pixels
            remaining_pixels = num_pixels % chunk_size_pixels

            if num_full_chunks > 0:
                data_chunk = pixel_bytes_tpl * chunk_size_pixels
                for _ in range(num_full_chunks):
                    self._spi.write(data_chunk)

            if remaining_pixels > 0:
                self._spi.write(pixel_bytes_tpl * remaining_pixels)

        finally:
            self._cs.value = True
            if self._is_spi_locked:
                self._spi.unlock()
                self._is_spi_locked = False

        # Si vous utilisez fillRect, le _last_frame_buffer_pil peut devenir désynchronisé.
        # Forcer un refresh complet la prochaine fois ou mettre à jour le buffer ici (plus coûteux).
        self._force_full_refresh = True # Solution simple

    def fillScreen(self, color: int):
        self.fillRect(0, 0, self._width, self._height, color)
        # Assurer que le prochain display() fera un full refresh
        self._force_full_refresh = True

    def drawPixel(self, x: int, y: int, color: int):
        if x < 0 or x >= self._width or y < 0 or y >= self._height: return
        self.fillRect(x, y, 1, 1, color)
        # _force_full_refresh sera déjà à True à cause de fillRect

    def setRotation(self, m: int):
        self._rotation = m % 4
        madctl_val = 0

        if self._rotation == 0:
            madctl_val = MADCTL_MX | MADCTL_BGR
            self._width  = self._native_width
            self._height = self._native_height
        elif self._rotation == 1:
            madctl_val = MADCTL_MV | MADCTL_BGR
            self._width  = self._native_height
            self._height = self._native_width
        elif self._rotation == 2:
            madctl_val = MADCTL_MY | MADCTL_BGR
            self._width  = self._native_width
            self._height = self._native_height
        elif self._rotation == 3:
            madctl_val = MADCTL_MX | MADCTL_MY | MADCTL_MV | MADCTL_BGR
            self._width  = self._native_height
            self._height = self._native_width

        self._write_command(ILI9488_MADCTL, bytes([madctl_val]))
        self._last_frame_buffer_pil = None
        self._force_full_refresh = True
        print(f"Rotation définie sur {self._rotation}. Dimensions: {self._width}x{self._height}")

    def display(self, image: Image.Image, force_full_refresh: bool = False):
        current_width, current_height = self._width, self._height

        if image.size != (current_width, current_height):
            image = image.resize((current_width, current_height), Image.Resampling.NEAREST) # Ou BICUBIC pour meilleure qualité
        if image.mode != "RGB":
            image = image.convert("RGB")

        if not self._spi.try_lock():
            raise RuntimeError("Impossible de verrouiller le bus SPI pour display().")
        self._is_spi_locked = True

        try:
            new_pixels = image.load()

            if self._force_full_refresh or force_full_refresh or \
               self._last_frame_buffer_pil is None or \
               self._last_frame_buffer_pil.size != (current_width, current_height) :

                self.setAddrWindow(0, 0, current_width - 1, current_height - 1)

                buffer_size = current_width * current_height * 3
                pixel_data = bytearray(buffer_size)
                idx = 0
                for y_coord in range(current_height):
                    for x_coord in range(current_width):
                        r, g, b = new_pixels[x_coord, y_coord]
                        pixel_data[idx]   = r & 0xFC
                        pixel_data[idx+1] = g & 0xFC
                        pixel_data[idx+2] = b & 0xFC
                        idx += 3

                self._dc.value = True
                chunk_write_size = 4096
                for i in range(0, buffer_size, chunk_write_size):
                    self._spi.write(pixel_data[i:i+chunk_write_size])

                self._force_full_refresh = False
            else:
                old_pixels = self._last_frame_buffer_pil.load()

                min_y_changed = current_height
                max_y_changed = -1
                changed_rows_data = {}

                for y_coord in range(current_height):
                    row_changed = False
                    # Pré-allouer row_pixel_data ici peut être légèrement plus performant
                    # que de le recréer à chaque fois si row_changed.
                    current_row_pixel_data = bytearray(current_width * 3)
                    row_idx = 0
                    for x_coord in range(current_width):
                        r_new, g_new, b_new = new_pixels[x_coord, y_coord]

                        current_row_pixel_data[row_idx]   = r_new & 0xFC
                        current_row_pixel_data[row_idx+1] = g_new & 0xFC
                        current_row_pixel_data[row_idx+2] = b_new & 0xFC
                        row_idx += 3

                        if not row_changed: # Optimisation: ne comparer que si pas déjà marqué comme changé
                            r_old, g_old, b_old = old_pixels[x_coord, y_coord]
                            if r_new != r_old or g_new != g_old or b_new != b_old:
                                row_changed = True

                    if row_changed:
                        min_y_changed = min(min_y_changed, y_coord)
                        max_y_changed = max(max_y_changed, y_coord)
                        changed_rows_data[y_coord] = current_row_pixel_data

                if min_y_changed <= max_y_changed:
                    y_start_block = -1
                    # Gérer le CS autour des blocs de setAddrWindow + write
                    for y_coord in range(min_y_changed, max_y_changed + 2):
                        if y_coord <= max_y_changed and y_coord in changed_rows_data:
                            if y_start_block == -1:
                                y_start_block = y_coord
                        else:
                            if y_start_block != -1:
                                y_end_block = y_coord - 1
                                # Important: Chaque setAddrWindow + write doit être une transaction SPI complète
                                # avec son propre CS low/high, ou du moins, CS doit être haut après le dernier write.
                                # L'implémentation actuelle de setAddrWindow laisse CS bas,
                                # donc on le remonte après l'écriture du bloc de données.
                                self.setAddrWindow(0, y_start_block, current_width - 1, y_end_block) # CS devient bas
                                self._dc.value = True
                                for y_b in range(y_start_block, y_end_block + 1):
                                    self._spi.write(changed_rows_data[y_b])
                                self._cs.value = True # Fin de ce bloc de transaction
                                y_start_block = -1
                # Si aucun CS.value = True n'a été appelé (ex: aucune ligne changée, ou après le dernier bloc)
                # on s'assure que CS est haut.
                if not self._cs.value: # Si CS est resté bas
                    self._cs.value = True


            self._last_frame_buffer_pil = image.copy()

        finally:
            if not self._cs.value: # Double check au cas où une condition l'aurait laissé bas
                 self._cs.value = True
            if self._is_spi_locked:
                self._spi.unlock()
                self._is_spi_locked = False

    def backlight_on(self, brightness: float = 1.0):
        if self._bl is None: return
        if isinstance(self._bl, digitalio.DigitalInOut):
            self._bl.value = True
            print("Rétroéclairage allumé (Digital).")
        elif hasattr(self._bl, 'duty_cycle'): # Supposition pour un objet PWM-like
            try:
                # Pour CircuitPython/Blinka analogio.PWMOut, duty_cycle est 0-65535
                duty = int(max(0.0, min(1.0, brightness)) * 65535)
                self._bl.duty_cycle = duty
                print(f"Rétroéclairage allumé (PWM) à {brightness*100:.0f}%.")
            except Exception as e:
                print(f"Erreur lors du réglage PWM du rétroéclairage: {e}. Utilisation ON/OFF Digital.")
                # Fallback si c'est un objet DigitalInOut qui a été passé par erreur avec un hasattr 'duty_cycle'
                if isinstance(self._bl, digitalio.DigitalInOut):
                    self._bl.value = True
        else:
            print(f"Type de broche de rétroéclairage non supporté pour le contrôle de la luminosité: {type(self._bl)}")


    def backlight_off(self):
        if self._bl is None: return
        if isinstance(self._bl, digitalio.DigitalInOut):
            self._bl.value = False
        elif hasattr(self._bl, 'duty_cycle'):
            self._bl.duty_cycle = 0
        print("Rétroéclairage éteint.")


    @property
    def width(self) -> int:
        """Current width of the display after rotation."""
        return self._width

    @property
    def height(self) -> int:
        """Current height of the display after rotation."""
        return self._height







# Helper function pour convertir R, G, B en couleur 24 bits (0xRRGGBB)
def color_rgb(r, g, b):
    r_val = max(0, min(255, int(r)))
    g_val = max(0, min(255, int(g)))
    b_val = max(0, min(255, int(b)))
    return (r_val << 16) | (g_val << 8) | b_val
