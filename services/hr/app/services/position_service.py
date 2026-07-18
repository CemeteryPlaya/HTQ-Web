"""Position service — weight system, level computation, CRUD."""

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.level_threshold import LevelThreshold
from app.models.position import Position
from app.models.position_weight_audit import PositionWeightAudit
from app.repositories.base_repo import BaseRepository
from app.schemas.position import LevelThresholdCreate, LevelThresholdUpdate, PositionCreate, PositionUpdate

logger = structlog.get_logger()

_DEFAULT_LEVEL = 5  # fallback if weight exceeds all configured thresholds


class PositionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = BaseRepository(Position, session)
        self.threshold_repo = BaseRepository(LevelThreshold, session)

    # ── Level computation ──────────────────────────────────────────────

    async def _compute_level(self, weight: int) -> int:
        """Return level_number for given weight using hr_level_thresholds."""
        stmt = (
            select(LevelThreshold)
            .where(LevelThreshold.weight_from <= weight)
            .where(LevelThreshold.weight_to >= weight)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        threshold = result.scalar_one_or_none()
        return threshold.level_number if threshold else _DEFAULT_LEVEL

    async def _get_threshold(self, level_number: int) -> LevelThreshold | None:
        result = await self.session.execute(
            select(LevelThreshold).where(LevelThreshold.level_number == level_number)
        )
        return result.scalar_one_or_none()

    async def _assert_weight_free(self, weight: int, exclude_id: int | None = None) -> None:
        """Warn (not block) if weight already taken; raise 409 only on exact collision."""
        stmt = select(Position).where(Position.weight == weight)
        if exclude_id:
            stmt = stmt.where(Position.id != exclude_id)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Weight {weight} is already taken by position '{existing.title}' (id={existing.id}). "
                       "Choose a different weight or update the existing position first.",
            )

    async def _assert_threshold_range_free(
        self,
        *,
        level_number: int,
        weight_from: int,
        weight_to: int,
    ) -> None:
        if weight_from > weight_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="weight_from must be <= weight_to",
            )

        stmt = (
            select(LevelThreshold)
            .where(LevelThreshold.level_number != level_number)
            .where(LevelThreshold.weight_from <= weight_to)
            .where(LevelThreshold.weight_to >= weight_from)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Level threshold range overlaps with "
                    f"L{existing.level_number} ({existing.weight_from}-{existing.weight_to})"
                ),
            )

    async def _record_weight_audit(
        self,
        *,
        position_id: int,
        old_weight: int | None,
        new_weight: int | None,
        old_level: int | None,
        new_level: int | None,
        reason: str,
        actor_user_id: int | None,
    ) -> None:
        self.session.add(
            PositionWeightAudit(
                position_id=position_id,
                old_weight=old_weight,
                new_weight=new_weight,
                old_level=old_level,
                new_level=new_level,
                changed_by=actor_user_id,
                reason=reason,
            )
        )

    async def _apply_new_weight(
        self,
        pos: Position,
        new_weight: int,
        *,
        reason: str,
        actor_user_id: int | None = None,
    ) -> Position:
        if new_weight < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="weight must be >= 0",
            )

        await self._assert_weight_free(new_weight, exclude_id=pos.id)
        new_level = await self._compute_level(new_weight)
        old_weight = pos.weight
        old_level = pos.level
        if old_weight == new_weight and old_level == new_level:
            return pos

        pos.weight = new_weight
        pos.level = new_level
        self.session.add(pos)
        await self._record_weight_audit(
            position_id=pos.id,
            old_weight=old_weight,
            new_weight=new_weight,
            old_level=old_level,
            new_level=new_level,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        await self.session.flush()
        await self.session.refresh(pos)
        return pos

    # ── CRUD ───────────────────────────────────────────────────────────

    async def list_positions(
        self, *, page: int = 1, limit: int = 20
    ) -> tuple[list[Position], int]:
        offset = (page - 1) * limit
        items, total = await self.repo.list(offset=offset, limit=limit, order_by="weight")
        return list(items), total

    async def get_position(self, id: int) -> Position:
        pos = await self.repo.get(id)
        if not pos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
        return pos

    async def create_position(self, data: PositionCreate) -> Position:
        await self._assert_weight_free(data.weight)
        level = await self._compute_level(data.weight)
        payload = data.model_dump()
        payload["level"] = level
        # Anything the API creates is by definition non-system; only the
        # alembic 013 backfill marks rows as is_system=True.
        payload["is_system"] = False
        pos = await self.repo.create(payload)
        logger.info("position_created", position_id=pos.id, weight=pos.weight, level=pos.level)
        return pos

    async def update_position(
        self,
        id: int,
        data: PositionUpdate,
        *,
        actor_user_id: int | None = None,
    ) -> Position:
        pos = await self.get_position(id)
        patch = data.model_dump(exclude_none=True)
        next_weight = patch.pop("weight", None)

        if pos.is_system:
            # System positions are part of the baseline org chart. Block
            # rename / department reassignment / deactivation — those would
            # break references and downstream auth heuristics. Weight,
            # grade, description, requirements, and the permissions matrix
            # remain editable so admins can still tune the hierarchy.
            blocked = {"title", "department_id", "is_active"} & patch.keys()
            if blocked:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Системную должность нельзя редактировать в этих полях: "
                        + ", ".join(sorted(blocked))
                    ),
                )

        updated = pos
        if patch:
            updated = await self.repo.update(pos, patch)
        if next_weight is not None:
            updated = await self._apply_new_weight(
                updated,
                next_weight,
                reason="manual",
                actor_user_id=actor_user_id,
            )
        logger.info("position_updated", position_id=id)
        return updated

    async def delete_position(self, id: int) -> None:
        pos = await self.get_position(id)
        if pos.is_system:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Системную должность нельзя удалить",
            )
        await self.repo.delete(pos)
        logger.info("position_deleted", position_id=id)

    # ── Weight endpoint ────────────────────────────────────────────────

    async def update_weight(
        self,
        id: int,
        weight: int,
        *,
        actor_user_id: int | None = None,
        reason: str = "manual",
    ) -> Position:
        pos = await self.get_position(id)
        updated = await self._apply_new_weight(
            pos,
            weight,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        logger.info("position_weight_updated", position_id=id, weight=updated.weight, level=updated.level)
        return updated

    async def move_position(
        self,
        position_id: int,
        *,
        before_position_id: int | None = None,
        after_position_id: int | None = None,
        target_level: int | None = None,
        actor_user_id: int | None = None,
    ) -> Position:
        if before_position_id and before_position_id == after_position_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="before_position_id and after_position_id must differ",
            )
        if position_id in (before_position_id, after_position_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="position cannot be moved relative to itself",
            )

        stmt = select(Position).where(Position.id == position_id).with_for_update()
        pos = (await self.session.execute(stmt)).scalar_one_or_none()
        if not pos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

        before = await self._get_position_for_move(before_position_id)
        after = await self._get_position_for_move(after_position_id)
        effective_level = target_level or (before.level if before else after.level if after else pos.level)

        if target_level is not None and not await self._get_threshold(target_level):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target level not found")

        new_weight = self._weight_between(before, after)
        threshold = await self._get_threshold(effective_level)
        if (
            new_weight is None
            or new_weight < 0
            or (
                threshold
                and not (threshold.weight_from <= new_weight <= threshold.weight_to)
            )
        ):
            return await self._rebalance_insert(
                pos,
                target_level=effective_level,
                before_position_id=before_position_id,
                after_position_id=after_position_id,
                actor_user_id=actor_user_id,
            )

        try:
            return await self._apply_new_weight(
                pos,
                new_weight,
                reason="move",
                actor_user_id=actor_user_id,
            )
        except HTTPException as exc:
            if exc.status_code != status.HTTP_409_CONFLICT:
                raise
            return await self._rebalance_insert(
                pos,
                target_level=effective_level,
                before_position_id=before_position_id,
                after_position_id=after_position_id,
                actor_user_id=actor_user_id,
            )

    async def _get_position_for_move(self, position_id: int | None) -> Position | None:
        if position_id is None:
            return None
        stmt = select(Position).where(Position.id == position_id).with_for_update()
        pos = (await self.session.execute(stmt)).scalar_one_or_none()
        if not pos:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Position {position_id} not found",
            )
        return pos

    def _weight_between(self, before: Position | None, after: Position | None) -> int | None:
        if before and after:
            if before.weight >= after.weight:
                before, after = after, before
            if after.weight - before.weight < 2:
                return None
            return (before.weight + after.weight) // 2
        if before:
            return before.weight + 100
        if after:
            return after.weight - 100
        return None

    async def _rebalance_insert(
        self,
        pos: Position,
        *,
        target_level: int,
        before_position_id: int | None,
        after_position_id: int | None,
        actor_user_id: int | None,
    ) -> Position:
        positions = await self._positions_for_level(target_level, lock=True)
        ordered = [p for p in positions if p.id != pos.id]

        insert_at = len(ordered)
        if before_position_id is not None:
            insert_at = next(
                (i + 1 for i, item in enumerate(ordered) if item.id == before_position_id),
                insert_at,
            )
        elif after_position_id is not None:
            insert_at = next(
                (i for i, item in enumerate(ordered) if item.id == after_position_id),
                0,
            )

        ordered.insert(insert_at, pos)
        await self._rebalance_positions(
            ordered,
            level=target_level,
            reason="move",
            actor_user_id=actor_user_id,
        )
        await self.session.refresh(pos)
        return pos

    async def rebalance_level(
        self,
        level: int,
        *,
        actor_user_id: int | None = None,
        reason: str = "rebalance",
    ) -> int:
        if not await self._get_threshold(level):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Level threshold not found")
        positions = await self._positions_for_level(level, lock=True)
        await self._rebalance_positions(
            positions,
            level=level,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        return len(positions)

    async def rebalance_all(self, *, actor_user_id: int | None = None) -> dict[int, int]:
        stmt = (
            select(Position)
            .order_by(Position.level.asc(), Position.weight.asc(), Position.title.asc(), Position.id.asc())
            .with_for_update()
        )
        positions = list((await self.session.execute(stmt)).scalars().all())
        counts: dict[int, int] = {}
        for pos in positions:
            counts[pos.level] = counts.get(pos.level, 0) + 1
        await self._rebalance_positions(
            positions,
            level=None,
            reason="rebalance",
            actor_user_id=actor_user_id,
        )
        return counts

    async def _positions_for_level(self, level: int, *, lock: bool) -> list[Position]:
        stmt = (
            select(Position)
            .where(Position.level == level)
            .order_by(Position.weight.asc(), Position.title.asc(), Position.id.asc())
        )
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).scalars().all())

    async def _final_weights(self, positions: list[Position], level: int | None) -> list[int]:
        if not positions:
            return []
        if level is None:
            return [idx * 100 for idx, _ in enumerate(positions)]

        threshold = await self._get_threshold(level)
        if not threshold:
            return [idx * 100 for idx, _ in enumerate(positions)]

        max_sparse = threshold.weight_from + ((len(positions) - 1) * 100)
        if max_sparse <= threshold.weight_to:
            return [threshold.weight_from + (idx * 100) for idx, _ in enumerate(positions)]

        width = threshold.weight_to - threshold.weight_from
        if len(positions) <= width + 1:
            step = max(1, width // max(len(positions) - 1, 1))
            return [threshold.weight_from + (idx * step) for idx, _ in enumerate(positions)]

        # The configured range cannot hold all positions with unique weights.
        # Preserve deterministic order and let cached level follow the final weight.
        return [threshold.weight_from + idx for idx, _ in enumerate(positions)]

    async def _rebalance_positions(
        self,
        positions: list[Position],
        *,
        level: int | None,
        reason: str,
        actor_user_id: int | None,
    ) -> None:
        if not positions:
            return

        old_values = {pos.id: (pos.weight, pos.level) for pos in positions}
        final_weights = await self._final_weights(positions, level)

        temp_base = -1_000_000_000
        for idx, pos in enumerate(positions):
            pos.weight = temp_base - idx
            self.session.add(pos)
        await self.session.flush()

        for pos, final_weight in zip(positions, final_weights, strict=True):
            await self._assert_weight_free(final_weight, exclude_id=pos.id)
            old_weight, old_level = old_values[pos.id]
            new_level = await self._compute_level(final_weight)
            pos.weight = final_weight
            pos.level = new_level
            self.session.add(pos)
            if old_weight != final_weight or old_level != new_level:
                await self._record_weight_audit(
                    position_id=pos.id,
                    old_weight=old_weight,
                    new_weight=final_weight,
                    old_level=old_level,
                    new_level=new_level,
                    reason=reason,
                    actor_user_id=actor_user_id,
                )
        await self.session.flush()

    # ── Level thresholds ───────────────────────────────────────────────

    async def list_thresholds(self) -> list[LevelThreshold]:
        items, _ = await self.threshold_repo.list(limit=100, order_by="level_number")
        return list(items)

    async def create_threshold(
        self,
        data: LevelThresholdCreate,
        *,
        actor_user_id: int | None = None,
    ) -> LevelThreshold:
        existing = await self._get_threshold(data.level_number)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Level threshold {data.level_number} already exists",
            )
        await self._assert_threshold_range_free(
            level_number=data.level_number,
            weight_from=data.weight_from,
            weight_to=data.weight_to,
        )
        threshold = LevelThreshold(**data.model_dump())
        self.session.add(threshold)
        await self.session.flush()
        await self._recompute_all_levels(actor_user_id=actor_user_id)
        await self.session.refresh(threshold)
        return threshold

    async def update_threshold(
        self,
        level_number: int,
        data: LevelThresholdUpdate,
        *,
        actor_user_id: int | None = None,
    ) -> LevelThreshold:
        stmt = select(LevelThreshold).where(LevelThreshold.level_number == level_number)
        result = await self.session.execute(stmt)
        threshold = result.scalar_one_or_none()
        if not threshold:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Level threshold {level_number} not found",
            )

        patch = data.model_dump(exclude_unset=True)
        next_weight_from = patch.get("weight_from", threshold.weight_from)
        next_weight_to = patch.get("weight_to", threshold.weight_to)
        await self._assert_threshold_range_free(
            level_number=level_number,
            weight_from=next_weight_from,
            weight_to=next_weight_to,
        )

        for key, value in patch.items():
            setattr(threshold, key, value)
        self.session.add(threshold)
        await self.session.flush()
        await self._recompute_all_levels(actor_user_id=actor_user_id)
        await self.session.refresh(threshold)
        logger.info("level_threshold_updated", level_number=level_number)
        return threshold

    async def delete_threshold(self, level_number: int, *, actor_user_id: int | None = None) -> None:
        threshold = await self._get_threshold(level_number)
        if not threshold:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Level threshold {level_number} not found",
            )
        await self.session.delete(threshold)
        await self.session.flush()
        await self._recompute_all_levels(actor_user_id=actor_user_id)

    async def _recompute_levels_in_range(self, weight_from: int, weight_to: int) -> None:
        """Recompute cached level for positions whose weight falls in the changed range."""
        stmt = select(Position).where(
            Position.weight >= weight_from,
            Position.weight <= weight_to,
        )
        result = await self.session.execute(stmt)
        positions = result.scalars().all()
        for pos in positions:
            new_level = await self._compute_level(pos.weight)
            if new_level != pos.level:
                pos.level = new_level
                self.session.add(pos)
        if positions:
            await self.session.flush()

    async def _recompute_all_levels(self, *, actor_user_id: int | None) -> int:
        stmt = select(Position).order_by(Position.id.asc()).with_for_update()
        result = await self.session.execute(stmt)
        positions = result.scalars().all()
        changed = 0
        for pos in positions:
            old_level = pos.level
            new_level = await self._compute_level(pos.weight)
            if new_level != old_level:
                pos.level = new_level
                self.session.add(pos)
                await self._record_weight_audit(
                    position_id=pos.id,
                    old_weight=pos.weight,
                    new_weight=pos.weight,
                    old_level=old_level,
                    new_level=new_level,
                    reason="threshold_change",
                    actor_user_id=actor_user_id,
                )
                changed += 1
        if changed:
            await self.session.flush()
        return changed
