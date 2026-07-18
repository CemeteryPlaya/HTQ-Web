"""Instance + action + activity data access."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_action import ApprovalAction
from app.models.request_activity import RequestActivity
from app.models.request_instance import RequestInstance
from app.models.request_watcher import RequestWatcher
from app.repositories.base_repo import BaseRepository


class InstanceRepository(BaseRepository[RequestInstance]):
    def __init__(self, session: AsyncSession):
        super().__init__(RequestInstance, session)

    async def next_code(self, template_id: int, slug: str) -> str:
        year = datetime.now(timezone.utc).year
        prefix = f"REQ-{slug}-{year}-"
        stmt = select(func.count()).select_from(RequestInstance).where(
            RequestInstance.template_id == template_id, RequestInstance.code.like(prefix + "%")
        )
        n = (await self.session.execute(stmt)).scalar_one() + 1
        return f"{prefix}{n:04d}"

    async def live_actions(self, request_id: int, node_id: str) -> list[ApprovalAction]:
        stmt = select(ApprovalAction).where(
            ApprovalAction.request_id == request_id, ApprovalAction.node_id == node_id
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def my_live_action(self, request_id: int, node_id: str, approver_id: int) -> ApprovalAction | None:
        stmt = select(ApprovalAction).where(
            ApprovalAction.request_id == request_id, ApprovalAction.node_id == node_id,
            ApprovalAction.approver_id == approver_id, ApprovalAction.acted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_user(self, user_id: int, *, role: str) -> list[RequestInstance]:
        """Boxes (Lark parity):
        - ``sent``  — requests the user initiated (Отправленные)
        - ``cc``    — requests the user follows as a watcher/CC (Копия)
        - ``done``  — requests the user has already acted on (Готово)
        - ``inbox`` — pending requests awaiting the user's action (Список дел)
        """
        if role == "sent":
            stmt = select(RequestInstance).where(RequestInstance.initiator_id == user_id)
        elif role == "cc":
            sub = select(RequestWatcher.request_id).where(RequestWatcher.user_id == user_id)
            stmt = select(RequestInstance).where(RequestInstance.id.in_(sub))
        elif role == "done":
            sub = select(ApprovalAction.request_id).where(
                ApprovalAction.approver_id == user_id, ApprovalAction.acted_at.is_not(None)
            )
            stmt = select(RequestInstance).where(RequestInstance.id.in_(sub))
        else:  # inbox — pending instances where the user has a live action
            sub = select(ApprovalAction.request_id).where(
                ApprovalAction.approver_id == user_id, ApprovalAction.acted_at.is_(None)
            )
            stmt = select(RequestInstance).where(RequestInstance.id.in_(sub))
        stmt = stmt.order_by(RequestInstance.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    def log(self, request_id: int, event_type: str, actor_id: int | None, payload: dict | None = None) -> None:
        self.session.add(RequestActivity(
            request_id=request_id, event_type=event_type, actor_id=actor_id, payload=payload,
        ))
