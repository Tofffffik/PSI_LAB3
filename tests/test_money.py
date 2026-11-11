from decimal import Decimal

import pytest

from fxconv.money import (
    LEU, AmountProblem, Currency, describe_exchange, describe_rate, exchange, parse_amount, pretty, rate_between)

USD = Currency("USD", "US Dollar", 1, Decimal("17.7575"))
EUR = Currency("EUR", "Euro", 1, Decimal("20.1512"))
JPY = Currency("JPY", "Japanese Yen", 100, Decimal("11.9438"))


@pytest.mark.parametrize("text, expected", [
    ("100", "100"), ("99,50", "99.5"), ("99.50", "99.5"), (" 42 ", "42"), ("0,001", "0.001"), ("1000000000000", "1E12"),
])
def test_amount_accepts_positive_numbers_with_dot_or_comma(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text, message", [
    (None, "Введите сумму."), ("", "Введите сумму."), ("  ", "Введите сумму."),
    ("abc", "числом"), ("1 000", "числом"), ("1e5", "числом"), ("+5", "числом"), (".5", "числом"), ("5,", "числом"),
    ("١٢٣", "числом"), ("0", "больше нуля"), ("0,00", "больше нуля"), ("-5", "больше нуля"), ("-0,01", "больше нуля"),
    ("1000000000000,01", "слишком большая"), ("9" * 40, "слишком большая"),
])
def test_amount_rejects_with_clear_message(text, message):
    with pytest.raises(AmountProblem, match=message):
        parse_amount(text)


def test_exchange_both_directions_and_cross():
    assert exchange(Decimal(100), USD, LEU) == Decimal("1775.75")
    assert exchange(Decimal("1775.75"), LEU, USD) == Decimal("100.00")
    assert exchange(Decimal(100), EUR, USD) == Decimal("113.48")


def test_exchange_respects_nominal_and_same_currency():
    assert exchange(Decimal(1000), JPY, LEU) == Decimal("119.44")
    assert exchange(Decimal("12.345"), USD, USD) == Decimal("12.35")
    assert rate_between(USD, USD) == 1


@pytest.mark.parametrize("amount", ["1", "99.5", "12345.67"])
@pytest.mark.parametrize("give, get", [(USD, LEU), (LEU, USD), (EUR, JPY)])
def test_round_trip_differs_only_by_rounding(amount, give, get):
    value = Decimal(amount)
    back = exchange(exchange(value, give, get), get, give)

    assert abs(back - value) <= Decimal("0.005") * rate_between(get, give) + Decimal("0.005")


@pytest.mark.parametrize("value, least, most, expected", [
    ("1775.75", 2, 2, "1 775,75"), ("100", 0, 6, "100"), ("99.50", 0, 6, "99,5"), ("1000000", 0, 6, "1 000 000"),
    ("0.0563141", 4, 6, "0,056314"), ("1", 4, 6, "1,0000"), ("17757500000000", 2, 2, "17 757 500 000 000,00"),
])
def test_pretty_numbers(value, least, most, expected):
    assert pretty(Decimal(value), least, most) == expected


def test_result_lines():
    assert describe_exchange(Decimal(100), USD, Decimal("1775.75"), LEU) == "100 USD = 1 775,75 MDL"
    assert describe_rate(USD, LEU) == "1 USD = 17,7575 MDL"
    assert describe_rate(LEU, USD) == "1 MDL = 0,056314 USD"
