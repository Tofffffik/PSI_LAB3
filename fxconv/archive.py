"""Архив последнего успешно полученного курса (JSON).

Переживает перезапуск. Если файла нет или он испорчен — архив пуст.
"""

import json
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .bnm import DailyRates
from .money import Currency


def default_location() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "fxconv" / "last-rates.json"


class RateArchive:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def keep(self, rates: DailyRates) -> None:
        """Перезаписывает архив. Может бросить ``OSError``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "day": rates.day.isoformat(),
            "source": rates.source,
            "received_at": rates.received_at.isoformat(timespec="seconds"),
            "currencies": {c.code: [c.title, c.units, str(c.lei)] for c in rates.sorted()},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def restore(self) -> DailyRates | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            currencies = {}
            for code, (title, units, lei) in payload["currencies"].items():
                currency = Currency(str(code), str(title), int(units), Decimal(str(lei)))
                if currency.units <= 0 or currency.lei <= 0:
                    return None
                currencies[currency.code] = currency
            if not currencies or not str(payload["source"]).strip():
                return None
            return DailyRates(date.fromisoformat(payload["day"]), str(payload["source"]),
                              datetime.fromisoformat(payload["received_at"]), currencies)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
            return None
