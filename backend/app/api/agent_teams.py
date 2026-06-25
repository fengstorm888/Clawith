"""Agent Team (Expert Panel) API routes — CRUD, member management, sessions, and WebSocket team chat."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import build_visible_teams_query, check_team_access
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.agent_team import AgentTeam, AgentTeamMember, AgentTeamMessage, AgentTeamSession
from app.models.user import User
from app.schemas.schemas import (
    AgentTeamCreate,
    AgentTeamMemberCreate,
    AgentTeamMemberOut,
    AgentTeamMessageOut,
    AgentTeamOut,
    AgentTeamSessionOut,
    AgentTeamUpdate,
)

router = APIRouter(prefix="/agent-teams", tags=["agent-teams"])


# ── Helpers ─────────────────────────────────────────────

async def _serialize_team(team: AgentTeam, db: AsyncSession, current_user: User) -> AgentTeamOut:
    """Serialize a team with member details and creator username."""
    # Load members with agent info
    member_result = await db.execute(
        select(AgentTeamMember)
        .where(AgentTeamMember.team_id == team.id)
        .order_by(AgentTeamMember.sort_order)
    )
    members = member_result.scalars().all()

    member_outs = []
    for m in members:
        agent_result = await db.execute(select(Agent).where(Agent.id == m.agent_id))
        agent = agent_result.scalar_one_or_none()
        member_outs.append(
            AgentTeamMemberOut(
                id=m.id,
                team_id=m.team_id,
                agent_id=m.agent_id,
                agent_name=agent.name if agent else None,
                agent_avatar_url=agent.avatar_url if agent else None,
                agent_role_description=agent.role_description if agent else None,
                agent_status=agent.status if agent else None,
                member_role=m.member_role,
                sort_order=m.sort_order,
                is_active=m.is_active,
                created_at=m.created_at,
            )
        )

    # Get creator username
    creator_result = await db.execute(select(User).where(User.id == team.creator_id))
    creator = creator_result.scalar_one_or_none()
    creator_username = creator.display_name or creator.username if creator else None

    return AgentTeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        avatar_url=team.avatar_url,
        coordinator_agent_id=team.coordinator_agent_id,
        creator_id=team.creator_id,
        creator_username=creator_username,
        access_mode=team.access_mode,
        collaboration_mode=team.collaboration_mode,
        max_rounds=team.max_rounds,
        welcome_message=team.welcome_message,
        status=team.status,
        members=member_outs,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


# ── Team CRUD ───────────────────────────────────────────

@router.get("/", response_model=list[AgentTeamOut])
async def list_teams(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all teams visible to the current user."""
    stmt = build_visible_teams_query(current_user)
    result = await db.execute(stmt.order_by(AgentTeam.created_at.desc()))
    teams = result.scalars().all()
    return [await _serialize_team(t, db, current_user) for t in teams]


