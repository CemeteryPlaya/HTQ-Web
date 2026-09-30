"""Отчёт переноса (B6.1): что перенесено, что нет и почему, сверка остатков.

Разделы копятся по ходу переноса и в конце уходят в xlsx (``--report``) —
тот же файл читают на репетиции переноса на дампе. Колонки раздела заданы
здесь, а не у вызывающих: иначе один раздел собрал бы строки разной формы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SECTIONS: dict[str, tuple[str, ...]] = {
    "Проекты": ("admin_id", "project_name", "project_code", "action"),
    "Контрагенты": ("old_id", "reg_number", "name", "action"),
    "Бюджеты": ("admin_id", "project_code", "years", "number", "status"),
    "Документы": ("kind", "old_id", "old_number", "new_number", "status"),
    "Переотправить": ("kind", "new_number", "author_id"),
    "Не перенесено": ("kind", "old_id", "reason"),
    "Сверка": ("project_code", "article_code", "old_limit", "old_committed", "old_remaining",
               "new_limit", "new_committed", "new_remaining", "expected_diff", "diff"),
    "Ожидаемые расхождения": ("project_code", "article_code", "kind", "number", "delta",
                              "reason"),
}


@dataclass
class MigrationReport:
    rows: dict[str, list[dict]] = field(default_factory=lambda: {name: [] for name in SECTIONS})

    def add(self, section: str, **row) -> None:
        unknown = set(row) - set(SECTIONS[section])
        if unknown:
            raise KeyError(f"Раздел «{section}»: нет колонок {sorted(unknown)}")
        self.rows[section].append(row)

    def count(self, section: str, **match) -> int:
        return sum(1 for row in self.rows[section]
                   if all(row.get(key) == value for key, value in match.items()))

    def write_xlsx(self, path: Path) -> None:
        from openpyxl import Workbook

        book = Workbook()
        book.remove(book.active)
        for name, columns in SECTIONS.items():
            sheet = book.create_sheet(name)
            sheet.append(list(columns))
            for row in self.rows[name]:
                sheet.append([row.get(column) for column in columns])
        book.save(path)
