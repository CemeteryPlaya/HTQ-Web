"""Движок праздников РК: правила должны воспроизводить прежние данные.

Главный тест здесь — ``test_2026_matches_the_hardcoded_table``. До этого
модуля праздники были захардкожены одним словарём на 2026 год
(``KZ_HOLIDAYS_2026`` в ``apps.tasks.services.production_calendar``); его
золотая копия лежит ниже. Пока она сходится дата-в-дату, замена таблицы на
движок не меняет ни один уже посчитанный дедлайн — а всё остальное
(2025, 2027, 2035) получается тем же кодом.
"""
from datetime import date

from apps.core import kz_holidays

# Дословная копия удалённого KZ_HOLIDAYS_2026. Не «упрощать» и не
# пересчитывать движком — весь смысл в том, что это независимый эталон.
KZ_HOLIDAYS_2026 = {
    date(2026, 1, 1): "Новый год",
    date(2026, 1, 2): "Новый год",
    date(2026, 1, 7): "Православное Рождество",
    date(2026, 3, 8): "Международный женский день",
    date(2026, 3, 9): "Международный женский день (перенос)",
    date(2026, 3, 21): "Наурыз мейрамы",
    date(2026, 3, 22): "Наурыз мейрамы",
    date(2026, 3, 23): "Наурыз мейрамы",
    date(2026, 3, 24): "Наурыз мейрамы (перенос)",
    date(2026, 3, 25): "Наурыз мейрамы (перенос)",
    date(2026, 5, 1): "Праздник единства народа Казахстана",
    date(2026, 5, 7): "День защитника Отечества",
    date(2026, 5, 9): "День Победы",
    date(2026, 5, 11): "День Победы (перенос)",
    date(2026, 5, 27): "Курбан-айт",
    date(2026, 7, 6): "День Столицы",
    date(2026, 8, 30): "День Конституции Республики Казахстан",
    date(2026, 8, 31): "День Конституции Республики Казахстан (перенос)",
    date(2026, 10, 25): "День Республики",
    date(2026, 10, 26): "День Республики (перенос)",
    date(2026, 12, 16): "День Независимости",
}


def test_2026_matches_the_hardcoded_table():
    assert dict(kz_holidays.holidays_for_year(2026)) == KZ_HOLIDAYS_2026


def test_every_year_has_holidays():
    """Ровно та поломка, ради которой всё затевалось: за 2026-м календарь
    вырождался в пн-пт/сб-вс без единого праздника."""
    for year in (2025, 2027, 2031, 2040):
        days = kz_holidays.holidays_for_year(year)
        assert date(year, 1, 1) in days
        assert date(year, 12, 16) in days
        # 14 фиксированных дат минимум; переносы и Курбан-айт сверх того.
        assert len(days) >= len(kz_holidays.KZ_FIXED_HOLIDAYS)


def test_weekend_holiday_transfers_to_the_next_working_day():
    # 25 октября 2027 — понедельник, переноса быть не должно.
    days_2027 = kz_holidays.holidays_for_year(2027)
    assert days_2027[date(2027, 10, 25)] == "День Республики"
    assert date(2027, 10, 26) not in days_2027

    # 1 января 2028 — суббота, 2 января — воскресенье: два переноса подряд,
    # причём 3 января (пн) занимать нельзя дважды.
    days_2028 = kz_holidays.holidays_for_year(2028)
    assert days_2028[date(2028, 1, 3)] == "Новый год (перенос)"
    assert days_2028[date(2028, 1, 4)] == "Новый год (перенос)"


def test_transfer_targets_accumulate_across_a_holiday_block():
    """21 и 22 марта 2026 — сб и вс, 23-е уже праздник: переносы обязаны
    разъехаться на 24 и 25, а не схлопнуться в один день."""
    days = kz_holidays.holidays_for_year(2026)
    assert days[date(2026, 3, 24)] == "Наурыз мейрамы (перенос)"
    assert days[date(2026, 3, 25)] == "Наурыз мейрамы (перенос)"


def test_year_override_adds_a_movable_holiday_and_its_transfer():
    """Курбан-айт 2027 приходится на воскресенье — перенос обязан появиться
    и у плавающего праздника, а не только у фиксированных."""
    days = kz_holidays.holidays_for_year(2027)
    assert days[date(2027, 5, 16)] == "Курбан-айт"
    assert days[date(2027, 5, 17)] == "Курбан-айт (перенос)"


def test_year_override_can_remove_a_day(monkeypatch):
    """``None`` в таблице года снимает даже авто-перенос — так чинится
    расхождение с постановлением правительства без правки движка."""
    monkeypatch.setitem(kz_holidays.KZ_YEAR_OVERRIDES, 2099,
                        {date(2099, 1, 7): None})
    kz_holidays.holidays_for_year.cache_clear()
    try:
        days = kz_holidays.holidays_for_year(2099)
        assert date(2099, 1, 7) not in days
        assert date(2099, 1, 1) in days
    finally:
        kz_holidays.holidays_for_year.cache_clear()


def test_point_lookups_pick_the_year_from_the_date():
    assert kz_holidays.is_holiday(date(2027, 3, 22))
    assert kz_holidays.holiday_note(date(2029, 1, 1)) == "Новый год"
    assert not kz_holidays.is_holiday(date(2027, 2, 11))
    assert kz_holidays.holiday_note(date(2027, 2, 11)) is None


# ── исходный день переноса (D-S7-7: банковские дни) ──────────────────────

def test_transfer_source_remembers_the_original_holiday_day():
    # Наурыз 2026: 21.03 (сб) и 22.03 (вс) переносятся на 24.03 и 25.03.
    assert kz_holidays.transfer_source(date(2026, 3, 24)) == date(2026, 3, 21)
    assert kz_holidays.transfer_source(date(2026, 3, 25)) == date(2026, 3, 22)
    assert kz_holidays.transfer_source(date(2026, 3, 21)) is None   # сам праздник
    assert kz_holidays.transfer_source(date(2026, 3, 26)) is None   # обычный день
    assert kz_holidays.transfer_source(date(2026, 3, 23)) is None   # праздник в будний день


def test_transfer_source_weekday_tells_saturday_from_sunday():
    assert kz_holidays.transfer_source(date(2026, 3, 24)).weekday() == 5
    assert kz_holidays.transfer_source(date(2026, 3, 25)).weekday() == 6


def test_transfer_source_is_consistent_with_holiday_note():
    for year in (2025, 2026, 2027):
        for day, name in kz_holidays.holidays_for_year(year).items():
            is_transfer = name.endswith(kz_holidays.TRANSFER_SUFFIX)
            assert (kz_holidays.transfer_source(day) is not None) == is_transfer, day


def test_transfer_source_dropped_when_year_override_replaces_the_target(monkeypatch):
    monkeypatch.setitem(kz_holidays.KZ_YEAR_OVERRIDES, 2026,
                        {**kz_holidays.KZ_YEAR_OVERRIDES[2026], date(2026, 3, 24): None})
    kz_holidays.holidays_for_year.cache_clear()
    try:
        assert kz_holidays.transfer_source(date(2026, 3, 24)) is None
        assert kz_holidays.transfer_source(date(2026, 3, 25)) == date(2026, 3, 22)
    finally:
        kz_holidays.holidays_for_year.cache_clear()
