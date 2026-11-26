"""ClassifyCrew: one agent, one task, a typed Classification out."""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from app.llm import get_llm
from app.models import Classification


@CrewBase
class ClassifyCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def classifier(self) -> Agent:
        return Agent(config=self.agents_config["classifier"], llm=get_llm("classify"), verbose=False)

    @task
    def classify(self) -> Task:
        return Task(config=self.tasks_config["classify"], output_pydantic=Classification)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=False)
