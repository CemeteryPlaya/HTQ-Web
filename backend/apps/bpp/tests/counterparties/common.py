"""Помощники тестов справочника «Контрагенты» (A2.3).

Номера БИН/ИИН и IBAN не зашиты руками, а находятся перебором по
алгоритму из ТЗ §18 (и ISO 13616 для IBAN), написанному здесь отдельно от
кода модуля: тест сверяет две независимые записи одного правила.
"""

from __future__ import annotations

from apps.refdata.models import Country

W1 = tuple(range(1, 12))
W2 = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)


def _rest(body: str, weights) -> int:
    return sum(int(d) * w for d, w in zip(body, weights)) % 11


def _bodies(start: int = 10**10):
    for n in range(start, start + 500_000):
        yield str(n).zfill(11)


def bin_first_pass(start: int = 10**10) -> str:
    """Действительный номер, контроль которого решён первым проходом."""
    for body in _bodies(start):
        rest = _rest(body, W1)
        if rest != 10:
            return body + str(rest)
    raise AssertionError("не найден")


def bin_second_pass() -> str:
    """Действительный номер: первый проход дал 10, второй — цифру."""
    for body in _bodies():
        if _rest(body, W1) == 10 and _rest(body, W2) != 10:
            return body + str(_rest(body, W2))
    raise AssertionError("не найден")


def bin_body_ten_twice() -> str:
    """11 цифр, у которых оба прохода дают 10: действительного 12-го
    разряда нет."""
    for body in _bodies():
        if _rest(body, W1) == 10 and _rest(body, W2) == 10:
            return body
    raise AssertionError("не найден")


def valid_bins(count: int) -> list[str]:
    found, start = [], 10**10
    while len(found) < count:
        number = bin_first_pass(start)
        found.append(number)
        start = int(number[:11]) + 1
    return found


def kz_iban(account: str) -> str:
    """IBAN Казахстана с верными контрольными цифрами для 16 знаков BBAN."""
    assert len(account) == 16
    numeric = "".join(str(int(ch, 36)) for ch in account + "KZ00")
    return f"KZ{98 - int(numeric) % 97:02d}{account}"


def countries() -> None:
    """Страны из сида refdata/0002: транзакционный тест идёт после очистки
    базы, где посеянных строк уже нет."""
    for code, name in (("KZ", "Казахстан"), ("RU", "Россия"), ("KG", "Кыргызстан")):
        Country.objects.get_or_create(code=code, defaults={"name": name})


def data(reg_number: str, **over) -> dict:
    return {"name": "Товарищество с ограниченной ответственностью «Альфа»",
            "short_name": "ТОО „Альфа“", "kind": "legal", "country_code": "KZ",
            "reg_number": reg_number, **over}
