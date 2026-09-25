"""Явные запреты на под-узлах ``hr.employees.*`` у четырёх кадровых ролей и
узел перевода — фикс-раунд 1 задачи 9 блока I (рулинги F и G контроллера).

Что было не так. ``0005`` засеяла ``hr-junior``…``hr-lead`` строками ровно
по старым ключам ``LEVEL_PRESETS`` (``apps.hr.legacy_roles.nodes_for_level``),
но глубина в реестре НАСЛЕДУЕТСЯ вниз (``apps/access/services/resolve.py::
_nearest``): под-узел без собственной строки берёт признаки ближайшего
предка, а «пустой набор» на найденном предке — это ЗАПРЕТ. Под-узлы
``hr.employees.{salary,passport,family,identity}`` строк не получили там, где
старый уровень этих ключей не давал, — и унаследовали ``hr.employees``:
junior видел зарплату, паспорт и семью, middle их правил и писал
идентичность в обход подтверждения (``hr.identity.force`` по замыслу не
входил ни в один уровень), senior/lead — тоже обход. Пока старая модель
прав стояла рядом «И-И», расширение было невидимо; задача 9 её сняла
(``apps.hr.rbac``), и §6 её отчёта перечислил расхождения.

Что делает миграция. Кладёт в КАЖДУЮ из четырёх ролей явные строки с
четырьмя ``False`` на тех под-узлах, где старый пресет права не давал, —
именно в каждую роль, а не только в младшую: признаки по узлу объединяются
по всем ролям вызывающего (``resolve.flags_for``), и запрет действует только
внутри той роли, что выдала право на предка. ``hr.employees.family`` у
middle/senior/lead и ``.salary``/``.passport`` у senior/lead уже имеют явные
строки EDIT из ``0005`` — они не трогаются.

Рулинг G — узел перевода. ``EMPLOYEES_TRANSFER`` вёл на ``("hr.employees",
EDIT)`` — тот же узел и признак, что ``EMPLOYEES_EDIT``, — поэтому middle
переводил и увольнял, хотя старая матрица давала это с senior. Заведён
под-узел ``hr.employees.transfer`` (``apps/hr/access_functions.py``,
``legacy_roles.KEY_TO_NODE``): senior/lead получают на нём EDIT
(``can_view``+``can_edit``), junior/middle — явный запрет (иначе middle
унаследовал бы EDIT от ``hr.employees``).

Сверка с ``LEVEL_PRESETS`` по каждому ключу — ``apps/access/tests/
test_hr_level_roles_exact.py`` (красный до этой миграции, зелёный после).
Идемпотентна (``update_or_create`` по ``(role, node)``, как ``0005``);
обратная операция удаляет ровно эти строки. Роли, которых нет (сид ``0005``
не прошёл), молча пропускаются — заводить их здесь значило бы завести
роль без остальных её прав.
"""

from django.db import migrations

_ALL_FLAGS = ("can_view", "can_create", "can_edit", "can_delete")
DENY: tuple[str, ...] = ()
EDIT = ("can_view", "can_edit")

#: ``код роли -> (узел -> признаки)``. Сверено с ``apps/hr/permissions.py::
#: LEVEL_PRESETS`` по каждому ключу под-узла:
#: * junior — ни одного ``hr.card.*``, ни ``hr.identity.force``, ни
#:   ``hr.employees.transfer`` → запрет на всех пяти под-узлах;
#: * middle — ``hr.card.groups.*`` ЕСТЬ (``hr.employees.family`` — явная
#:   строка EDIT в 0005, не трогаем), остальных нет → запрет на четырёх;
#: * senior/lead — ``hr.card.financial/personal.*`` и перевод ЕСТЬ
#:   (``.salary``/``.passport`` — явные EDIT в 0005), ``hr.identity.force``
#:   — нет → запрет только на ``.identity``, EDIT на ``.transfer``.
ROLE_NODES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "hr-junior": (
        ("hr.employees.salary", DENY),
        ("hr.employees.passport", DENY),
        ("hr.employees.family", DENY),
        ("hr.employees.identity", DENY),
        ("hr.employees.transfer", DENY),
    ),
    "hr-middle": (
        ("hr.employees.salary", DENY),
        ("hr.employees.passport", DENY),
        ("hr.employees.identity", DENY),
        ("hr.employees.transfer", DENY),
    ),
    "hr-senior": (
        ("hr.employees.identity", DENY),
        ("hr.employees.transfer", EDIT),
    ),
    "hr-lead": (
        ("hr.employees.identity", DENY),
        ("hr.employees.transfer", EDIT),
    ),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")

    for code, nodes in ROLE_NODES.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for node, flags in nodes:
            RolePermission.objects.update_or_create(
                role=role, node=node,
                defaults={flag: flag in flags for flag in _ALL_FLAGS},
            )


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")

    for code, nodes in ROLE_NODES.items():
        RolePermission.objects.filter(
            role__code=code, node__in=[node for node, _flags in nodes],
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0007_positionrole_scope_kind_choices"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
