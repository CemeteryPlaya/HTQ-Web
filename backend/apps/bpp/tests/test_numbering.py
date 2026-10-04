"""Годовые номера документов без дублей (§13.3, D-11)."""

import threading

import pytest
from django.db import connection

from apps.bpp.services.core.numbering import next_number


@pytest.mark.django_db
def test_numbers_grow_inside_a_year(company_context):
    assert next_number("СЧ", year=2026) == "СЧ-2026-000001"
    assert next_number("СЧ", year=2026) == "СЧ-2026-000002"
    assert next_number("ДГ", year=2026) == "ДГ-2026-000001"


@pytest.mark.django_db
def test_year_starts_a_new_counter(company_context):
    next_number("СЧ", year=2026)
    assert next_number("СЧ", year=2027) == "СЧ-2027-000001"


@pytest.mark.django_db
def test_width_is_configurable(company_context):
    assert next_number("ВП", year=2026, width=4) == "ВП-2026-0001"


@pytest.mark.django_db(transaction=True)
def test_parallel_numbers_are_unique():
    """20 потоков, по своему соединению каждый: номера не повторяются."""
    got: list[str] = []
    lock = threading.Lock()

    def worker():
        try:
            number = next_number("ЗЗ", year=2026)
            with lock:
                got.append(number)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(got) == 20 and len(set(got)) == 20
