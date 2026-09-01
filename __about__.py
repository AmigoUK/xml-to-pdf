"""Project identity: version and the credit footer shown in the UI."""

__version__ = "0.5.1"

AUTHOR = "Tomasz 'Amigo' Lewandowski"
CONTACT_EMAIL = "dev@attv.uk"
WEBSITE = "https://www.attv.uk"

# Resolved from `git remote get-url origin`, with the git@ form converted to
# https. A test asserts it still matches the checkout's actual remote; it is a
# constant because a frozen build has neither git nor the repository.
REPO_URL = "https://github.com/AmigoUK/xml-to-pdf"

SEPARATOR = " · "


def footer_segments() -> list[tuple[str, str | None]]:
    """The credit footer as (label, url) pairs; url is None for plain text."""
    return [
        (CONTACT_EMAIL, f"mailto:{CONTACT_EMAIL}"),
        (f"Project & Development: {AUTHOR}", None),
        ("www.attv.uk", WEBSITE),
        ("GitHub", REPO_URL),
        (f"v{__version__}", None),
    ]


def footer_text() -> str:
    """The footer as one line, for surfaces that cannot render links."""
    return SEPARATOR.join(label for label, _ in footer_segments())
