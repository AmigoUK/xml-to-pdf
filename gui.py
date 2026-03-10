#!/usr/bin/env python3
"""
gui.py
======
CustomTkinter GUI for XML-to-PDF field mapping and generation.
"""

from __future__ import annotations

import os
import sys

# Auto-relaunch with venv Python if running under system Python and venv exists
_VENV_PYTHON = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python3")
if (
    os.path.isfile(_VENV_PYTHON)
    and os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON)
):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from xml_parser import InvoiceData, DiscoveredSchema, discover_fields
from mapping import (
    MappingConfig, SLOT_CATEGORIES, HEADER_SLOTS, ITEM_SLOTS,
    DEFAULT_MAPPINGS, save_config, load_config, auto_match_fields,
)
from pdf_renderer import xml_to_pdf
from preview import HAS_PYMUPDF, HAS_PIL, render_pdf_page, get_page_count, open_in_viewer

CONFIGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")
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
        self.slot_vars: dict[str, ctk.StringVar] = {}
        self.slot_labels: dict[str, ctk.CTkLabel] = {}
        self.match_reasons: dict[str, str] = {}
        self.preview_pdf_path: str | None = None
        self.preview_page = 0
        self.preview_page_count = 0
        self._temp_files: list[str] = []

        self._build_top_bar()
        self._build_tabs()
        self._build_bottom_bar()

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
        configs = ["Default"]
        if os.path.isdir(CONFIGS_DIR):
            for f in sorted(os.listdir(CONFIGS_DIR)):
                if f.endswith(".json"):
                    configs.append(f[:-5])
        return configs

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

        self._build_mapping_tab()
        self._build_options_tab()
        self._build_preview_tab()

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

        if not HAS_PYMUPDF:
            ctk.CTkButton(nav, text="Open in Viewer", width=120, command=self._open_in_viewer).pack(side="right")

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
            self.page_label.configure(text="PyMuPDF not available — use 'Open in Viewer'")
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

    # ── Actions ─────────────────────────────────────────

    def _open_xml(self):
        path = filedialog.askopenfilename(
            title="Open Invoice XML",
            filetypes=[("XML Files", "*.xml"), ("All Files", "*.*")],
        )
        if not path:
            return

        self.xml_path = path
        self.xml_label.configure(text=os.path.basename(path), text_color=("gray10", "gray90"))

        try:
            schema = discover_fields(path)
            self.discovered_schema = schema
            self.discovered = {"header": schema.header_tags, "item": schema.item_tags}
        except Exception as e:
            messagebox.showerror("XML Error", f"Failed to parse XML:\n{e}")
            return

        self._update_fields_display()
        self._populate_slot_dropdowns()

        # Smart auto-matching
        matched, reasons = auto_match_fields(schema)
        self._apply_auto_match(matched, reasons)

    def _build_config(self) -> MappingConfig:
        """Build a MappingConfig from current GUI state."""
        mappings = {}
        for slot, var in self.slot_vars.items():
            val = var.get()
            if val != NONE_TAG and val != HEADER_SEPARATOR and val != ITEM_SEPARATOR:
                mappings[slot] = val

        font_dir = self.font_dir_var.get().strip() or None

        # Include discovered XPaths
        header_xpath = ".//Naglowek"
        item_xpath = ".//Pozycja"
        if self.discovered_schema:
            header_xpath = self.discovered_schema.header_xpath or header_xpath
            item_xpath = self.discovered_schema.item_xpath or item_xpath

        return MappingConfig(
            name=self.config_var.get(),
            mappings=mappings,
            include_barcodes=self.barcodes_var.get(),
            font_dir=font_dir,
            header_xpath=header_xpath,
            item_xpath=item_xpath,
        )

    def _generate_pdf(self):
        if not self.xml_path:
            messagebox.showwarning("No XML", "Please load an XML file first.")
            return

        output_path = filedialog.asksaveasfilename(
            title="Save PDF As",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile=os.path.splitext(os.path.basename(self.xml_path))[0] + ".pdf",
        )
        if not output_path:
            return

        config = self._build_config()
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
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_path = tmp.name
        tmp.close()
        self._temp_files.append(tmp_path)

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
            path = os.path.join(CONFIGS_DIR, f"{value}.json")
            if not os.path.isfile(path):
                return
            try:
                config = load_config(path)
            except Exception as e:
                messagebox.showerror("Load Error", str(e))
                return

        # Apply config to GUI
        self.barcodes_var.set(config.include_barcodes)
        self.font_dir_var.set(config.font_dir or "")

        for slot, var in self.slot_vars.items():
            tag = config.mappings.get(slot, "")
            var.set(tag if tag else NONE_TAG)

        self.status_label.configure(text=f"Loaded config: {value}")

    def _on_closing(self):
        from preview import cleanup_temp_files
        cleanup_temp_files(self._temp_files)
        self.destroy()


def launch_gui():
    """Entry point to launch the GUI."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    launch_gui()
