"""Валюты, сумма, пересчёт и красивый вывод чисел.

Деньги — только ``Decimal``. Разбор и вывод не зависят от региональных
настроек компьютера.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

LIMIT = Decimal("1000000000000")
_AMOUNT = re.compile(r"(?P<minus>-?)(?P<whole>[0-9]+)(?:[.,](?P<fraction>[0-9]+))?")


class AmountProblem(ValueError):
    """Сумма не принята; текст исключения — что сказать пользователю."""


@dataclass(frozen=True)
class Currency:
    code: str
    title: str
    units: int          # за сколько единиц указан курс
    lei: Decimal        # сколько леев стоят ``units`` единиц

    @property
    def lei_per_unit(self) -> Decimal:
        return self.lei / self.units

    @property
    def caption(self) -> str:
        """Пункт выпадающего списка: «USD · US Dollar»."""
        return f"{self.code} · {self.title}"


LEU = Currency("MDL", "Moldovan Leu", 1, Decimal(1))


def parse_amount(text: str | None) -> Decimal:
    """Положительное число, дробная часть через точку или запятую,
    пробелы по краям допускаются, максимум — триллион."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise AmountProblem("Введите сумму.")
    match = _AMOUNT.fullmatch(cleaned)
    if not match:
        raise AmountProblem("Сумма должна быть числом, например 100 или 99,50.")
    if match["minus"]:
        raise AmountProblem("Сумма должна быть больше нуля.")
    try:
        amount = Decimal(f"{match['whole']}.{match['fraction'] or '0'}")
    except InvalidOperation as error:  # на практике не случается: строка уже проверена
        raise AmountProblem("Сумма должна быть числом, например 100 или 99,50.") from error
    if amount > LIMIT:
        raise AmountProblem("Сумма слишком большая (максимум 1 000 000 000 000).")
    if amount == 0:
        raise AmountProblem("Сумма должна быть больше нуля.")
    return amount


def rate_between(give: Currency, get: Currency) -> Decimal:
    """Сколько единиц ``get`` дают за одну единицу ``give``."""
    return Decimal(1) if give.code == get.code else give.lei_per_unit / get.lei_per_unit


def exchange(amount: Decimal, give: Currency, get: Currency) -> Decimal:
    """Пересчёт через лей, округление до сотых (половина — вверх по модулю)."""
    return (amount * rate_between(give, get)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pretty(value: Decimal, least: int, most: int) -> str:
    """Число с пробелами между тысячами и запятой: от ``least`` до ``most``
    знаков после запятой, лишние нули отбрасываются."""
    rounded = value.quantize(Decimal(1).scaleb(-most), rounding=ROUND_HALF_UP)
    sign, digits = ("-", -rounded) if rounded < 0 else ("", rounded)
    whole, _, fraction = format(digits, "f").partition(".")
    fraction = fraction.rstrip("0").ljust(least, "0")
    groups = []
    while len(whole) > 3:
        whole, tail = whole[:-3], whole[-3:]
        groups.insert(0, tail)
    grouped = " ".join([whole, *groups])
    return f"{sign}{grouped},{fraction}" if fraction else f"{sign}{grouped}"


def describe_exchange(amount: Decimal, give: Currency, result: Decimal, get: Currency) -> str:
    """«100 USD = 1 775,75 MDL»."""
    return f"{pretty(amount, 0, 6)} {give.code} = {pretty(result, 2, 2)} {get.code}"


def describe_rate(give: Currency, get: Currency) -> str:
    """«1 USD = 17,7575 MDL»."""
    return f"1 {give.code} = {pretty(rate_between(give, get), 4, 6)} {get.code}"
