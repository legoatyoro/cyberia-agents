import json
from core.multi_model_router import get_router

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class TaskDecomposer:
    def __init__(self):
        self.router = get_router()
        self.name = 'TASK_DECOMPOSER'

    def _ensure_networkx(self):
        global HAS_NETWORKX
        if not HAS_NETWORKX:
            import subprocess
            import sys
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'networkx', '-q'])
            import importlib
            nx = importlib.import_module('networkx')
            HAS_NETWORKX = True
            return nx
        import networkx as nx
        return nx

    def decompose(self, cdc: str) -> dict:
        print(f'[{self.name}] Décomposition de la tâche...')
        prompt = f'''Tu es un architecte expert. Décompose ce projet en sous-tâches.

PROJET : {cdc}

Génère UNIQUEMENT ce JSON :
{{
  "project_name": "nom-snake-case",
  "complexity": "simple|medium|complex",
  "tasks": [
    {{
      "id": "task_1",
      "name": "Nom court",
      "description": "Ce que fait cette tâche",
      "agent": "ARCHITECTE|BUILDER|EXPERT_PYTHON|EXPERT_TYPESCRIPT|EXPERT_DATABASE|EXPERT_SECURITY|TESTER|DOCUMENTER|DEPLOYER",
      "depends_on": [],
      "parallel": false,
      "estimated_minutes": 2
    }}
  ]
}}

Règles :
- Maximum 10 tâches
- depends_on contient les IDs des tâches prérequises
- parallel: true si la tâche peut tourner en parallèle
- Toujours finir par TESTER et DOCUMENTER'''

        raw = self.router.call(prompt, task_type='planning', temperature=0.3)
        raw = raw.strip().replace('```json', '').replace('```', '').strip()

        try:
            plan = json.loads(raw)
        except Exception:
            print(f'  Avertissement : JSON invalide — plan par défaut')
            plan = {
                'project_name': 'projet',
                'complexity': 'medium',
                'tasks': [
                    {'id': 't1', 'name': 'Architecture', 'description': 'Blueprint',
                     'agent': 'ARCHITECTE', 'depends_on': [], 'parallel': False, 'estimated_minutes': 2},
                    {'id': 't2', 'name': 'Génération', 'description': 'Code',
                     'agent': 'BUILDER', 'depends_on': ['t1'], 'parallel': False, 'estimated_minutes': 5},
                    {'id': 't3', 'name': 'Tests', 'description': 'Tests',
                     'agent': 'TESTER', 'depends_on': ['t2'], 'parallel': False, 'estimated_minutes': 2},
                ]
            }

        execution_order = self._build_dag(plan['tasks'])
        plan['execution_order'] = execution_order
        total_minutes = sum(t.get('estimated_minutes', 2) for t in plan['tasks'])
        plan['estimated_total_minutes'] = total_minutes

        print(f'  {len(plan["tasks"])} tâches | Complexité : {plan["complexity"]} | ~{total_minutes} min')
        self._print_plan(plan)
        return plan

    def _build_dag(self, tasks: list) -> list:
        nx = self._ensure_networkx()
        G = nx.DiGraph()
        task_ids = {t['id'] for t in tasks}
        for task in tasks:
            G.add_node(task['id'], **task)
        for task in tasks:
            for dep in task.get('depends_on', []):
                if dep in task_ids:
                    G.add_edge(dep, task['id'])
        if nx.is_directed_acyclic_graph(G):
            return list(nx.topological_sort(G))
        else:
            print('  Avertissement : Cycle détecté dans les dépendances — ordre séquentiel')
            return [t['id'] for t in tasks]

    def _print_plan(self, plan: dict):
        print(f'\n  Plan d\'exécution :')
        task_map = {t['id']: t for t in plan['tasks']}
        for task_id in plan.get('execution_order', []):
            if task_id in task_map:
                task = task_map[task_id]
                deps = task.get('depends_on', [])
                dep_str = f' (après {", ".join(deps)})' if deps else ''
                parallel = ' [parallel]' if task.get('parallel') else ''
                print(f'    [{task["agent"]}] {task["name"]}{dep_str}{parallel}')
        print()


if __name__ == '__main__':
    decomposer = TaskDecomposer()
    plan = decomposer.decompose('application de facturation pour PME avec Stripe')
    print(f'Résultat : projet={plan["project_name"]}, complexité={plan["complexity"]}')
