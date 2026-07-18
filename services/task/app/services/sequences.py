from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import TaskSequence

async def next_task_key(session: AsyncSession, project_prefix: str) -> str:
    # SELECT last_number FROM task_sequences WHERE prefix = :p FOR UPDATE
    # UPDATE ... SET last_number = last_number + 1
    # return f"{prefix}-{n}"
    result = await session.execute(
        select(TaskSequence).where(TaskSequence.prefix == project_prefix).with_for_update()
    )
    seq = result.scalar_one_or_none()
    if seq is None:
        seq = TaskSequence(prefix=project_prefix, last_number=0)
        session.add(seq)
    seq.last_number += 1
    await session.flush()
    return f"{project_prefix}-{seq.last_number}"
