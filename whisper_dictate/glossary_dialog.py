"""UI dialog for managing glossary rules."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import BooleanVar, StringVar, Toplevel, filedialog, messagebox, ttk

from whisper_dictate.glossary import GlossaryManager, GlossaryRule


class GlossaryDialog(Toplevel):
    """Manage glossary rules with add/edit/delete support."""

    def __init__(self, parent: tk.Tk, manager: GlossaryManager):
        super().__init__(parent)
        self.title("Glossary / Custom Dictionary")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        # Work on a copy so changes are only applied when the user clicks Save
        self.manager = GlossaryManager(GlossaryRule.from_dict(r.to_dict()) for r in manager.rules)
        self.result: GlossaryManager | None = None

        self.columnconfigure(0, weight=1)

        ttk.Label(
            self,
            text=(
                "Use triggers to match what you say or what Whisper outputs. "
                "Replacements are inserted into the transcript."
            ),
            wraplength=520,
            justify="left",
        ).grid(row=0, column=0, sticky="we", padx=12, pady=(12, 8))

        self.tree = ttk.Treeview(
            self,
            columns=("trigger", "replacement", "type", "case", "boundary"),
            show="headings",
            height=8,
        )
        for col, heading, width in (
            ("trigger", "Trigger", 160),
            ("replacement", "Replacement", 180),
            ("type", "Match", 70),
            ("case", "Case", 70),
            ("boundary", "Whole words", 100),
        ):
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=12)

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, sticky="ew", padx=12, pady=10)
        btns.columnconfigure(0, weight=1)

        ttk.Button(btns, text="Add", command=self._on_add).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Edit", command=self._on_edit).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(btns, text="Delete", command=self._on_delete).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(btns, text="Import CSV", command=self._on_import).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(btns, text="Export CSV", command=self._on_export).grid(row=0, column=4)

        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="e", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Cancel", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Save", command=self._on_save).grid(row=0, column=1)

        self._refresh_tree()
        self.tree.focus_set()

        self.bind("<Escape>", lambda event: self._on_cancel())

    # ------------------------------------------------------------------
    # Tree helpers
    # ------------------------------------------------------------------
    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, rule in enumerate(self.manager.rules):
            self.tree.insert(
                "",
                "end",
                iid=f"rule-{idx}",
                values=(
                    rule.trigger,
                    rule.replacement,
                    rule.match_type,
                    "Yes" if rule.case_sensitive else "No",
                    "Yes" if rule.word_boundary else "No",
                ),
            )

    def _selected_rule(self) -> GlossaryRule | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            idx = int(selection[0].split("-")[-1])
            return self.manager.rules[idx]
        except (IndexError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------
    def _on_add(self) -> None:
        dialog = GlossaryRuleDialog(self)
        dialog.wait_window()
        if dialog.result:
            self.manager.upsert_rule(dialog.result)
            self._refresh_tree()

    def _on_edit(self) -> None:
        rule = self._selected_rule()
        if not rule:
            messagebox.showinfo("Glossary", "Select a rule to edit.")
            return
        dialog = GlossaryRuleDialog(self, rule)
        dialog.wait_window()
        if dialog.result:
            self.manager.upsert_rule(dialog.result)
            self._refresh_tree()

    def _on_delete(self) -> None:
        rule = self._selected_rule()
        if not rule:
            messagebox.showinfo("Glossary", "Select a rule to delete.")
            return
        if messagebox.askyesno("Delete rule", f"Remove '{rule.trigger}'?"):
            self.manager.remove_rule(rule.trigger)
            self._refresh_tree()

    def _on_import(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Import glossary CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            self.manager.import_csv(text)
            self._refresh_tree()
        except (OSError, UnicodeDecodeError, ValueError) as e:
            # OSError: File access errors
            # UnicodeDecodeError: Invalid UTF-8 encoding
            # ValueError: Invalid CSV format from import_csv
            messagebox.showerror("Import glossary", f"Could not import: {e}")

    def _on_export(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export glossary CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self.manager.export_csv(), encoding="utf-8")
            messagebox.showinfo("Export glossary", f"Saved to {path}")
        except (OSError, UnicodeEncodeError) as e:
            # OSError: File write errors (permission, disk space, etc.)
            # UnicodeEncodeError: Invalid character encoding
            messagebox.showerror("Export glossary", f"Could not export: {e}")

    def _on_save(self) -> None:
        self.result = self.manager
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class GlossaryRuleDialog(Toplevel):
    """Add or edit a single glossary rule."""

    def __init__(self, parent: tk.Tk, rule: GlossaryRule | None = None):
        super().__init__(parent)
        self.title("Glossary Rule")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.result: GlossaryRule | None = None

        self.var_trigger = StringVar(value=rule.trigger if rule else "")
        self.var_replacement = StringVar(value=rule.replacement if rule else "")
        self.var_match_type = StringVar(value=rule.match_type if rule else "phrase")
        self.var_case_sensitive = BooleanVar(value=rule.case_sensitive if rule else False)
        self.var_word_boundary = BooleanVar(value=rule.word_boundary if rule else True)
        # Description can be missing when creating a new rule
        self.var_description = StringVar(value=rule.description if rule and rule.description else "")

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Trigger (what you say or see)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.var_trigger, width=46).grid(row=1, column=0, sticky="we", pady=(0, 8))

        ttk.Label(frame, text="Replacement (what should appear)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.var_replacement, width=46).grid(row=3, column=0, sticky="we", pady=(0, 8))

        opts = ttk.Frame(frame)
        opts.grid(row=4, column=0, sticky="we", pady=(4, 4))
        ttk.Label(opts, text="Match type:").grid(row=0, column=0, sticky="w")
        cmb = ttk.Combobox(opts, textvariable=self.var_match_type, values=["word", "phrase", "regex"], state="readonly", width=10)
        cmb.grid(row=0, column=1, padx=(6, 18))
        ttk.Checkbutton(opts, text="Case sensitive", variable=self.var_case_sensitive).grid(row=0, column=2, padx=(0, 12))
        ttk.Checkbutton(opts, text="Whole words only", variable=self.var_word_boundary).grid(row=0, column=3)

        ttk.Label(frame, text="Description (optional)").grid(row=5, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.var_description, width=46).grid(row=6, column=0, sticky="we", pady=(0, 10))

        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, sticky="e")
        ttk.Button(actions, text="Cancel", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Save", command=self._on_save).grid(row=0, column=1)

        self.bind("<Escape>", lambda event: self._on_cancel())
        self.bind("<Return>", lambda event: self._on_save())

    def _on_save(self) -> None:
        trigger = self.var_trigger.get().strip()
        replacement = self.var_replacement.get().strip()
        if not trigger or not replacement:
            messagebox.showerror("Glossary", "Trigger and replacement are required.")
            return
        self.result = GlossaryRule(
            trigger=trigger,
            replacement=replacement,
            match_type=self.var_match_type.get() or "phrase",
            case_sensitive=bool(self.var_case_sensitive.get()),
            word_boundary=bool(self.var_word_boundary.get()),
            description=self.var_description.get().strip() or None,
        )
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
