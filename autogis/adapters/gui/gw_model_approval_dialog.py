"""Groundwater-model review and approval dialog (#384)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from . import gw_model_approval

__all__ = ["GWModelApprovalDialog"]


def _pick_gdb(parent, start: str) -> str:
    return QFileDialog.getExistingDirectory(
        parent, "Select file geodatabase", start)


def _text(value) -> str:
    return "" if value is None else str(value)


class GWModelApprovalDialog(QDialog):
    """List DRAFT runs, show rankings, and approve any executed model."""

    def __init__(self, local_python: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Approve Groundwater Model")
        self._local_python = local_python
        self._records: list[dict] = []

        outer = QVBoxLayout(self)
        gdb_row = QHBoxLayout()
        self._gdb = QLineEdit()
        self._gdb.setPlaceholderText("Select a geodatabase containing GW_ModelRun")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        self._refresh = QPushButton("Load DRAFT runs")
        self._refresh.clicked.connect(self._on_refresh)
        gdb_row.addWidget(self._gdb)
        gdb_row.addWidget(browse)
        gdb_row.addWidget(self._refresh)
        outer.addLayout(gdb_row)

        self._runs = QTableWidget(0, 6)
        self._runs.setHorizontalHeaderLabels(
            ["Run ID", "Site", "Event", "Executed models",
             "Approved model", "Review status"])
        self._runs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._runs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._runs.setSelectionMode(QAbstractItemView.SingleSelection)
        self._runs.itemSelectionChanged.connect(self._on_run_selected)
        outer.addWidget(self._runs)

        outer.addWidget(QLabel("Ranked cross-validation statistics:"))
        self._stats = QTableWidget(0, 7)
        self._stats.setHorizontalHeaderLabels(
            ["Rank", "Model", "N", "RMSE", "Mean error", "MAE",
             "% within tolerance"])
        self._stats.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self._stats)

        form = QFormLayout()
        self._model = QComboBox()
        self._model.currentTextChanged.connect(self._sync_approve)
        self._reviewer = QLineEdit()
        self._reviewer.setPlaceholderText("Required name or initials")
        self._reviewer.textChanged.connect(self._sync_approve)
        form.addRow("Approve executed model:", self._model)
        form.addRow("Reviewer:", self._reviewer)
        outer.addLayout(form)

        self._approve = QPushButton("Confirm and approve")
        self._approve.setEnabled(False)
        self._approve.clicked.connect(self._on_approve)
        outer.addWidget(self._approve)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

    def _on_browse(self) -> None:
        path = _pick_gdb(self, self._gdb.text())
        if path:
            self._gdb.setText(path)

    def _on_refresh(self, _checked=False, *, focus_run_id: str = "") -> bool:
        try:
            records = gw_model_approval.load_review_runs(
                self._local_python, self._gdb.text().strip())
        except Exception as exc:  # noqa: BLE001 - show child/ArcPy error in UI
            self._status.setText(f"Could not load model runs: {exc}")
            return False
        self._populate(records, focus_run_id=focus_run_id)
        return True

    def _populate(self, records: list[dict], *, focus_run_id: str = "") -> None:
        # Initial load is DRAFT-only. After approval, retain the just-approved
        # row once so ApprovedModel/ReviewStatus visibly refresh.
        self._records = [
            r for r in records
            if r.get("ReviewStatus") == "DRAFT"
            or (focus_run_id and r.get("RunID") == focus_run_id)
        ]
        self._runs.setRowCount(len(self._records))
        for row, rec in enumerate(self._records):
            values = [
                rec.get("RunID"), rec.get("SiteID"), rec.get("EventDate"),
                ", ".join(rec.get("ExecutedMethods") or ()),
                rec.get("ApprovedModel"), rec.get("ReviewStatus"),
            ]
            for col, value in enumerate(values):
                self._runs.setItem(row, col, QTableWidgetItem(_text(value)))
        self._runs.resizeColumnsToContents()
        if self._records:
            target = next(
                (i for i, rec in enumerate(self._records)
                 if rec.get("RunID") == focus_run_id),
                0,
            )
            self._runs.selectRow(target)
        else:
            self._clear_selection()
        self._status.setText(
            f"Loaded {len(self._records)} review row(s)."
            if self._records else "No DRAFT groundwater-model runs found.")

    def _selected_record(self) -> dict | None:
        row = self._runs.currentRow()
        return self._records[row] if 0 <= row < len(self._records) else None

    def _clear_selection(self) -> None:
        self._stats.setRowCount(0)
        self._model.clear()
        self._sync_approve()

    def _on_run_selected(self) -> None:
        rec = self._selected_record()
        if rec is None:
            self._clear_selection()
            return
        stats = rec.get("Models") or []
        self._stats.setRowCount(len(stats))
        fields = [
            "Rank", "ModelName", "NPoints", "RMSE", "MeanError", "MAE",
            "PctWithinTolerance",
        ]
        for row, stat in enumerate(stats):
            for col, field in enumerate(fields):
                self._stats.setItem(
                    row, col, QTableWidgetItem(_text(stat.get(field))))
        self._stats.resizeColumnsToContents()
        self._model.clear()
        self._model.addItems(rec.get("ExecutedMethods") or ())
        approved = rec.get("ApprovedModel") or ""
        if approved:
            self._model.setCurrentText(approved)
        elif stats:
            self._model.setCurrentText(_text(stats[0].get("ModelName")))
        self._sync_approve()

    def _sync_approve(self) -> None:
        rec = self._selected_record()
        self._approve.setEnabled(
            rec is not None
            and rec.get("ReviewStatus") == "DRAFT"
            and bool(self._model.currentText())
            and bool(self._reviewer.text().strip())
        )

    def _on_approve(self) -> None:
        rec = self._selected_record()
        if rec is None or not self._approve.isEnabled():
            return
        model = self._model.currentText()
        reviewer = self._reviewer.text().strip()
        answer = QMessageBox.question(
            self, "Confirm groundwater-model approval",
            f"Approve {model} for run {rec['RunID']} as {reviewer}?\n\n"
            "This records ReviewStatus=APPROVED.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            gw_model_approval.approve_model(
                self._local_python, self._gdb.text().strip(),
                rec["RunID"], model, reviewer,
                site_id=rec.get("SiteID") or "",
                event_id=rec.get("EventDate") or "")
        except Exception as exc:  # noqa: BLE001 - show child/ArcPy error in UI
            self._status.setText(f"Approval failed: {exc}")
            return
        if self._on_refresh(focus_run_id=rec["RunID"]):
            self._status.setText(
                f"Approved {model}; refreshed ApprovedModel and ReviewStatus.")
