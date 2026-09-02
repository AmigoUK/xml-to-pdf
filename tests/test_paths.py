"""Path resolution has to work both from source and from a frozen bundle."""

import os
import sys

import paths


class _Frozen:
    """Context manager faking a PyInstaller one-file bundle."""

    def __init__(self, meipass, executable):
        self.meipass = meipass
        self.executable = executable

    def __enter__(self):
        self._saved_exe = sys.executable
        sys.frozen = True
        sys._MEIPASS = self.meipass
        sys.executable = self.executable

    def __exit__(self, *exc):
        del sys.frozen
        del sys._MEIPASS
        sys.executable = self._saved_exe


def test_not_frozen_by_default():
    assert paths.is_frozen() is False


def test_resource_dir_is_the_project_dir_when_running_from_source():
    assert os.path.isfile(os.path.join(paths.resource_dir(), "xml_invoice_to_pdf.py"))


def test_app_dir_is_the_project_dir_when_running_from_source():
    assert os.path.isfile(os.path.join(paths.app_dir(), "xml_invoice_to_pdf.py"))


def test_resource_dir_points_at_the_bundle_when_frozen(tmp_path):
    bundle = tmp_path / "_MEI123"
    bundle.mkdir()
    exe = tmp_path / "dist" / "xml-to-pdf.exe"
    exe.parent.mkdir()

    with _Frozen(str(bundle), str(exe)):
        assert paths.is_frozen() is True
        assert paths.resource_dir() == str(bundle)


def test_app_dir_points_next_to_the_executable_when_frozen(tmp_path):
    bundle = tmp_path / "_MEI123"
    bundle.mkdir()
    exe = tmp_path / "dist" / "xml-to-pdf.exe"
    exe.parent.mkdir()

    with _Frozen(str(bundle), str(exe)):
        assert paths.app_dir() == str(exe.parent)


def test_frozen_font_search_prefers_files_next_to_the_executable(tmp_path):
    """A user dropping fonts beside the exe must override the bundled ones."""
    bundle = tmp_path / "_MEI123"
    bundle.mkdir()
    exe = tmp_path / "dist" / "xml-to-pdf.exe"
    exe.parent.mkdir()

    with _Frozen(str(bundle), str(exe)):
        search = paths.font_search_paths()

    assert search.index(str(exe.parent)) < search.index(str(bundle))


def test_font_search_still_covers_the_system_directories():
    search = paths.font_search_paths()
    assert "/usr/share/fonts/truetype/dejavu" in search


def test_config_dirs_include_the_bundle_and_the_executable_directory(tmp_path):
    bundle = tmp_path / "_MEI123"
    (bundle / "configs").mkdir(parents=True)
    exe = tmp_path / "dist" / "xml-to-pdf.exe"
    exe.parent.mkdir()
    (exe.parent / "configs").mkdir()

    with _Frozen(str(bundle), str(exe)):
        dirs = paths.config_dirs()

    assert str(exe.parent / "configs") in dirs
    assert str(bundle / "configs") in dirs


# ── the venv auto-relaunch ───────────────────────────────────

def test_venv_relaunch_is_skipped_when_frozen(tmp_path):
    """In a bundle sys.executable is the exe; re-exec'ing a stray .venv would break it."""
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python.chmod(0o755)

    calls = []
    exe = tmp_path / "dist" / "xml-to-pdf.exe"
    exe.parent.mkdir()

    with _Frozen(str(tmp_path / "_MEI"), str(exe)):
        paths.maybe_reexec_in_venv(str(tmp_path), _exec=lambda *a: calls.append(a))

    assert calls == []


def test_venv_relaunch_happens_from_source_when_a_venv_exists(tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python.chmod(0o755)

    calls = []
    paths.maybe_reexec_in_venv(str(tmp_path), _exec=lambda *a: calls.append(a))

    assert len(calls) == 1
    assert calls[0][0] == str(venv_python)


def test_no_relaunch_when_there_is_no_venv(tmp_path):
    calls = []
    paths.maybe_reexec_in_venv(str(tmp_path), _exec=lambda *a: calls.append(a))
    assert calls == []


def test_no_relaunch_when_already_running_that_interpreter(tmp_path):
    """Guards against an exec loop."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python3"
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python.chmod(0o755)

    calls = []
    saved = sys.executable
    try:
        sys.executable = str(venv_python)
        paths.maybe_reexec_in_venv(str(tmp_path), _exec=lambda *a: calls.append(a))
    finally:
        sys.executable = saved

    assert calls == []


def test_a_fonts_subdirectory_is_searched(tmp_path, monkeypatch):
    """`python scripts/fetch_fonts.py fonts` must be enough — no --font-dir flag.

    macOS and Windows have no system DejaVu, so anyone running from source has
    to fetch it. Searching ./fonts means they fetch once and forget.
    """
    monkeypatch.setattr(paths, "_SOURCE_DIR", str(tmp_path))
    search = paths.font_search_paths()
    assert os.path.join(str(tmp_path), "fonts") in search


def test_the_fonts_subdirectory_outranks_the_system_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_SOURCE_DIR", str(tmp_path))
    search = paths.font_search_paths()
    assert search.index(os.path.join(str(tmp_path), "fonts")) < search.index(
        "/usr/share/fonts/truetype/dejavu")


def test_an_explicit_font_dir_still_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_SOURCE_DIR", str(tmp_path))
    assert paths.font_search_paths("/somewhere/else") == ["/somewhere/else"]
