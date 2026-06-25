"""Team collaboration orchestration service.

Handles multi-agent team chat: dispatches user questions to expert agents
in parallel/sequential mode, then optionally synthesizes via coordinator agent.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.permissions import check_team_access
from app.core.security import decode_access_token
from app.database import async_session
from app.models.agent import Agent
from app.models.agent_team import AgentTeam, AgentTeamMember, AgentTeamMessage, AgentTeamSession
from app.models.llm import LLMModel
from app.models.user import User

# ── Prompt suffixes ──────────────────────────────────────

EXPERT_PROMPT_SUFFIX = """

You are now participating in an expert team discussion. A user has asked a question,
and you should answer from your area of expertise: **{role}**.

Guidelines:
- Focus on your domain of expertise
- Be concise and actionable
- If the question is outside your expertise, say so briefly
- Do not repeat what others may have already covered — provide your unique perspective
"""

COORDINATOR_PROMPT = """You are the coordinator of an expert team. The user asked:

{question}

Your team of experts provided the following responses:

{expert_responses}

As the coordinator, synthesize these expert opinions into a single, coherent answer.
- Highlight key points of agreement and disagreement
- Provide a clear, actionable recommendation
- Structure the answer with headers if needed
- Do not introduce new information not supported by the experts
"""


class TeamChatHandler:
    """Manages WebSocket lifecycle and multi-agent orchestration for team chat."""

    def __init__(
        self,
        websocket: WebSocket,
        team_id: uuid.UUID,
        token: str,
        session_id: str | None = None,
        lang: str = "en",
    ):
        self.websocket = websocket
        self.team_id = team_id
        self.token = token
        self.session_id_param = session_id
        self.lang = lang

        self.user: User | None = None
        self.team: AgentTeam | None = None
        self.members: list[AgentTeamMember] = []
        self.coordinator: Agent | None = None
        self.session: AgentTeamSession | None = None
        self.current_round: int = 1

    async def run(self):
        """Main entry point — setup, then message loop."""
        try:
            success = await self.setup()
            if not success:
                return
            await self.message_loop()
        except Exception as e:
            logger.error(f"[TeamChat] Error: {e}")
            try:
                await self.websocket.send_json({"type": "error", "content": str(e)})
            except Exception:
                pass
        finally:
            try:
                await self.websocket.close()
            except Exception:
                pass

    async def setup(self) -> bool:
        """Authenticate, load team members, create/resume session."""
        # 1. Decode token → user
        payload = decode_access_token(self.token)
        user_id = payload.get("sub")
        if not user_id:
            await self.websocket.send_json({"type": "error", "content": "Invalid token"})
            return False

        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.id == uuid.UUID(user_id))
            )
            self.user = result.scalar_one_or_none()
            if not self.user or not self.user.is_active:
                await self.websocket.send_json({"type": "error", "content": "User not found or inactive"})
                return False

            # 2. Check team access
            self.team, access_level = await check_team_access(db, self.user, self.team_id)

            # 3. Load active members with their agents
            member_result = await db.execute(
                select(AgentTeamMember)
                .where(
                    AgentTeamMember.team_id == self.team_id,
                    AgentTeamMember.is_active == True,  # noqa: E712
                )
                .order_by(AgentTeamMember.sort_order)
            )
            self.members = member_result.scalars().all()

            # Load agent info for each member
            for m in self.members:
                agent_result = await db.execute(select(Agent).where(Agent.id == m.agent_id))
                m.agent = agent_result.scalar_one_or_none()

            # Filter out members whose agents are unavailable
            self.members = [m for m in self.members if m.agent and m.agent.status not in ("stopped", "error")]

            # 4. Load coordinator
            if self.team.coordinator_agent_id:
                coord_result = await db.execute(
                    select(Agent).where(Agent.id == self.team.coordinator_agent_id)
                )
                self.coordinator = coord_result.scalar_one_or_none()

            # 5. Create or resume session
            if self.session_id_param:
                sess_result = await db.execute(
                    select(AgentTeamSession).where(
                        AgentTeamSession.id == uuid.UUID(self.session_id_param),
                        AgentTeamSession.team_id == self.team_id,
                    )
                )
                self.session = sess_result.scalar_one_or_none()

            if not self.session:
                self.session = AgentTeamSession(
                    team_id=self.team_id,
                    user_id=self.user.id,
                    title=f"Team Chat - {self.team.name}",
                )
                db.add(self.session)
                await db.commit()
                await db.refresh(self.session)

        # 6. Send connected event with member info
        await self.websocket.send_json({
            "type": "connected",
            "team_id": str(self.team_id),
            "session_id": str(self.session.id),
            "team_name": self.team.name,
            "members": [
                {
                    "agent_id": str(m.agent_id),
                    "agent_name": m.agent.name if m.agent else "",
                    "member_role": m.member_role,
                    "avatar_url": m.agent.avatar_url if m.agent else None,
                }
                for m in self.members
            ],
            "has_coordinator": self.coordinator is not None,
            "coordinator_name": self.coordinator.name if self.coordinator else None,
        })

        return True

    async def message_loop(self):
        """Receive user messages and orchestrate team responses."""
        while True:
            data = await self.websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
                await self.orchestrate(content)

    async def orchestrate(self, user_question: str):
        """Dispatch question to experts, then coordinator."""
        # 1. Persist user message
        await self._persist_message(
            speaker_type="user",
            speaker_name=self.user.display_name or self.user.username,
            content=user_question,
            round_number=self.current_round,
            user_id=self.user.id,
        )

        # 2. Run experts
        mode = self.team.collaboration_mode or "parallel"

        if mode == "sequential":
            expert_outputs = await self._run_experts_sequential(user_question)
        else:
            expert_outputs = await self._run_experts_parallel(user_question)

        # 3. Run coordinator if configured
        if self.coordinator and expert_outputs:
            await self._run_coordinator(user_question, expert_outputs)

        # 4. Signal round done
        await self.websocket.send_json({
            "type": "round_done",
            "round_number": self.current_round,
        })
        self.current_round += 1

    async def _run_experts_parallel(self, question: str) -> list[dict]:
        """Run all experts concurrently."""
        tasks = [self._run_single_expert(m, question) for m in self.members]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        outputs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[TeamChat] Expert {self.members[i].agent.name if self.members[i].agent else '?'} failed: {result}")
                continue
            if result:
                outputs.append(result)
        return outputs

    async def _run_experts_sequential(self, question: str) -> list[dict]:
        """Run experts one by one, each seeing prior responses."""
        outputs = []
        for member in self.members:
            prior_context = ""
            if outputs:
                prior_context = "\n\nPrevious expert responses:\n"
                for o in outputs:
                    prior_context += f"- {o['speaker_name']} ({o['member_role']}): {o['content'][:500]}\n"

            result = await self._run_single_expert(member, question, prior_context)
            if result:
                outputs.append(result)
        return outputs

    async def _run_single_expert(
        self,
        member: AgentTeamMember,
        question: str,
        prior_context: str = "",
    ) -> dict | None:
        """Run a single expert agent and stream chunks to the WebSocket."""
        agent = member.agent
        if not agent:
            return None

        speaker_name = agent.name
        member_role = member.member_role or agent.role_description or "expert"

        # Notify frontend that this expert is starting
        await self.websocket.send_json({
            "type": "expert_start",
            "speaker_agent_id": str(agent.id),
            "speaker_name": speaker_name,
            "member_role": member_role,
        })

        try:
            # Build context for this agent
            from app.services.agent_context import build_agent_context
            system_prompt, _ = await build_agent_context(
                agent.id, agent.name, agent.role_description, self.user.display_name or self.user.username
            )
            system_prompt += EXPERT_PROMPT_SUFFIX.format(role=member_role)
            if prior_context:
                system_prompt += prior_context

            # Load LLM model
            primary_model = await self._load_llm_model(agent.primary_model_id)
            fallback_model = await self._load_llm_model(agent.fallback_model_id)

            if not primary_model:
                await self.websocket.send_json({
                    "type": "expert_chunk",
                    "speaker_agent_id": str(agent.id),
                    "content": f"[Error: No LLM model configured for {speaker_name}]",
                })
                await self.websocket.send_json({
                    "type": "expert_done",
                    "speaker_agent_id": str(agent.id),
                })
                return {
                    "speaker_name": speaker_name,
                    "member_role": member_role,
                    "content": f"[Error: No LLM model configured]",
                }

            # Prepare messages
            messages = [{"role": "user", "content": question}]

            # Stream callback
            accumulated_content = []

            async def on_chunk(text: str):
                accumulated_content.append(text)
                await self.websocket.send_json({
                    "type": "expert_chunk",
                    "speaker_agent_id": str(agent.id),
                    "content": text,
                })

            # Call LLM
            from app.services.llm.caller import call_llm_with_failover
            response = await call_llm_with_failover(
                primary_model=primary_model,
                fallback_model=fallback_model,
                messages=messages,
                agent_name=agent.name,
                role_description=agent.role_description,
                agent_id=agent.id,
                user_id=self.user.id,
                session_id=str(self.session.id),
                on_chunk=on_chunk,
                skip_tools=True,
                system_prompt_suffix=EXPERT_PROMPT_SUFFIX.format(role=member_role) + prior_context,
            )

            full_content = response if response else "".join(accumulated_content)

            # Persist expert message
            await self._persist_message(
                speaker_type="expert",
                speaker_agent_id=agent.id,
                speaker_name=speaker_name,
                member_role=member_role,
                content=full_content,
                round_number=self.current_round,
                user_id=self.user.id,
            )

            await self.websocket.send_json({
                "type": "expert_done",
                "speaker_agent_id": str(agent.id),
            })

            return {
                "speaker_name": speaker_name,
                "member_role": member_role,
                "content": full_content,
            }

        except Exception as e:
            logger.error(f"[TeamChat] Expert {speaker_name} error: {e}")
            await self.websocket.send_json({
                "type": "expert_chunk",
                "speaker_agent_id": str(agent.id),
                "content": f"[Error: {str(e)}]",
            })
            await self.websocket.send_json({
                "type": "expert_done",
                "speaker_agent_id": str(agent.id),
            })
            return None

    async def _run_coordinator(self, question: str, expert_outputs: list[dict]):
        """Run the coordinator agent to synthesize expert responses."""
        await self.websocket.send_json({
            "type": "coordinator_start",
            "speaker_name": self.coordinator.name,
        })

        try:
            # Build expert responses text
            expert_text = ""
            for i, o in enumerate(expert_outputs, 1):
                expert_text += f"### Expert {i}: {o['speaker_name']} ({o['member_role']})\n{o['content']}\n\n"

            system_prompt = COORDINATOR_PROMPT.format(question=question, expert_responses=expert_text)

            primary_model = await self._load_llm_model(self.coordinator.primary_model_id)
            fallback_model = await self._load_llm_model(self.coordinator.fallback_model_id)

            if not primary_model:
                await self.websocket.send_json({
                    "type": "coordinator_chunk",
                    "content": "[Error: No LLM model configured for coordinator]",
                })
                await self.websocket.send_json({"type": "coordinator_done"})
                return

            messages = [{"role": "user", "content": question}]

            accumulated = []

            async def on_chunk(text: str):
                accumulated.append(text)
                await self.websocket.send_json({
                    "type": "coordinator_chunk",
                    "content": text,
                })

            from app.services.llm.caller import call_llm_with_failover
            response = await call_llm_with_failover(
                primary_model=primary_model,
                fallback_model=fallback_model,
                messages=messages,
                agent_name=self.coordinator.name,
                role_description="Team Coordinator",
                agent_id=self.coordinator.id,
                user_id=self.user.id,
                session_id=str(self.session.id),
                on_chunk=on_chunk,
                skip_tools=True,
                system_prompt_suffix=system_prompt,
            )

            full_content = response if response else "".join(accumulated)

            await self._persist_message(
                speaker_type="coordinator",
                speaker_agent_id=self.coordinator.id,
                speaker_name=self.coordinator.name,
                content=full_content,
                round_number=self.current_round,
                user_id=self.user.id,
            )

            await self.websocket.send_json({"type": "coordinator_done"})

        except Exception as e:
            logger.error(f"[TeamChat] Coordinator error: {e}")
            await self.websocket.send_json({
                "type": "coordinator_chunk",
                "content": f"[Error: {str(e)}]",
            })
            await self.websocket.send_json({"type": "coordinator_done"})

    async def _load_llm_model(self, model_id: uuid.UUID | None) -> LLMModel | None:
        """Load an LLM model by ID."""
        if not model_id:
            return None
        async with async_session() as db:
            result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
            return result.scalar_one_or_none()

    async def _persist_message(
        self,
        speaker_type: str,
        speaker_agent_id: uuid.UUID | None = None,
        speaker_name: str = "",
        member_role: str | None = None,
        content: str = "",
        round_number: int = 1,
        user_id: uuid.UUID | None = None,
    ):
        """Persist a team message to the database."""
        async with async_session() as db:
            msg = AgentTeamMessage(
                team_id=self.team_id,
                session_id=self.session.id,
                speaker_type=speaker_type,
                speaker_agent_id=speaker_agent_id,
                speaker_name=speaker_name,
                member_role=member_role,
                content=content,
                round_number=round_number,
                user_id=user_id,
            )
            db.add(msg)

            # Update session last_message_at
            self.session.last_message_at = datetime.now(timezone.utc)
            db.add(self.session)

            await db.commit()
