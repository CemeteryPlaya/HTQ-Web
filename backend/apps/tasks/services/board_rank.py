"""Порядок карточек внутри колонки — дробная индексация (мастер-план §3.2).

Ранг — строка из цифр base-62 (``0-9A-Za-z``, порядок совпадает с побайтным
сравнением ``COLLATE "C"``). Чтобы вставить карточку между двумя соседями,
не нужно переписывать остальные: ``between(a, b)`` даёт строку строго между
ними. Ни один ранг не кончается на ``"0"`` — иначе между ``"A"`` и ``"A0"``
нечего было бы вставить.

Строки растут, когда вставляют много раз в одно и то же место. Ранг длиннее
``MAX_LENGTH`` — сигнал перебалансировать колонку: ``spread(n)`` раздаёт ``n``
равномерных коротких рангов. Чистые функции: ни базы, ни Django.
"""

from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(DIGITS)
#: Длиннее — колонку пора перебалансировать (``BoardCardRank.rank`` — 64 символа).
MAX_LENGTH = 48

_INDEX = {digit: position for position, digit in enumerate(DIGITS)}


def _check(key: str) -> None:
    if key and (key[-1] == "0" or any(ch not in _INDEX for ch in key)):
        raise ValueError(f"Недопустимый ранг: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """Строка строго между ``a`` и ``b`` (``a`` может быть пустой — «минус
    бесконечность», ``b`` — ``None``, «плюс бесконечность»). Алгоритм —
    дробная индексация с общим префиксом и серединой первой различающейся
    цифры."""
    if b is not None:
        prefix = 0
        while prefix < len(b) and (a[prefix] if prefix < len(a) else "0") == b[prefix]:
            prefix += 1
        if prefix:
            return b[:prefix] + _midpoint(a[prefix:], b[prefix:])
    low = _INDEX[a[0]] if a else 0
    high = _INDEX[b[0]] if b is not None else BASE
    if high - low > 1:
        return DIGITS[(low + high + 1) // 2]
    # Цифры соседние: если у ``b`` есть хвост, достаточно его первой цифры
    # (она больше ``a`` и меньше ``b``), иначе — цифра ``a`` и середина хвоста.
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[low] + _midpoint(a[1:], None)


def _increment(key: str) -> str:
    """Ранг после последнего: следующая цифра в самой правой позиции, где она
    есть, с отбрасыванием хвоста (``"Vz"`` → ``"W"``); все цифры ``"z"`` —
    дописать самую младшую. Длина растёт на символ примерно раз в 60
    добавлений в конец, а не раз в 5, как у середины."""
    for position in range(len(key) - 1, -1, -1):
        if key[position] != DIGITS[-1]:
            return key[:position] + DIGITS[_INDEX[key[position]] + 1]
    return key + DIGITS[1]


def _decrement(key: str) -> str:
    """Ранг перед первым — меньше ``key`` и без завершающего ``"0"``."""
    first = _INDEX[key[0]]
    if first > 1:
        return DIGITS[first - 1]
    if first == 1:
        return DIGITS[1] if len(key) > 1 else DIGITS[0] + DIGITS[-1]
    return DIGITS[0] + _decrement(key[1:])


def between(before: str | None, after: str | None) -> str:
    """Ранг карточки, вставленной после ``before`` и перед ``after``.

    ``before=None`` — в начало колонки, ``after=None`` — в конец, оба
    ``None`` — первая карточка пустой колонки.
    """
    a = before or ""
    _check(a)
    if after is not None:
        _check(after)
        if a >= after:
            raise ValueError(f"Ранги не по порядку: {before!r} >= {after!r}")
    if not a and after is None:
        return DIGITS[BASE // 2]
    if after is None:
        return _increment(a)
    if not a:
        return _decrement(after)
    return _midpoint(a, after)


def _encode(value: int, width: int) -> str:
    digits = []
    for _ in range(width):
        value, remainder = divmod(value, BASE)
        digits.append(DIGITS[remainder])
    return "".join(reversed(digits)).rstrip("0")


def spread(count: int) -> list[str]:
    """``count`` равномерно разнесённых рангов по возрастанию — для
    перебалансировки колонки и для раздачи рангов карточкам без строки."""
    if count <= 0:
        return []
    width = 1
    while BASE ** width < 2 * (count + 1):
        width += 1
    step = BASE ** width // (count + 1)
    return [_encode(step * position, width) for position in range(1, count + 1)]


def needs_rebalance(rank: str) -> bool:
    return len(rank) > MAX_LENGTH
