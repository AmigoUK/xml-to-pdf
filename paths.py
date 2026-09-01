"""
paths.py
========
Where to find fonts, configs and the interpreter — from source or from a
PyInstaller bundle.

A frozen build changes two assumptions the rest of the code used to make:
`sys.executable` is the application itself rather than a Python interpreter,
and the source directory no longer exists. Both are handled here so the other
modules stay free of freeze-specific branching.
"""

from __future__ import annotations

import os
import sys

_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))

# System locations that ship DejaVu Sans.
SYSTEM_FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/share/fonts/dejavu",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    r"C:\Windows\Fonts",
]


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    """Directory holding the files bundled with the application.

    One-file builds unpack into a temporary directory exposed as sys._MEIPASS;
    running from source, this is simply the project directory.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return _SOURCE_DIR


def app_dir() -> str:
    """Directory the user sees — next to the executable, or the project dir."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SOURCE_DIR


def font_search_paths(font_dir: str | None = None) -> list[str]:
    """Directories to search for DejaVuSans*.ttf, most specific first.

    An explicit --font-dir wins. Otherwise files sitting next to the executable
    take precedence over the bundled copies, so a user can substitute their own
    fonts without rebuilding.
    """
    if font_dir:
        return [font_dir]

    candidates = [app_dir()]
    if resource_dir() not in candidates:
        candidates.append(resource_dir())
    candidates.extend(SYSTEM_FONT_DIRS)

    seen, ordered = set(), []
    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def config_dirs() -> list[str]:
    """Directories that may hold mapping profiles, most specific first.

    Beside the executable comes first so a user's own profiles win over — and
    can be saved alongside — the ones shipped in the bundle.
    """
    candidates = [os.path.join(app_dir(), "configs")]
    bundled = os.path.join(resource_dir(), "configs")
    if bundled not in candidates:
        candidates.append(bundled)
    return candidates


def writable_config_dir() -> str:
    """Where newly saved profiles go: always next to the executable."""
    return os.path.join(app_dir(), "configs")


def maybe_reexec_in_venv(project_dir: str | None = None, _exec=os.execv) -> None:
    """Re-run the current script under ./.venv if one exists and we are not in it.

    A convenience for source checkouts. It must never fire in a frozen build:
    there sys.executable is the application, so exec'ing an unrelated
    interpreter with the application's argv would simply break it — and a
    .venv directory could well be sitting next to the executable by accident.
    """
    if is_frozen():
        return

    base = project_dir or _SOURCE_DIR
    for relative in (("bin", "python3"), ("Scripts", "python.exe")):
        candidate = os.path.join(base, ".venv", *relative)
        if not os.path.isfile(candidate):
            continue
        if os.path.realpath(sys.executable) == os.path.realpath(candidate):
            return  # already running it — do not loop
        _exec(candidate, [candidate] + sys.argv)
        return
