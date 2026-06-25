"""Agent Team (Expert Panel) models — multi-agent collaborative teams."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentTeam(Base):
    """A team of expert agents that collaborate on user questions."""

    __tablename__ = "agent_teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    # Coordinator agent that synthesizes expert opinions (optional)
    coordinator_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))

    # Ownership & permissions (mirrors Agent access_mode pattern)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    access_mode: Mapped[str] = mapped_column(String(20), default="company")  # company | private | custom

    # Collaboration strategy: parallel (experts answer simultaneously) | sequential (ordered) | debate (multi-round)
    collaboration_mode: Mapped[str] = mapped_column(String(20), default="parallel")
    max_rounds: Mapped[int] = mapped_column(Integer, default=1)  # debate mode round limit

    welcome_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    members: Mapped[list["AgentTeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan", order_by="AgentTeamMember.sort_order"
    )
    coordinator: Mapped["Agent | None"] = relationship(foreign_keys=[coordinator_agent_id])
    creator: Mapped["User"] = relationship(foreign_keys=[creator_id])
    sessions: Mapped[list["AgentTeamSession"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class AgentTeamMember(Base):
    """A member agent in a team, with a role label for the team context."""

    __tablename__ = "agent_team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "agent_id", name="uq_team_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False, index=True)

    # Role label within this team, e.g. "frontend", "backend", "tester"
    member_role: Mapped[str] = mapped_column(String(50), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped["AgentTeam"] = relationship(back_populates="members")
    agent: Mapped["Agent"] = relationship(foreign_keys=[agent_id])


class AgentTeamSession(Base):
    """A chat session within a team (conversation thread)."""

    __tablename__ = "agent_team_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), default="Team Session")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped["AgentTeam"] = relationship(back_populates="sessions")
    messages: Mapped[list["AgentTeamMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AgentTeamMessage.created_at"
    )


class AgentTeamMessage(Base):
    """A message in a team chat session (from user, expert, coordinator, or system)."""

    __tablename__ = "agent_team_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_team_sessions.id", ondelete="CASCADE"), nullable=False, index=True)

    speaker_type: Mapped[str] = mapped_column(
        Enum("user", "expert", "coordinator", "system", name="team_speaker_type_enum"),
        nullable=False,
    )
    speaker_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    speaker_name: Mapped[str] = mapped_column(String(100), default="")
    member_role: Mapped[str | None] = mapped_column(String(50))

    content: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[str | None] = mapped_column(Text)

    round_number: Mapped[int] = mapped_column(Integer, default=1)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    session: Mapped["AgentTeamSession"] = relationship(back_populates="messages")


# Avoid circular import at module level — these are only for type checking
from app.models.agent import Agent  # noqa: E402
from app.models.user import User  # noqa: E402
