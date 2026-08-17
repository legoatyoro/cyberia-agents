import json
import re
from pathlib import Path
from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType, AgentOutput, ArchitectureBlueprint


def deduplicate_blueprint_apps(blueprint: dict) -> dict:
    # Case 1: blueprint has an 'apps' dict with explicit model lists
    if 'apps' in blueprint and isinstance(blueprint.get('apps'), dict):
        seen_models: dict = {}
        apps_to_remove = []
        for app_name, app_spec in blueprint['apps'].items():
            if not isinstance(app_spec, dict):
                continue
            models = app_spec.get('models', [])
            model_names = tuple(sorted(m.get('name', '') for m in models if isinstance(m, dict)))
            if model_names and model_names in seen_models:
                print(f'  ⚠️ [ARCHITECTE] App {app_name} dupliquée de {seen_models[model_names]} — supprimée du blueprint')
                apps_to_remove.append(app_name)
            elif model_names:
                seen_models[model_names] = app_name
        for app_name in apps_to_remove:
            del blueprint['apps'][app_name]
        return blueprint

    # Case 2: blueprint uses 'files_to_create' list (path-based structure)
    files = blueprint.get('files_to_create')
    if not isinstance(files, list):
        return blueprint

    models_files = [f for f in files if f.endswith('models.py')]
    if len(models_files) <= 1:
        return blueprint

    # Compare already-generated model files by their Django class names via regex
    seen_classes: dict = {}
    paths_to_remove = set()
    class_pattern = re.compile(r'class\s+(\w+)\s*\([^)]*(?:models\.Model|AbstractUser|AbstractBaseUser)[^)]*\)')

    for rel_path in models_files:
        full_path = Path(rel_path)
        if not full_path.exists():
            # File not generated yet — skip content check, warn on obvious path duplicates
            app_segment = full_path.parent.name if full_path.parent.name != '.' else ''
            if app_segment in seen_classes:
                print(f'  ⚠️ [ARCHITECTE] Chemin models.py suspect (app déjà vue) : {rel_path}')
            else:
                seen_classes[app_segment] = rel_path
            continue
        try:
            content = full_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        class_names = tuple(sorted(class_pattern.findall(content)))
        if class_names and class_names in seen_classes:
            print(f'  ⚠️ [ARCHITECTE] {rel_path} duplique {seen_classes[class_names]} (mêmes classes : {list(class_names)}) — retiré du blueprint')
            paths_to_remove.add(rel_path)
        elif class_names:
            seen_classes[class_names] = rel_path

    if paths_to_remove:
        blueprint['files_to_create'] = [f for f in files if f not in paths_to_remove]

    return blueprint

class ArchitecteAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'ARCHITECTE'

    def run(self, cdc: str, project_dir: Path) -> tuple[AgentOutput, ArchitectureBlueprint]:
        print(f'🏗️ [{self.name}] Analyse du CDC et génération du blueprint...')
        prompt = f'''Analyse ce cahier des charges et génère un blueprint JSON complet.

CDC :
{cdc}

Réponds UNIQUEMENT avec un JSON valide ayant cette structure exacte :
{{
  "project_name": "nom-du-projet",
  "stack": {{"backend": "fastapi", "db": "sqlite", "auth": "none", "frontend": "jinja2"}},
  "files_to_create": ["main.py", "models.py", "schemas.py", "database.py", "templates/index.html", "requirements.txt", ".env.example", "README.md"],
  "dependencies": ["fastapi", "uvicorn", "sqlalchemy", "pydantic"],
  "env_vars": ["DATABASE_URL", "SECRET_KEY"],
  "security_notes": ["Ajouter authentification sur les routes DELETE", "Valider les inputs utilisateur"]
}}'''
        raw = self.llm.call(TaskType.ARCHITECTURE, prompt)
        raw = raw.strip().replace('```json', '').replace('```', '').strip()
        data = json.loads(raw)
        data = deduplicate_blueprint_apps(data)
        blueprint = ArchitectureBlueprint(**data)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / 'architecture.json').write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'✅ [{self.name}] Blueprint généré : {len(blueprint.files_to_create)} fichiers planifiés')
        return AgentOutput(agent_name=self.name, success=True, artifacts={'blueprint': data}), blueprint
