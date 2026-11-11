"""Окно «Обмен валют».

Вкладка «Конвертер»: сумма, две валюты (с кнопкой ⇄), дата курса,
результат, дата и источник курса, предупреждение. Вкладка «Курсы на
дату»: таблица всех курсов. Курс загружается в фоновом потоке.
"""

import queue
import threading
from datetime import date, datetime, timedelta
from tkinter import messagebox
from typing import Callable, Literal

import customtkinter as ctk

from .. import money
from ..bnm import SourceProblem
from ..money import AmountProblem, Currency
from ..provider import Quote, RateProvider
from . import look

TITLE = "Обмен валют"
PICK = "— валюта —"
NO_RATES = "Курсы не загружены."
LOADING = "Загружаем курс…"
DAY_FORMAT = "%d.%m.%Y"

Kind = Literal["ok", "yesno"]
# (текст, вид) -> True для «ОК»/«Да». В тестах подменяется: настоящий
# messagebox модальный и остановил бы тест.
Ask = Callable[[str, Kind], bool]


def real_dialogs(parent) -> Ask:
    def ask(text: str, kind: Kind) -> bool:
        if kind == "yesno":
            return messagebox.askyesno(TITLE, text, icon=messagebox.WARNING, parent=parent)
        messagebox.showwarning(TITLE, text, parent=parent)
        return True

    return ask


