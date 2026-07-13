import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from config import LOG_PATH, get

def setup_logging():
    level = getattr(logging, get("log_level"), logging.INFO)
    fmt   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    root  = logging.getLogger()
    root.setLevel(level)
    fh = RotatingFileHandler(LOG_PATH, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(fmt))
    root.addHandler(ch)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def install_crash_handler(on_crash=None):
    log = get_logger("crash")
    def handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.critical(f"Unhandled exception:\n{msg}")
        if on_crash:
            try: on_crash(str(exc_value))
            except Exception: pass
    sys.excepthook = handler
