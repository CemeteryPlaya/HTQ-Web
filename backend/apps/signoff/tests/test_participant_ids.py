"""``interface.participant_subject_ids`` — «кто согласующий» пачкой (БЗО, D-S8-3).

Поиск договоров для привлечения партнёра проверяет участие в согласовании не
на каждую строку, а одной выборкой. Правило участия при этом одно:
``is_participant`` выражена через ту же функцию и отвечает так же.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.signoff import interface
from apps.signoff.models import ApprovalRoute, Quorum
from apps.signoff.services import engine
from apps.signoff.tests.helpers import SUBJECT, make_doc, make_route, make_user
from apps.signoff.tests.testapp.models import UuidProbeDoc

pytestmark = pytest.mark.django_db

UUID_SUBJECT = UuidProbeDoc.SIGNOFF_SUBJECT_TYPE


def _start(subject_type, doc, user):
    make_route([(1, "Единственный", Quorum.ALL, [user.pk])], subject_type=subject_type)
    return engine.start(subject_type=subject_type, subject_id=doc.pk, initiator_id=99)


def test_returns_the_subset_of_input_ids_as_they_were_given():
    a, b = make_user("a"), make_user("b")
    mine, theirs, untouched = (UuidProbeDoc.objects.create(title=t) for t in "абв")
    _start(UUID_SUBJECT, mine, a)
    # Второй процесс того же типа — у другого согласующего.
    ApprovalRoute.objects.filter(subject_type=UUID_SUBJECT).update(is_active=False)
    _start(UUID_SUBJECT, theirs, b)
    asked = [str(mine.pk).upper(), str(theirs.pk), str(untouched.pk), "мусор",
             str(uuid.uuid4())]

    found = interface.participant_subject_ids(a.pk, UUID_SUBJECT, asked)

    # Ключ — как его передали (верхний регистр сохранён), невозможный —
    # пропущен, а не роняет весь ответ.
    assert found == {str(mine.pk).upper()}
    assert interface.participant_subject_ids(b.pk, UUID_SUBJECT, asked) == {str(theirs.pk)}
    for key in asked[:3] + asked[4:]:
        assert interface.is_participant(a.pk, UUID_SUBJECT, key) == (key in found)
        assert interface.is_participant(b.pk, UUID_SUBJECT, key) == (key == str(theirs.pk))


def test_integer_keys_and_any_spelling_of_one_object():
    a = make_user("a")
    doc = make_doc()
    other = make_doc()
    _start(SUBJECT, doc, a)

    found = interface.participant_subject_ids(a.pk, SUBJECT,
                                              [str(doc.pk), f"0{doc.pk}", other.pk])
    assert found == {str(doc.pk), f"0{doc.pk}"}
    assert interface.is_participant(a.pk, SUBJECT, doc.pk)
    assert not interface.is_participant(a.pk, SUBJECT, other.pk)


def test_other_subject_type_with_the_same_key_does_not_count():
    a = make_user("a")
    doc = make_doc()
    _start(SUBJECT, doc, a)
    assert interface.participant_subject_ids(a.pk, "testapp.other", [str(doc.pk)]) == set()


def test_one_query_whatever_the_number_of_ids():
    a = make_user("a")
    docs = [UuidProbeDoc.objects.create(title=str(n)) for n in range(12)]
    make_route([(1, "Единственный", Quorum.ALL, [a.pk])], subject_type=UUID_SUBJECT)
    for doc in docs[::2]:
        engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk, initiator_id=99)
    interface.participant_subject_ids(a.pk, UUID_SUBJECT, [str(docs[0].pk)])   # прогрев

    with CaptureQueriesContext(connection) as few:
        assert len(interface.participant_subject_ids(
            a.pk, UUID_SUBJECT, [str(d.pk) for d in docs[:2]])) == 1
    with CaptureQueriesContext(connection) as many:
        assert len(interface.participant_subject_ids(
            a.pk, UUID_SUBJECT, [str(d.pk) for d in docs])) == 6
    assert len(few) == len(many) == 1


def test_empty_input_needs_no_query():
    with CaptureQueriesContext(connection) as ctx:
        assert interface.participant_subject_ids(1, UUID_SUBJECT, []) == set()
        assert interface.participant_subject_ids(1, UUID_SUBJECT, ["мусор"]) == set()
    assert [q for q in ctx.captured_queries if "signoff_approvaltask" in q["sql"]] == []


def test_disabled_signoff_raises():
    ServiceStatus.objects.update_or_create(app_label="signoff", defaults={"enabled": False})
    cache.clear()
    with pytest.raises(ServiceDisabled):
        interface.participant_subject_ids(1, UUID_SUBJECT, [str(uuid.uuid4())])
