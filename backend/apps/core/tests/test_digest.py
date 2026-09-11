"""Форматирование утренней сводки.

Тесты без базы и без сети: ``digest.render`` принимает словари, а не модели, —
ради этого форматирование и вынесено из задачи в отдельный модуль. Отправку
(и её отказ) проверяет ``test_tasks``-часть, здесь только текст.
"""
from __future__ import annotations

import datetime as dt

from apps.core import digest

NOW = dt.datetime(2026, 9, 3, 9, 0, tzinfo=dt.timezone.utc)


def _snapshot(overdue: int, unhandled: int = 0) -> dict:
    return {
        "tasks": {
            "tasks_overdue": {"values": [((), overdue)]},
        },
        "cms": {
            "cms_contact_requests_unhandled": {"values": [((), unhandled)]},
        },
    }


def test_delta_against_yesterday_is_shown():
    """Смысл сводки — сравнение, а не текущее значение."""
    text = digest.render(_snapshot(31), _snapshot(35), now=NOW)
    assert "31" in text
    assert "−4" in text          # U+2212, не дефис


def test_growth_is_marked_with_a_plus():
    text = digest.render(_snapshot(40), _snapshot(35), now=NOW)
    assert "+5" in text


def test_delta_is_omitted_without_a_baseline():
    """Первый выпуск и выпуск после вытеснения кэша — без скобок, а не «(+0)»."""
    text = digest.render(_snapshot(31), None, now=NOW)
    assert "31" in text
    assert "(" not in text.split("Задачи")[-1].split("\n")[1]


def test_unchanged_values_carry_no_delta_at_all():
    """Молчание = «не изменилось».

    Пометка «без изменений» стоит у большинства строк и забивает те немногие,
    ради которых сводку и читают.
    """
    text = digest.render(_snapshot(31), _snapshot(31), now=NOW)
    assert "31" in text
    assert "(" not in text


def test_metric_absent_from_snapshot_draws_no_line():
    """Выключенный домен не должен выглядеть как «ноль»."""
    text = digest.render(_snapshot(3), None, now=NOW)
    # В снимке нет ни contracts, ни hr — их разделов быть не должно.
    assert "Деньги" not in text
    assert "Люди" not in text


def test_empty_snapshot_says_so_instead_of_reporting_zeros():
    """Пустой снимок — это «сборщик встал», а не «всё по нулям»."""
    text = digest.render({}, None, now=NOW)
    assert "Данных нет" in text
    assert "backend-beat" in text


def test_money_is_formatted_with_currency():
    snapshot = {"contracts": {
        "contracts_accountable_funds_outstanding": {"values": [((), 1234567)]}}}
    text = digest.render(snapshot, None, now=NOW)
    assert "₸" in text
    assert "1" in text and "234" in text     # разряды разделены


def test_dashboard_link_appears_only_with_a_base_url():
    assert "grafana" not in digest.render(_snapshot(1), None, now=NOW)
    text = digest.render(_snapshot(1), None, now=NOW, base_url="https://htq.group/")
    assert "https://htq.group/grafana/d/htqweb-domains" in text
