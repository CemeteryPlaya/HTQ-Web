"""Владельцы файлов подмодулей ``bpp`` подключаются сами (план этапа 3 A,
задача 1, решение D-S3-1).

Документ подмодуля объявляет себя владельцем файлов в
``services/<подмодуль>/file_owner.py`` функцией ``register()``, и
``file_owners.register()`` (из ``BppConfig.ready()``) находит такие модули
сам — так же, как ``models/*.py`` и ``urls_*.py`` (``test_autodiscovery``):
у двух исполнителей нет общей строки в ``file_owners.py``.

Устройство проверяется на подставном пакете ``services`` на диске
(``tmp_path``): обход идёт по настоящим файлам, а список сегодняшних
подмодулей тест не держит — он вырастет без правки этого файла.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
import uuid

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.bpp import file_owners
from apps.files.services import registry

PROBE_OWNER = "bpp.discovery_probe"

_REGISTERS_ITSELF = """
    from apps.files import interface as files


    def register():
        files.register_owner(
            "bpp.discovery_probe", label="Проба автоподключения", service="bpp",
            tenant=False, folder="bpp-discovery-probe",
            file_types=(files.FileTypeSpec("bpp_probe.discovery"),),
            can_view=lambda *a: True, can_modify=lambda *a: None,
            was_sent=lambda *a: False, lock=lambda *a: None)
"""

_RECORDS_CALL = """
    from .. import CALLS


    def register():
        CALLS.append(__name__.split(".")[-2])
"""


class _Services:
    """Подставной пакет ``services``: ``add("x", body)`` — подпакет ``x`` с
    ``file_owner.py`` (``body=None`` — подпакет без него)."""

    def __init__(self, root, name):
        self.root, self.name = root, name

    def add(self, sub: str, body: str | None = None, *, init: str | None = "") -> None:
        """``init=None`` — папка без ``__init__.py``."""
        pkg = self.root / sub
        pkg.mkdir()
        if init is not None:
            (pkg / "__init__.py").write_text(textwrap.dedent(init), encoding="utf-8")
        if body is not None:
            (pkg / "file_owner.py").write_text(textwrap.dedent(body), encoding="utf-8")

    @property
    def calls(self) -> list[str]:
        return importlib.import_module(self.name).CALLS


@pytest.fixture
def services(tmp_path, monkeypatch):
    name = f"bpp_fo_probe_{uuid.uuid4().hex[:8]}"
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("CALLS = []\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(file_owners, "SERVICES_PACKAGE", name)
    yield _Services(root, name)
    for module in [m for m in sys.modules if m == name or m.startswith(f"{name}.")]:
        del sys.modules[module]
    registry._OWNERS.pop(PROBE_OWNER, None)


def test_probe_file_owner_registers_itself(services):
    """Подмодуль ``probe`` с ``file_owner.py`` — и владелец уже в
    ``apps.files`` после обычного ``file_owners.register()``: строку в
    ``file_owners.py`` под него не пишут."""
    services.add("probe", _REGISTERS_ITSELF)

    file_owners.register()

    entry = registry.get_owner(PROBE_OWNER)
    assert entry.folder == "bpp-discovery-probe"
    # Свои владельцы модуля никуда не делись.
    assert registry.get_owner(file_owners.REQUEST_OWNER)
    assert registry.get_owner(file_owners.REPORT_OWNER)


def test_file_owners_are_called_in_alphabetical_order(services):
    for sub in ("zeta", "alpha", "mid"):
        services.add(sub, _RECORDS_CALL)

    file_owners.register()

    assert services.calls == ["alpha", "mid", "zeta"]


def test_only_packages_with_a_file_owner_module_are_picked(services):
    """Подпакет без ``file_owner.py`` не импортируется вовсе (его
    ``__init__`` здесь падал бы), приватный ``_x`` и простой модуль пакета
    пропускаются, ``file_owner`` — подпакет, а не модуль — тоже."""
    services.add("alpha", _RECORDS_CALL)
    services.add("no_owner", init="raise RuntimeError('не должен импортироваться')\n")
    services.add("_private", _RECORDS_CALL)
    (services.root / "plain.py").write_text("raise RuntimeError('модуль')\n",
                                            encoding="utf-8")
    services.add("pkg_owner")
    (services.root / "pkg_owner" / "file_owner").mkdir()
    (services.root / "pkg_owner" / "file_owner" / "__init__.py").write_text(
        "raise RuntimeError('подпакет')\n", encoding="utf-8")

    assert file_owners._file_owner_modules() == [f"{services.name}.alpha.file_owner"]
    file_owners.register()
    assert services.calls == ["alpha"]


def test_file_owner_without_register_is_improperly_configured(services):
    services.add("broken", "OWNER = 'bpp.broken'\n")

    with pytest.raises(ImproperlyConfigured) as exc_info:
        file_owners.register()

    assert f"{services.name}.broken.file_owner" in str(exc_info.value)
    assert "register()" in str(exc_info.value)


def test_file_owner_in_a_folder_without_init_is_improperly_configured(services):
    """Папку без ``__init__.py`` ``pkgutil`` пакетом не считает — владелец
    не подключился бы молча, и файлы документа отвечали бы 404. Поэтому —
    отказ запуска с именем папки, а не пропуск."""
    services.add("alpha", _RECORDS_CALL)
    services.add("bank", _RECORDS_CALL, init=None)

    with pytest.raises(ImproperlyConfigured) as exc_info:
        file_owners.register()

    assert f"{services.name}.bank" in str(exc_info.value)
    assert "__init__.py" in str(exc_info.value)


def test_folder_without_init_and_without_file_owner_is_not_an_error(services):
    """Папка без ``__init__.py`` сама по себе — не подмодуль с владельцем
    (шаблоны, данные): её не трогают."""
    services.add("alpha", _RECORDS_CALL)
    services.add("templates_only", init=None)

    assert file_owners._file_owner_modules() == [f"{services.name}.alpha.file_owner"]


def test_real_file_owner_modules_are_well_formed():
    """Настоящие ``services/*/file_owner.py`` (договор и счёт — B, выписка —
    A): имя по соглашению, порядок — по алфавиту, у каждого есть
    ``register()``."""
    names = file_owners._file_owner_modules()

    assert names == sorted(names)
    for name in names:
        assert name.startswith("apps.bpp.services.") and name.endswith(".file_owner")
        assert callable(getattr(importlib.import_module(name), "register", None)), name
