#!/usr/bin/env python3
"""
Download the DejaVu Sans faces the renderer needs into ./fonts.

Used before a PyInstaller build: Windows has no system DejaVu, so the two
required faces travel inside the executable. Kept out of git (the repo ignores
*.ttf) so the fonts are fetched at build time rather than vendored.

    python scripts/fetch_fonts.py [target_dir]

Falls back to copying from the local system when a download is not possible.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import urllib.request
import zipfile

DEJAVU_VERSION = "2.37"
DEJAVU_URL = (
    "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
    f"version_{DEJAVU_VERSION.replace('.', '_')}/dejavu-fonts-ttf-{DEJAVU_VERSION}.zip"
)

WANTED = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
LICENSE_MEMBER = "LICENSE"

SYSTEM_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    r"C:\Windows\Fonts",
]


def _from_download(target: str) -> bool:
    try:
        with urllib.request.urlopen(DEJAVU_URL, timeout=60) as response:
            payload = response.read()
    except Exception as exc:  # offline, or GitHub unreachable
        print(f"Download failed ({exc}); trying the local system instead.")
        return False

    written = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.namelist():
            base = os.path.basename(member)
            if base in WANTED:
                with archive.open(member) as src, \
                        open(os.path.join(target, base), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                written += 1
            elif base == LICENSE_MEMBER:
                with archive.open(member) as src, \
                        open(os.path.join(target, "LICENSE-DejaVu.txt"), "wb") as dst:
                    shutil.copyfileobj(src, dst)

    if written == len(WANTED):
        print(f"Fetched DejaVu {DEJAVU_VERSION} into {target}")
        return True
    print(f"Archive did not contain all of {WANTED}")
    return False


def _from_system(target: str) -> bool:
    found = 0
    for name in WANTED:
        for directory in SYSTEM_DIRS:
            source = os.path.join(directory, name)
            if os.path.isfile(source):
                shutil.copy(source, os.path.join(target, name))
                found += 1
                break
    if found == len(WANTED):
        print(f"Copied DejaVu from the local system into {target}")
        return True
    print(f"Only found {found}/{len(WANTED)} faces on this system")
    return False


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "fonts"
    os.makedirs(target, exist_ok=True)

    if _from_download(target) or _from_system(target):
        return 0

    print("Could not obtain DejaVuSans.ttf and DejaVuSans-Bold.ttf.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
