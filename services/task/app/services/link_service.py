"""Task link service with cycle detection."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.link import TaskLink, LinkType
from app.repositories import LinkRepository
from app.repositories.task_repo import TaskRepository


class LinkService:
    """Business logic for task links."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.link_repo = LinkRepository(session)
        self.task_repo = TaskRepository(session)

    async def create_link(
        self,
        source_id: int,
        target_id: int,
        link_type: LinkType,
        user_id: int | None = None,
    ) -> TaskLink:
        """Create a task link with validation."""
        # Validate tasks exist
        source = await self.task_repo.get_by_id(source_id)
        target = await self.task_repo.get_by_id(target_id)
        if not source or not target:
            raise ValueError("Source or target task not found")

        # Prevent self-reference
        if source_id == target_id:
            raise ValueError("Task cannot link to itself")

        # Detect cycles for blocks/is_blocked_by
        if link_type in (LinkType.BLOCKS, LinkType.IS_BLOCKED_BY):
            would_create_cycle = await self._would_create_cycle(
                source_id, target_id
            )
            if would_create_cycle:
                raise ValueError(
                    "Creating this link would introduce a cycle in blocking chain"
                )

        # Create bidirectional link
        link = await self.link_repo.create(
            source_id=source_id,
            target_id=target_id,
            link_type=link_type,
            created_by_id=user_id,
        )

        # Create reverse link for is_blocked_by
        if link_type == LinkType.BLOCKS:
            await self.link_repo.create(
                source_id=target_id,
                target_id=source_id,
                link_type=LinkType.IS_BLOCKED_BY,
                created_by_id=user_id,
            )
        elif link_type == LinkType.IS_BLOCKED_BY:
            await self.link_repo.create(
                source_id=target_id,
                target_id=source_id,
                link_type=LinkType.BLOCKS,
                created_by_id=user_id,
            )

        await self.session.flush()
        return link

    async def delete_link(self, link_id: int) -> None:
        """Delete a task link and its reverse if exists."""
        link = await self.link_repo.get_by_id(link_id)
        if not link:
            raise ValueError(f"Link {link_id} not found")

        # Find and delete reverse link
        reverse_links = await self.link_repo.get_all(
            source_id=link.target_id,
            target_id=link.source_id,
        )
        for reverse_link in reverse_links:
            await self.link_repo.delete(reverse_link)

        await self.link_repo.delete(link)
        await self.session.flush()

    async def _would_create_cycle(self, source_id: int, target_id: int) -> bool:
        """Detect if adding this link would create a cycle."""
        # Simple DFS to check if there's a path from target to source
        visited = set()
        stack = [target_id]

        while stack:
            current = stack.pop()
            if current == source_id:
                return True
            if current in visited:
                continue
            visited.add(current)

            # Get all tasks that current blocks
            task = await self.task_repo.get_by_id(current)
            if task:
                blocking_links = await self.link_repo.get_all(
                    source_id=current,
                    link_type=LinkType.BLOCKS,
                )
                for link in blocking_links:
                    if link.target_id not in visited:
                        stack.append(link.target_id)

        return False
