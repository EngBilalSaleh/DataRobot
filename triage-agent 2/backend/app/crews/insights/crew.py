"""InsightsCrew: a workforce analyst that turns queue volumes into staffing moves."""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from app.llm import get_llm
from app.models import StaffingSuggestion


@CrewBase
class InsightsCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def analyst(self) -> Agent:
        return Agent(config=self.agents_config["analyst"], llm=get_llm("insights"), verbose=False)

    @task
    def suggest_staffing(self) -> Task:
        return Task(config=self.tasks_config["suggest_staffing"], output_pydantic=StaffingSuggestion)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)
