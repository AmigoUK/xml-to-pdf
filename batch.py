"""
batch.py
========
Batch conversion: collect XML inputs, plan collision-free output names, and
run the queue with progress and stop callbacks. No GUI imports, so the CLI and
the GUI share it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from mapping import HEADER_SLOTS, MappingConfig
from naming import NameAllocator, build_stem, sanitize, validate_pattern
from pdf_renderer import xml_to_pdf
from xml_parser import InvoiceData


# ── Collecting inputs ─────────────────────────────────────────────

def collect_xml_files(paths: list[str]) -> list[str]:
    """Expand files and folders into a de-duplicated, sorted list of XML paths.

    Folders are walked recursively. De-duplication uses the real path so the
    same invoice reached through a symlink or two overlapping selections is
    converted once; the first spelling seen is the one kept.
    """
    found: dict[str, str] = {}

    def add(path: str) -> None:
        found.setdefault(os.path.realpath(path), path)

    for p in paths:
        if os.path.isdir(p):
            for dirpath, _dirs, names in os.walk(p):
                for n in names:
                    if n.lower().endswith(".xml"):
                        add(os.path.join(dirpath, n))
        else:
            add(p)
    return sorted(found.values())


# ── Planning ──────────────────────────────────────────────────────

def header_values(xml_path: str, config: MappingConfig) -> dict[str, str]:
    """Read every mapped header slot, using the XPaths the renderer uses.

    Reading with different XPaths than the renderer would name a file after a
    different element than the one printed on it (invariant 2).
    """
    inv = InvoiceData(xml_path,
                      header_xpath=config.header_xpath,
                      item_xpath=config.item_xpath)
    return {slot: inv.h(config.get(slot))
            for slot in HEADER_SLOTS if config.get(slot)}


@dataclass
class PlannedFile:
    source: str
    filename: str
    stem: str
    warnings: list[str]
    error: str = ""


@dataclass
class BatchPlan:
    output_dir: str
    files: list[PlannedFile]
    allocator: NameAllocator


def plan_batch(xml_paths: list[str], config: MappingConfig, output_dir: str,
               pattern: str | None = None) -> BatchPlan:
    """Decide every output name up front so the GUI can preview them.

    *pattern* ``None`` means the profile's own pattern. An invalid pattern
    raises PatternError before anything is planned. A file whose header cannot
    be read stays in the plan with ``error`` set and an XML-stem name, so it
    fails visibly at run time instead of silently vanishing.
    """
    if pattern is None:
        pattern = config.filename_pattern
    validate_pattern(pattern)

    allocator = NameAllocator(output_dir)
    files: list[PlannedFile] = []
    for source in xml_paths:
        xml_stem = sanitize(os.path.splitext(os.path.basename(source))[0]) or "invoice"
        stem, warnings, error = xml_stem, [], ""
        if pattern:
            try:
                built, warnings = build_stem(pattern, header_values(source, config))
                # A pattern of only forbidden characters sanitises to nothing;
                # falling back keeps the name from ever being ".pdf".
                stem = built or xml_stem
            except Exception as exc:  # unreadable XML must not abort the plan
                error = str(exc)
        files.append(PlannedFile(source, allocator.allocate(stem), stem, warnings, error))
    return BatchPlan(output_dir, files, allocator)


# ── Running ───────────────────────────────────────────────────────

@dataclass
class BatchResult:
    succeeded: list[tuple[str, str]]
    failed: list[tuple[str, str]]
    stopped: bool = False


def run_batch(plan: BatchPlan, config: MappingConfig, *,
              include_barcodes: bool | None = None,
              font_dir: str | None = None,
              on_progress: Callable[[int, int, PlannedFile], None] | None = None,
              should_stop: Callable[[], bool] | None = None,
              on_done: Callable[[int, int, PlannedFile, str | None, str | None], None]
              | None = None) -> BatchResult:
    """Render every planned file; one file's failure never stops the rest.

    *on_done* fires after each file with ``(i, total, item, path, error)``:
    *path* is the PDF actually written (``None`` on failure), *error* the
    reason (``None`` on success). It lets a caller show outcomes live.

    Stopping is checked between files, so the current PDF always finishes.
    """
    os.makedirs(plan.output_dir, exist_ok=True)
    result = BatchResult([], [])
    total = len(plan.files)
    for i, item in enumerate(plan.files, 1):
        if should_stop is not None and should_stop():
            result.stopped = True
            break
        if on_progress is not None:
            on_progress(i, total, item)
        if item.error:
            result.failed.append((item.source, item.error))
            if on_done is not None:
                on_done(i, total, item, None, item.error)
            continue
        try:
            target = os.path.join(plan.output_dir, item.filename)
            if os.path.exists(target):
                # Something appeared since planning. reportlab writes by path,
                # so there is no exclusive-open; re-checking here is the guard.
                target = os.path.join(plan.output_dir, plan.allocator.allocate(item.stem))
            xml_to_pdf(item.source, target, include_barcodes=include_barcodes,
                       font_dir=font_dir, mapping_config=config)
            result.succeeded.append((item.source, target))
        except Exception as exc:
            result.failed.append((item.source, str(exc)))
            if on_done is not None:
                on_done(i, total, item, None, str(exc))
        else:
            if on_done is not None:
                on_done(i, total, item, target, None)
    return result
