"""QApplication setup — dark palette, custom stylesheet, app-wide config."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from meeting_copilot.domain.settings import Settings

# Teal accent colour from the spec
TEAL = "#0D9488"
TEAL_BORDER = "#0D7377"
DARK_BG = "#111827"
CARD_BG = "#1F2937"
SEPARATOR = "#1F2937"
TEXT_PRIMARY = "#F9FAFB"
TEXT_SECONDARY = "#9CA3AF"

APP_STYLESHEET = f"""
QWidget {{
    font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}

QToolTip {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {TEAL_BORDER};
    padding: 4px 8px;
    border-radius: 4px;
}}

QPushButton {{
    background-color: {TEAL};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}}

QPushButton:hover {{
    background-color: #0F766E;
}}

QPushButton:pressed {{
    background-color: #0D5D56;
}}

QLineEdit {{
    background-color: {CARD_BG};
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
}}

QLineEdit:focus {{
    border-color: {TEAL};
}}

QComboBox {{
    background-color: {CARD_BG};
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: #374151;
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: {TEAL};
    border-radius: 8px;
}}

QSlider::sub-page:horizontal {{
    background: {TEAL};
    border-radius: 3px;
}}

QTabWidget::pane {{
    border: 1px solid #374151;
    border-radius: 8px;
    background: {DARK_BG};
}}

QTabBar::tab {{
    background: {CARD_BG};
    color: {TEXT_SECONDARY};
    padding: 8px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background: {DARK_BG};
    color: {TEAL};
    font-weight: bold;
}}

QSpinBox {{
    background-color: {CARD_BG};
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 4px 8px;
    color: {TEXT_PRIMARY};
}}

QCheckBox {{
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #374151;
}}

QCheckBox::indicator:checked {{
    background-color: {TEAL};
    border-color: {TEAL};
}}
"""


def build_qapplication(settings: Settings) -> QApplication:
    """Create and configure the QApplication with a dark palette and stylesheet."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Interview Co-Pilot")
    app.setApplicationVersion("0.1.0")

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(DARK_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(CARD_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(DARK_BG))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(CARD_BG))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(CARD_BG))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FF6B6B"))
    palette.setColor(QPalette.ColorRole.Link, QColor(TEAL))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(TEAL))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_PRIMARY))
    app.setPalette(palette)  # type: ignore[union-attr]

    # Apply stylesheet
    app.setStyleSheet(APP_STYLESHEET)  # type: ignore[union-attr]

    return app  # type: ignore[return-value]
