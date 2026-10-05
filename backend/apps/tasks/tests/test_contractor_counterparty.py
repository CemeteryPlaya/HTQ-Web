"""Партнёр ↔ контрагент модуля «Закупки и оплаты» (A6.1, D-S6-2).

Партнёр (``tasks.Contractor``) — это контрагент модуля (``bpp.Counterparty``)
в роли исполнителя на объектах; ключ — UUID строкой в
``bpp_counterparty_id``. Ссылка голая через границу аппок, поэтому всё, что
обычно держит FK, держат проверки сервиса; этот файл — их исполняемая
версия:

* команда ``tasks_link_counterparties`` переводит старые связи с «Договорами»
  по связям переноса B6.1 — идемпотентно, ручную связь не затирает, спор
  двух партнёров за одного контрагента — в отчёт (Review Focus 2);
* у связанной пары один БИН/ИИН, одна организация — один партнёр, новая
  связь — только с действующим контрагентом;
* договор привлечения (договор «Договоров») — с контрагентом ЭТОГО партнёра,
  сверка через связь переноса;
* выключенный модуль стоит списку партнёров подписи, а не ответа;
* старое ``counterparty_id`` в ``apps.tasks`` больше никто не читает.

Заменяет ``test_contractor_counterparty_link.py`` (связь с «Договорами»).
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize
import uuid

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client

from apps.bpp.models import Counterparty as BppCounterparty
from apps.bpp.services.migration import links
from apps.contracts.models import Counterparty as ContractsCounterparty
from apps.contracts.tests import helpers as contracts_helpers
from apps.core.models import ServiceStatus
from apps.tasks import interface as tasks_interface
from apps.tasks.models import Contractor, ContractorEngagement, Site

from .helpers import BASE, admin_token, auth, patch_json, post_json, token

CONTRACTS = contracts_helpers.BASE
SOURCE, TARGET = "contracts.counterparty", "bpp.counterparty"


def _cp(reg_number="123456789012", name="ТОО «Альфа»", **over) -> BppCounterparty:
    return BppCounterparty.objects.create(
        name=name, kind="legal", country_code="KZ", reg_number=reg_number, **over)


def _moved(source_id: int, cp: BppCounterparty) -> None:
    """Связь переноса B6.1: контрагент «Договоров» ``source_id`` → ``cp``."""
    links.link(SOURCE, source_id, TARGET, cp.pk)


def _site(name="Алга") -> Site:
    return Site.objects.create(name=name)


def _disable(app_label: str) -> None:
    ServiceStatus.objects.update_or_create(app_label=app_label, defaults={"enabled": False})
    cache.clear()


def _link(company: str, *extra: str) -> str:
    out = io.StringIO()
    call_command("tasks_link_counterparties", "--company", company, *extra, stdout=out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# Команда связки по переносу
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_link_by_migration_links(company_context):
    slug = company_context["slug"]
    alpha = _cp()
    _moved(41, alpha)
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=41)
    lonely = Contractor.objects.create(name="Сами по себе")
    not_moved = Contractor.objects.create(name="Бета-Монтаж", counterparty_id=42)

    dry = _link(slug, "--dry-run")
    assert "ПРОБНЫЙ ПРОГОН" in dry
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == ""

    text = _link(slug)
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == str(alpha.pk)
    # Пустой БИН — «не вписали»: берётся у контрагента, как на экране.
    assert partner.bin_iin == "123456789012"
    assert "связан — 1" in text
    assert "без пары — 2" in text
    for row in (lonely, not_moved):
        row.refresh_from_db()
        assert row.bpp_counterparty_id == ""
        assert f"#{row.pk} «{row.name}»" in text


@pytest.mark.django_db
def test_link_idempotent_and_keeps_manual(company_context):
    slug = company_context["slug"]
    alpha, manual = _cp(), _cp(reg_number="210987654321", name="ТОО «Ручной»")
    _moved(41, alpha)
    _moved(43, _cp(reg_number="310987654321", name="ТОО «Гамма»"))
    partner = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=41)
    # Связь поставили руками на экране — перенос вёл бы к «Гамме».
    hand = Contractor.objects.create(name="Гамма-Монтаж", counterparty_id=43,
                                     bpp_counterparty_id=str(manual.pk))

    _link(slug)
    again = _link(slug)

    partner.refresh_from_db()
    hand.refresh_from_db()
    assert partner.bpp_counterparty_id == str(alpha.pk)
    assert hand.bpp_counterparty_id == str(manual.pk)
    assert "связан — 0" in again
    assert "уже связан — 1" in again
    assert "оставлен — 1" in again


@pytest.mark.django_db
def test_two_contractors_one_counterparty_reported(company_context):
    """Два контрагента «Договоров» с одним БИН перенеслись в одного
    контрагента модуля — партнёров двое. Отчёт, а не IntegrityError, и ни
    один не связан: кто из них «тот самый», решает человек."""
    slug = company_context["slug"]
    alpha = _cp()
    _moved(41, alpha)
    _moved(42, alpha)
    first = Contractor.objects.create(name="Альфа-Монтаж", counterparty_id=41)
    second = Contractor.objects.create(name="Альфа-Сервис", counterparty_id=42)
    # И третий — к контрагенту, которого уже держит ручная связь.
    beta = _cp(reg_number="210987654321", name="ТОО «Бета»")
    _moved(44, beta)
    Contractor.objects.create(name="Бета-Монтаж", bpp_counterparty_id=str(beta.pk))
    third = Contractor.objects.create(name="Бета-Сервис", counterparty_id=44)

    text = _link(slug)

    for row in (first, second, third):
        row.refresh_from_db()
        assert row.bpp_counterparty_id == ""
    assert "конфликт — 3" in text
    assert "«Альфа-Монтаж», «Альфа-Сервис»" in text
    assert "уже связан с партнёром «Бета-Монтаж»" in text


@pytest.mark.django_db
def test_link_reports_a_different_bin_as_conflict(company_context):
    slug = company_context["slug"]
    _moved(41, _cp())
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin="999999999999",
                                        counterparty_id=41)
    text = _link(slug)
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == ""
    assert "не совпадает" in text


# ─────────────────────────────────────────────────────────────────────────
# Сторож: старое поле не читается
# ─────────────────────────────────────────────────────────────────────────

_APP = pathlib.Path(__file__).resolve().parents[1]
_OLD = re.compile(r"^counterparty_id(__\w+)?$")
#: Где старое поле законно: модель (объявление), миграции и команда
#: перевода связей — единственный читатель (и тесты, которые её кормят).
_ALLOWED = {"models.py", "management/commands/tasks_link_counterparties.py"}


def _old_field_uses(path: pathlib.Path, root: pathlib.Path = _APP) -> list[str]:
    """Имя ``counterparty_id`` в коде: атрибут (``row.counterparty_id``),
    аргумент и фильтр (``counterparty_id=``, ``counterparty_id__in``),
    строка-имя поля (``values("counterparty_id")``). Не считается ключ
    чужого словаря (``agreement["counterparty_id"]`` — договор «Договоров»)
    и упоминания в тексте докстрингов и комментариев."""
    found = []
    previous = None
    with path.open("rb") as handle:
        for tok in tokenize.tokenize(handle.readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
                continue
            if tok.type == tokenize.NAME and _OLD.match(tok.string):
                found.append(f"{path.relative_to(root)}:{tok.start[0]}")
            elif tok.type == tokenize.STRING and previous != "[":
                text = tok.string.strip("rbuRBU")
                if text[:1] in "\"'" and _OLD.match(text.strip("\"'")):
                    found.append(f"{path.relative_to(root)}:{tok.start[0]}")
            previous = tok.string
    return found


def test_old_field_is_not_read():
    offenders = []
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_APP).as_posix()
        if rel.startswith(("migrations/", "tests/")) or rel in _ALLOWED:
            continue
        offenders += _old_field_uses(path)
    assert offenders == [], (
        "Contractor.counterparty_id (контрагент «Договоров») после A6.1 не читается — "
        f"связь партнёра живёт в bpp_counterparty_id: {offenders}")


def test_guard_sees_reads(tmp_path):
    """Сторож не слепой: ловит атрибут, фильтр и имя поля строкой."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        'x = row.counterparty_id\n'
        'Contractor.objects.filter(counterparty_id__in=ids)\n'
        'qs.values("counterparty_id")\n'
        'ok = agreement["counterparty_id"]\n'
        '"""counterparty_id в тексте"""\n', encoding="utf-8")
    hits = _old_field_uses(probe, root=tmp_path)
    assert [hit.split(":")[1] for hit in hits] == ["1", "2", "3"]


