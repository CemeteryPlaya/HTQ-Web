"""Реестр согласуемых типов — механизм, которым signoff заменяет
межаппный импорт.

Проверяется главным образом то, что реестр НЕ принимает: рассинхрон между
объявленным на модели типом и типом регистрации приводит к процессу,
который никто не найдёт, и ловить его лучше на старте платформы.
"""

from __future__ import annotations

import pytest
from django.db import models

from apps.signoff import interface as signoff
from apps.signoff.services import registry
from apps.signoff.tests.testapp.models import ProbeDoc


def test_registered_subject_exposes_its_model_and_callbacks():
    subject = registry.get_subject(ProbeDoc.SIGNOFF_SUBJECT_TYPE)
    assert subject.model is ProbeDoc
    assert subject.label == "Пробный документ"
    assert subject.on_approved is not None


def test_unknown_subject_names_the_registered_ones():
    with pytest.raises(registry.UnknownSubject, match="testapp.probedoc"):
        registry.get_subject("nosuch.model")


def test_a_model_without_the_mixin_is_refused():
    """``model`` обязан наследовать ``Approvable``: signoff ведёт на нём
    колонку ``approval_state``, которой у чужой модели иначе просто нет."""

    class NotApprovable(models.Model):
        class Meta:
            app_label = "signoff_testapp"
            managed = False

    with pytest.raises(TypeError, match="Approvable"):
        signoff.register_subject("testapp.notapprovable", label="Нет",
                                 model=NotApprovable)


def test_subject_type_must_match_the_one_declared_on_the_model():
    """Рассинхрон тихо разводит ``submit_for_approval()`` и маршрут по
    разным типам — падаем на регистрации, а не на первой заявке."""
    with pytest.raises(ValueError, match="SIGNOFF_SUBJECT_TYPE"):
        signoff.register_subject("testapp.something_else", label="Другое",
                                 model=ProbeDoc)


def test_subject_type_must_be_namespaced():
    with pytest.raises(ValueError, match="subject_type"):
        signoff.register_subject("probedoc", label="Без пространства имён",
                                 model=ProbeDoc)


def test_registering_the_same_type_twice_overwrites_instead_of_failing():
    """``AppConfig.ready()`` при autoreload выполняется не один раз —
    падение на повторной регистрации означало бы, что аппка не поднимается
    по причине, не имеющей отношения к делу.

    Реестр после теста восстанавливается автоматически
    (``restore_subject_registry`` в ``conftest.py``).
    """
    signoff.register_subject(ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                             label="Переопределённый", model=ProbeDoc)
    assert registry.get_subject(ProbeDoc.SIGNOFF_SUBJECT_TYPE).label == \
        "Переопределённый"
