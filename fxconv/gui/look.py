"""Цвета и шрифты. Цвет — пара (светлая тема, тёмная тема)."""

import customtkinter as ctk

ACCENT = ("#00796B", "#26A69A")
ACCENT_HOVER = ("#00695C", "#2BBBAD")
ON_ACCENT = "#FFFFFF"
ON_ACCENT_SOFT = "#D7F5F1"
MUTED = ("gray38", "gray66")
DANGER = ("#C62828", "#FF8A80")
NOTE_BG = ("#FFF1D6", "#4A3A12")
NOTE_TEXT = ("#7A4B00", "#FFD27A")
FIELD = ("#E3F4F1", "#253634")
FIELD_TEXT = ("gray10", "gray92")
OUTLINE_TEXT = ("gray15", "gray90")


def setup() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("green")


def font(size: int = 14, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")


def menu_colors() -> dict:
    return dict(fg_color=FIELD, button_color=ACCENT, button_hover_color=ACCENT_HOVER, text_color=FIELD_TEXT,
                dropdown_hover_color=FIELD)


def outline() -> dict:
    """Кнопка-контур для второстепенных действий."""
    return dict(fg_color="transparent", border_width=1, border_color=ACCENT, text_color=OUTLINE_TEXT,
                hover_color=FIELD)