# ─────────────────────────────────────────────────────────────────────────
# Карточка партнёра
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_api_shows_bpp_counterparty():
    cp = _cp()
    Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.reg_number,
                              bpp_counterparty_id=str(cp.pk))
    Contractor.objects.create(name="Сами по себе")

    resp = Client().get(f"{BASE}/contractors/", **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    linked, alone = resp.json()
    assert linked["bpp_counterparty_id"] == str(cp.pk)
    assert linked["bpp_counterparty"] == {"id": str(cp.pk), "name": "ТОО «Альфа»",
                                          "reg_number": "123456789012", "status": "active"}
    assert "counterparty_id" not in linked and "counterparty" not in linked
    assert alone["bpp_counterparty_id"] is None
    assert alone["bpp_counterparty"] is None


@pytest.mark.django_db
def test_partner_links_to_counterparty_and_takes_its_bin():
    cp = _cp()
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bpp_counterparty_id": str(cp.pk).upper()},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    body = resp.json()
    # Ключ — в каноническом виде, как его пишет связь переноса.
    assert body["bpp_counterparty_id"] == str(cp.pk)
    assert body["bpp_counterparty"]["name"] == "ТОО «Альфа»"
    assert body["bin_iin"] == "123456789012"


@pytest.mark.django_db
def test_different_bin_is_a_conflict_not_a_silent_overwrite():
    cp = _cp()
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bin_iin": "999999999999",
                      "bpp_counterparty_id": str(cp.pk)},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "не совпадает" in resp.json()["detail"]
    assert not Contractor.objects.exists()


