"""«Обмен валют» — конвертер по официальному курсу Национального банка Молдовы.

Запуск:
    python main.py
"""

from tkinter import messagebox

import customtkinter as ctk

from fxconv.archive import RateArchive, default_location
from fxconv.bnm import BnmFeed
from fxconv.gui import look
from fxconv.gui.window import TITLE, FxWindow
from fxconv.provider import RateProvider


def main() -> None:
    look.setup()
    app = ctk.CTk()
    app.title(TITLE)
    app.geometry("640x780")
    app.minsize(600, 720)
    app.report_callback_exception = lambda exc_type, error, traceback: messagebox.showerror(
        TITLE, f"Непредвиденная ошибка: {error}", parent=app)

    FxWindow(app, RateProvider(BnmFeed(), RateArchive(default_location())))
    app.mainloop()


if __name__ == "__main__":
    main()
