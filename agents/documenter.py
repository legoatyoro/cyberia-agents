from pathlib import Path
from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType, AgentOutput, ArchitectureBlueprint

class DocumenterAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'DOCUMENTER'

    def run(self, blueprint: ArchitectureBlueprint, project_dir: Path) -> AgentOutput:
        print(f'📚 [{self.name}] Génération de la documentation...')
        prompt = f'''Génère un README.md complet pour le projet {blueprint.project_name}.
Stack : {blueprint.stack}
Fichiers : {blueprint.files_to_create}
Variables d\'env : {blueprint.env_vars}

Le README doit contenir : description, prérequis, installation, configuration .env, lancement, endpoints API, exemples curl, structure du projet.'''
        readme = self.llm.call(TaskType.DOC, prompt)
        (project_dir / 'README.md').write_text(readme, encoding='utf-8')
        makefile = 'run:\n\tpython main.py\ntest:\n\tpytest tests/ -v\ninstall:\n\tpip install -r requirements.txt\nlint:\n\tpython -m py_compile *.py\n'
        (project_dir / 'Makefile').write_text(makefile, encoding='utf-8')
        print(f'✅ [{self.name}] README.md + Makefile générés')
        return AgentOutput(agent_name=self.name, success=True, artifacts={'readme': True, 'makefile': True})