@pytest.mark.django_db
def test_linked_partner_cannot_get_a_foreign_bin_later():
    cp = _cp()
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.reg_number,
                                        bpp_counterparty_id=str(cp.pk))
    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"bin_iin": "999999999999"}, **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_one_counterparty_is_one_partner():
    cp = _cp()
    Contractor.objects.create(name="Первый", bpp_counterparty_id=str(cp.pk))
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Второй", "bpp_counterparty_id": str(cp.pk)},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "Первый" in resp.json()["detail"]


@pytest.mark.django_db
@pytest.mark.parametrize("key", [str(uuid.uuid4()), "не-ключ"])
def test_unknown_counterparty_is_404(key):
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bpp_counterparty_id": key},
                     **auth(admin_token()))
    assert resp.status_code == 404
    assert not Contractor.objects.exists()


@pytest.mark.django_db
def test_blocked_counterparty_is_not_linked_but_existing_link_survives():
    cp = _cp(status="blocked")
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bpp_counterparty_id": str(cp.pk)},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "заблокирован" in resp.json()["detail"]

    # Связь поставлена до блокировки — правка карточки её не трогает.
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.reg_number,
                                        bpp_counterparty_id=str(cp.pk))
    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"phone": "+77010000000", "bpp_counterparty_id": str(cp.pk)},
                      **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["bpp_counterparty"]["status"] == "blocked"


@pytest.mark.django_db
def test_partner_without_counterparty_is_still_allowed():
    resp = post_json(Client(), f"{BASE}/contractors/", {"name": "Сами по себе"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["bpp_counterparty"] is None


@pytest.mark.django_db
def test_unlinking_drops_engagement_agreements_but_keeps_the_number():
    cp = _cp()
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.reg_number,
                                        bpp_counterparty_id=str(cp.pk))
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), agreement_id=4242, contract_no="Д-777")

    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"bpp_counterparty_id": None}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["bpp_counterparty"] is None
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == ""

    engagement.refresh_from_db()
    assert engagement.agreement_id is None
    assert engagement.contract_no == "Д-777"


