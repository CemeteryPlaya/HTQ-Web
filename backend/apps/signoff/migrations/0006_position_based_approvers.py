"""Routes target HR positions; live tasks keep their resolved user ids.

Existing route assignments are converted where the former platform account is
linked to an employee.  Unlinked accounts cannot be guessed into a business
position and are deliberately omitted: the route remains visible to an admin
but must be repaired before it can start.
"""

import django.db.models.deletion

from django.db import migrations, models


def copy_account_assignments_to_positions(apps, schema_editor):
    LegacyApprover = apps.get_model("signoff", "ApprovalRouteStageApprover")
    RouteRole = apps.get_model("signoff", "ApprovalRouteStageRole")
    Employee = apps.get_model("hr", "Employee")

    user_positions = dict(
        Employee.objects.exclude(user_id__isnull=True)
        .values_list("user_id", "position_id")
    )
    seen = set()
    rows = []
    for assignment in LegacyApprover.objects.all().iterator():
        position_id = user_positions.get(assignment.user_id)
        key = (assignment.stage_id, position_id)
        if position_id is not None and key not in seen:
            seen.add(key)
            rows.append(RouteRole(stage_id=assignment.stage_id,
                                  position_id=position_id))
    RouteRole.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0016_remove_employeecard_certs"),
        ("signoff", "0005_stage_requires_comment"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalRouteStageRole",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                         serialize=False, verbose_name="ID")),
                ("position_id", models.IntegerField(db_index=True,
                                                    verbose_name="Должность")),
                ("stage", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name="roles",
                                             to="signoff.approvalroutestage")),
            ],
            options={
                "verbose_name": "Должность согласующего",
                "verbose_name_plural": "Должности согласующих",
                "ordering": ("id",),
                "constraints": [
                    models.UniqueConstraint(fields=("stage", "position_id"),
                                            name="uq_signoff_stage_role"),
                ],
            },
        ),
        migrations.RunPython(copy_account_assignments_to_positions,
                             migrations.RunPython.noop),
        migrations.AlterField(
            model_name="approvalroutestage",
            name="approver_kind",
            field=models.CharField(choices=[("position", "По должности"),
                                            ("initiator", "Инициатор согласования")],
                                   db_default="position", default="position",
                                   help_text="«Инициатор» — список должностей не заполняется, решение принимает отправивший объект на согласование",
                                   max_length=16, verbose_name="Кто согласует"),
        ),
        migrations.AlterField(
            model_name="approvalprocessstage",
            name="approver_kind",
            field=models.CharField(choices=[("position", "По должности"),
                                            ("initiator", "Инициатор согласования")],
                                   db_default="position", default="position", max_length=16),
        ),
        migrations.AddField(
            model_name="approvalprocessstage",
            name="role_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunSQL(
            "UPDATE signoff_approvalroutestage SET approver_kind = 'position' WHERE approver_kind = 'named'",
            "UPDATE signoff_approvalroutestage SET approver_kind = 'named' WHERE approver_kind = 'position'",
        ),
        migrations.RunSQL(
            "UPDATE signoff_approvalprocessstage SET approver_kind = 'position' WHERE approver_kind = 'named'",
            "UPDATE signoff_approvalprocessstage SET approver_kind = 'named' WHERE approver_kind = 'position'",
        ),
        migrations.DeleteModel(name="ApprovalRouteStageApprover"),
    ]
