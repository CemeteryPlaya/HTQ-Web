"""Порядок строк по дробным рангам ``board_rank``: чек-листы задачи, пункты
чек-листа, поля доски (у карточек доски — свой порядок в ``board_service``).

У строки — поле ``position`` (``COLLATE "C"``); вставка между соседями не
переписывает остальные строки. Сосед не из этого списка — 409: список
изменился, клиент перечитывает его.
"""

from __future__ import annotations

from htqweb.errors import DomainError

from . import board_rank


def ordered(rows: list) -> list:
    return sorted(rows, key=lambda row: (row.position, row.id))


def position_between(rows: list, moving_id: int | None, before_id: int | None,
                     after_id: int | None, *, code: str, what: str) -> str:
    """Ранг между соседями (``before_id`` — над местом вставки, ``after_id`` —
    под ним); без соседей — в конец. ``what`` — что обновить клиенту
    («чек-лист», «поля доски»)."""
    rows = [row for row in ordered(rows) if row.id != moving_id]
    order = [row.id for row in rows]
    ranks = {row.id: row.position for row in rows}

    def stale() -> DomainError:
        return DomainError(code, f"Список изменился — обновите {what} и повторите", status=409)

    for neighbour in (before_id, after_id):
        if neighbour is not None and neighbour not in ranks:
            raise stale()
    if before_id is None and after_id is None:
        return board_rank.between(rows[-1].position if rows else None, None)
    if before_id is not None and after_id is not None:
        if order.index(after_id) != order.index(before_id) + 1:
            raise stale()
        return board_rank.between(ranks[before_id], ranks[after_id])
    if before_id is not None:
        index = order.index(before_id)
        nxt = ranks[order[index + 1]] if index + 1 < len(order) else None
        return board_rank.between(ranks[before_id], nxt)
    index = order.index(after_id)
    prev = ranks[order[index - 1]] if index > 0 else None
    return board_rank.between(prev, ranks[after_id])


def respread(rows: list) -> None:
    """Слишком длинный ранг — список раскладывается заново в текущем порядке."""
    rows = ordered(rows)
    for row, rank in zip(rows, board_rank.spread(len(rows))):
        if row.position != rank:
            row.position = rank
            row.save(update_fields=["position", "updated_at"])
