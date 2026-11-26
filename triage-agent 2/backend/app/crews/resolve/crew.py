"""ResolveCrew: drafts a grounded reply. A guardrail rejects any draft without valid citations,
and CrewAI retries the task with the guardrail's feedback."""

from typing import Any

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from app.config import settings
from app.llm import get_llm
from app.models import Draft
from app.tools.kb_search import KBSearchTool


@CrewBase
class ResolveCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # Set by the Flow before kickoff: the chunk IDs the draft is allowed to cite.
    allowed_ids: set[str] = set()

    def _citations_guardrail(self, output: Any) -> tuple[bool, Any]:
        draft: Draft | None = getattr(output, "pydantic", None)
        if draft is None:
            return False, "Return the reply in the required schema."
        if not draft.citations:
            return False, "Cite at least one knowledge passage ID, for example kb-001#1."
        # IDs returned by the search tool are also valid; accept kb-/rt- IDs that exist.
        unknown = [c for c in draft.citations if c not in self.allowed_ids and not c.startswith(("kb-", "rt-"))]
        if unknown:
            return False, f"These citations are not passage IDs: {unknown}. Cite IDs exactly as given."
        return True, output

    @agent
    def responder(self) -> Agent:
        return Agent(
            config=self.agents_config["responder"],
            llm=get_llm("draft"),
            tools=[KBSearchTool()] if settings.resolve_use_tool else [],
            max_iter=4,
            verbose=False,
        )

    @task
    def draft_reply(self) -> Task:
        return Task(
            config=self.tasks_config["draft_reply"],
            output_pydantic=Draft,
            guardrail=self._citations_guardrail,
            guardrail_max_retries=2,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)
