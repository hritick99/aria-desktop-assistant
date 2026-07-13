"""System tray icon via pystray."""
import threading
from typing import Callable
from core.logger import get_logger
log = get_logger("tray")
try: import pystray; from PIL import Image, ImageDraw; TRAY_OK = True
except ImportError: TRAY_OK = False

def _make_icon(size=64, color="#6C63FF", letter="A"):
    img = Image.new("RGBA", (size,size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2,2,size-2,size-2], fill=color)
    try: from PIL import ImageFont; font = ImageFont.load_default()
    except: font = None
    bbox = draw.textbbox((0,0), letter, font=font)
    tw,th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((size-tw)//2,(size-th)//2), letter, fill="white", font=font)
    return img

class TrayIcon:
    def __init__(self, on_show: Callable, on_quit: Callable, on_settings: Callable, assistant_name="Aria"):
        self.on_show=on_show; self.on_quit=on_quit; self.on_settings=on_settings
        self.name=assistant_name; self._icon=None

    def start(self):
        if not TRAY_OK: log.warning("pystray/Pillow not installed"); return
        img  = _make_icon(letter=self.name[0].upper())
        menu = pystray.Menu(
            pystray.MenuItem(f"Show {self.name}", self._show, default=True),
            pystray.MenuItem("Settings", self._settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon(self.name, img, title=f"{self.name} — AI Assistant", menu=menu)
        threading.Thread(target=self._icon.run, daemon=True).start()
        log.info("Tray started")

    def _show(self, icon, item):
        try: self.on_show()
        except Exception as e: log.error(f"Tray show: {e}")
    def _settings(self, icon, item):
        try: self.on_settings()
        except Exception as e: log.error(f"Tray settings: {e}")
    def _quit(self, icon, item):
        icon.stop()
        try: self.on_quit()
        except Exception as e: log.error(f"Tray quit: {e}")
    def stop(self):
        if self._icon:
            try: self._icon.stop()
            except: pass
