"""Task links, with cycle detection on the blocking graph.

Ported from ``services/task/app/services/link_service.py``. Two behaviours
carried over that are easy to lose and hard to notice missing:

* **Links are stored in both directions.** Creating ``A blocks B`` also
  writes ``B is_blocked_by A``, so each task sees the relationship from its
  own side without a UNION query. Deleting either row deletes its mirror.
* **Cycle detection walks the ``blocks`` graph only.** Adding a link that
  would let a blocking chain reach back to its source is rejected — the
  chain would otherwise deadlock the board.

The cycle walk is a DFS in Python. It stays here rather than becoming a
recursive CTE because it runs once per link creation, over the handful of
edges a real blocking chain has, and the readable version is the one that
can be checked against the original.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404

from ..models import LinkType, Task, TaskLink

# The mirror written alongside each direction.
_MIRROR = {
    LinkType.BLOCKS: LinkType.IS_BLOCKED_BY,
    LinkType.IS_BLOCKED_BY: LinkType.BLOCKS,
}


def _would_create_cycle(source_id: int, target_id: int) -> bool:
    """True when a ``blocks`` path already leads from ``target`` to ``source``."""
    visited: set[int] = set()
    stack = [target_id]
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(
            TaskLink.objects.filter(source_id=current,
                                    link_type=LinkType.BLOCKS)
            .values_list("target_id", flat=True)
        )
    return False


@transaction.atomic
def create_link(*, source_id: int, target_id: int, link_type: str,
                user_id: int | None = None) -> TaskLink:
    """Raises ``ValueError`` for every rejection — the view maps it to 400,
    which is what the original returned for all of them."""
    if source_id == target_id:
        raise ValueError("Task cannot link to itself")

    known = set(Task.objects.filter(id__in=(source_id, target_id))
                .values_list("id", flat=True))
    if {source_id, target_id} - known:
        raise ValueError("Source or target task not found")

    if link_type in _MIRROR and _would_create_cycle(source_id, target_id):
        raise ValueError(
            "Creating this link would introduce a cycle in blocking chain"
        )

    link = TaskLink.objects.create(source_id=source_id, target_id=target_id,
                                   link_type=link_type,
                                   created_by_id=user_id)
    mirror = _MIRROR.get(link_type)
    if mirror is not None:
        # get_or_create, not create: the mirror may already exist from an
        # earlier link in the other direction, and the unique constraint
        # would otherwise turn a legitimate request into a 500.
        TaskLink.objects.get_or_create(
            source_id=target_id, target_id=source_id, link_type=mirror,
            defaults={"created_by_id": user_id},
        )
    return link


@transaction.atomic
def link_source_task_id(link_id: int) -> int:
    """Which task owns this link, for the caller's permission check.

    Deleting a link is an edit of the *source* task (that is the side the
    link was created from, and the side ``create_link`` authorises), so the
    view authorises against it. ``Http404`` for an unknown id.
    """
    source_id = TaskLink.objects.filter(pk=link_id).values_list(
        "source_id", flat=True).first()
    if source_id is None:
        raise Http404(f"Link {link_id} not found")
    return source_id


def delete_link(link_id: int) -> None:
    link = TaskLink.objects.filter(pk=link_id).first()
    if link is None:
        raise Http404(f"Link {link_id} not found")
    # Drop the mirror too, whatever its type — the original matched purely on
    # the reversed endpoints, so an asymmetric pair cannot survive a delete.
    TaskLink.objects.filter(source_id=link.target_id,
                            target_id=link.source_id).delete()
    link.delete()
