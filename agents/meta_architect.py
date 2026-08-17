import json
from pathlib import Path
from core.multi_model_router import get_router
from core.agent_registry import register_agent
from core.event_bus import publish
from schemas.agent_schemas import AgentOutput, TaskType
from cyberia_sanitizer import strip_markdown_artifacts

META_ARCHITECT_SCHEMA = '''
{
  "project_name": "snake_case_name",
  "description": "Description courte du système",
  "agents": [
    {
      "name": "AGENT_NAME",
      "file": "agents/agent_name.py",
      "class": "AgentNameAgent",
      "responsibilities": ["liste des responsabilités"],
      "inputs": ["type_entree_1", "type_entree_2"],
      "outputs": ["type_sortie_1"],
      "dependencies": ["librairie_pip_1"],
      "calls_agents": ["AUTRE_AGENT"],
      "publishes_events": ["EVENT_TYPE"],
      "subscribes_events": ["EVENT_TYPE"]
    }
  ],
  "pipeline": ["AGENT_1", "AGENT_2", "AGENT_3"],
  "estimated_files": 5
}
'''

class MetaArchitectAgent:
    def __init__(self):
        self.router = get_router()
        self.name = 'META_ARCHITECT'

    def design_agent_system(self, description: str) -> tuple[dict, str]:
        print(f'🏛️ [{self.name}] Conception du système d\'agents...')
        prompt = f'''Tu es un architecte expert en systèmes multi-agents Python.
L\'utilisateur veut construire : {description}

Conçois un système d\'agents Python spécialisés pour accomplir cette tâche de façon autonome.

Réponds avec DEUX sections :

## ARCHITECTURE NARRATIVE
(2-3 paragraphes expliquant l\'architecture, les choix techniques, les flux de données)

## JSON_SCHEMA
(JSON strict respectant exactement ce schéma)
{META_ARCHITECT_SCHEMA}

Règles :
- Maximum 5 agents
- Chaque agent a une seule responsabilité (SRP)
- Les agents communiquent via event_bus
- Les noms d\'agents en MAJUSCULES_UNDERSCORE
- Les classes en PascalCase + Agent suffix'''

        response = self.router.call(prompt, task_type='architecture', temperature=0.5)
        narrative, schema = self._parse_response(response)
        return schema, narrative

    def _parse_response(self, response: str) -> tuple[str, dict]:
        import re
        narrative = ''
        schema = {}
        narrative_match = re.search(r'## ARCHITECTURE NARRATIVE\n(.*?)## JSON_SCHEMA', response, re.DOTALL)
        if narrative_match:
            narrative = narrative_match.group(1).strip()
        json_match = re.search(r'\{[\s\S]+\}', response)
        if json_match:
            try:
                schema = json.loads(json_match.group(0))
            except Exception:
                schema = {'agents': [], 'project_name': 'unknown', 'pipeline': []}
        return narrative, schema

    def generate_agent_code(self, agent_spec: dict, project_context: str) -> str:
        prompt = f'''Génère le code Python complet pour cet agent.

SPEC :
{json.dumps(agent_spec, indent=2, ensure_ascii=False)}

CONTEXTE DU PROJET :
{project_context[:1000]}

L\'agent doit :
1. Avoir une classe {agent_spec.get("class", "Agent")} avec méthode run()
2. Utiliser core/event_bus.py pour publier/souscrire aux événements
3. Retourner un AgentOutput (from schemas.agent_schemas import AgentOutput)
4. Gérer les erreurs proprement
5. Logger ses actions avec print()

Génère UNIQUEMENT le code Python, sans markdown.'''

        code = self.router.call(prompt, task_type='code', temperature=0.15)
        return strip_markdown_artifacts(code)

    def run(self, description: str, output_dir: Path = None) -> AgentOutput:
        schema, narrative = self.design_agent_system(description)
        if not schema or not schema.get('agents'):
            return AgentOutput(agent_name=self.name, success=False, artifacts={}, errors=['Schéma invalide généré'])
        if output_dir is None:
            output_dir = Path('agents/auto')
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f'\n  🏛️ Architecture : {schema.get("description", "")}')
        print(f'  📋 {len(schema["agents"])} agents planifiés : {[a["name"] for a in schema["agents"]]}')
        generated = []
        for agent_spec in schema['agents']:
            print(f'  ⚙️ Génération de {agent_spec["name"]}...', end='', flush=True)
            code = self.generate_agent_code(agent_spec, narrative)
            agent_file = output_dir / Path(agent_spec['file']).name
            agent_file.write_text(code, encoding='utf-8')
            register_agent(
                name=agent_spec['name'],
                description='; '.join(agent_spec.get('responsibilities', []))[:200],
                capabilities=agent_spec.get('responsibilities', []),
                path=str(agent_file),
                tags=['meta_generated', schema.get('project_name', 'unknown')],
                auto_generated=True
            )
            generated.append(agent_spec['name'])
            print(f' ✅')
            publish('AGENT_CREATED', self.name, {'name': agent_spec['name'], 'file': str(agent_file)})
        arch_file = output_dir / f'{schema.get("project_name", "system")}_architecture.json'
        arch_file.write_text(json.dumps({'narrative': narrative, 'schema': schema}, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'\n  ✅ [{self.name}] {len(generated)} agents créés : {generated}')
        return AgentOutput(agent_name=self.name, success=True,
                          artifacts={'agents': generated, 'architecture': schema, 'narrative': narrative})
