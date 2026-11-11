"""Откуда взять курс: источник, предыдущие дни, архив."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .archive import RateArchive
from .bnm import BnmFeed, DailyRates, NothingPublished

DAYS_BACK = 10


@dataclass(frozen=True)
class Quote:
    rates: DailyRates
    asked_for: date
    offline: bool = False   # курс из архива, сеть недоступна

    @property
    def substituted(self) -> bool:
        """Источник дал курс за другую дату, чем просили."""
        return not self.offline and self.rates.day != self.asked_for


class RateProvider:
    def __init__(self, feed: BnmFeed, archive: RateArchive, today: Callable[[], date] = date.today) -> None:
        self._feed = feed
        self._archive = archive
        self._today = today

    def quote(self, day: date) -> Quote:
        """Курс на ``day``. Нет курса — ищем раньше, но не дальше 10 дней
        (не больше 11 запросов); будущая дата начинается с сегодня.
        Удачный ответ кладётся в архив. Сбой источника — ``SourceProblem``."""
        first = min(day, self._today())
        for back in range(DAYS_BACK + 1):
            rates = self._feed.rates_for(first - timedelta(days=back))
            if rates is not None:
                try:
                    self._archive.keep(rates)
                except OSError:
                    pass  # не смогли сохранить — свежий курс всё равно показываем
                return Quote(rates, day)
        raise NothingPublished()

    def from_archive(self, day: date) -> Quote | None:
        rates = self._archive.restore()
        return Quote(rates, day, offline=True) if rates else None
