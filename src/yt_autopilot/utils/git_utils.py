\
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def git_config_user(name: str = "yt-autopilot-bot", email: str = "actions@users.noreply.github.com") -> None:
    subprocess.run(["git", "config", "user.name", name], check=False)
    subprocess.run(["git", "config", "user.email", email], check=False)


def git_commit_push(message: str, paths: Optional[list] = None) -> None:
    try:
        paths = paths or []
        if paths:
            subprocess.run(["git", "add", *paths], check=True)
        else:
            subprocess.run(["git", "add", "-A"], check=True)

        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        if not st.stdout.strip():
            logger.info("No changes to commit")
            return

        subprocess.run(["git", "commit", "-m", message], check=True)

        # push with GitHub Actions token (already configured in checkout)
        subprocess.run(["git", "push"], check=True)
        logger.info("Changes committed and pushed")
    except Exception as e:
        logger.warning("git commit/push failed: %s", e)