@pytest.mark.django_db
def test_counterparty_search_offers_only_active():
    _cp(name="ТОО «Альфа»")
    _cp(reg_number="210987654321", name="ТОО «Альфа-Блок»", status="blocked")
    _cp(reg_number="310987654321", name="ТОО «Бета»")

    resp = Client().get(f"{BASE}/contractors/counterparty-search", {"q": "альфа"},
                        **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert [row["name"] for row in resp.json()] == ["ТОО «Альфа»"]
    assert resp.json()[0]["reg_number"] == "123456789012"

    by_bin = Client().get(f"{BASE}/contractors/counterparty-search", {"q": "3109"},
                          **auth(admin_token()))
    assert [row["name"] for row in by_bin.json()] == ["ТОО «Бета»"]


@pytest.mark.django_db
def test_counterparty_search_is_for_those_who_edit_partners():
    resp = Client().get(f"{BASE}/contractors/counterparty-search", **auth(token()))
    assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────
# Привлечение по договору «Договоров»
# ─────────────────────────────────────────────────────────────────────────

def _contracts_cp(bin_iin="123456789012", name="ТОО «Альфа»"):
    return contracts_helpers.make_counterparty(bin_iin=bin_iin, name=name)


def _agreement(counterparty, number="Д-001", line=None):
    # Программа строки уникальна по (name, expense_item): второй вызов без
    # общей строки упирается в uq_contracts_program_uncoded.
    line = line or contracts_helpers.make_line(
        program=contracts_helpers.make_program(name=f"Программа {number}"))
    return contracts_helpers.make_agreement(
        line=line, counterparty=counterparty, number=number)


@pytest.mark.django_db
def test_engagement_takes_agreement_of_its_migrated_counterparty():
    old, cp = _contracts_cp(), _cp()
    _moved(old.id, cp)
    agreement = _agreement(old, number="Д-042")
    partner = Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))

    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site().id,
                      "agreement_id": agreement.id, "contract_no": "что-то своё"},
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["agreement"]["number"] == "Д-042"
    assert resp.json()["contract_no"] == "Д-042"


@pytest.mark.django_db
def test_contract_no_of_a_linked_engagement_follows_the_agreement():
    old, cp = _contracts_cp(), _cp()
    _moved(old.id, cp)
    agreement = _agreement(old, number="Д-100")
    partner = Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))
    engagement = ContractorEngagement.objects.create(
        contractor=partner, site=_site(), agreement_id=agreement.id,
        contract_no="Д-100")

    resp = patch_json(Client(), f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"contract_no": "другой"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["contract_no"] == "Д-100"


@pytest.mark.django_db
def test_agreement_with_another_or_unmigrated_counterparty_is_rejected():
    ours, theirs = _contracts_cp(), _contracts_cp(bin_iin="210987654321", name="ТОО «Бета»")
    cp = _cp()
    _moved(ours.id, cp)
    _moved(theirs.id, _cp(reg_number="210987654321", name="ТОО «Бета»"))
    unmigrated = _contracts_cp(bin_iin="310987654321", name="ТОО «Гамма»")
    partner = Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))

    for counterparty, number in ((theirs, "Д-БЕТА"), (unmigrated, "Д-ГАММА")):
        resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                         {"contractor_id": partner.id, "site_id": _site(number).id,
                          "agreement_id": _agreement(counterparty, number=number).id},
                         **auth(admin_token()))
        assert resp.status_code == 409, number
    assert not ContractorEngagement.objects.exists()


@pytest.mark.django_db
def test_agreement_needs_a_linked_partner():
    agreement = _agreement(_contracts_cp())
    partner = Contractor.objects.create(name="Без контрагента")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": partner.id, "site_id": _site().id,
                      "agreement_id": agreement.id},
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "не связан" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────
# Выключенный модуль «Закупки и оплаты»
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_partner_list_survives_disabled_bpp():
    cp = _cp()
    Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))
    _disable("bpp")

    resp = Client().get(f"{BASE}/contractors/", **auth(admin_token()))
    assert resp.status_code == 200
    [row] = resp.json()
    assert row["bpp_counterparty_id"] == str(cp.pk)
    assert row["bpp_counterparty"] is None


