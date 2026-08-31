"""Функции конструктора заявок для реестра прав (``apps.access.registry``)."""

FUNCTIONS = (
    ("approvals.requests", "Заявки"),
    ("approvals.templates", "Шаблоны заявок"),
    ("approvals.projects", "Проекты заявок"),
    ("approvals.reference", "Справочники"),
    # Решение по адресованной заявке — действие: его либо принимают, либо нет.
    ("approvals.decisions", "Решения по адресованным заявкам", ("view",)),
    ("approvals.stats", "Моя статистика"),
)
