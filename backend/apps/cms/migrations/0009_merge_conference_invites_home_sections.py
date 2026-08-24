"""Схождение двух веток миграций cms после мерджа ruslan -> pre-production.

На 0004 граф разошёлся: ruslan добавил ``0005_conference_invites``
(ConferenceInvite), pre-production — цепочку ``0005_homesection...`` ->
``0008_mark_system_sections`` (управляемый лендинг). Ветки независимы и не
пересекаются по таблицам, поэтому схождение пустое: операций нет, миграция
существует только чтобы у графа снова был ОДИН лист.

Без неё ``migrate`` падает с ``Conflicting migrations detected: multiple leaf
nodes``, то есть не применяется вообще ничего — ни на тестовой, ни на боевой.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0005_conference_invites'),
        ('cms', '0008_mark_system_sections'),
    ]

    operations = [
    ]
