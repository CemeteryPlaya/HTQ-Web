"""EICAR против НАСТОЯЩЕГО clamd (A7.4, D-31) — для ручного прогона на стенде.

Без ``ANTIVIRUS_E2E_HOST`` пропускается (в CI и локально clamd нет). Прогон на
стенде ``test-local`` — внутри контейнера backend, где имя ``clamav`` видно по
сети compose::

    docker compose -f docker-compose.test-local.yml --profile antivirus up -d --no-deps clamav
    docker compose -f docker-compose.test-local.yml exec -e ANTIVIRUS_E2E_HOST=clamav \
        backend-web python -m pytest -q -p no:cacheprovider apps/core/tests/test_antivirus_live.py

EICAR склеен из частей: целая строка в файле заставила бы антивирус хоста
удалить сам тест.
"""

from __future__ import annotations

import os

import pytest

from apps.core import infrastructure
from htqweb import antivirus

HOST = os.environ.get("ANTIVIRUS_E2E_HOST", "")

pytestmark = pytest.mark.skipif(not HOST, reason="нужен ANTIVIRUS_E2E_HOST (настоящий clamd)")

EICAR = (
    r"X5O!P%@AP[4\PZX54(P^)7CC)7}$"
    + "EICAR-STANDARD-ANTIVIRUS-"
    + "TEST-FILE!$H+H*"
).encode()


@pytest.fixture(autouse=True)
def _live(settings):
    settings.ANTIVIRUS_CLAMD_HOST = HOST
    settings.ANTIVIRUS_CLAMD_PORT = int(os.environ.get("ANTIVIRUS_E2E_PORT", "3310"))
    settings.ANTIVIRUS_TIMEOUT = 30


def test_ping_is_green():
    assert infrastructure.active_checks()["clamav"]() == ("ok", "PONG")


def test_clean_bytes_pass():
    assert antivirus.scan(b"%PDF-1.4\n% clean document\n").clean is True


def test_eicar_is_found():
    verdict = antivirus.scan(EICAR)
    assert verdict.clean is False
    assert "EICAR" in verdict.signature.upper()


def test_pipeline_refuses_eicar_with_422_and_counts_it():
    """Тот же путь, что у загрузки документа: ``_scan`` → 422 (код E-FIL-08
    ставит файловая подсистема поверх ``FileInfected``)."""
    from prometheus_client import REGISTRY

    from apps.media_files.services import upload_service
    from apps.media_files.services.scope_policy import ScopePolicy

    def count():
        return REGISTRY.get_sample_value(
            "htqweb_antivirus_scans_total", {"verdict": "infected"}) or 0.0

    before = count()
    with pytest.raises(upload_service.FileInfected) as err:
        upload_service._scan(EICAR, "eicar.pdf", ScopePolicy(name="file_object", antivirus=True))
    assert err.value.status_code == 422
    assert count() == before + 1
