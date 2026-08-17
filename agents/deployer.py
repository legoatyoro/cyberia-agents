from pathlib import Path
from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType, AgentOutput, ArchitectureBlueprint

class DeployerAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'DEPLOYER'

    def run(self, blueprint: ArchitectureBlueprint, project_dir: Path) -> AgentOutput:
        print(f'🚀 [{self.name}] Génération des fichiers de déploiement...')
        prompt = f'''Génère un Dockerfile multi-stage optimisé et un docker-compose.yml pour le projet {blueprint.project_name}.
Stack : {blueprint.stack}
Dépendances : {blueprint.dependencies}
Variables d\'env : {blueprint.env_vars}
Génère d\'abord le Dockerfile, puis le docker-compose.yml, séparés par ---SEPARATOR---.'''
        result = self.llm.call(TaskType.DEPLOY, prompt)
        parts = result.split('---SEPARATOR---')
        from cyberia_sanitizer import strip_markdown_artifacts
        if len(parts) >= 1:
            (project_dir / 'Dockerfile').write_text(strip_markdown_artifacts(parts[0].strip()), encoding='utf-8')
        if len(parts) >= 2:
            (project_dir / 'docker-compose.yml').write_text(strip_markdown_artifacts(parts[1].strip()), encoding='utf-8')
        reqs = '\n'.join(blueprint.dependencies)
        (project_dir / 'requirements.txt').write_text(reqs, encoding='utf-8')
        print(f'✅ [{self.name}] Dockerfile + docker-compose.yml + requirements.txt générés')
        return AgentOutput(agent_name=self.name, success=True, artifacts={'dockerfile': True, 'compose': True})
