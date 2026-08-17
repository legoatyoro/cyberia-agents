import json, re, uuid
from datetime import datetime
from core.multi_model_router import MultiModelRouter
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class TaskStatus(Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


@dataclass
class Task:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ''
    description: str = ''
    agent: str = ''
    depends_on: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class TaskPlanner:
    def __init__(self):
        self.router = MultiModelRouter()
        self.tasks: List[Task] = []
        self.context = {}

    def decompose(self, goal, project_context=''):
        prompt = f'''Tu es un orchestrateur IA. Decompose cet objectif en taches atomiques avec dependances.
OBJECTIF: {goal}
CONTEXTE: {project_context[:500]}

Agents disponibles: ARCHITECT (conception), CODER (generation code), REVIEWER (verification), TESTER (tests), FIXER (correction bugs), DOCUMENTER (documentation)

Reponds UNIQUEMENT en JSON:
[
  {{"id": "t1", "name": "...", "description": "...", "agent": "ARCHITECT", "depends_on": []}},
  {{"id": "t2", "name": "...", "description": "...", "agent": "CODER", "depends_on": ["t1"]}},
  {{"id": "t3", "name": "...", "description": "...", "agent": "REVIEWER", "depends_on": ["t2"]}}
]
Maximum 6 taches. Ordre logique avec vraies dependances.'''
        response = self.router.call(prompt, task_type='architecture')
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                tasks_data = json.loads(match.group())
                self.tasks = [Task(**t) for t in tasks_data]
                return self.tasks
            except Exception as e:
                print(f'  [PLANNER] Erreur decomposition: {e}')
        return []

    def execute_task(self, task, accumulated_context=''):
        task.status = TaskStatus.RUNNING
        print(f'  [PLANNER] Execution {task.agent}: {task.name}')
        agent_prompts = {
            'ARCHITECT': f'Tu es un architecte logiciel expert. Reponds en francais. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
            'CODER': f'Tu es un developpeur expert. Genere du code production-ready sans markdown. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
            'REVIEWER': f'Tu es un reviewer expert. Identifie les problemes concrets et propose des corrections. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
            'TESTER': f'Tu es un expert QA. Genere des tests pytest complets. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
            'FIXER': f'Tu es un expert debugging. Corrige les problemes identifies. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
            'DOCUMENTER': f'Tu es un redacteur technique. Genere de la documentation claire. Tache: {task.description}\nContexte: {accumulated_context[:1000]}',
        }
        task_type = (
            'architecture' if task.agent == 'ARCHITECT' else
            'code' if task.agent in ('CODER', 'FIXER') else
            'analysis'
        )
        prompt = agent_prompts.get(task.agent, f'Tache: {task.description}')
        result = self.router.call(prompt, task_type=task_type)
        task.result = result
        task.status = TaskStatus.DONE
        return result

    def run_pipeline(self, goal, project_context='', on_task_done=None):
        print(f'\n  [PLANNER] Decomposition de: {goal[:60]}')
        tasks = self.decompose(goal, project_context)
        if not tasks:
            return 'Echec decomposition'
        print(f'  [PLANNER] {len(tasks)} taches planifiees')
        completed = {}
        results = []
        for task in tasks:
            deps_done = all(dep in completed for dep in task.depends_on)
            if not deps_done:
                task.status = TaskStatus.FAILED
                continue
            deps_context = '\n'.join(
                f'[{dep}]: {completed[dep][:300]}' for dep in task.depends_on if dep in completed
            )
            accumulated = project_context + '\n' + deps_context
            result = self.execute_task(task, accumulated)
            completed[task.id] = result or ''
            results.append(f'=== {task.agent}: {task.name} ===\n{result}')
            if on_task_done:
                on_task_done(task)
        return '\n\n'.join(results)

    def get_status(self):
        return [(t.name, t.agent, t.status.value, len(t.result or '')) for t in self.tasks]
