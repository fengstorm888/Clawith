"""add_agent_teams

Revision ID: add_agent_teams
Revises: add_title_to_agent_focus_items
Create Date: 2026-06-25 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'add_agent_teams'
down_revision: Union[str, None] = 'add_title_to_agent_focus_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_teams',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text, server_default=''),
        sa.Column('avatar_url', sa.String(500)),
        sa.Column('coordinator_agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id')),
        sa.Column('creator_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), index=True),
        sa.Column('access_mode', sa.String(20), server_default='company'),
        sa.Column('collaboration_mode', sa.String(20), server_default='parallel'),
        sa.Column('max_rounds', sa.Integer, server_default='1'),
        sa.Column('welcome_message', sa.Text),
        sa.Column('status', sa.String(20), server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'agent_team_members',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', UUID(as_uuid=True), sa.ForeignKey('agent_teams.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id'), nullable=False, index=True),
        sa.Column('member_role', sa.String(50), server_default=''),
        sa.Column('sort_order', sa.Integer, server_default='0'),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('team_id', 'agent_id', name='uq_team_member'),
    )

    op.create_table(
        'agent_team_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', UUID(as_uuid=True), sa.ForeignKey('agent_teams.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(200), server_default='Team Session'),
        sa.Column('last_message_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'agent_team_messages',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', UUID(as_uuid=True), sa.ForeignKey('agent_teams.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('agent_team_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('speaker_type', sa.Enum('user', 'expert', 'coordinator', 'system', name='team_speaker_type_enum'), nullable=False),
        sa.Column('speaker_agent_id', UUID(as_uuid=True), sa.ForeignKey('agents.id')),
        sa.Column('speaker_name', sa.String(100), server_default=''),
        sa.Column('member_role', sa.String(50)),
        sa.Column('content', sa.Text, server_default=''),
        sa.Column('thinking', sa.Text),
        sa.Column('round_number', sa.Integer, server_default='1'),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table('agent_team_messages')
    op.drop_table('agent_team_sessions')
    op.drop_table('agent_team_members')
    op.drop_table('agent_teams')
    sa.Enum(name='team_speaker_type_enum').drop(op.get_bind(), checkfirst=True)
