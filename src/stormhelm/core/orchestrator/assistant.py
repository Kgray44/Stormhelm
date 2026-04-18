from __future__ import annotations

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.memory.repositories import ConversationRepository
from stormhelm.core.orchestrator.router import IntentRouter


class AssistantOrchestrator:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        jobs: JobManager,
        router: IntentRouter,
        events: EventBuffer,
    ) -> None:
        self.conversations = conversations
        self.jobs = jobs
        self.router = router
        self.events = events

    async def handle_message(self, message: str, session_id: str = "default") -> dict[str, object]:
        self.conversations.ensure_session(session_id)
        user_message = self.conversations.add_message(session_id, "user", message)
        routed = self.router.route(message)

        if routed.tool_name is None:
            assistant_text = routed.fallback_message or "I did not recognize that request."
            assistant_message = self.conversations.add_message(session_id, "assistant", assistant_text)
            return {
                "session_id": session_id,
                "user_message": user_message.to_dict(),
                "assistant_message": assistant_message.to_dict(),
                "job": None,
            }

        job = await self.jobs.submit_and_wait(routed.tool_name, routed.arguments)
        if job.result and job.result.get("success"):
            assistant_text = job.result.get("summary", "Tool completed successfully.")
        else:
            assistant_text = job.error or "The requested tool did not complete successfully."

        assistant_message = self.conversations.add_message(
            session_id,
            "assistant",
            assistant_text,
            metadata={"job_id": job.job_id, "tool_name": job.tool_name},
        )
        self.events.publish(
            level="INFO",
            source="assistant",
            message=f"Handled message in session '{session_id}'.",
            payload={"job_id": job.job_id, "tool_name": job.tool_name},
        )
        return {
            "session_id": session_id,
            "user_message": user_message.to_dict(),
            "assistant_message": assistant_message.to_dict(),
            "job": job.to_dict(),
        }

