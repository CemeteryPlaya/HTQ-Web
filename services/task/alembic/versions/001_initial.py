"""Initial task service schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types
    status_enum = postgresql.ENUM('open', 'in_progress', 'in_review', 'done', 'closed', name='status', create_type=False)
    status_enum.create(op.get_bind(), checkfirst=True)
    
    priority_enum = postgresql.ENUM('critical', 'high', 'medium', 'low', 'trivial', name='priority', create_type=False)
    priority_enum.create(op.get_bind(), checkfirst=True)
    
    task_type_enum = postgresql.ENUM('task', 'bug', 'story', 'epic', 'subtask', name='tasktype', create_type=False)
    task_type_enum.create(op.get_bind(), checkfirst=True)
    
    link_type_enum = postgresql.ENUM('blocks', 'is_blocked_by', 'relates_to', 'duplicates', name='linktype', create_type=False)
    link_type_enum.create(op.get_bind(), checkfirst=True)
    
    version_status_enum = postgresql.ENUM('planned', 'in_progress', 'released', 'archived', name='versionstatus', create_type=False)
    version_status_enum.create(op.get_bind(), checkfirst=True)

    # Task sequence table
    op.create_table(
        'task_sequence',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
        sa.Column('current_value', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Production calendar
    op.create_table(
        'production_days',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('date', sa.Date(), unique=True, nullable=False),
        sa.Column('day_type', sa.String(20), nullable=False, server_default='working'),
        sa.Column('working_days_since_epoch', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_production_days_date', 'production_days', ['date'])
    op.create_index('ix_production_days_working_days', 'production_days', ['working_days_since_epoch'])

    # Labels
    op.create_table(
        'labels',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('color', sa.String(7), nullable=False, server_default='#808080'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Project versions
    op.create_table(
        'project_versions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(200), unique=True, nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', version_status_enum, nullable=False, server_default='planned'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('release_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Tasks
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('key', sa.String(20), unique=True, nullable=False),
        sa.Column('summary', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('task_type', task_type_enum, nullable=False, server_default='task'),
        sa.Column('priority', priority_enum, nullable=False, server_default='medium'),
        sa.Column('status', status_enum, nullable=False, server_default='open'),
        sa.Column('reporter_id', sa.Integer(), nullable=True),
        sa.Column('assignee_id', sa.Integer(), nullable=True),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('version_id', sa.Integer(), sa.ForeignKey('project_versions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('estimated_working_days', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint('start_date IS NULL OR due_date IS NULL OR start_date <= due_date', name='ck_task_dates'),
    )
    op.create_index('ix_tasks_key', 'tasks', ['key'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index('ix_tasks_reporter_id', 'tasks', ['reporter_id'])
    op.create_index('ix_tasks_assignee_id', 'tasks', ['assignee_id'])
    op.create_index('ix_tasks_department_id', 'tasks', ['department_id'])
    op.create_index('ix_tasks_version_id', 'tasks', ['version_id'])
    op.create_index('ix_tasks_parent_id', 'tasks', ['parent_id'])
    op.create_index('ix_tasks_is_deleted', 'tasks', ['is_deleted'])

    # Task labels (many-to-many)
    op.create_table(
        'task_labels',
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('label_id', sa.Integer(), sa.ForeignKey('labels.id', ondelete='CASCADE'), primary_key=True),
    )

    # Task comments
    op.create_table(
        'task_comments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_task_comments_task_id', 'task_comments', ['task_id'])

    # Task attachments
    op.create_table(
        'task_attachments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_task_attachments_task_id', 'task_attachments', ['task_id'])

    # Task activities
    op.create_table(
        'task_activities',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('field_name', sa.String(50), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_task_activities_task_id', 'task_activities', ['task_id'])

    # Task links
    op.create_table(
        'task_links',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('link_type', link_type_enum, nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('source_id', 'target_id', 'link_type', name='uq_task_link'),
    )
    op.create_index('ix_task_links_source_id', 'task_links', ['source_id'])
    op.create_index('ix_task_links_target_id', 'task_links', ['target_id'])

    # Notifications
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('verb', sa.String(200), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_notifications_recipient_id', 'notifications', ['recipient_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('task_links')
    op.drop_table('task_activities')
    op.drop_table('task_attachments')
    op.drop_table('task_comments')
    op.drop_table('task_labels')
    op.drop_table('tasks')
    op.drop_table('project_versions')
    op.drop_table('labels')
    op.drop_index('ix_production_days_working_days', table_name='production_days')
    op.drop_index('ix_production_days_date', table_name='production_days')
    op.drop_table('production_days')
    op.drop_table('task_sequence')
    
    # Drop ENUM types
    op.execute('DROP TYPE IF EXISTS versionstatus')
    op.execute('DROP TYPE IF EXISTS linktype')
    op.execute('DROP TYPE IF EXISTS tasktype')
    op.execute('DROP TYPE IF EXISTS priority')
    op.execute('DROP TYPE IF EXISTS status')