@pytest.mark.django_db
def test_editing_linked_partner_does_not_need_bpp():
    cp = _cp()
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin=cp.reg_number,
                                        bpp_counterparty_id=str(cp.pk))
    _disable("bpp")
    resp = patch_json(Client(), f"{BASE}/contractors/{partner.id}/",
                      {"phone": "+77010000000", "bin_iin": cp.reg_number,
                       "bpp_counterparty_id": str(cp.pk)},
                      **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["phone"] == "+77010000000"


@pytest.mark.django_db
def test_linking_with_disabled_bpp_is_503_not_a_blind_write():
    cp = _cp()
    _disable("bpp")
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "Альфа-Монтаж", "bpp_counterparty_id": str(cp.pk)},
                     **auth(admin_token()))
    assert resp.status_code == 503
    assert not Contractor.objects.exists()


# ─────────────────────────────────────────────────────────────────────────
# Сторона «Договоров» (до заморозки A6.2)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_contracts_card_finds_its_partner_through_the_migration_link():
    old, cp = _contracts_cp(), _cp()
    _moved(old.id, cp)
    partner = Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))

    card = Client().get(f"{CONTRACTS}/counterparties/{old.id}",
                        **contracts_helpers.auth(contracts_helpers.token()))
    assert card.status_code == 200, card.content
    assert card.json()["contractor"]["id"] == partner.id


@pytest.mark.django_db
def test_link_from_contracts_goes_through_the_migration_link():
    old, cp = _contracts_cp(), _cp()
    partner = Contractor.objects.create(name="Альфа-Монтаж")
    with pytest.raises(tasks_interface.ContractorLinkConflict, match="не перенесён"):
        tasks_interface.link_contractor_to_counterparty(partner.id, old.id)

    _moved(old.id, cp)
    assert tasks_interface.link_contractor_to_counterparty(partner.id, old.id)["id"] \
        == partner.id
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == str(cp.pk)


@pytest.mark.django_db
def test_partner_is_not_silently_taken_from_another_counterparty():
    old, other, mine = _contracts_cp(), _cp(reg_number="210987654321", name="ТОО «Бета»"), _cp()
    _moved(old.id, mine)
    partner = Contractor.objects.create(name="Бета-Монтаж", bpp_counterparty_id=str(other.pk))
    with pytest.raises(tasks_interface.ContractorLinkConflict, match="другим контрагентом"):
        tasks_interface.link_contractor_to_counterparty(partner.id, old.id)
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == str(other.pk)


@pytest.mark.django_db
def test_counterparty_created_from_partner_in_contracts_is_refused_whole():
    """Новый контрагент «Договоров» не перенесён — связывать нечем: ни
    контрагента, ни связи (раньше это был путь «завести из партнёра»)."""
    partner = Contractor.objects.create(name="Альфа-Монтаж", bin_iin="123456789012")
    resp = post_json(Client(), f"{CONTRACTS}/counterparties/full",
                     {"bin_iin": "123456789012", "name": "ТОО «Альфа»",
                      "country": {"id": contracts_helpers.make_country().id},
                      "contractor_id": partner.id},
                     **contracts_helpers.auth(contracts_helpers.token()))
    assert resp.status_code == 409
    assert not ContractsCounterparty.objects.exists()


@pytest.mark.django_db
def test_deleting_contracts_counterparty_keeps_the_bpp_link():
    old, cp = _contracts_cp(), _cp()
    _moved(old.id, cp)
    partner = Contractor.objects.create(name="Альфа-Монтаж", bpp_counterparty_id=str(cp.pk))
    resp = Client().delete(f"{CONTRACTS}/counterparties/{old.id}",
                           **contracts_helpers.auth(contracts_helpers.admin_token()))
    assert resp.status_code == 204
    partner.refresh_from_db()
    assert partner.bpp_counterparty_id == str(cp.pk)
