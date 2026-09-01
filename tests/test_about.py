"""The credit footer's content: segments, order, links, version."""

import re
import shutil
import subprocess

import pytest

from __about__ import (
    AUTHOR, CONTACT_EMAIL, REPO_URL, WEBSITE, __version__, footer_segments,
    footer_text,
)


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_segments_are_in_the_documented_order():
    labels = [label for label, _ in footer_segments()]
    assert labels == [
        CONTACT_EMAIL,
        f"Project & Development: {AUTHOR}",
        "www.attv.uk",
        "GitHub",
        f"v{__version__}",
    ]


def test_the_email_segment_links_to_mailto():
    segments = dict(footer_segments())
    assert segments[CONTACT_EMAIL] == f"mailto:{CONTACT_EMAIL}"


def test_the_credit_segment_is_plain_text():
    segments = dict(footer_segments())
    assert segments[f"Project & Development: {AUTHOR}"] is None


def test_the_website_segment_links_to_the_site():
    segments = dict(footer_segments())
    assert segments["www.attv.uk"] == WEBSITE
    assert WEBSITE.startswith("https://")


def test_the_github_segment_links_to_this_repository():
    segments = dict(footer_segments())
    assert segments["GitHub"] == REPO_URL


def test_the_version_segment_is_plain_text():
    segments = dict(footer_segments())
    assert segments[f"v{__version__}"] is None


def test_footer_text_joins_segments_with_middle_dots():
    text = footer_text()
    assert " · " in text
    assert text.startswith(CONTACT_EMAIL)
    assert text.endswith(f"v{__version__}")
    assert "Tomasz" in text


def test_repo_url_matches_the_actual_git_remote():
    """The GitHub link must point at this project, not a copied-over URL."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    result = subprocess.run(["git", "remote", "get-url", "origin"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("no git remote configured")

    remote = result.stdout.strip()
    # git@github.com:owner/repo.git -> https://github.com/owner/repo
    remote = re.sub(r"^git@github\.com:", "https://github.com/", remote)
    remote = re.sub(r"\.git$", "", remote)
    assert REPO_URL == remote


def test_repo_url_has_no_trailing_slash_or_git_suffix():
    assert not REPO_URL.endswith("/")
    assert not REPO_URL.endswith(".git")
