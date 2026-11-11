"""Официальный курс Национального банка Молдовы (XML по HTTP)."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .money import LEU, Currency

SOURCE = "Национальный банк Молдовы (bnm.md)"


class SourceProblem(Exception):
    """Курс получить не удалось; текст — для пользователя."""


class NoConnection(SourceProblem):
    def __init__(self) -> None:
        super().__init__("Нет связи с источником курсов. Проверьте подключение к интернету.")


class BadAnswer(SourceProblem):
    def __init__(self) -> None:
        super().__init__("Источник курсов прислал некорректные данные.")


class NothingPublished(SourceProblem):
    def __init__(self) -> None:
        super().__init__("Источник не опубликовал курс за 10 дней до выбранной даты.")


@dataclass(frozen=True)
class DailyRates:
    day: date
    source: str
    received_at: datetime
    currencies: dict[str, Currency] = field(default_factory=dict)

    def sorted(self) -> list[Currency]:
        return [self.currencies[code] for code in sorted(self.currencies)]


# (адрес) -> (HTTP-код, тело); нет связи или тайм-аут — ConnectionError.
Transport = Callable[[str], tuple[int, str]]


def internet(url: str) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "fxconv/1.0"})
    try:
        with urlopen(request, timeout=10) as reply:
            return reply.status, reply.read().decode("utf-8", "replace")
    except HTTPError as error:
        return error.code, ""
    except (URLError, OSError) as error:  # OSError включает тайм-аут
        raise ConnectionError(error) from error


def read_bnm_xml(xml: str, received_at: datetime) -> DailyRates | None:
    """Разбор ответа. ``None`` — в ответе нет валют (курса на дату нет);
    испорченный документ — ``BadAnswer``. Повреждённая валюта
    пропускается, лей добавляется как базовая валюта."""
    try:
        root = ElementTree.fromstring(xml or "")
        if root.tag != "ValCurs":
            raise BadAnswer()
        day = datetime.strptime(root.attrib.get("Date", ""), "%d.%m.%Y").date()
    except (ElementTree.ParseError, ValueError) as error:
        raise BadAnswer() from error

    items = root.findall("Valute")
    if not items:
        return None

    currencies: dict[str, Currency] = {}
    for item in items:
        currency = _currency(item)
        if currency and currency.code not in currencies:
            currencies[currency.code] = currency
    if not currencies:
        raise BadAnswer()
    currencies.setdefault(LEU.code, LEU)
    return DailyRates(day, SOURCE, received_at, currencies)


def _currency(item) -> Currency | None:
    code = (item.findtext("CharCode") or "").strip().upper()
    units = (item.findtext("Nominal") or "").strip()
    lei = (item.findtext("Value") or "").strip()
    title = (item.findtext("Name") or "").strip() or code
    if not (re.fullmatch(r"[A-Z]{3}", code) and re.fullmatch(r"[0-9]+", units)
            and re.fullmatch(r"[0-9]+(\.[0-9]+)?", lei)):
        return None
    if int(units) == 0 or Decimal(lei) == 0:
        return None
    return Currency(code, title, int(units), Decimal(lei))


class BnmFeed:
    def __init__(self, transport: Transport = internet, clock: Callable[[], datetime] = datetime.now) -> None:
        self._transport = transport
        self._clock = clock

    @staticmethod
    def address(day: date) -> str:
        return f"https://www.bnm.md/en/official_exchange_rates?get_xml=1&date={day:%d.%m.%Y}"

    def rates_for(self, day: date) -> DailyRates | None:
        """Курсы на дату; ``None`` — на эту дату курса нет (у BNM это 404)."""
        try:
            status, body = self._transport(self.address(day))
        except ConnectionError as error:
            raise NoConnection() from error
        if status == 404:
            return None
        if status != 200:
            raise NoConnection()
        return read_bnm_xml(body, self._clock())