class FxWindow:
    def __init__(self, master, provider: RateProvider, ask: Ask | None = None,
                 today: Callable[[], date] = date.today) -> None:
        self.master = master
        self.provider = provider
        self.ask = ask or real_dialogs(master)
        self.today = today

        self.quote: Quote | None = None
        self.loading = False
        self.table_rows: list[tuple[str, str, str, str]] = []
        self._by_caption: dict[str, Currency] = {}
        self._results: queue.Queue = queue.Queue()

        self.amount = ctk.StringVar(master)
        self.day_text = ctk.StringVar(master, value=today().strftime(DAY_FORMAT))

        self._build()
        self._no_rates()
        master.after(120, self.reload)

    # --- разметка ----------------------------------------------------------

    def _build(self) -> None:
        header = ctk.CTkFrame(self.master, fg_color=look.ACCENT, corner_radius=0)
        header.pack(fill="x")
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", padx=24, pady=(18, 16))
        ctk.CTkLabel(titles, text=TITLE, text_color=look.ON_ACCENT, font=look.font(24, bold=True)).pack(anchor="w")
        ctk.CTkLabel(titles, text="Официальный курс Национального банка Молдовы", text_color=look.ON_ACCENT_SOFT,
                     font=look.font(13)).pack(anchor="w")
        self.theme_switch = ctk.CTkSwitch(header, text="Тёмная тема", text_color=look.ON_ACCENT,
                                          progress_color=look.ACCENT_HOVER,
                                          command=lambda: ctk.set_appearance_mode(
                                              "dark" if self.theme_switch.get() else "light"))
        self.theme_switch.pack(side="right", padx=24)
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()

        self.tabs = ctk.CTkTabview(self.master, segmented_button_selected_color=look.ACCENT,
                                   segmented_button_selected_hover_color=look.ACCENT_HOVER, corner_radius=14)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        self._build_converter(self.tabs.add("Конвертер"))
        self._build_table(self.tabs.add("Курсы на дату"))

    def _build_converter(self, tab) -> None:
        tab.grid_columnconfigure(0, weight=1)
        caption = dict(text_color=look.MUTED, font=look.font(12))

        ctk.CTkLabel(tab, text="Сумма", **caption).grid(row=0, column=0, sticky="w", padx=8)
        self.amount_entry = ctk.CTkEntry(tab, textvariable=self.amount, height=46, corner_radius=12,
                                         font=look.font(20))
        self.amount_entry.grid(row=1, column=0, sticky="ew", padx=8)
        self.amount_error = ctk.CTkLabel(tab, text="", text_color=look.DANGER, font=look.font(13))
        self.amount_error.grid(row=2, column=0, sticky="w", padx=8)

        pair = ctk.CTkFrame(tab, fg_color="transparent")
        pair.grid(row=3, column=0, sticky="ew", padx=8, pady=(12, 0))
        pair.grid_columnconfigure((0, 2), weight=1, uniform="side")
        ctk.CTkLabel(pair, text="Отдаю", **caption).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(pair, text="Получаю", **caption).grid(row=0, column=2, sticky="w")
        self.give_menu = ctk.CTkOptionMenu(pair, values=[PICK], command=lambda _: self._changed(), height=38,
                                           corner_radius=10, dynamic_resizing=False, **look.menu_colors())
        self.give_menu.grid(row=1, column=0, sticky="ew")
        self.swap_button = ctk.CTkButton(pair, text="⇄", width=44, height=38, corner_radius=19,
                                         font=look.font(18, bold=True), command=self.swap, **look.outline())
        self.swap_button.grid(row=1, column=1, padx=10)
        self.get_menu = ctk.CTkOptionMenu(pair, values=[PICK], command=lambda _: self._changed(), height=38,
                                          corner_radius=10, dynamic_resizing=False, **look.menu_colors())
        self.get_menu.grid(row=1, column=2, sticky="ew")

        ctk.CTkLabel(tab, text="Дата курса (ДД.ММ.ГГГГ)", **caption).grid(row=4, column=0, sticky="w", padx=8,
                                                                          pady=(12, 0))
        days = ctk.CTkFrame(tab, fg_color="transparent")
        days.grid(row=5, column=0, sticky="ew", padx=8)
        days.grid_columnconfigure(0, weight=1)
        self.day_entry = ctk.CTkEntry(days, textvariable=self.day_text, height=38, corner_radius=10)
        self.day_entry.grid(row=0, column=0, sticky="ew")
        self.day_entry.bind("<Return>", lambda _: self.reload())
        self.earlier_button = ctk.CTkButton(days, text="‹", width=38, height=38, corner_radius=10,
                                            command=lambda: self.move_day(-1), **look.outline())
        self.earlier_button.grid(row=0, column=1, padx=(8, 0))
        self.later_button = ctk.CTkButton(days, text="›", width=38, height=38, corner_radius=10,
                                          command=lambda: self.move_day(1), **look.outline())
        self.later_button.grid(row=0, column=2, padx=(6, 0))
        self.today_button = ctk.CTkButton(days, text="Сегодня", width=90, height=38, corner_radius=10,
                                          command=lambda: self.pick_day(self.today()), **look.outline())
        self.today_button.grid(row=0, column=3, padx=(6, 0))
        self.day_error = ctk.CTkLabel(tab, text="", text_color=look.DANGER, font=look.font(13))
        self.day_error.grid(row=6, column=0, sticky="w", padx=8)

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=7, column=0, sticky="ew", padx=8, pady=(14, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.convert_button = ctk.CTkButton(actions, text="Пересчитать", height=46, corner_radius=12,
                                            fg_color=look.ACCENT, hover_color=look.ACCENT_HOVER,
                                            font=look.font(16, bold=True), command=self.convert)
        self.convert_button.grid(row=0, column=0, sticky="ew")
        self.refresh_button = ctk.CTkButton(actions, text="Обновить курс", width=140, height=46, corner_radius=12,
                                            command=self.reload, **look.outline())
        self.refresh_button.grid(row=0, column=1, padx=(10, 0))

        board = ctk.CTkFrame(tab, corner_radius=14, fg_color=look.FIELD)
        board.grid(row=8, column=0, sticky="ew", padx=8, pady=(16, 8))
        board.grid_columnconfigure(0, weight=1)
        self.result_label = ctk.CTkLabel(board, text="", text_color=look.ACCENT, font=look.font(26, bold=True),
                                         wraplength=480, justify="left")
        self.result_label.grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        self.rate_label = ctk.CTkLabel(board, text="", font=look.font(14))
        self.rate_label.grid(row=1, column=0, sticky="w", padx=18)
        self.info_label = ctk.CTkLabel(board, text=NO_RATES, text_color=look.MUTED, font=look.font(13),
                                       wraplength=480, justify="left")
        self.info_label.grid(row=2, column=0, sticky="w", padx=18, pady=(6, 14))
        self.notice = ctk.CTkFrame(board, fg_color=look.NOTE_BG, corner_radius=10)
        self.notice.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.notice_label = ctk.CTkLabel(self.notice, text="", text_color=look.NOTE_TEXT, font=look.font(13),
                                         wraplength=460, justify="left")
        self.notice_label.pack(anchor="w", padx=12, pady=8)

        self.amount.trace_add("write", lambda *_: self._changed())
        self.amount_entry.bind("<Return>", lambda _: self.convert() if self._can_convert() else None)

    def _build_table(self, tab) -> None:
        self.table = ctk.CTkScrollableFrame(tab, corner_radius=12)
        self.table.pack(fill="both", expand=True, padx=8, pady=8)
        self.table.grid_columnconfigure(1, weight=1)

    # --- маленькие помощники видимости -------------------------------------

    @staticmethod
    def shown(widget) -> bool:
        return bool(widget.winfo_manager())

    @staticmethod
    def _say(label, text: str) -> None:
        label.configure(text=text)
        label.grid() if text else label.grid_remove()

    def _set_notice(self, text: str) -> None:
        self.notice_label.configure(text=text)
        self.notice.grid() if text else self.notice.grid_remove()

    def _clear_result(self) -> None:
        self._say(self.result_label, "")
        self._say(self.rate_label, "")

    # --- валюты --------------------------------------------------------------

    def chosen(self, menu) -> Currency | None:
        return self._by_caption.get(menu.get())

    def choose(self, menu, code: str) -> None:
        """Выбор валюты по коду — как выбор пункта мышью."""
        caption = next(caption for caption, currency in self._by_caption.items() if currency.code == code)
        menu.set(caption)
        self._changed()

    def swap(self) -> None:
        give, get = self.give_menu.get(), self.get_menu.get()
        self.give_menu.set(get)
        self.get_menu.set(give)
        self._changed()

    # --- даты и загрузка -----------------------------------------------------

    def asked_day(self) -> date | None:
        try:
            return datetime.strptime(self.day_text.get().strip(), DAY_FORMAT).date()
        except ValueError:
            return None

    def pick_day(self, day: date) -> None:
        self.day_text.set(day.strftime(DAY_FORMAT))
        self.reload()

    def move_day(self, step: int) -> None:
        self.pick_day((self.asked_day() or self.today()) + timedelta(days=step))

    def reload(self) -> None:
        if self.loading:
            return
        day = self.asked_day()
        if day is None:
            self._say(self.day_error, "Дата должна быть в формате ДД.ММ.ГГГГ, например 05.11.2026.")
            return
        self._say(self.day_error, "")

        keep = (self.chosen(self.give_menu), self.chosen(self.get_menu))
        self._no_rates()
        self._busy(True)

        def work():
            try:
                self._results.put(("ok", self.provider.quote(day)))
            except Exception as error:  # передаём в окно как есть
                self._results.put(("error", error))

        threading.Thread(target=work, daemon=True).start()
        self._collect(day, keep)

    def _collect(self, day: date, keep) -> None:
        try:
            outcome, value = self._results.get_nowait()
        except queue.Empty:
            self.master.after(30, self._collect, day, keep)
            return
        try:
            if outcome == "ok":
                self._show(value, keep)
            elif isinstance(value, SourceProblem):
                offline = self._offer_archive(value, day)
                if offline:
                    self._show(offline, keep)
            else:
                raise value
        finally:
            self._busy(False)

    def _offer_archive(self, problem: SourceProblem, day: date) -> Quote | None:
        saved = self.provider.from_archive(day)
        if saved is None:
            self.ask(f"{problem}\n\nСохранённого курса нет. Проверьте подключение и нажмите «Обновить курс».",
                     "ok")
            return None
        if self.ask(f"{problem}\n\nПоказать сохранённый курс от {saved.rates.day:%d.%m.%Y}?", "yesno"):
            return saved
        return None

    def _busy(self, busy: bool) -> None:
        self.loading = busy
        state = "disabled" if busy else "normal"
        for widget in (self.amount_entry, self.day_entry, self.refresh_button, self.earlier_button,
                       self.later_button, self.today_button, self.give_menu, self.get_menu, self.swap_button):
            widget.configure(state=state)
        if busy:
            self.info_label.configure(text=LOADING)
        elif self.quote is None:
            self.info_label.configure(text=NO_RATES)
        self._update_button()

    def _show(self, quote: Quote, keep) -> None:
        self.quote = quote
        currencies = quote.rates.sorted()
        self._by_caption = {currency.caption: currency for currency in currencies}
        captions = list(self._by_caption)
        for menu, previous in zip((self.give_menu, self.get_menu), keep):
            menu.configure(values=captions)
            again = previous and quote.rates.currencies.get(previous.code)
            menu.set(again.caption if again else PICK)

        rates = quote.rates
        self.info_label.configure(text=f"Курс на {rates.day:%d.%m.%Y}  ·  Источник: {rates.source}")
        if quote.offline:
            self._set_notice(f"Без сети: показан сохранённый курс от {rates.day:%d.%m.%Y}, "
                             f"получен {rates.received_at:%d.%m.%Y %H:%M}.")
        elif quote.substituted:
            self._set_notice(f"На {quote.asked_for:%d.%m.%Y} курс не опубликован. "
                             f"Показан последний доступный — от {rates.day:%d.%m.%Y}.")
        else:
            self._set_notice("")
        self._fill_table(currencies)
        self._clear_result()
        self._update_button()

    def _no_rates(self) -> None:
        self.quote = None
        self._by_caption = {}
        for menu in (self.give_menu, self.get_menu):
            menu.configure(values=[PICK])
            menu.set(PICK)
        self.info_label.configure(text=NO_RATES)
        self._set_notice("")
        self._say(self.amount_error, "")
        self._clear_result()
        self._fill_table([])
        self._update_button()

    def _fill_table(self, currencies: list[Currency]) -> None:
        for child in self.table.winfo_children():
            child.destroy()
        self.table_rows = [(c.code, c.title, str(c.units), money.pretty(c.lei, 4, 4)) for c in currencies]
        if not self.table_rows:
            ctk.CTkLabel(self.table, text=NO_RATES, text_color=look.MUTED).grid(row=0, column=0, sticky="w",
                                                                               padx=10, pady=10)
            return
        heads = ("Код", "Валюта", "Номинал", "Курс, MDL")
        for column, head in enumerate(heads):
            ctk.CTkLabel(self.table, text=head, text_color=look.MUTED, font=look.font(12, bold=True)).grid(
                row=0, column=column, sticky="e" if column >= 2 else "w", padx=10, pady=(6, 4))
        for row, cells in enumerate(self.table_rows, start=1):
            for column, cell in enumerate(cells):
                ctk.CTkLabel(self.table, text=cell, font=look.font(13, bold=column == 0)).grid(
                    row=row, column=column, sticky="e" if column >= 2 else "w", padx=10, pady=1)

    # --- пересчёт --------------------------------------------------------------

    def _changed(self) -> None:
        # Изменили ввод — прежний результат и ошибка больше не верны.
        self._say(self.amount_error, "")
        self._clear_result()
        self._update_button()

    def _can_convert(self) -> bool:
        return (not self.loading and self.quote is not None and bool(self.amount.get().strip())
                and self.chosen(self.give_menu) is not None and self.chosen(self.get_menu) is not None)

    def _update_button(self) -> None:
        self.convert_button.configure(state="normal" if self._can_convert() else "disabled")

    def convert(self) -> None:
        give, get = self.chosen(self.give_menu), self.chosen(self.get_menu)
        if give is None or get is None:
            return
        try:
            amount = money.parse_amount(self.amount.get())
        except AmountProblem as problem:
            self._clear_result()
            self._say(self.amount_error, str(problem))
            return
        self._say(self.amount_error, "")
        self._say(self.result_label, money.describe_exchange(amount, give, money.exchange(amount, give, get), get))
        self._say(self.rate_label, money.describe_rate(give, get))
