"""Функции домена задач для реестра прав (``apps.access.registry``)."""

FUNCTIONS = (
    ("tasks.tasks", "Задачи"),
    ("tasks.daily_reports", "Ежедневные отчёты"),
    ("tasks.roadmap", "Роудмапы"),
    ("tasks.projects", "Проекты"),
    ("tasks.sites", "Объекты и площадки"),
    ("tasks.equipment", "Техника"),
    ("tasks.contractors", "Подрядчики"),
    ("tasks.resources", "Потребности в ресурсах"),
    ("tasks.staff_reports", "Отчёты по персоналу"),
    ("tasks.reports", "Отчётность"),
    ("tasks.calendar", "Календарь и события"),

    # Только чтение: сводка по группе ничего не создаёт и не правит, и
    # предлагать для неё create/edit/delete в редакторе ролей было бы ложью.
    # Та же форма, что у ``hr.holding``.
    ("tasks.holding", "Задачи: сводка по группе", ("view",)),
)
