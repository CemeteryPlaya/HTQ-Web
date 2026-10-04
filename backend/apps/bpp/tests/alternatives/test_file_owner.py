"""КП альтернативы в ``apps.files`` и доступ к журналу АП и KPI (план этапа
5 A, задача 1).

- Владелец ``bpp.alternative_offer``: правила §21/§12.3 и колбэки — менять
  КП может только автор и только в «Черновике», черновик видит только он.
- Проверки журнала регистрируются путём импорта строкой
  (``file_owner.HISTORY_CHECKS``) и разрешаются при чтении журнала. Пути
  закреплены здесь: задачи 4 и 5 обязаны создать ровно
  ``alternatives.read.can_view`` и ``alternatives.kpi.can_view``, а как
  только модуль появился — путь обязан разрешаться в функцию (иначе журнал
  отвечал бы 500, а не 404).
"""

from __future__ import annotations

import importlib
import itertools
import importlib.util
import uuid
from types import SimpleNamespace

import pytest
from django.utils.module_loading import import_string

from apps.bpp.models import AlternativeOffer, KpiRecord, OfferStatus
from apps.bpp.services.alternatives import file_owner
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.files import interface as files
from apps.files.services import registry

_SEED = importlib.import_module("apps.files.migrations.0005_bpp_alternative_offer_type")

_SEQ = itertools.count(700001)

PINNED_HISTORY_CHECKS = {
    "bpp.alternativeoffer": (AlternativeOffer, "apps.bpp.services.alternatives.read.can_view"),
    "bpp.kpirecord": (KpiRecord, "apps.bpp.services.alternatives.kpi.can_view"),
}


# ── журнал ──────────────────────────────────────────────────────────────

def test_history_check_paths_are_pinned():
    """Задачи 4 и 5 создают проверки ровно по этим путям; перенос функции —
    правка здесь и в ``HISTORY_CHECKS`` одновременно, а не молчаливый 500."""
    assert file_owner.HISTORY_CHECKS == PINNED_HISTORY_CHECKS


def test_history_access_is_registered_at_startup():
    for object_type in PINNED_HISTORY_CHECKS:
        assert object_type in audit._HISTORY_ACCESS, object_type


@pytest.mark.parametrize("object_type", sorted(PINNED_HISTORY_CHECKS))
def test_history_check_path_resolves_once_its_module_exists(object_type):
    _model, path = PINNED_HISTORY_CHECKS[object_type]
    module_name, _, _attr = path.rpartition(".")
    if importlib.util.find_spec(module_name) is None:
        pytest.skip(f"{module_name} ещё не создан (задачи 4/5 этапа 5 A)")
    assert callable(import_string(path)), path


@pytest.mark.django_db
def test_history_of_unknown_or_malformed_key_is_closed():
    request = SimpleNamespace(token=SimpleNamespace(user_id=501), company=None)
    for object_type in PINNED_HISTORY_CHECKS:
        assert audit.can_view_history(request, object_type, "not-a-uuid") is False
        assert audit.can_view_history(request, object_type, str(uuid.uuid4())) is False


# ── владелец КП ─────────────────────────────────────────────────────────

def test_owner_is_registered_by_tz_rules():
    entry = registry.get_owner(file_owner.OWNER)
    assert (entry.tenant, entry.service, entry.folder) == (
        True, "bpp_alternatives", "alternative-offer")
    (spec,) = entry.file_types
    assert (spec.code, spec.cardinality, spec.max_documents, spec.required) == (
        "alternative_offer", files.MULTI, 5, True)
    assert core_files.owner_type_of(AlternativeOffer()) == file_owner.OWNER


def test_kp_type_seed_follows_tz_12_3():
    """ТЗ §12.3: КП — PDF, JPG, PNG, DOCX до 10 МБ (без XLSX — это вложения
    заявки, тип ``request_attachment``)."""
    ((code, owner, _name, formats, max_mb, _order),) = _SEED.TYPES
    assert (code, owner, max_mb) == ("alternative_offer", file_owner.OWNER, 10)
    assert set(formats) == {".pdf", ".docx", ".jpg", ".jpeg", ".png"}


def _offer(status=OfferStatus.DRAFT, author_id=501) -> AlternativeOffer:
    return AlternativeOffer.objects.create(
        number=f"АП-2026-{next(_SEQ):06d}", source_type="invoice",
        source_id=uuid.uuid4(), author_id=author_id, author_role="sn", status=status)


def _token(user_id: int):
    return SimpleNamespace(user_id=user_id, is_superuser=False)


@pytest.mark.django_db
def test_only_author_changes_kp_and_only_in_draft():
    draft = _offer()
    assert file_owner._can_modify(draft.pk, _token(501)) is None
    with pytest.raises(files.FilesForbidden):
        file_owner._can_modify(draft.pk, _token(777))
    with pytest.raises(files.FilesForbidden):
        file_owner._can_modify(uuid.uuid4(), _token(501))

    submitted = _offer(OfferStatus.SUBMITTED)
    with pytest.raises(files.FilesLocked) as exc:
        file_owner._can_modify(submitted.pk, _token(501))
    assert "КП меняется только в черновике АП" in str(exc.value)


@pytest.mark.django_db
def test_draft_is_seen_by_author_only():
    draft = _offer()
    assert file_owner._can_view(draft.pk, _token(501)) is True
    assert file_owner._can_view(draft.pk, _token(777)) is False
    assert file_owner._can_view(uuid.uuid4(), _token(501)) is False


@pytest.mark.django_db
@pytest.mark.parametrize("status,sent", [
    (OfferStatus.DRAFT, False), (OfferStatus.SUBMITTED, True),
    (OfferStatus.WITHDRAWN, True), (OfferStatus.ANNULLED, True),
])
def test_was_sent_is_anything_but_draft(status, sent):
    assert file_owner._was_sent(_offer(status).pk) is sent


@pytest.mark.django_db
def test_was_sent_of_missing_offer_is_false():
    assert file_owner._was_sent(uuid.uuid4()) is False
