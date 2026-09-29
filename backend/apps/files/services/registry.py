"""Реестр владельцев файлов — какие объекты принимают документы и по каким правилам.

Приём тот же, что у согласования (``apps/signoff/services/registry.py``):
подсистема не импортирует модели владельцев — владелец сам регистрируется
из своего ``AppConfig.ready()`` через ``apps.files.interface.register_owner``
и отдаёт колбэки, которыми подсистема задаёт ему вопросы: видно ли объект,
можно ли сейчас менять его файлы, отправлялся ли он, как заблокировать его
строку. Автопоиск модулей отвергнут по той же причине, что в signoff: он
спрятал бы межаппный импорт от теста изоляции.

Регистрация не трогает БД и не требует включённого сервиса ``files`` —
``ready()`` выполняется до того, как БД доступна, а выключенная подсистема
не должна ронять запуск платформы.

**Права по типу файла** (ТЗ §21: счёт на оплату видят автор, ФД, БУХ, ТД,
ОД, ГД, а АВР и накладную — только автор, ФД и БУХ; закрывающие документы
прикладываются и после оплаты, когда файл счёта уже закрыт). Колбэки
``can_view``/``can_modify`` отвечают про объект целиком и тип файла не
различают, поэтому у владельца есть два необязательных уточнения:

* ``can_view_type(owner_id, token, file_type) -> bool`` — видит ли человек
  документы этого типа. ``False``: документов типа нет в папке и в списке
  типов, ссылка на их версию, новая версия и удаление — 404, как у
  несуществующего документа (существование не раскрываем);
* ``can_modify_type(owner_id, token, file_type) -> bool`` — может ли он
  добавлять, заменять и удалять документы этого типа. Проверяется ПОСЛЕ
  ``can_modify`` (тот остаётся ответом «может ли человек менять в папке хоть
  что-то сейчас» — по нему идёт ранний отказ до разбора multipart), поэтому
  владелец с правом на поздние типы делает ``can_modify`` разрешающим, а
  узкое правило — здесь. ``False`` — 403 ``E-ACC-01`` с общим текстом;
  своё объяснение — поднять ``FilesForbidden`` (403) или ``FilesLocked``
  (409), как в ``can_modify``. Любое ложное значение, включая ``None``, —
  отказ: колбэк обязан вернуть ``True``.

Без них (``None``, умолчание) — как раньше: тип файла на доступ не влияет.
Загрузка из кода (``attach_bytes``/``replace_bytes``) их не спрашивает —
права проверил сам владелец.

**Новая версия — своё правило** (ТЗ §21 у заявки: «удаление — в Черновике /
На доработке; далее только новая версия»). ``can_modify`` отвечает за папку
целиком, и документ, отправленный на согласование, закрыт им для всех
правок — а новая версия документа заявки допустима и после отправки.
Необязательный ``can_version(owner_id, token, file_type) -> bool`` отвечает
только за новую версию уже приложенного документа и, если он есть,
проверяется ВМЕСТО ``can_modify``/``can_modify_type`` на этом пути (ранняя
проверка, после разбора тела и под блокировкой владельца). Отказ — как у
``can_modify_type``: ``FilesForbidden``/``FilesLocked`` со своим текстом или
ложное значение (403 с общим текстом). Без него новая версия подчиняется
тем же правилам, что добавление и удаление. Папка отдаёт у каждого
документа ``can_version`` и ``can_delete`` — чтобы интерфейс не предлагал
то, что сервер отвергнет.

**Политика ошибок колбэков.** ``can_view``/``can_modify``/``was_sent``/
``lock`` (и уточнения по типу) решают доступ и судьбу байтов, поэтому их
исключения НЕ глушатся: упавший колбэк — это 500, а не молча открытый или
молча закрытый доступ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from django.core.exceptions import ValidationError

MULTI = "multi"
SINGLE = "single"

_OWNER_TYPE_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
# Папка владельца становится сегментом ключа в хранилище —
# см. media_files.services.upload_service._FOLDER_RE.
_FOLDER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class UnknownOwner(LookupError):
    """Такого типа владельца никто не регистрировал."""


class BadOwnerId(LookupError):
    """Ключ не подходит модели владельца — ``"abc"`` у объекта с целым
    ключом. Для подсистемы это «объект не найден», а не 500."""


class FilesForbidden(Exception):
    """Владелец: у этого человека нет права менять файлы объекта (403).

    Текст — готовое объяснение для человека (ТЗ §26: что произошло, почему,
    что делать): подсистема отдаёт его как есть.
    """


class FilesLocked(Exception):
    """Владелец: в текущем состоянии объекта файлы менять нельзя (409).

    Текст — готовое объяснение, например «Файлы заявки меняются только в
    статусах «Черновик» и «На доработке».».
    """


@dataclass(frozen=True)
class FileTypeSpec:
    """Правила одного типа файла у владельца — то, чего нет в справочнике.

    ``cardinality``: ``multi`` — сколько угодно документов этого типа (в
    пределах квоты); ``single`` — «1 действующий + версии» (ТЗ §21, файл
    договора): второй документ того же типа не принимается, менять — только
    новой версией. ``quota_group`` — общая квота нескольких типов (у заявки
    «до 20» — на КП, ТЗ, спецификации и прочее вместе); ``max_documents`` —
    предел для одного типа без группы. Версии в квоту не входят.
    ``required`` — обязателен для отправки владельца; проверяет владелец в
    своём переходе (``interface.missing_required``), подсистема лишь
    сообщает.
    """

    code: str
    cardinality: str = MULTI
    quota_group: str | None = None
    max_documents: int | None = None
    required: bool = False


@dataclass(frozen=True)
class OwnerEntry:
    owner_type: str
    label: str
    service: str
    tenant: bool
    folder: str
    file_types: tuple[FileTypeSpec, ...]
    quotas: dict[str, int]
    # (owner_id, token) -> bool. False → 404: существование не раскрываем.
    can_view: Callable
    # (owner_id, token) -> None; поднимает FilesForbidden / FilesLocked.
    can_modify: Callable
    # (owner_id) -> bool. False → удаление физическое.
    was_sent: Callable
    # (owner_id) -> None; SELECT … FOR UPDATE строки владельца внутри atomic.
    lock: Callable
    # (owner_id, event, actor_id, payload) -> None; журнал владельца, в той
    # же транзакции, что и изменение файлов.
    on_event: Callable | None = None
    # Модель владельца — только ради типа её ключа (``native_id``). Без неё
    # ключ целый: так устроены все владельцы, заведённые до модуля БЗО.
    model: type | None = None
    # (owner_id, token, file_type) -> bool. Уточнения по типу файла — см.
    # докстринг модуля; None — тип на доступ не влияет.
    can_view_type: Callable | None = None
    can_modify_type: Callable | None = None
    # (owner_id, token, file_type) -> bool. Новая версия документа — своё
    # правило вместо can_modify/can_modify_type; None — те же правила.
    can_version: Callable | None = None
    _by_code: dict = field(default_factory=dict, compare=False, repr=False)

    def spec(self, code: str) -> FileTypeSpec | None:
        return self._by_code.get(code)

    def native_id(self, owner_id: Any) -> Any:
        """Ключ владельца в типе ключа ЕГО модели: ``"5"`` → ``5``, строка
        UUID → ``UUID`` (документы модуля БЗО адресуются UUID, мастер-план
        D-05). Колбэки владельца получают ключ именно таким, а в
        ``FileObject.owner_id`` он хранится строкой — ``str(native_id(…))``,
        поэтому ``5``, ``"5"`` и ``"05"`` адресуют одну папку."""
        try:
            if self.model is None:
                return int(owner_id)
            return self.model._meta.pk.to_python(owner_id)
        except (TypeError, ValueError, ValidationError) as exc:
            raise BadOwnerId(
                f"«{owner_id}» не может быть ключом объекта «{self.label}»") from exc

    def storage_id(self, owner_id: Any) -> str:
        """Ключ владельца так, как его хранит ``FileObject.owner_id``."""
        return str(self.native_id(owner_id))


_OWNERS: dict[str, OwnerEntry] = {}


def register_owner(owner_type: str, *, label: str, service: str, tenant: bool,
                   folder: str, file_types: tuple[FileTypeSpec, ...],
                   quotas: dict[str, int] | None = None,
                   can_view: Callable, can_modify: Callable,
                   was_sent: Callable, lock: Callable,
                   on_event: Callable | None = None,
                   model: type | None = None,
                   can_view_type: Callable | None = None,
                   can_modify_type: Callable | None = None,
                   can_version: Callable | None = None) -> OwnerEntry:
    """Зарегистрировать тип владельца. Повторная регистрация перезаписывает:
    ``ready()`` может выполниться дважды.

    ``model`` нужна владельцу с НЕцелым ключом (UUID у документов модуля
    БЗО): по ней подсистема приводит ключ к типу модели. Без неё ключ целый.
    ``can_view_type``/``can_modify_type`` — права по типу файла, ``can_version``
    — правило новой версии (см. докстринг модуля); все необязательны.
    """
    if not _OWNER_TYPE_RE.fullmatch(owner_type):
        raise ValueError(f"owner_type должен иметь вид '<аппка>.<модель>': {owner_type!r}")
    if not _FOLDER_RE.fullmatch(folder):
        raise ValueError(f"папка владельца {owner_type!r} не годится для ключа хранилища: {folder!r}")
    if not file_types:
        raise ValueError(f"у владельца {owner_type!r} нет ни одного типа файла")
    quotas = dict(quotas or {})
    by_code: dict[str, FileTypeSpec] = {}
    for spec in file_types:
        if spec.code in by_code:
            raise ValueError(f"тип файла {spec.code!r} объявлен дважды у {owner_type!r}")
        if spec.cardinality not in (MULTI, SINGLE):
            raise ValueError(f"{spec.code!r}: cardinality {spec.cardinality!r}; допустимы {MULTI!r}, {SINGLE!r}")
        if spec.quota_group is not None and spec.quota_group not in quotas:
            raise ValueError(f"{spec.code!r}: квота {spec.quota_group!r} не объявлена в quotas")
        by_code[spec.code] = spec
    for group, limit in quotas.items():
        if limit < 1:
            raise ValueError(f"квота {group!r} у {owner_type!r} должна быть ≥ 1")

    entry = OwnerEntry(
        owner_type=owner_type, label=label, service=service, tenant=tenant,
        folder=folder, file_types=tuple(file_types), quotas=quotas,
        can_view=can_view, can_modify=can_modify, was_sent=was_sent,
        lock=lock, on_event=on_event, model=model,
        can_view_type=can_view_type, can_modify_type=can_modify_type,
        can_version=can_version, _by_code=by_code,
    )
    _OWNERS[owner_type] = entry
    return entry


def get_owner(owner_type: str) -> OwnerEntry:
    try:
        return _OWNERS[owner_type]
    except KeyError:
        raise UnknownOwner(owner_type) from None


def registered_owners() -> dict[str, OwnerEntry]:
    return dict(_OWNERS)


def spec_for(file_type_code: str) -> tuple[OwnerEntry, FileTypeSpec] | None:
    """Владелец и правила типа по коду — для справочника типов."""
    for entry in _OWNERS.values():
        spec = entry.spec(file_type_code)
        if spec is not None:
            return entry, spec
    return None