@router.post("/", response_model=AgentTeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: AgentTeamCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent team with optional initial members."""
    if not current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tenant assigned")

    # Validate coordinator if provided
    if payload.coordinator_agent_id:
        coord_result = await db.execute(select(Agent).where(Agent.id == payload.coordinator_agent_id))
        coord = coord_result.scalar_one_or_none()
        if not coord or coord.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid coordinator agent")

    # Validate member agents
    for m in payload.members:
        agent_result = await db.execute(select(Agent).where(Agent.id == m.agent_id))
        agent = agent_result.scalar_one_or_none()
        if not agent or agent.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid agent: {m.agent_id}")

    team = AgentTeam(
        name=payload.name,
        description=payload.description,
        avatar_url=payload.avatar_url,
        coordinator_agent_id=payload.coordinator_agent_id,
        creator_id=current_user.id,
        tenant_id=current_user.tenant_id,
        access_mode=payload.access_mode,
        collaboration_mode=payload.collaboration_mode,
        max_rounds=payload.max_rounds,
        welcome_message=payload.welcome_message,
    )
    db.add(team)
    await db.flush()  # Get team.id

    # Add initial members
    for i, m in enumerate(payload.members):
        member = AgentTeamMember(
            team_id=team.id,
            agent_id=m.agent_id,
            member_role=m.member_role,
            sort_order=m.sort_order or i,
        )
        db.add(member)

    await db.commit()
    await db.refresh(team)

    return await _serialize_team(team, db, current_user)


@router.get("/{team_id}", response_model=AgentTeamOut)
async def get_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get team details by ID."""
    team, _ = await check_team_access(db, current_user, team_id)
    return await _serialize_team(team, db, current_user)


@router.patch("/{team_id}", response_model=AgentTeamOut)
async def update_team(
    team_id: uuid.UUID,
    payload: AgentTeamUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update team settings (creator/admin only)."""
    team, access_level = await check_team_access(db, current_user, team_id)
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team creator can update")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(team, key, value)

    await db.commit()
    await db.refresh(team)
    return await _serialize_team(team, db, current_user)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a team and all its members, sessions, and messages."""
    team, access_level = await check_team_access(db, current_user, team_id)
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team creator can delete")

    await db.delete(team)
    await db.commit()


# ── Member Management ───────────────────────────────────

@router.post("/{team_id}/members", response_model=AgentTeamMemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(
    team_id: uuid.UUID,
    payload: AgentTeamMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an agent to a team."""
    team, access_level = await check_team_access(db, current_user, team_id)
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team creator can add members")

    # Validate agent
    agent_result = await db.execute(select(Agent).where(Agent.id == payload.agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent")

    # Check duplicate
    existing = await db.execute(
        select(AgentTeamMember).where(
            AgentTeamMember.team_id == team_id,
            AgentTeamMember.agent_id == payload.agent_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent already in team")

    member = AgentTeamMember(
        team_id=team_id,
        agent_id=payload.agent_id,
        member_role=payload.member_role,
        sort_order=payload.sort_order,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return AgentTeamMemberOut(
        id=member.id,
        team_id=member.team_id,
        agent_id=member.agent_id,
        agent_name=agent.name,
        agent_avatar_url=agent.avatar_url,
        agent_role_description=agent.role_description,
        agent_status=agent.status,
        member_role=member.member_role,
        sort_order=member.sort_order,
        is_active=member.is_active,
        created_at=member.created_at,
    )


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a team."""
    team, access_level = await check_team_access(db, current_user, team_id)
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team creator can remove members")

    result = await db.execute(
        select(AgentTeamMember).where(
            AgentTeamMember.id == member_id,
            AgentTeamMember.team_id == team_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    await db.delete(member)
    await db.commit()


@router.patch("/{team_id}/members/{member_id}", response_model=AgentTeamMemberOut)
async def update_member(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role, sort order, or active status."""
    team, access_level = await check_team_access(db, current_user, team_id)
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only team creator can update members")

    result = await db.execute(
        select(AgentTeamMember).where(
            AgentTeamMember.id == member_id,
            AgentTeamMember.team_id == team_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    for key in ("member_role", "sort_order", "is_active"):
        if key in payload:
            setattr(member, key, payload[key])

    await db.commit()
    await db.refresh(member)

    # Load agent info
    agent_result = await db.execute(select(Agent).where(Agent.id == member.agent_id))
    agent = agent_result.scalar_one_or_none()

    return AgentTeamMemberOut(
        id=member.id,
        team_id=member.team_id,
        agent_id=member.agent_id,
        agent_name=agent.name if agent else None,
        agent_avatar_url=agent.avatar_url if agent else None,
        agent_role_description=agent.role_description if agent else None,
        agent_status=agent.status if agent else None,
        member_role=member.member_role,
        sort_order=member.sort_order,
        is_active=member.is_active,
        created_at=member.created_at,
    )


# ── Sessions ────────────────────────────────────────────

@router.get("/{team_id}/sessions", response_model=list[AgentTeamSessionOut])
async def list_sessions(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List chat sessions for a team."""
    team, _ = await check_team_access(db, current_user, team_id)
    result = await db.execute(
        select(AgentTeamSession)
        .where(AgentTeamSession.team_id == team_id)
        .order_by(AgentTeamSession.last_message_at.desc().nullslast())
    )
    return result.scalars().all()


@router.post("/{team_id}/sessions", response_model=AgentTeamSessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session for a team."""
    team, _ = await check_team_access(db, current_user, team_id)
    session = AgentTeamSession(
        team_id=team_id,
        user_id=current_user.id,
        title=f"Team Chat - {team.name}",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{team_id}/sessions/{session_id}/messages", response_model=list[AgentTeamMessageOut])
async def list_messages(
    team_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List messages in a team chat session."""
    team, _ = await check_team_access(db, current_user, team_id)
    result = await db.execute(
        select(AgentTeamMessage)
        .where(
            AgentTeamMessage.team_id == team_id,
            AgentTeamMessage.session_id == session_id,
        )
        .order_by(AgentTeamMessage.created_at.asc())
    )
    return result.scalars().all()


# ── WebSocket Team Chat ─────────────────────────────────

@router.websocket("/ws/team-chat/{team_id}")
async def team_chat_websocket(
    websocket: WebSocket,
    team_id: uuid.UUID,
    token: str = Query(...),
    session_id: str = Query(None),
    lang: str = Query("en"),
):
    """WebSocket endpoint for real-time team chat with multiple expert agents."""
    from app.services.team_collaboration import TeamChatHandler

    await websocket.accept()
    handler = TeamChatHandler(websocket, team_id, token, session_id, lang)
    await handler.run()
