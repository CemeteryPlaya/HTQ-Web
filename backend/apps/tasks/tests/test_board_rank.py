"""Дробная индексация порядка карточек (мастер-план §3.2): чистые функции."""

from __future__ import annotations

import random

import pytest

from apps.tasks.services import board_rank


def test_first_card_of_an_empty_column():
    rank = board_rank.between(None, None)
    assert rank and not rank.endswith("0")


@pytest.mark.parametrize("before,after", [("A", "B"), ("A", "A1"), ("1", "2"),
                                           ("zz", None), (None, "1"), (None, "01"),
                                           ("Vz", None), ("V", "W")])
def test_between_is_strictly_between(before, after):
    rank = board_rank.between(before, after)
    assert before is None or before < rank
    assert after is None or rank < after
    assert not rank.endswith("0")


@pytest.mark.parametrize("before,after", [("B", "A"), ("A", "A"), ("A0", None), (None, "x!")])
def test_bad_neighbours_are_rejected(before, after):
    with pytest.raises(ValueError):
        board_rank.between(before, after)


def test_random_inserts_keep_order_and_uniqueness():
    rng = random.Random(42)
    keys: list[str] = []
    for _ in range(1500):
        position = rng.randint(0, len(keys))
        before = keys[position - 1] if position else None
        after = keys[position] if position < len(keys) else None
        keys.insert(position, board_rank.between(before, after))
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("prepend", [False, True])
def test_appending_and_prepending_grow_slowly(prepend):
    """Быстрое добавление кладёт карточку в конец колонки: 500 добавлений
    подряд не должны раздувать ранг (раньше середина давала символ на 5)."""
    keys = [board_rank.between(None, None)]
    for _ in range(500):
        if prepend:
            keys.insert(0, board_rank.between(None, keys[0]))
        else:
            keys.append(board_rank.between(keys[-1], None))
    assert keys == sorted(keys)
    assert max(map(len, keys)) <= 12


@pytest.mark.parametrize("count", [0, 1, 5, 61, 200, 1000])
def test_spread_gives_ordered_short_ranks(count):
    ranks = board_rank.spread(count)
    assert len(ranks) == count
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == count
    assert all(rank and not rank.endswith("0") for rank in ranks)
    assert all(len(rank) <= 3 for rank in ranks)


def test_needs_rebalance_threshold():
    assert not board_rank.needs_rebalance("V" * board_rank.MAX_LENGTH)
    assert board_rank.needs_rebalance("V" * (board_rank.MAX_LENGTH + 1))
