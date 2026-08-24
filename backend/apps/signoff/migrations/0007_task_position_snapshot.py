"""Snapshot each task's resolved HR position for role-scoped quorums.

Existing tasks deliberately remain null: their holder-to-position association
was not recorded at process start, and retroactively resolving it from the
current organisation chart would rewrite an in-flight approval's meaning.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signoff", "0006_position_based_approvers"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvaltask",
            name="position_id",
            field=models.IntegerField(
                blank=True, db_index=True, null=True,
                verbose_name="Position of approver",
            ),
        ),
    ]
