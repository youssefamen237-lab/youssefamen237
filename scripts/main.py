import logging
import sys
from pathlib import Path

from .scheduler import ContentScheduler
from .config import Config

def setup_root_logger():
    log_file = Config.LOG_DIR / "app.log"
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    # Also output to stdout
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

def main():
    setup_root_logger()
    scheduler = ContentScheduler()
    scheduler.start()

    # Keep the main thread alive
    try:
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Shutdown requested. Exiting.")
        scheduler.scheduler.shutdown()

if __name__ == "__main__":
    main()
