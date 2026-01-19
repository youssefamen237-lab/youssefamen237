from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from yt_auto.utils import ensure_dir


@dataclass(frozen=True)
class ArtifactHit:
    name: str
    archive_download_url: str


def _github_api_get(url: str, token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(url, headers=headers, timeout=45)
    r.raise_for_status()
    return r.json()


def list_artifacts(owner_repo: str, token: str, per_page: int = 100, max_pages: int = 10) -> list[ArtifactHit]:
    owner, repo = owner_repo.split("/", 1)
    hits: list[ArtifactHit] = []
    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/artifacts?per_page={per_page}&page={page}"
        data = _github_api_get(url, token)
        arts = data.get("artifacts") or []
        for a in arts:
            name = str((a or {}).get("name", "")).strip()
            dl = str((a or {}).get("archive_download_url", "")).strip()
            expired = bool((a or {}).get("expired", False))
            if name and dl and not expired:
                hits.append(ArtifactHit(name=name, archive_download_url=dl))
        if len(arts) < per_page:
            break
    return hits


def download_artifact_zip(archive_download_url: str, token: str) -> bytes:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(archive_download_url, headers=headers, timeout=90)
    r.raise_for_status()
    return r.content


def download_shorts_for_date(cfg_out_dir: Path, date_yyyymmdd: str, token: str, owner_repo: str) -> list[Path]:
    ensure_dir(cfg_out_dir)
    wanted = {
        f"short-{date_yyyymmdd}-slot1",
        f"short-{date_yyyymmdd}-slot2",
        f"short-{date_yyyymmdd}-slot3",
        f"short-{date_yyyymmdd}-slot4",
    }

    arts = list_artifacts(owner_repo, token)
    by_name = {a.name: a for a in arts if a.name in wanted}

    out_files: list[Path] = []
    for name in sorted(wanted):
        hit = by_name.get(name)
        if not hit:
            continue
        zbytes = download_artifact_zip(hit.archive_download_url, token)
        z = zipfile.ZipFile(io.BytesIO(zbytes))
        mp4_members = [m for m in z.namelist() if m.lower().endswith(".mp4")]
        if not mp4_members:
            continue
        member = mp4_members[0]
        out_path = cfg_out_dir / f"{name}.mp4"
        out_path.write_bytes(z.read(member))
        out_files.append(out_path)

    return out_files
