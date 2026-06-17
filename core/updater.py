"""
In-app auto-updater.

Checks a release feed for a newer version, and (on request) downloads the new
build, swaps the installed app in place, and relaunches it.

ALL saved data survives an update: login (connection.json), config, the SQLite
database, and logs live in the user-data dir, OUTSIDE the app bundle — updating
only replaces the bundle, never the data.

Feed sources (configured in config.yaml -> update):
  * repo: "owner/repo"   -> reads the GitHub Releases "latest" API and picks the
                            asset for this OS (zip produced by the CI workflow).
  * feed_url: "https://…/latest.json"  -> a manifest:
        {"version":"1.1.0","notes":"…",
         "mac":{"url":"…zip","sha256":"…"},
         "windows":{"url":"…zip","sha256":"…"}}
A local file path or file:// URL is also accepted (used for testing).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .version import VERSION

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

import json


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str = ""


def parse_version(v: str) -> tuple:
    v = (v or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    out = []
    for part in v.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def platform_key() -> str:
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


class Updater:
    def __init__(self, settings: dict):
        self.enabled = bool(settings.get("enabled", True))
        self.repo = settings.get("repo", "") or ""
        self.feed_url = settings.get("feed_url", "") or ""
        self.current = VERSION
        self.latest: Optional[UpdateInfo] = None
        self.checking = False
        self.last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self.repo or self.feed_url)

    @property
    def available(self) -> bool:
        return self.latest is not None and is_newer(self.latest.version, self.current)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "current": self.current,
            "checking": self.checking,
            "available": self.available,
            "latest_version": self.latest.version if self.latest else None,
            "notes": self.latest.notes if self.latest else "",
            "error": self.last_error,
        }

    # --- fetching ---------------------------------------------------------
    async def _fetch_json(self, url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme in ("", "file"):
            path = parsed.path if parsed.scheme == "file" else url
            return json.loads(Path(path).read_text())
        if aiohttp is None:
            raise RuntimeError("aiohttp required for update checks")
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"Accept": "application/json",
                                           "User-Agent": "futures-bot-updater"}) as r:
                r.raise_for_status()
                return await r.json(content_type=None)

    async def check(self) -> Optional[UpdateInfo]:
        if not (self.enabled and self.configured):
            return None
        self.checking = True
        self.last_error = ""
        try:
            if self.repo:
                url = f"https://api.github.com/repos/{self.repo}/releases/latest"
                data = await self._fetch_json(url)
                info = self._from_github(data)
            else:
                data = await self._fetch_json(self.feed_url)
                info = self._from_manifest(data)
            if info and info.url and is_newer(info.version, self.current):
                self.latest = info
                return info
            return None
        except Exception as e:
            self.last_error = str(e)
            return None
        finally:
            self.checking = False

    def _from_github(self, data: dict) -> Optional[UpdateInfo]:
        version = data.get("tag_name") or data.get("name") or ""
        notes = data.get("body", "") or ""
        want = platform_key()
        marker = {"mac": ("macos", "mac", "darwin"),
                  "windows": ("windows", "win"),
                  "linux": ("linux",)}[want]
        for asset in data.get("assets", []):
            name = (asset.get("name") or "").lower()
            if name.endswith(".zip") and any(m in name for m in marker):
                return UpdateInfo(version, notes, asset.get("browser_download_url", ""))
        return None

    def _from_manifest(self, data: dict) -> Optional[UpdateInfo]:
        version = data.get("version", "")
        notes = data.get("notes", "")
        plat = data.get(platform_key(), {}) or {}
        return UpdateInfo(version, notes, plat.get("url", ""), plat.get("sha256", ""))

    # --- download + stage -------------------------------------------------
    async def download(self, info: UpdateInfo) -> Path:
        staging = Path(tempfile.mkdtemp(prefix="futuresbot-update-"))
        zip_path = staging / "update.zip"
        parsed = urlparse(info.url)
        if parsed.scheme in ("", "file"):
            data = Path(parsed.path if parsed.scheme == "file" else info.url).read_bytes()
        else:
            if aiohttp is None:
                raise RuntimeError("aiohttp required to download updates")
            async with aiohttp.ClientSession() as s:
                async with s.get(info.url) as r:
                    r.raise_for_status()
                    data = await r.read()
        if info.sha256:
            digest = hashlib.sha256(data).hexdigest()
            if digest.lower() != info.sha256.lower():
                raise RuntimeError("update checksum mismatch — aborting")
        zip_path.write_bytes(data)
        extracted = staging / "extracted"
        extracted.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            # ditto preserves the code signature and framework symlinks inside the
            # .app; plain unzip corrupts both and the app won't launch.
            subprocess.run(["ditto", "-x", "-k", str(zip_path), str(extracted)], check=True)
        else:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extracted)
        return extracted

    # --- locating the running install ------------------------------------
    @staticmethod
    def current_bundle() -> Optional[Path]:
        exe = Path(sys.executable)
        if sys.platform == "darwin":
            for p in exe.parents:
                if p.suffix == ".app":
                    return p
        elif sys.platform.startswith("win"):
            return exe.parent          # onedir folder
        return None

    @staticmethod
    def _find_new_app(extracted: Path) -> Optional[Path]:
        if sys.platform == "darwin":
            apps = list(extracted.rglob("*.app"))
            return apps[0] if apps else None
        if sys.platform.startswith("win"):
            exes = list(extracted.rglob("*.exe"))
            return exes[0].parent if exes else extracted
        return extracted

    # --- swap + relaunch --------------------------------------------------
    def build_swap_script(self, new_path: Path) -> Optional[Path]:
        """Write (don't run) the script that swaps the app once we exit."""
        dest = self.current_bundle()
        if dest is None:
            raise RuntimeError("not running from a packaged app — cannot self-update")
        pid = os.getpid()
        if sys.platform == "darwin":
            script = (
                "#!/bin/bash\n"
                f'while kill -0 {pid} 2>/dev/null; do sleep 0.4; done\n'
                f'ditto "{new_path}" "{dest}.new" || exit 1\n'
                f'rm -rf "{dest}"\n'
                f'mv "{dest}.new" "{dest}"\n'
                # Clear download/quarantine/provenance attrs and re-sign ad-hoc so
                # Apple Silicon will launch it (an invalid signature = won't open).
                f'xattr -dr com.apple.provenance "{dest}" 2>/dev/null\n'
                f'xattr -rd com.apple.quarantine "{dest}" 2>/dev/null\n'
                f'xattr -cr "{dest}" 2>/dev/null\n'
                f'codesign --force --deep -s - "{dest}" 2>/dev/null\n'
                f'open "{dest}"\n'
            )
            sh = Path(tempfile.gettempdir()) / "futuresbot_update.sh"
            sh.write_text(script)
            sh.chmod(0o755)
            return sh
        if sys.platform.startswith("win"):
            exe = Path(sys.executable)
            bat = (
                "@echo off\r\n"
                f":wait\r\n"
                f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                f'robocopy "{new_path}" "{dest}" /MIR /NFL /NDL /NJH /NJS >nul\r\n'
                f'start "" "{exe}"\r\n'
            )
            b = Path(tempfile.gettempdir()) / "futuresbot_update.bat"
            b.write_text(bat)
            return b
        return None

    def spawn_swap(self, new_path: Path) -> None:
        script = self.build_swap_script(new_path)
        if script is None:
            raise RuntimeError("self-update not supported on this platform")
        if sys.platform == "darwin":
            subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
        else:
            subprocess.Popen(["cmd", "/c", str(script)],
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
