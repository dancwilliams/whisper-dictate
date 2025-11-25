"""UI dialog for managing per-application prompts."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import StringVar, Toplevel, messagebox
from tkinter import ttk

from whisper_dictate import app_prompts


class AppPromptDialog(Toplevel):
    """Manage prompts scoped to specific applications."""

    def __init__(
        self,
        parent: tk.Tk,
        rules: app_prompts.AppPromptMap,
        recent_processes: list[dict[str, str | None]] | None = None,
    ):
        super().__init__(parent)
        self.title("Per-app prompts")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.entries = app_prompts.rules_to_entries(app_prompts.clone_rules(rules))
        self.result: app_prompts.AppPromptMap | None = None
        self._recent_entries: list[dict[str, str | None]] = []
        self._prepare_recent_entries(recent_processes or [])

        ttk.Label(
            self,
            text=(
                "Add prompts tailored to specific applications. "
                "Optional window title patterns (regex) help pick prompts for certain tabs."
            ),
            wraplength=520,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="we", padx=12, pady=(12, 8))

        content = ttk.Frame(self)
        content.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            content,
            columns=("process", "window_regex", "prompt"),
            show="headings",
            height=8,
        )
        for col, heading, width in (
            ("process", "Process", 160),
            ("window_regex", "Window title regex", 180),
            ("prompt", "Prompt", 220),
        ):
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")

        recent_frame = ttk.Labelframe(content, text="Recent apps")
        recent_frame.grid(row=0, column=1, sticky="nsw", padx=(12, 0))
        self.lst_recent = tk.Listbox(recent_frame, height=8, width=18, exportselection=False)
        for entry in self._recent_entries:
            label = entry["process_name"]
            if entry.get("window_title"):
                label = f"{label} — {entry['window_title']}"
            self.lst_recent.insert("end", label)
        self.lst_recent.grid(row=0, column=0, sticky="nsew", padx=8, pady=(6, 4))
        self.lst_recent.bind("<Double-Button-1>", lambda event: self._on_add_from_recent())
        ttk.Button(
            recent_frame, text="Add from recent", command=self._on_add_from_recent
        ).grid(row=1, column=0, padx=8, pady=(0, 8))
        recent_frame.columnconfigure(0, weight=1)
        recent_frame.rowconfigure(0, weight=1)

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=10)
        btns.columnconfigure(0, weight=1)

        ttk.Button(btns, text="Add", command=self._on_add).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Edit", command=self._on_edit).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(btns, text="Delete", command=self._on_delete).grid(row=0, column=2)

        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, columnspan=2, sticky="e", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Cancel", command=self._on_cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Save", command=self._on_save).grid(row=0, column=1)

        self._refresh_tree()
        self.tree.focus_set()

        self.bind("<Escape>", lambda event: self._on_cancel())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, entry in enumerate(self.entries):
            prompt_preview = entry.get("prompt", "").strip().replace("\n", " ")
            if len(prompt_preview) > 60:
                prompt_preview = f"{prompt_preview[:57]}..."
            self.tree.insert(
                "",
                "end",
                iid=f"rule-{idx}",
                values=(
                    entry.get("process_name", ""),
                    entry.get("window_title_regex", ""),
                    prompt_preview,
                ),
            )

    def _selected_entry(self) -> tuple[int, dict[str, str]] | tuple[None, None]:
        selection = self.tree.selection()
        if not selection:
            return None, None
        try:
            idx = int(selection[0].split("-")[-1])
            return idx, self.entries[idx]
        except (IndexError, ValueError):
            return None, None

    def _selected_recent_process(self) -> tuple[str, str | None] | None:
        selection = self.lst_recent.curselection()
        if not selection:
            return None
        try:
            entry = self._recent_entries[selection[0]]
            return entry["process_name"], entry.get("window_title")
        except IndexError:
            return None

    def _prepare_recent_entries(
        self, recent_processes: list[str | dict[str, str | None]]
    ) -> None:
        for entry in recent_processes:
            if isinstance(entry, str):
                process_name = entry.strip()
                window_title = None
            elif isinstance(entry, dict):
                process_name = (entry.get("process_name") or "").strip()
                window_title = entry.get("window_title")
            else:
                continue

            if not process_name:
                continue

            self._recent_entries.append(
                {"process_name": process_name, "window_title": window_title}
            )

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------
    def _on_add(self, process_name: str | None = None, window_title: str | None = None) -> None:
        window_regex = f"^{re.escape(window_title)}$" if window_title else None
        initial = {
            key: value
            for key, value in {
                "process_name": process_name,
                "window_title_regex": window_regex,
            }.items()
            if value
        }
        initial = initial or None
        dialog = AppPromptEntryDialog(self, initial)
        dialog.wait_window()
        if dialog.result:
            self.entries.append(dialog.result)
            self._refresh_tree()

    def _on_add_from_recent(self) -> None:
        recent = self._selected_recent_process()
        if not recent:
            messagebox.showinfo("Per-app prompts", "Select a recent app to prefill.")
            return
        process_name, window_title = recent
        self._on_add(process_name, window_title)

    def _on_edit(self) -> None:
        idx, entry = self._selected_entry()
        if entry is None or idx is None:
            messagebox.showinfo("Per-app prompts", "Select an entry to edit.")
            return
        dialog = AppPromptEntryDialog(self, entry)
        dialog.wait_window()
        if dialog.result:
            self.entries[idx] = dialog.result
            self._refresh_tree()

    def _on_delete(self) -> None:
        idx, entry = self._selected_entry()
        if entry is None or idx is None:
            messagebox.showinfo("Per-app prompts", "Select an entry to delete.")
            return
        if messagebox.askyesno(
            "Delete entry",
            f"Remove prompt for '{entry.get('process_name', 'unknown')}'?",
        ):
            self.entries.pop(idx)
            self._refresh_tree()

    def _on_save(self) -> None:
        self.result = app_prompts.entries_to_rules(self.entries)
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


class AppPromptEntryDialog(Toplevel):
    """Add or edit a single app prompt entry."""

    def __init__(self, parent: tk.Tk, entry: dict[str, str] | None = None):
        super().__init__(parent)
        self.title("App prompt")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        self.result: dict[str, str] | None = None

        self.var_process = StringVar(value=entry.get("process_name", "") if entry else "")
        self.var_window_regex = StringVar(
            value=entry.get("window_title_regex", "") if entry else ""
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Process name (e.g., chrome.exe)").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(frame, textvariable=self.var_process, width=30).grid(
            row=0, column=1, sticky="we", pady=(0, 8), padx=(12, 0)
        )

        ttk.Label(frame, text="Window title regex (optional)").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Entry(frame, textvariable=self.var_window_regex, width=30).grid(
            row=1, column=1, sticky="we", pady=(0, 8), padx=(12, 0)
        )

        ttk.Label(frame, text="Prompt").grid(row=2, column=0, sticky="nw", pady=(4, 0))
        self.txt_prompt = tk.Text(frame, width=50, height=8, wrap="word")
        if entry and entry.get("prompt"):
            self.txt_prompt.insert("1.0", entry["prompt"])
        self.txt_prompt.grid(row=2, column=1, sticky="we", padx=(12, 0))

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=1, sticky="e", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self._on_cancel).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(actions, text="Save", command=self._on_save).grid(row=0, column=1)

        self.bind("<Escape>", lambda event: self._on_cancel())

    def _on_save(self) -> None:
        process = self.var_process.get().strip()
        prompt = self.txt_prompt.get("1.0", "end").strip()
        if not process:
            messagebox.showerror("App prompt", "Process name is required.")
            return
        if not prompt:
            messagebox.showerror("App prompt", "Prompt cannot be empty.")
            return

        self.result = {
            "process_name": process,
            "window_title_regex": self.var_window_regex.get().strip(),
            "prompt": prompt,
        }
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
