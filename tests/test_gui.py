"""UI-тесты «Обмена валют»: настоящее окно за пределами экрана, подставные
источник и архив. Тест вводит сумму, выбирает валюты и дату, нажимает
кнопки и проверяет, что видно. Сеть не используется, диалоги подменены."""

import time
import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal

import customtkinter as ctk
import pytest

from fxconv.bnm import SOURCE, DailyRates, NoConnection
from fxconv.gui import look
from fxconv.gui.window import NO_RATES, PICK, FxWindow
from fxconv.money import LEU, Currency
from fxconv.provider import RateProvider

TODAY = date.today()


def d(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def daily(day: date, received: datetime | None = None) -> DailyRates:
    return DailyRates(day, SOURCE, received or datetime(day.year, day.month, day.day, 14, 0), {
        "EUR": Currency("EUR", "Euro", 1, Decimal("20.1512")),
        "MDL": LEU,
        "USD": Currency("USD", "US Dollar", 1, Decimal("17.7575")),
    })


class Feed:
    def __init__(self):
        self.gaps: set[date] = set()
        self.offline = False
        self.calls = 0

    def rates_for(self, day):
        self.calls += 1
        if self.offline:
            raise NoConnection()
        return None if day in self.gaps else daily(day)


class Archive:
    def __init__(self):
        self.saved = None

    def keep(self, rates):
        self.saved = rates

    def restore(self):
        return self.saved


class Screen:
    def __init__(self, host):
        self.host, self.feed, self.archive = host, Feed(), Archive()
        self.asked: list[tuple[str, str]] = []
        self.answer = True
        self.window: FxWindow | None = None

    def open(self) -> FxWindow:
        self.window = FxWindow(self.host, RateProvider(self.feed, self.archive, today=lambda: TODAY),
                               ask=self._ask, today=lambda: TODAY)
        self.loaded(0)
        return self.window

    def _ask(self, text, kind):
        self.asked.append((kind, text))
        return self.answer

    def wait(self, condition, what, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise TimeoutError(f"Не дождались: {what}")
            self.host.update()
            time.sleep(0.01)

    def loaded(self, calls_before):
        self.wait(lambda: self.feed.calls > calls_before and not self.window.loading, "загрузка курса")

    def press(self, button):
        assert button.cget("state") == "normal", f"кнопка «{button.cget('text')}» недоступна"
        calls = self.feed.calls
        button.invoke()
        self.host.update()
        return calls

    def press_and_load(self, button):
        self.loaded(self.press(button))

    def convert(self, amount, give, get):
        self.window.amount.set(amount)
        self.window.choose(self.window.give_menu, give)
        self.window.choose(self.window.get_menu, get)
        self.press(self.window.convert_button)

    def text(self, label):
        return label.cget("text")


@pytest.fixture(scope="session")
def app():
    look.setup()
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def screen(app):
    host = tk.Toplevel(app)
    host.geometry("+-20000+-20000")
    yield Screen(host)
    host.destroy()


def info(day):
    return f"Курс на {d(day)}  ·  Источник: Национальный банк Молдовы (bnm.md)"


def test_start_loads_today_and_fills_lists_and_table(screen):
    window = screen.open()

    assert screen.text(window.info_label) == info(TODAY)
    assert list(window.give_menu.cget("values")) == ["EUR · Euro", "MDL · Moldovan Leu", "USD · US Dollar"]
    assert window.give_menu.get() == PICK and window.get_menu.get() == PICK
    assert window.convert_button.cget("state") == "disabled"
    assert [row[0] for row in window.table_rows] == ["EUR", "MDL", "USD"]
    assert window.table_rows[2] == ("USD", "US Dollar", "1", "17,7575")
    assert not window.shown(window.notice) and screen.asked == []


def test_button_needs_amount_and_two_currencies(screen):
    window = screen.open()

    window.amount.set("100")
    assert window.convert_button.cget("state") == "disabled"
    window.choose(window.give_menu, "USD")
    assert window.convert_button.cget("state") == "disabled"
    window.choose(window.get_menu, "MDL")
    assert window.convert_button.cget("state") == "normal"
    window.amount.set("  ")
    assert window.convert_button.cget("state") == "disabled"


def test_convert_both_ways(screen):
    window = screen.open()

    screen.convert("100", "USD", "MDL")
    assert screen.text(window.result_label) == "100 USD = 1 775,75 MDL"
    assert screen.text(window.rate_label) == "1 USD = 17,7575 MDL"

    screen.convert("1775,75", "MDL", "USD")
    assert screen.text(window.result_label) == "1 775,75 MDL = 100,00 USD"


def test_swap_button_exchanges_currencies(screen):
    window = screen.open()
    window.choose(window.give_menu, "USD")
    window.choose(window.get_menu, "EUR")

    screen.press(window.swap_button)

    assert window.chosen(window.give_menu).code == "EUR" and window.chosen(window.get_menu).code == "USD"


def test_same_currency_gives_same_amount(screen):
    window = screen.open()

    screen.convert("50", "EUR", "EUR")

    assert screen.text(window.result_label) == "50 EUR = 50,00 EUR"


@pytest.mark.parametrize("amount, message", [("abc", "числом"), ("-5", "больше нуля"), ("0", "больше нуля")])
def test_bad_amount_shows_error_and_hides_result(screen, amount, message):
    window = screen.open()
    screen.convert("100", "USD", "MDL")

    screen.convert(amount, "USD", "MDL")

    assert window.shown(window.amount_error) and message in screen.text(window.amount_error)
    assert not window.shown(window.result_label)


def test_editing_hides_old_result(screen):
    window = screen.open()
    screen.convert("100", "USD", "MDL")

    window.amount.set("150")

    assert not window.shown(window.result_label)


def test_future_day_shows_todays_rate_with_warning(screen):
    window = screen.open()
    future = TODAY + timedelta(days=20)

    window.pick_day(future)
    screen.loaded(screen.feed.calls - 1)

    assert screen.text(window.info_label) == info(TODAY)
    assert screen.text(window.notice_label) == (f"На {d(future)} курс не опубликован. "
                                                f"Показан последний доступный — от {d(TODAY)}.")


def test_day_buttons_move_and_return_to_today(screen):
    window = screen.open()

    screen.press_and_load(window.earlier_button)
    assert screen.text(window.info_label) == info(TODAY - timedelta(days=1))

    screen.press_and_load(window.today_button)
    assert screen.text(window.info_label) == info(TODAY)


def test_gap_day_falls_back_and_warns(screen):
    window = screen.open()
    gap = TODAY - timedelta(days=2)
    screen.feed.gaps.add(gap)

    window.pick_day(gap)
    screen.loaded(screen.feed.calls - 1)

    assert "Показан последний доступный — от " + d(gap - timedelta(days=1)) in screen.text(window.notice_label)


def test_wrong_date_text_is_reported_without_loading(screen):
    window = screen.open()
    calls = screen.feed.calls

    window.day_text.set("40.40.2026")
    window.reload()

    assert window.shown(window.day_error) and "ДД.ММ.ГГГГ" in screen.text(window.day_error)
    assert screen.feed.calls == calls


def test_offline_with_archive_accepted(screen):
    saved_day = TODAY - timedelta(days=3)
    screen.archive.saved = daily(saved_day, datetime(saved_day.year, saved_day.month, saved_day.day, 9, 41))
    screen.feed.offline = True

    window = screen.open()

    [(kind, text)] = screen.asked
    assert kind == "yesno" and "Нет связи с источником" in text and d(saved_day) in text
    assert screen.text(window.notice_label) == (f"Без сети: показан сохранённый курс от {d(saved_day)}, "
                                                f"получен {d(saved_day)} 09:41.")
    screen.convert("100", "USD", "MDL")
    assert screen.text(window.result_label) == "100 USD = 1 775,75 MDL"


def test_offline_with_archive_declined(screen):
    screen.archive.saved = daily(TODAY - timedelta(days=3))
    screen.feed.offline = True
    screen.answer = False

    window = screen.open()

    assert screen.text(window.info_label) == NO_RATES
    assert window.table_rows == [] and window.convert_button.cget("state") == "disabled"
    assert window.refresh_button.cget("state") == "normal"


def test_offline_without_archive_says_so(screen):
    screen.feed.offline = True

    window = screen.open()

    [(kind, text)] = screen.asked
    assert kind == "ok" and "Сохранённого курса нет" in text
    assert screen.text(window.info_label) == NO_RATES


def test_refresh_when_back_online_replaces_saved_rate(screen):
    screen.archive.saved = daily(TODAY - timedelta(days=3))
    screen.feed.offline = True
    window = screen.open()

    screen.feed.offline = False
    screen.press_and_load(window.refresh_button)

    assert not window.shown(window.notice)
    assert screen.text(window.info_label) == info(TODAY) and screen.archive.saved.day == TODAY


def test_reload_keeps_chosen_currencies(screen):
    window = screen.open()
    window.choose(window.give_menu, "USD")
    window.choose(window.get_menu, "EUR")

    screen.press_and_load(window.refresh_button)

    assert window.chosen(window.give_menu).code == "USD" and window.chosen(window.get_menu).code == "EUR"
