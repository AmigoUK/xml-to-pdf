#!/usr/bin/env python3
"""
gui.py
======
CustomTkinter GUI for XML-to-PDF field mapping and generation.
"""

from __future__ import annotations

import os
import sys

from __about__ import SEPARATOR, footer_segments
from paths import config_dirs, maybe_reexec_in_venv, writable_config_dir

maybe_reexec_in_venv()

import tempfile
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

from xml_parser import InvoiceData, DiscoveredSchema, discover_fields
from mapping import (
    MappingConfig, SLOT_CATEGORIES, HEADER_SLOTS, ITEM_SLOTS,
    DEFAULT_MAPPINGS, save_config, load_config, auto_match_fields, resolve_xpaths,
)
from pdf_renderer import xml_to_pdf
from batch import collect_xml_files, header_values, plan_batch, run_batch
from naming import NAME_FIELDS, PatternError, build_stem, validate_pattern
from preview import HAS_PYMUPDF, HAS_PIL, render_pdf_page, get_page_count, open_in_viewer

# Where new profiles are saved; config_dirs() is what gets listed.
CONFIGS_DIR = writable_config_dir()
NONE_TAG = "(none)"
HEADER_SEPARATOR = "── Header ──"
ITEM_SEPARATOR = "── Item ──"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("XML to PDF — Field Mapping")
        self.geometry("920x720")
        self.minsize(800, 600)

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.xml_path: str | None = None
        self.discovered: dict[str, list[str]] = {"header": [], "item": []}
        self.discovered_schema: DiscoveredSchema | None = None
        self.loaded_config: MappingConfig | None = None
        self.slot_vars: dict[str, ctk.StringVar] = {}
        self.slot_labels: dict[str, ctk.CTkLabel] = {}
        self.match_reasons: dict[str, str] = {}
        self.preview_pdf_path: str | None = None
        self.preview_page = 0
        self.preview_page_count = 0
        self._temp_files: list[str] = []
        self._preview_temp: str | None = None

        # Created before the tabs: the Batch tab binds an entry to it, and
        # _build_config() reads it whichever tab the user is on.
        self.pattern_var = ctk.StringVar(value="")
        self.batch_inputs: list[str] = []
        self.batch_plan = None
        self._batch_stop_event = threading.Event()
        self._batch_running = False
        self._close_requested = False

        self._build_top_bar()
        self._build_tabs()
        self._build_bottom_bar()
        self._build_footer()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ── Top bar ─────────────────────────────────────────

    def _build_top_bar(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=(10, 0))

        ctk.CTkLabel(frame, text="XML File:").pack(side="left")
        self.xml_label = ctk.CTkLabel(frame, text="No file loaded", text_color="gray")
        self.xml_label.pack(side="left", padx=(6, 12))
        ctk.CTkButton(frame, text="Open XML...", width=110, command=self._open_xml).pack(side="left")

        # Config profile
        ctk.CTkLabel(frame, text="Config:").pack(side="left", padx=(20, 0))
        self.config_var = ctk.StringVar(value="Default")
        self.config_menu = ctk.CTkOptionMenu(frame, variable=self.config_var,
                                             values=self._list_configs(),
                                             command=self._on_config_selected)
        self.config_menu.pack(side="left", padx=6)

    def _list_configs(self) -> list[str]:
        """List profiles from every config directory, nearest first, deduplicated."""
        configs = ["Default"]
        for directory in config_dirs():
            if not os.path.isdir(directory):
                continue
            for f in sorted(os.listdir(directory)):
                if f.endswith(".json") and f[:-5] not in configs:
                    configs.append(f[:-5])
        return configs

    def _find_config(self, name: str) -> str | None:
        """Resolve a profile name to a file, preferring the nearest directory."""
        for directory in config_dirs():
            path = os.path.join(directory, f"{name}.json")
            if os.path.isfile(path):
                return path
        return None

    def _refresh_config_menu(self):
        values = self._list_configs()
        self.config_menu.configure(values=values)

    # ── Tabs ────────────────────────────────────────────

    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=8)

        self.tab_mapping = self.tabview.add("Field Mapping")
        self.tab_options = self.tabview.add("Options")
        self.tab_preview = self.tabview.add("Preview")
        self.tab_batch = self.tabview.add("Batch")

        self._build_mapping_tab()
        self._build_options_tab()
        self._build_preview_tab()
        self._build_batch_tab()

    # ── Field Mapping tab ───────────────────────────────

    def _build_mapping_tab(self):
        container = ctk.CTkFrame(self.tab_mapping, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # Left panel: discovered XML fields (read-only)
        left_frame = ctk.CTkFrame(container)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ctk.CTkLabel(left_frame, text="Discovered XML Fields", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 4))
        self.fields_textbox = ctk.CTkTextbox(left_frame, state="disabled", font=ctk.CTkFont(family="Courier", size=12))
        self.fields_textbox.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Right panel: slot mappings
        right_frame = ctk.CTkFrame(container)
        right_frame.pack(side="right", fill="both", expand=True, padx=(6, 0))

        ctk.CTkLabel(right_frame, text="PDF Slot Mappings", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 4))
        self.mapping_scroll = ctk.CTkScrollableFrame(right_frame)
        self.mapping_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._populate_slot_dropdowns()

    def _populate_slot_dropdowns(self):
        for widget in self.mapping_scroll.winfo_children():
            widget.destroy()
        self.slot_vars.clear()
        self.slot_labels.clear()

        options = self._grouped_tag_options()

        for category, slots in SLOT_CATEGORIES.items():
            cat_label = ctk.CTkLabel(self.mapping_scroll, text=category,
                                     font=ctk.CTkFont(weight="bold", size=13))
            cat_label.pack(anchor="w", pady=(10, 2), padx=4)

            for slot in slots:
                row = ctk.CTkFrame(self.mapping_scroll, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=1)

                display_name = slot.replace("_", " ").title()
                label = ctk.CTkLabel(row, text=display_name, width=160, anchor="w")
                label.pack(side="left")
                self.slot_labels[slot] = label

                var = ctk.StringVar(value=DEFAULT_MAPPINGS.get(slot, NONE_TAG))
                self.slot_vars[slot] = var

                menu = ctk.CTkOptionMenu(row, variable=var, values=options, width=200)
                menu.pack(side="left", padx=(4, 0))

    def _grouped_tag_options(self) -> list[str]:
        """Return dropdown options grouped by section: header tags then item tags."""
        header_tags = self.discovered.get("header", [])
        item_tags = self.discovered.get("item", [])

        if not header_tags and not item_tags:
            # No XML loaded — use default tag names
            return [NONE_TAG] + sorted(set(DEFAULT_MAPPINGS.values()))

        options = [NONE_TAG]
        if header_tags:
            options.append(HEADER_SEPARATOR)
            options.extend(sorted(header_tags))
        if item_tags:
            options.append(ITEM_SEPARATOR)
            options.extend(sorted(item_tags))
        return options

    def _all_tags(self) -> list[str]:
        """Return all unique discovered XML tags, or default tags if no XML loaded."""
        tags = set()
        for group in self.discovered.values():
            tags.update(group)
        if not tags:
            tags = set(DEFAULT_MAPPINGS.values())
        return sorted(tags)

    def _update_fields_display(self):
        self.fields_textbox.configure(state="normal")
        self.fields_textbox.delete("1.0", "end")

        if not self.discovered["header"] and not self.discovered["item"]:
            self.fields_textbox.insert("end", "Load an XML file to discover fields.")
        else:
            schema = self.discovered_schema
            sample_values = schema.sample_values if schema else {}

            # Structure info
            if schema:
                self.fields_textbox.insert("end", "=== Structure ===\n")
                self.fields_textbox.insert("end", f"  Header: {schema.header_xpath}\n")
                self.fields_textbox.insert("end", f"  Items:  {schema.item_xpath} ({schema.item_count} items found)\n")
                self.fields_textbox.insert("end", "\n")

            # Header fields
            header_tags = self.discovered["header"]
            self.fields_textbox.insert("end", f"=== Header Fields ({len(header_tags)} tags) ===\n")
            for tag in header_tags:
                val = sample_values.get(tag, "")
                if val:
                    # Truncate long values for display
                    display_val = val[:40] + "..." if len(val) > 40 else val
                    self.fields_textbox.insert("end", f'  {tag} = "{display_val}"\n')
                else:
                    self.fields_textbox.insert("end", f"  {tag}\n")

            # Item fields
            item_tags = self.discovered["item"]
            self.fields_textbox.insert("end", f"\n=== Item Fields ({len(item_tags)} tags) ===\n")
            for tag in item_tags:
                val = sample_values.get(tag, "")
                if val:
                    display_val = val[:40] + "..." if len(val) > 40 else val
                    self.fields_textbox.insert("end", f'  {tag} = "{display_val}"\n')
                else:
                    self.fields_textbox.insert("end", f"  {tag}\n")

        self.fields_textbox.configure(state="disabled")

    def _apply_auto_match(self, matched: dict[str, str], reasons: dict[str, str]):
        """Apply auto-matched mappings and color-code labels."""
        self.match_reasons = reasons
        all_tags = set()
        for group in self.discovered.values():
            all_tags.update(group)

        matched_count = 0
        total_count = len(self.slot_vars)

        for slot, var in self.slot_vars.items():
            label = self.slot_labels.get(slot)
            if slot in matched:
                var.set(matched[slot])
                matched_count += 1
                if label:
                    label.configure(text_color="#2E8B57")  # green
            else:
                var.set(NONE_TAG)
                if label:
                    label.configure(text_color="#CC7722")  # orange

        unmatched = total_count - matched_count
        self.status_label.configure(
            text=f"Auto-matched {matched_count}/{total_count} fields. {unmatched} unmatched."
        )

    # ── Options tab ─────────────────────────────────────

    def _build_options_tab(self):
        frame = ctk.CTkFrame(self.tab_options, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Barcodes toggle
        self.barcodes_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(frame, text="Include barcode pages", variable=self.barcodes_var).pack(anchor="w", pady=8)

        # Font directory
        font_frame = ctk.CTkFrame(frame, fg_color="transparent")
        font_frame.pack(fill="x", pady=8)
        ctk.CTkLabel(font_frame, text="Font directory:").pack(side="left")
        self.font_dir_var = ctk.StringVar(value="")
        ctk.CTkEntry(font_frame, textvariable=self.font_dir_var, width=350).pack(side="left", padx=6)
        ctk.CTkButton(font_frame, text="Browse...", width=80, command=self._browse_font_dir).pack(side="left")

        # Theme
        theme_frame = ctk.CTkFrame(frame, fg_color="transparent")
        theme_frame.pack(fill="x", pady=8)
        ctk.CTkLabel(theme_frame, text="Theme:").pack(side="left")
        self.theme_var = ctk.StringVar(value="System")
        ctk.CTkOptionMenu(theme_frame, variable=self.theme_var,
                          values=["System", "Dark", "Light"],
                          command=self._on_theme_changed).pack(side="left", padx=6)

    def _browse_font_dir(self):
        d = filedialog.askdirectory(title="Select font directory")
        if d:
            self.font_dir_var.set(d)

    def _on_theme_changed(self, value: str):
        ctk.set_appearance_mode(value)

    # ── Preview tab ─────────────────────────────────────

    def _build_preview_tab(self):
        self.preview_frame = ctk.CTkFrame(self.tab_preview, fg_color="transparent")
        self.preview_frame.pack(fill="both", expand=True)

        # Navigation bar
        nav = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        nav.pack(fill="x", padx=8, pady=4)

        self.btn_prev_page = ctk.CTkButton(nav, text="< Prev", width=70, command=self._prev_page)
        self.btn_prev_page.pack(side="left")

        self.page_label = ctk.CTkLabel(nav, text="No preview")
        self.page_label.pack(side="left", padx=12)

        self.btn_next_page = ctk.CTkButton(nav, text="Next >", width=70, command=self._next_page)
        self.btn_next_page.pack(side="left")

        ctk.CTkButton(nav, text="Refresh Preview", width=120, command=self._refresh_preview).pack(side="left", padx=20)

        ctk.CTkButton(nav, text="Open in Viewer", width=120,
                      command=self._open_in_viewer).pack(side="right")

        # Image area
        self.preview_label = ctk.CTkLabel(self.preview_frame, text="Generate a PDF to see preview here.")
        self.preview_label.pack(fill="both", expand=True)

    def _prev_page(self):
        if self.preview_page > 0:
            self.preview_page -= 1
            self._show_preview_page()

    def _next_page(self):
        if self.preview_page < self.preview_page_count - 1:
            self.preview_page += 1
            self._show_preview_page()

    def _refresh_preview(self):
        if self.preview_pdf_path and os.path.isfile(self.preview_pdf_path):
            self.preview_page = 0
            self.preview_page_count = get_page_count(self.preview_pdf_path) if HAS_PYMUPDF else 0
            self._show_preview_page()

    def _show_preview_page(self):
        if not HAS_PYMUPDF or not HAS_PIL:
            missing = "PyMuPDF" if not HAS_PYMUPDF else "Pillow"
            self.page_label.configure(
                text=f"{missing} not installed — use 'Open in Viewer'")
            return

        if not self.preview_pdf_path or not os.path.isfile(self.preview_pdf_path):
            self.page_label.configure(text="No preview")
            return

        img = render_pdf_page(self.preview_pdf_path, self.preview_page, dpi=120)
        if img is None:
            return

        # Fit to available space
        max_h = self.preview_frame.winfo_height() - 50
        max_w = self.preview_frame.winfo_width() - 20
        if max_h < 100:
            max_h = 600
        if max_w < 100:
            max_w = 500

        ratio = min(max_w / img.width, max_h / img.height, 1.0)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        img = img.resize((new_w, new_h))

        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(new_w, new_h))
        self.preview_label.configure(image=ctk_img, text="")
        self.preview_label._ctk_image = ctk_img  # prevent GC

        self.page_label.configure(text=f"Page {self.preview_page + 1} / {self.preview_page_count}")

    def _open_in_viewer(self):
        if self.preview_pdf_path and os.path.isfile(self.preview_pdf_path):
            open_in_viewer(self.preview_pdf_path)
        else:
            messagebox.showinfo("Preview", "No PDF generated yet.")

    # ── Batch tab ───────────────────────────────────────

    BATCH_FIELD_COLUMNS = 5

    def _build_batch_tab(self):
        frame = ctk.CTkFrame(self.tab_batch, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        small = ctk.CTkFont(size=11)

        # Inputs
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        # Everything that changes what the batch is. Locked while a run is in
        # progress: choosing new inputs mid-run used to relabel the old run's
        # results with the new folder's file count.
        self._batch_input_widgets: list = []
        btn = ctk.CTkButton(row, text="Choose Folder…", width=120,
                            command=self._choose_batch_folder)
        btn.pack(side="left")
        self._batch_input_widgets.append(btn)
        btn = ctk.CTkButton(row, text="Choose Files…", width=120,
                            command=self._choose_batch_files)
        btn.pack(side="left", padx=6)
        self._batch_input_widgets.append(btn)
        self.batch_count_label = ctk.CTkLabel(row, text="No files chosen", text_color="gray")
        self.batch_count_label.pack(side="left", padx=6)

        # Output folder
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(row, text="Output folder:", width=100, anchor="w").pack(side="left")
        self.batch_output_var = ctk.StringVar(value="")
        entry = ctk.CTkEntry(row, textvariable=self.batch_output_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        btn = ctk.CTkButton(row, text="Browse…", width=80,
                            command=self._browse_batch_output)
        btn.pack(side="left")
        self._batch_input_widgets += [entry, btn]

        # Name pattern
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(row, text="Name pattern:", width=100, anchor="w").pack(side="left")
        self.pattern_entry = ctk.CTkEntry(row, textvariable=self.pattern_var)
        self.pattern_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._batch_input_widgets.append(self.pattern_entry)
        self.pattern_error_label = ctk.CTkLabel(frame, text="", text_color="#D9534F",
                                                font=small, height=16, anchor="w")
        self.pattern_error_label.pack(fill="x", padx=(106, 0))

        # One button per field, so a field name never has to be typed (and so
        # cannot be mistyped into a PatternError).
        fields = ctk.CTkFrame(frame, fg_color="transparent")
        fields.pack(fill="x", padx=(106, 0))
        for index, name in enumerate(NAME_FIELDS):
            col = index % self.BATCH_FIELD_COLUMNS
            fields.grid_columnconfigure(col, weight=1, uniform="field")
            btn = ctk.CTkButton(fields, text=name, height=22, font=small,
                                fg_color=("gray78", "gray28"),
                                text_color=("gray10", "gray90"),
                                hover_color=("gray70", "gray36"),
                                command=lambda n=name: self._insert_pattern_field(n))
            btn.grid(row=index // self.BATCH_FIELD_COLUMNS, column=col,
                     padx=2, pady=2, sticky="ew")
            self._batch_input_widgets.append(btn)

        ctk.CTkLabel(frame, text="One batch = one supplier's XML format. "
                                 "The mapping is taken from the first file.",
                     text_color="gray", anchor="w").pack(fill="x", pady=(4, 2))

        # Planned names
        self.batch_list = ctk.CTkTextbox(frame, height=120, state="disabled",
                                         font=ctk.CTkFont(family="Courier", size=12))
        self.batch_list.pack(fill="both", expand=True, pady=(0, 4))

        # Actions and progress
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")
        self.btn_batch_preview = ctk.CTkButton(row, text="Preview First", width=110,
                                               command=self._batch_preview)
        self.btn_batch_preview.pack(side="left")
        self._batch_input_widgets.append(self.btn_batch_preview)
        self.btn_batch_run = ctk.CTkButton(row, text="Generate All", width=110,
                                           fg_color="#2E86DE", state="disabled",
                                           command=self._batch_run)
        self.btn_batch_run.pack(side="left", padx=6)
        self.btn_batch_stop = ctk.CTkButton(row, text="Stop", width=70, state="disabled",
                                            command=self._batch_stop)
        self.btn_batch_stop.pack(side="left")
        self.batch_progress = ctk.CTkProgressBar(row, width=160)
        self.batch_progress.set(0)
        self.batch_progress.pack(side="left", padx=(12, 6))
        self.batch_progress_label = ctk.CTkLabel(row, text="", anchor="w")
        self.batch_progress_label.pack(side="left", fill="x", expand=True)

    def _set_batch_inputs_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for widget in self._batch_input_widgets:
            widget.configure(state=state)

    def _insert_pattern_field(self, name: str):
        # The guards below back up the disabled widgets: keyboard shortcuts or
        # a queued click can still reach a handler while a run is going.
        if self._batch_running:
            return
        entry = self.pattern_entry
        entry.insert(entry.index("insert"), "{" + name + "}")
        entry.focus_set()
        self.pattern_error_label.configure(text="")

    def _choose_batch_folder(self):
        if self._batch_running:
            return
        folder = filedialog.askdirectory(title="Choose a folder of XML invoices")
        if folder:
            self._set_batch_inputs([folder], default_output=folder)

    def _choose_batch_files(self):
        if self._batch_running:
            return
        paths = filedialog.askopenfilenames(
            title="Choose XML invoices",
            filetypes=[("XML Files", "*.xml"), ("All Files", "*.*")],
        )
        if paths:
            self._set_batch_inputs(list(paths), default_output=os.path.dirname(paths[0]))

    def _set_batch_inputs(self, paths: list[str], default_output: str):
        if self._batch_running:
            return
        self.batch_inputs = collect_xml_files(paths)
        self._invalidate_batch_plan()
        self._show_batch_list("")
        if not self.batch_inputs:
            self.batch_count_label.configure(text="No XML files found",
                                             text_color="#D9534F")
            return
        n = len(self.batch_inputs)
        self.batch_count_label.configure(text=f"{n} XML file{'s' if n != 1 else ''}",
                                         text_color=("gray10", "gray90"))
        self.batch_output_var.set(default_output)
        # The whole batch is converted with the mapping of its first file.
        self._load_batch_xml(self.batch_inputs[0])

    def _browse_batch_output(self):
        if self._batch_running:
            return
        d = filedialog.askdirectory(title="Choose the output folder")
        if d:
            self.batch_output_var.set(d)

    def _load_batch_xml(self, path: str) -> bool:
        """Load the batch's first XML without losing the selected profile.

        _load_xml() auto-matches every slot. On its own that silently replaced
        a chosen profile's mapping while the Config dropdown still named the
        profile, so the batch was named and rendered with a mapping the user
        never picked, and Save Config could write it over the profile. The
        XML still supplies the discovered XPaths; the profile's slots win.
        """
        if not self._load_xml(path):
            return False
        if self.loaded_config is not None and self.config_var.get() != "Default":
            self._apply_profile_mappings(self.loaded_config)
            self.status_label.configure(
                text=f"Using the mapping of profile: {self.config_var.get()}")
        return True

    def _invalidate_batch_plan(self):
        self.batch_plan = None
        if not self._batch_running:
            self.btn_batch_run.configure(state="disabled")

    def _show_batch_list(self, text: str):
        self.batch_list.configure(state="normal")
        self.batch_list.delete("1.0", "end")
        self.batch_list.insert("end", text)
        self.batch_list.configure(state="disabled")

    def _make_batch_plan(self):
        """Validate, build the config, and plan; report problems in the tab.

        Returns ``(plan, config)`` or ``None``. Errors go to labels, not
        message boxes, so nothing modal interrupts the batch flow.
        """
        if not self.batch_inputs:
            self.status_label.configure(text="Choose a folder or XML files first.")
            return None
        pattern = self.pattern_var.get().strip()
        try:
            validate_pattern(pattern)
        except PatternError as e:
            self.pattern_error_label.configure(text=str(e))
            self._invalidate_batch_plan()
            return None
        self.pattern_error_label.configure(text="")

        # Another XML may have been opened from the top bar since the batch was
        # chosen; the batch's mapping must come from its own first file.
        if (self.xml_path != self.batch_inputs[0]
                and not self._load_batch_xml(self.batch_inputs[0])):
            self._invalidate_batch_plan()
            return None

        output_dir = self.batch_output_var.get().strip()
        if not output_dir:
            output_dir = os.path.dirname(self.batch_inputs[0])
            self.batch_output_var.set(output_dir)

        config = self._build_config()
        plan = plan_batch(self.batch_inputs, config, output_dir, pattern=pattern)
        self.batch_plan = plan
        self._show_batch_list(self._format_plan(plan))
        self.btn_batch_run.configure(state="normal")
        return plan, config

    @staticmethod
    def _format_plan(plan) -> str:
        lines = []
        for item in plan.files:
            lines.append(f"{item.filename}  ←  {item.source}")
            lines.extend(f"    ⚠ {w}" for w in item.warnings)
            if item.error:
                lines.append(f"    ✖ {item.error}")
        return "\n".join(lines)

    def _batch_preview(self):
        if self._batch_running:
            return
        if self._make_batch_plan() is None:
            return
        # Renders batch_inputs[0] (the current XML) and switches to Preview.
        self._generate_preview()

    def _batch_run(self):
        if self._batch_running:
            return
        # Re-plan right before running: the pattern, the mapping or the output
        # folder may have changed since the preview, and files may have
        # appeared in the output folder.
        planned = self._make_batch_plan()
        if planned is None:
            return
        plan, config = planned
        total = len(plan.files)
        outcomes: dict[int, tuple[str | None, str | None]] = {}

        self._batch_running = True
        self._batch_stop_event.clear()
        self.btn_batch_run.configure(state="disabled")
        self._set_batch_inputs_enabled(False)
        self.btn_batch_stop.configure(state="normal")
        self.batch_progress.set(0)
        self.batch_progress_label.configure(text=f"0 of {total}")
        self.status_label.configure(text="Batch running...")

        def on_progress(i, n, item):
            self.after(0, self._on_batch_progress, i, n, item)

        def on_done(i, n, item, path, error):
            outcomes[i] = (path, error)
            self.after(0, self.batch_progress.set, i / n if n else 1)

        def run():
            try:
                result = run_batch(plan, config,
                                   include_barcodes=config.include_barcodes,
                                   font_dir=config.font_dir,
                                   on_progress=on_progress,
                                   should_stop=self._batch_stop_event.is_set,
                                   on_done=on_done)
                self.after(0, self._on_batch_finished, plan, outcomes, result, None)
            except Exception as e:  # e.g. the output folder cannot be created
                self.after(0, self._on_batch_finished, plan, outcomes, None, e)

        threading.Thread(target=run, daemon=True).start()

    def _on_batch_progress(self, i: int, total: int, item):
        self.batch_progress.set((i - 1) / total if total else 0)
        self.batch_progress_label.configure(
            text=f"{i} of {total}: {os.path.basename(item.source)}")

    def _batch_stop(self):
        self._batch_stop_event.set()
        self.btn_batch_stop.configure(state="disabled")
        self.status_label.configure(text="Stopping after the current file...")

    def _on_batch_finished(self, plan, outcomes, result, error):
        # Unlock first, before either outcome is reported, so no finish path
        # can leave the inputs disabled.
        self._batch_running = False
        if self._close_requested:
            self._on_closing()
            return
        self._set_batch_inputs_enabled(True)
        self.btn_batch_run.configure(state="normal")
        self.btn_batch_stop.configure(state="disabled")

        if error is not None:
            self.status_label.configure(text=f"Batch error: {error}")
            return

        # List what actually happened. The written name can differ from the
        # planned one when a file appeared in the folder meanwhile.
        lines = []
        for i, item in enumerate(plan.files, 1):
            path, reason = outcomes.get(i, (None, None))
            if path:
                lines.append(f"{os.path.basename(path)}  ←  {item.source}")
                lines.extend(f"    ⚠ {w}" for w in item.warnings)
            else:
                lines.append(f"{item.filename}  ←  {item.source}")
                lines.append(f"    ✖ {reason}" if reason else "    – not generated (stopped)")
        self._show_batch_list("\n".join(lines))

        text = f"Batch done: {len(result.succeeded)} succeeded, {len(result.failed)} failed"
        if result.stopped:
            text += " (stopped)"
        self.status_label.configure(text=text)

    # ── Bottom bar ──────────────────────────────────────

    def _build_bottom_bar(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=(0, 10))

        self.status_label = ctk.CTkLabel(frame, text="Ready", text_color="gray")
        self.status_label.pack(side="left")

        ctk.CTkButton(frame, text="Save Config", width=100, command=self._save_config).pack(side="right", padx=4)
        ctk.CTkButton(frame, text="Preview", width=80, command=self._generate_preview).pack(side="right", padx=4)
        ctk.CTkButton(frame, text="Generate PDF", width=110,
                      fg_color="#2E86DE", command=self._generate_pdf).pack(side="right", padx=4)

    # ── Credit footer ───────────────────────────────────

    def _build_footer(self):
        """Small muted credit line across the bottom of the window."""
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(0, 8))

        # An inner frame that only takes the width it needs, so pack() centres it.
        row = ctk.CTkFrame(footer, fg_color="transparent")
        row.pack()

        muted = ("gray45", "gray60")
        dim = ("gray70", "gray35")
        font = ctk.CTkFont(size=11)

        for index, (label, url) in enumerate(footer_segments()):
            if index:
                ctk.CTkLabel(row, text=SEPARATOR.strip(), font=font,
                             text_color=dim).pack(side="left", padx=4)
            item = ctk.CTkLabel(row, text=label, font=font, text_color=muted)
            item.pack(side="left")
            if url:
                self._make_link(item, url, muted)

    def _make_link(self, widget, url: str, resting_color):
        """Turn a label into a link: hand cursor, hover highlight, opens the URL."""
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda _event, u=url: webbrowser.open(u))
        widget.bind("<Enter>",
                    lambda _e, w=widget: w.configure(text_color=("gray10", "gray90")))
        widget.bind("<Leave>",
                    lambda _e, w=widget: w.configure(text_color=resting_color))

    # ── Actions ─────────────────────────────────────────

    def _open_xml(self):
        path = filedialog.askopenfilename(
            title="Open Invoice XML",
            filetypes=[("XML Files", "*.xml"), ("All Files", "*.*")],
        )
        if not path:
            return
        if not self._load_xml(path):
            messagebox.showerror("XML Error",
                                 f"Failed to parse XML:\n{self._load_error}")

    def _load_xml(self, path: str) -> bool:
        """Load *path* as the current XML: discover fields and auto-match.

        Split from the dialog so the Batch tab can load its first file the
        same way. It reports failure by return value instead of a message box:
        a modal dialog raised from a batch action would block the queue (and a
        headless test) until someone clicks it.
        """
        self._load_error = ""
        self.xml_path = path
        self.xml_label.configure(text=os.path.basename(path), text_color=("gray10", "gray90"))

        try:
            schema = discover_fields(path)
            self.discovered_schema = schema
            self.discovered = {"header": schema.header_tags, "item": schema.item_tags}
        except Exception as e:
            self._load_error = str(e)
            self.status_label.configure(text=f"XML error: {e}")
            return False

        self._update_fields_display()
        self._populate_slot_dropdowns()

        # Smart auto-matching
        matched, reasons = auto_match_fields(schema)
        self._apply_auto_match(matched, reasons)
        return True

    def _build_config(self) -> MappingConfig:
        """Build a MappingConfig from current GUI state."""
        mappings = {}
        for slot, var in self.slot_vars.items():
            val = var.get()
            if val != NONE_TAG and val != HEADER_SEPARATOR and val != ITEM_SEPARATOR:
                mappings[slot] = val

        font_dir = self.font_dir_var.get().strip() or None

        # What the XML told us wins; then the loaded config; then the defaults.
        header_xpath, item_xpath = resolve_xpaths(self.discovered_schema,
                                                  self.loaded_config)

        return MappingConfig(
            name=self.config_var.get(),
            mappings=mappings,
            include_barcodes=self.barcodes_var.get(),
            font_dir=font_dir,
            header_xpath=header_xpath,
            item_xpath=item_xpath,
            filename_pattern=self.pattern_var.get().strip(),
        )

    def _suggested_filename(self, config: MappingConfig) -> str:
        """The single-file Save As name: the pattern's name, else the XML's."""
        fallback = os.path.splitext(os.path.basename(self.xml_path))[0] + ".pdf"
        pattern = config.filename_pattern
        if not pattern:
            return fallback
        try:
            validate_pattern(pattern)
            stem, _warnings = build_stem(pattern, header_values(self.xml_path, config))
        except Exception:
            # Only a suggestion for the dialog; a bad pattern or unreadable
            # header must not stop the user from saving under any name.
            return fallback
        return (stem + ".pdf") if stem else fallback

    def _generate_pdf(self):
        if not self.xml_path:
            messagebox.showwarning("No XML", "Please load an XML file first.")
            return

        config = self._build_config()
        output_path = filedialog.asksaveasfilename(
            title="Save PDF As",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile=self._suggested_filename(config),
        )
        if not output_path:
            return

        self.status_label.configure(text="Generating PDF...")
        self.update_idletasks()

        def run():
            try:
                result = xml_to_pdf(self.xml_path, output_path, mapping_config=config,
                                    include_barcodes=config.include_barcodes,
                                    font_dir=config.font_dir)
                self.preview_pdf_path = result
                self.after(0, lambda: self._on_generate_done(result, None))
            except Exception as e:
                self.after(0, lambda: self._on_generate_done(None, e))

        threading.Thread(target=run, daemon=True).start()

    def _generate_preview(self):
        if not self.xml_path:
            messagebox.showwarning("No XML", "Please load an XML file first.")
            return

        config = self._build_config()
        if self._preview_temp is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            self._preview_temp = tmp.name
            tmp.close()
            self._temp_files.append(self._preview_temp)
        tmp_path = self._preview_temp

        self.status_label.configure(text="Generating preview...")
        self.update_idletasks()

        def run():
            try:
                result = xml_to_pdf(self.xml_path, tmp_path, mapping_config=config,
                                    include_barcodes=config.include_barcodes,
                                    font_dir=config.font_dir)
                self.preview_pdf_path = result
                self.after(0, lambda: self._on_preview_done(result, None))
            except Exception as e:
                self.after(0, lambda: self._on_preview_done(None, e))

        threading.Thread(target=run, daemon=True).start()

    def _on_generate_done(self, result: str | None, error: Exception | None):
        if error:
            self.status_label.configure(text="Error!")
            messagebox.showerror("Generation Error", str(error))
        else:
            self.status_label.configure(text=f"PDF saved: {os.path.basename(result)}")
            self._refresh_preview()

    def _on_preview_done(self, result: str | None, error: Exception | None):
        if error:
            self.status_label.configure(text="Preview error!")
            messagebox.showerror("Preview Error", str(error))
        else:
            self.status_label.configure(text="Preview ready")
            self._refresh_preview()
            self.tabview.set("Preview")

    def _save_config(self):
        name = self.config_var.get()
        if name == "Default":
            name = filedialog.asksaveasfilename(
                title="Save Config As",
                defaultextension=".json",
                filetypes=[("JSON Files", "*.json")],
                initialdir=CONFIGS_DIR,
                initialfile="my_config.json",
            )
            if not name:
                return
            # Extract config name from filename
            config_name = os.path.splitext(os.path.basename(name))[0]
        else:
            config_name = name
            name = os.path.join(CONFIGS_DIR, f"{name}.json")

        config = self._build_config()
        config.name = config_name

        try:
            save_config(name, config)
            self.status_label.configure(text=f"Config saved: {config_name}")
            self._refresh_config_menu()
            self.config_var.set(config_name)
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def _on_config_selected(self, value: str):
        if value == "Default":
            config = MappingConfig()
        else:
            path = self._find_config(value)
            if path is None:
                return
            try:
                config = load_config(path)
            except Exception as e:
                messagebox.showerror("Load Error", str(e))
                return

        # Apply config to GUI
        self.loaded_config = config
        self.barcodes_var.set(config.include_barcodes)
        self.font_dir_var.set(config.font_dir or "")
        self.pattern_var.set(config.filename_pattern or "")

        self._apply_profile_mappings(config)

        self.status_label.configure(text=f"Loaded config: {value}")

    def _apply_profile_mappings(self, config: MappingConfig):
        for slot, var in self.slot_vars.items():
            tag = config.mappings.get(slot, "")
            var.set(tag if tag else NONE_TAG)

    def _on_closing(self):
        # The batch worker is a daemon thread: destroying the window now would
        # kill it, possibly mid-save, leaving a truncated PDF under its final
        # name. Ask it to stop and close once _on_batch_finished runs. No
        # dialog: a modal "really quit?" would also block headless runs.
        if self._batch_running:
            self._close_requested = True
            self._batch_stop()
            return
        from preview import cleanup_temp_files
        cleanup_temp_files(self._temp_files)
        self.destroy()


def launch_gui():
    """Entry point to launch the GUI."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
