from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from fxconv.archive import RateArchive
from fxconv.bnm import SOURCE, BadAnswer, BnmFeed, DailyRates, NoConnection, NothingPublished, read_bnm_xml
from fxconv.money import LEU, Currency
from fxconv.provider import RateProvider

NOW = datetime(2026, 11, 11, 12, 0, 0)
TODAY = date(2026, 11, 11)
XML = ('<ValCurs Date="11.11.2026">'
       "<Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Name>US Dollar</Name><Value>17.7575</Value></Valute>"
       "<Valute><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Japanese Yen</Name><Value>11.9438</Value></Valute>"
       "</ValCurs>")


def daily(day: date) -> DailyRates:
    return DailyRates(day, SOURCE, datetime(day.year, day.month, day.day, 13, 0),
                      {"MDL": LEU, "USD": Currency("USD", "US Dollar", 1, Decimal("17.7575"))})


# --- разбор ответа ----------------------------------------------------------------

def test_xml_gives_day_currencies_and_leu():
    rates = read_bnm_xml(XML, NOW)

    assert rates.day == TODAY and rates.received_at == NOW and rates.source == SOURCE
    assert [c.code for c in rates.sorted()] == ["JPY", "MDL", "USD"]
    assert rates.currencies["JPY"].lei_per_unit == Decimal("0.119438")


def test_xml_without_currencies_means_nothing_for_that_day():
    assert read_bnm_xml('<ValCurs Date="11.11.2026"/>', NOW) is None


@pytest.mark.parametrize("xml", ["", "<html/>", "not xml", "<ValCurs/>", '<ValCurs Date="2026-11-11"/>',
                                 '<ValCurs Date="31.02.2026"><Valute/></ValCurs>',
                                 '<ValCurs Date="11.11.2026"><Valute><CharCode>US</CharCode></Valute></ValCurs>'])
def test_broken_xml_is_bad_answer(xml):
    with pytest.raises(BadAnswer):
        read_bnm_xml(xml, NOW)


@pytest.mark.parametrize("code, units, lei", [("US1", "1", "1.5"), ("EUR", "0", "1.5"), ("EUR", "1", "abc"),
                                               ("EUR", "1", "1,5"), ("EUR", "1", "0")])
def test_broken_currency_is_skipped(code, units, lei):
    xml = (f'<ValCurs Date="11.11.2026"><Valute><CharCode>{code}</CharCode><Nominal>{units}</Nominal>'
           f"<Value>{lei}</Value></Valute><Valute><CharCode>USD</CharCode><Nominal>1</Nominal>"
           "<Value>17.7575</Value></Valute></ValCurs>")

    assert sorted(read_bnm_xml(xml, NOW).currencies) == ["MDL", "USD"]


# --- HTTP ---------------------------------------------------------------------------

def feed(status=200, body=XML, error=None, asked=None):
    def transport(url):
        if asked is not None:
            asked.append(url)
        if error:
            raise error
        return status, body
    return BnmFeed(transport, clock=lambda: NOW)


def test_feed_asks_the_right_address_and_parses():
    asked = []

    rates = feed(asked=asked).rates_for(date(2026, 1, 5))

    assert asked == ["https://www.bnm.md/en/official_exchange_rates?get_xml=1&date=05.01.2026"]
    assert rates.currencies["USD"].lei == Decimal("17.7575")


def test_feed_404_means_nothing_for_that_day():
    assert feed(status=404, body="").rates_for(TODAY) is None


@pytest.mark.parametrize("source", [feed(status=500), feed(error=ConnectionError("down"))])
def test_feed_errors_and_no_connection_are_no_connection(source):
    with pytest.raises(NoConnection):
        source.rates_for(TODAY)


def test_feed_garbage_is_bad_answer():
    with pytest.raises(BadAnswer):
        feed(body="<html>maintenance</html>").rates_for(TODAY)


# --- архив --------------------------------------------------------------------------

def test_archive_survives_restart(tmp_path):
    RateArchive(tmp_path / "a" / "last.json").keep(daily(TODAY))

    restored = RateArchive(tmp_path / "a" / "last.json").restore()

    assert restored == daily(TODAY)


@pytest.mark.parametrize("content", ["", "null", "{", "[]", '{"day": "2026-11-11"}',
                                     '{"day": "2026-11-11", "source": "x", "received_at": "2026-11-11T10:00:00",'
                                     ' "currencies": {"USD": ["US Dollar", 0, "17"]}}',
                                     '{"day": "2026-11-11", "source": "x", "received_at": "2026-11-11T10:00:00",'
                                     ' "currencies": {}}'])
def test_archive_ignores_broken_file(tmp_path, content):
    path = tmp_path / "last.json"
    path.write_text(content, encoding="utf-8")

    assert RateArchive(path).restore() is None


def test_archive_missing_or_busy_file_is_empty(tmp_path, opened_in_excel):
    archive = RateArchive(tmp_path / "last.json")
    assert archive.restore() is None

    archive.keep(daily(TODAY))
    with opened_in_excel(archive.path):
        assert archive.restore() is None


# --- выбор курса ---------------------------------------------------------------------

class Feed:
    def __init__(self, *days, fail=None, fail_on=None):
        self.days, self.fail, self.fail_on, self.asked = set(days), fail, fail_on, []

    def rates_for(self, day):
        self.asked.append(day)
        if self.fail and self.fail_on in (None, day):
            raise self.fail
        return daily(day) if day in self.days else None


class Archive:
    def __init__(self, saved=None, broken=False):
        self.saved, self.broken, self.kept = saved, broken, 0

    def keep(self, rates):
        self.kept += 1
        if self.broken:
            raise OSError("диск полон")
        self.saved = rates

    def restore(self):
        return self.saved


def provider(feed_, archive=None):
    return RateProvider(feed_, archive or Archive(), today=lambda: TODAY)


def test_quote_for_published_day():
    quote = provider(Feed(TODAY)).quote(TODAY)

    assert quote.rates.day == TODAY and not quote.substituted and not quote.offline


def test_quote_goes_back_to_last_published_day():
    source = Feed(TODAY - timedelta(days=3))

    quote = provider(source).quote(TODAY)

    assert quote.rates.day == TODAY - timedelta(days=3) and quote.substituted
    assert len(source.asked) == 4


def test_future_day_starts_from_today():
    source = Feed(TODAY)

    quote = provider(source).quote(TODAY + timedelta(days=40))

    assert source.asked == [TODAY] and quote.substituted


def test_gives_up_after_eleven_days():
    source = Feed(TODAY - timedelta(days=11))

    with pytest.raises(NothingPublished):
        provider(source).quote(TODAY)
    assert len(source.asked) == 11


def test_connection_problem_stops_the_search():
    source = Feed(TODAY - timedelta(days=2), fail=NoConnection(), fail_on=TODAY - timedelta(days=1))

    with pytest.raises(NoConnection):
        provider(source).quote(TODAY)
    assert source.asked == [TODAY, TODAY - timedelta(days=1)]


def test_good_quote_is_archived_and_archive_failure_is_harmless():
    archive = Archive()
    provider(Feed(TODAY), archive).quote(TODAY)
    assert archive.saved.day == TODAY

    assert provider(Feed(TODAY), Archive(broken=True)).quote(TODAY).rates.day == TODAY


def test_from_archive_marks_offline():
    quote = provider(Feed(), Archive(daily(TODAY - timedelta(days=4)))).from_archive(TODAY)

    assert quote.offline and not quote.substituted
    assert provider(Feed(), Archive()).from_archive(TODAY) is None
