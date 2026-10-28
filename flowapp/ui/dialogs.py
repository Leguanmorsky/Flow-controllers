"""Dialogs: channel settings and the questions the app asks."""

from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..config import ChannelConfig
from ..core import dde
from .units import decimals_for


class ChannelSettingsDialog(QDialog):
    """Alias, gas, colour, max flow and step of one instrument (saved by serial number)."""

    def __init__(self, info, config, default_color, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Channel settings – address {info.address}")
        self.info = info
        self.default_color = default_color
        self.color = config.color
        decimals = decimals_for(info.capacity)

        form = QFormLayout(self)
        self.alias_edit = QLineEdit(config.alias)
        self.alias_edit.setPlaceholderText(info.fluid or f"Address {info.address}")
        self.gas_edit = QLineEdit(config.gas)
        self.gas_edit.setPlaceholderText(info.fluid or "e.g. O2")
        form.addRow("Name", self.alias_edit)
        form.addRow("Gas", self.gas_edit)

        color_row = QHBoxLayout()
        self.color_button = QPushButton()
        self.color_button.setFixedWidth(90)
        self.color_button.clicked.connect(self._pick_color)
        reset = QPushButton("Default")
        reset.clicked.connect(lambda: self._set_color(""))
        color_row.addWidget(self.color_button)
        color_row.addWidget(reset)
        color_row.addStretch(1)
        form.addRow("Colour", self._wrap(color_row))

        limit_row = QHBoxLayout()
        self.limit_check = QCheckBox("Limit to")
        self.limit_spin = QDoubleSpinBox()
        self.limit_spin.setDecimals(decimals)
        self.limit_spin.setRange(0.0, info.capacity)
        self.limit_spin.setSuffix(f" {info.unit}")
        self.limit_check.setChecked(config.max_flow is not None)
        self.limit_spin.setValue(config.max_flow if config.max_flow is not None else info.capacity)
        self.limit_spin.setEnabled(self.limit_check.isChecked())
        self.limit_check.toggled.connect(self.limit_spin.setEnabled)
        limit_row.addWidget(self.limit_check)
        limit_row.addWidget(self.limit_spin, 1)
        form.addRow("Max flow", self._wrap(limit_row))

        self.step_spin = QDoubleSpinBox()
        self.step_spin.setDecimals(decimals)
        self.step_spin.setRange(10 ** -decimals, info.capacity)
        self.step_spin.setSuffix(f" {info.unit}")
        self.step_spin.setValue(config.step if config.step else info.capacity / 100)
        self.step_spin.setToolTip("Step of the − / + buttons and the spin box arrows")
        form.addRow("Step", self.step_spin)

        details = (f"Serial {info.serial or '?'} · {info.device_type or '?'}"
                   f"{' · firmware ' + info.firmware if info.firmware else ''}\n"
                   f"Capacity {info.capacity:g} {info.unit} · fluid {info.fluid or '?'} · "
                   f"control mode {dde.control_mode_name(info.control_mode)}")
        details_label = QLabel(details)
        details_label.setEnabled(False)
        form.addRow(details_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._set_color(self.color)

    @staticmethod
    def _wrap(layout):
        layout.setContentsMargins(0, 0, 0, 0)
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _set_color(self, color):
        self.color = color
        shown = color or self.default_color
        self.color_button.setText("default" if not color else color)
        self.color_button.setStyleSheet(f"background: {shown}; color: white; font-weight: bold;")

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(self.color or self.default_color), self, "Channel colour")
        if color.isValid():
            self._set_color(color.name())

    def result_config(self):
        return ChannelConfig(
            alias=self.alias_edit.text().strip(),
            gas=self.gas_edit.text().strip(),
            color=self.color,
            max_flow=self.limit_spin.value() if self.limit_check.isChecked() else None,
            step=self.step_spin.value(),
        )


def show_text(parent, title, text, path=None):
    """Read-only text (e.g. the instrument report) with a Copy button."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    view = QPlainTextEdit(text)
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.NoWrap)
    view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
    layout.addWidget(view)
    if path:
        layout.addWidget(QLabel(f"Saved to {path}"))
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    copy = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(text))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(900, 560)
    dialog.exec()


def confirm(parent, title, text):
    """Yes/No question; tests replace this function."""
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


def ask_zero_failed(parent, error, action):
    """Asks what to do when the flows could not be confirmed at 0. Returns "retry", "anyway" or "cancel"."""
    box = QMessageBox(QMessageBox.Warning, "Flows not confirmed at 0",
                      f"Could not confirm that all flows are 0:\n{error}\n\n"
                      f"Gas may still be flowing. Check the instruments.", parent=parent)
    retry = box.addButton("Retry", QMessageBox.AcceptRole)
    anyway = box.addButton(f"{action} anyway", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(retry)
    box.exec()
    clicked = box.clickedButton()
    return "retry" if clicked is retry else "anyway" if clicked is anyway else "cancel"


def gas_blocked(parent, blocked):
    """Gas was refused by a safety rule. Returns "override", "acknowledge" or None; tests replace this."""
    if blocked.rule == "trip":
        box = QMessageBox(QMessageBox.Critical, "Gas blocked: pressure trip",
                          f"{blocked.reason}\n\nEvery flow was set to 0. Check the chamber before you set gas "
                          f"again. Acknowledging the trip does not send anything; set the flow again afterwards.",
                          parent=parent)
        ack = box.addButton("Acknowledge trip", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        return "acknowledge" if box.clickedButton() is ack else None
    box = QMessageBox(QMessageBox.Warning, "Gas blocked", f"{blocked.reason}\n\nThe setpoint was not sent.",
                      parent=parent)
    box.setInformativeText("Override this protection? Gas is then allowed while the main chamber is not "
                           "confirmed pumped, until you disconnect or switch the protection on again in "
                           "Vacuum → Advanced.")
    override = box.addButton("Override and send", QMessageBox.DestructiveRole)
    box.addButton(QMessageBox.Cancel)
    box.exec()
    return "override" if box.clickedButton() is override else None


def confirm_typed(parent, title, text, word):
    """Asks the user to type `word` to confirm a serious command; tests replace this function."""
    answer, ok = QInputDialog.getText(parent, title, f"{text}\n\nType {word} to confirm:")
    return ok and answer.strip().upper() == word
