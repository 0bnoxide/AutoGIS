"""Site Config Builder dialog (ADR-0065).

A Qt form that authors a harvest-job ``config.yaml`` for a user who may not
know AGOL concepts — plain-language help on every field, a live
"Fetch layers/tables" lookup that turns an item ID into a dropdown of
sublayers (so nobody has to inspect ``item.layers`` in a Python console
again), Browse/Save dialogs instead of typed paths.

All dict-building / validation / YAML logic lives in ``config_builder.py``
(pure, no Qt); this module is only widgets and wiring, matching the
``forms.py`` / ``app.py`` split. Validation is a round-trip through
``HarvestConfig.load`` via ``config_builder.write_config`` — never a second
copy of the rules.

Seams, per the existing conventions:

- ``_pick_path`` wraps the two native ``QFileDialog`` calls this dialog
  needs (folder / save-YAML) so headless tests stub it (ADR-0060 pattern).
- ``_FetchWorker`` runs ``config_builder.fetch_sublayers`` (network +
  arcgis) off the UI thread and reports back via signals (``_StepWorker``
  pattern, ADR-0055/0057). Tests stub ``config_builder.fetch_sublayers``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from autogis.core.common.config import ConfigError

from . import config_builder

__all__ = ["ConfigBuilderDialog"]


def _pick_path(kind: str, parent, title: str, start: str) -> str:
    """Native folder ("dir") or save-YAML ("save") dialog; "" if cancelled.
    Thin modal-dialog seam, stubbed in tests (same reason as app._pick_path,
    ADR-0060) — kept local so this module never imports app.py."""
    if kind == "dir":
        return QFileDialog.getExistingDirectory(parent, title, start)
    return QFileDialog.getSaveFileName(parent, title, start,
                                       "YAML config (*.yaml *.yml)")[0]


class _FetchWorker(QThread):
    """Runs the AGOL sublayer lookup off the UI thread."""

    finished_entries = Signal(object)  # list[config_builder.SublayerEntry]
    failed = Signal(str)

    def __init__(self, profile: str, item_id: str, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._item_id = item_id

    def run(self) -> None:
        try:
            entries = config_builder.fetch_sublayers(self._profile,
                                                     self._item_id)
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_entries.emit(entries)


def _help(text: str) -> QLabel:
    """A small word-wrapped helper line under a field."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class ConfigBuilderDialog(QDialog):
    """Author a harvest ``config.yaml`` without knowing AGOL internals."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Site Config Builder — harvest config.yaml")
        self._worker: _FetchWorker | None = None
        self._entries: list[config_builder.SublayerEntry] = []

        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)

        # --- connection ---------------------------------------------------
        self._profile = QLineEdit()
        self._profile.setToolTip(
            "AGOL/Portal connection profile name saved via ArcGIS Pro or "
            "the ArcGIS API for Python — leave blank for anonymous access.")
        form.addRow("Connection profile:", self._profile)
        form.addRow("", _help(
            "AGOL/Portal connection profile name saved via ArcGIS Pro or the "
            "ArcGIS API for Python — leave blank for anonymous access."))
        self._profile.textChanged.connect(self._sync_fetch_enabled)

        # --- layer: item_id XOR url ----------------------------------------
        self._item_id = QLineEdit()
        self._item_id.setPlaceholderText("e.g. 0123456789abcdef0123456789abcdef")
        self._item_id.setToolTip(
            "The 32-character ID of the AGOL item (from the item page URL). "
            "Recommended — use Fetch below to pick the exact layer/table.")
        form.addRow("Item ID:", self._item_id)

        self._url = QLineEdit()
        self._url.setPlaceholderText(
            "e.g. https://services.arcgis.com/.../FeatureServer/5")
        self._url.setToolTip(
            "Full REST URL of one specific layer or table — the escape "
            "hatch when you already know exactly what to harvest. Filled "
            "automatically when you pick from the fetched list.")
        form.addRow("…or layer/table URL:", self._url)
        form.addRow("", _help(
            "Fill exactly ONE of Item ID or URL. Item ID is the easy path: "
            "enter it, then use “Fetch layers/tables” to pick the "
            "target — that fills the URL for you."))
        self._item_id.textChanged.connect(self._sync_xor)
        self._url.textChanged.connect(self._sync_xor)

        # --- fetch sublayers ------------------------------------------------
        fetch_row = QHBoxLayout()
        self._fetch_button = QPushButton("Fetch layers/tables…")
        self._fetch_button.clicked.connect(self._on_fetch)
        self._fetch_button.setEnabled(False)
        self._sublayer_box = QComboBox()
        self._sublayer_box.addItem("")  # blank until fetched / nothing picked
        self._sublayer_box.currentIndexChanged.connect(self._on_pick_sublayer)
        fetch_row.addWidget(self._fetch_button)
        fetch_row.addWidget(self._sublayer_box, stretch=1)
        form.addRow("Target layer/table:", fetch_row)
        form.addRow("", _help(
            "Lists every layer and table in the item (attachment-bearing "
            "ones first). Picking one writes its resolved URL above."))

        self._all_sublayers = QCheckBox("Harvest every layer/table in this item")
        self._all_sublayers.setToolTip(
            "Harvest every attachment-bearing layer AND table of the item in "
            "one run, each under its own subfolder. Requires Item ID (not a "
            "URL) and disables Incremental.")
        self._all_sublayers.toggled.connect(self._on_all_sublayers_toggled)
        form.addRow("", self._all_sublayers)

        # --- where filter ----------------------------------------------------
        self._where = QLineEdit()
        self._where.setPlaceholderText("e.g. Status = 'Open'")
        self._where.setToolTip(
            "Optional SQL filter: only features matching it are checked for "
            "attachments. Leave blank for all features.")
        form.addRow("Where filter:", self._where)
        form.addRow("", _help(
            "Optional SQL filter deciding WHICH features get checked for "
            "attachments, e.g. Status = 'Open'. Blank = every feature."))

        # --- output ----------------------------------------------------------
        dir_row = QHBoxLayout()
        self._directory = QLineEdit()
        self._directory.setToolTip(
            "Base folder every downloaded attachment is saved under.")
        dir_browse = QPushButton("Browse…")
        dir_browse.setObjectName("dir-browse")
        dir_browse.clicked.connect(self._on_browse_directory)
        dir_row.addWidget(self._directory)
        dir_row.addWidget(dir_browse)
        form.addRow("Output folder:", dir_row)

        self._group_template = QLineEdit()
        self._group_template.setPlaceholderText("{OBJECTID}")
        self._group_template.setToolTip(
            "Subfolder name under the output folder, built from each "
            "feature's attribute values.")
        form.addRow("Subfolder template:", self._group_template)

        self._filename_template = QLineEdit()
        self._filename_template.setPlaceholderText("{OBJECTID}_{name}")
        self._filename_template.setToolTip(
            "Saved filename; {name} is the attachment's original filename.")
        form.addRow("Filename template:", self._filename_template)
        form.addRow("", _help(
            "Templates use {FieldName} placeholders filled from each "
            "feature's attributes ({OBJECTID} always works; a field the "
            "layer doesn't have becomes “_unknown”, and illegal "
            "path characters are stripped automatically). The filename "
            "template can also use {name}: the attachment's original "
            "filename."))

        # --- options -----------------------------------------------------------
        self._incremental = QCheckBox("Incremental")
        self._incremental.setChecked(False)
        self._incremental.setToolTip(
            "Only look at features added or changed since the last run, "
            "instead of re-scanning everything.")
        self._skip_existing = QCheckBox("Skip already-downloaded files")
        self._skip_existing.setChecked(True)
        self._skip_existing.setToolTip(
            "Don't re-download an attachment whose file already exists in "
            "the output folder.")
        opt_row = QHBoxLayout()
        opt_row.addWidget(self._incremental)
        opt_row.addWidget(self._skip_existing)
        form.addRow("Options:", opt_row)

        self._retries = QSpinBox()
        self._retries.setRange(0, 99)
        self._retries.setValue(3)
        self._retries.setToolTip(
            "How many times a failed download is retried before giving up "
            "on that attachment.")
        form.addRow("Retries:", self._retries)

        self._backoff = QDoubleSpinBox()
        self._backoff.setRange(0.0, 3600.0)
        self._backoff.setValue(2.0)
        self._backoff.setToolTip(
            "Base wait between retries. The wait grows linearly: 1st retry "
            "waits this many seconds, 2nd waits twice that, and so on.")
        form.addRow("Backoff (seconds):", self._backoff)
        form.addRow("", _help(
            "A failed download is retried up to “Retries” times, "
            "waiting backoff × attempt-number seconds each time "
            "(2 s, then 4 s, then 6 s…)."))

        # --- save + status --------------------------------------------------
        save_row = QHBoxLayout()
        self._save_button = QPushButton("Save config as…")
        self._save_button.clicked.connect(self._on_save)
        save_row.addStretch(1)
        save_row.addWidget(self._save_button)
        outer.addLayout(save_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

    # --- item_id XOR url ---------------------------------------------------

    def _sync_xor(self) -> None:
        """Filling one of Item ID / URL disables the other (the schema
        accepts exactly one); clearing it re-enables both. Also gates Fetch,
        which needs Profile + Item ID. all_sublayers requires item_id, so it
        keeps URL disabled regardless of what Item ID holds."""
        has_item = bool(self._item_id.text().strip())
        has_url = bool(self._url.text().strip())
        all_sub = self._all_sublayers.isChecked()
        self._item_id.setEnabled(not has_url)
        self._url.setEnabled(not has_item and not all_sub)
        self._sync_fetch_enabled()

    def _sync_fetch_enabled(self) -> None:
        self._fetch_button.setEnabled(
            bool(self._profile.text().strip())
            and bool(self._item_id.text().strip())
            and not self._all_sublayers.isChecked()
            and self._worker is None)

    def _on_all_sublayers_toggled(self, checked: bool) -> None:
        """all_sublayers requires item_id (not url) and conflicts with
        incremental (HarvestConfig.load enforces both) -- clear/disable the
        URL field, the sublayer picker, and Incremental here so the form
        can't be filled into a state that only fails at Save time."""
        self._sublayer_box.setEnabled(not checked)
        if checked:
            self._url.clear()
            self._incremental.setChecked(False)
        self._incremental.setEnabled(not checked)
        self._sync_xor()

    # --- fetch layers/tables -------------------------------------------------

    def _on_fetch(self) -> None:
        if self._worker is not None:
            return  # a fetch is already in flight
        self._status.setText("Fetching layers/tables…")
        self._fetch_button.setEnabled(False)
        self._worker = _FetchWorker(self._profile.text(),
                                    self._item_id.text(), parent=self)
        self._worker.finished_entries.connect(self._on_fetch_done)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.start()

    def _join_worker(self) -> None:
        # Same rationale as app._join_worker: wait() until the OS thread has
        # truly terminated before dropping the ref (ADR-0055/0057).
        if self._worker is not None:
            self._worker.wait()
            self._worker = None

    def _on_fetch_done(self, entries) -> None:
        self._join_worker()
        self._entries = list(entries)
        self._sublayer_box.blockSignals(True)
        self._sublayer_box.clear()
        self._sublayer_box.addItem("")  # "nothing picked" stays expressible
        self._sublayer_box.addItems([e.label for e in self._entries])
        self._sublayer_box.blockSignals(False)
        self._status.setText(
            f"Found {len(self._entries)} layer(s)/table(s) — pick one above."
            if self._entries else "The item has no layers or tables.")
        self._sync_fetch_enabled()

    def _on_fetch_failed(self, message: str) -> None:
        self._join_worker()
        self._status.setText(f"Fetch failed: {message}")
        self._sync_fetch_enabled()

    def _on_pick_sublayer(self, index: int) -> None:
        """Write the picked entry's resolved URL into the URL field and clear
        Item ID — the config targets one specific layer/table via layer.url
        (deliberate: a resolved URL survives service edits that would shift
        a sublayer index, and needs no schema change)."""
        if index <= 0 or index > len(self._entries):
            return
        entry = self._entries[index - 1]  # row 0 is the blank item
        self._item_id.clear()
        self._url.setText(entry.url)

    # --- output folder / save -------------------------------------------------

    def _on_browse_directory(self) -> None:
        path = _pick_path("dir", self, "Select output folder",
                          self._directory.text())
        if path:
            self._directory.setText(path)

    def _build_config(self) -> dict:
        return config_builder.build_config(
            profile=self._profile.text(),
            item_id=self._item_id.text(),
            url=self._url.text(),
            where=self._where.text(),
            directory=self._directory.text(),
            group_template=self._group_template.text(),
            filename_template=self._filename_template.text(),
            all_sublayers=self._all_sublayers.isChecked(),
            incremental=self._incremental.isChecked(),
            skip_existing=self._skip_existing.isChecked(),
            retries=self._retries.value(),
            backoff_seconds=self._backoff.value(),
        )

    def _on_save(self) -> None:
        config = self._build_config()
        try:
            # Validate BEFORE the save dialog so a form error never costs the
            # user a pointless file-picker round trip.
            config_builder.validate_config(config)
        except ConfigError as exc:
            self._status.setText(f"Fix before saving: {exc}")
            return
        path = _pick_path("save", self, "Save harvest config", "config.yaml")
        if not path:
            return  # cancelled
        try:
            config_builder.write_config(config, Path(path))
        except (ConfigError, OSError) as exc:
            self._status.setText(f"Could not save: {exc}")
            return
        self._status.setText(f"Saved {path}")

    # --- lifecycle -----------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Never destroy a QThread whose OS thread is still running (same
        # crash class app.closeEvent guards against).
        if self._worker is not None and self._worker.isRunning():
            self._status.setText(
                "Still fetching — please wait for it to finish before "
                "closing.")
            event.ignore()
            return
        self._join_worker()
        event.accept()
