import ast, json
from pathlib import Path
from core.llm_client import LLMClient
from core.manifest_manager import detect_user_modifications, load_manifest
from schemas.agent_schemas import TaskType, AgentOutput

class AnalysteAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'ANALYSTE'

    def scan_project(self, project_dir: Path) -> dict:
        files_info = {}
        for f in project_dir.rglob('*'):
            if f.is_file() and f.suffix in ['.py', '.ts', '.tsx', '.js', '.json', '.html']:
                try:
                    content = f.read_text(encoding='utf-8')
                    files_info[str(f.relative_to(project_dir))] = {
                        'lines': len(content.splitlines()),
                        'size': len(content),
                        'preview': content[:300]
                    }
                except Exception:
                    pass
        return files_info

    def generate_diff_plan(self, project_dir: Path, improvement_request: str) -> dict:
        print(f'🔍 [{self.name}] Analyse du projet existant...')
        files_info = self.scan_project(project_dir)
        mods = detect_user_modifications(project_dir)

        prompt = f'''Tu es un architecte senior. Analyse ce projet existant et génère un plan de modification.

PROJET : {project_dir.name}
DEMANDE : {improvement_request}

FICHIERS EXISTANTS :
{json.dumps(files_info, indent=2, ensure_ascii=False)[:3000]}

FICHIERS MODIFIÉS PAR L UTILISATEUR (ne pas écraser) :
{mods.get("modified_files", [])}

Génère un JSON avec :
{{
  "files_to_create": ["liste des nouveaux fichiers à créer"],
  "files_to_modify": ["liste des fichiers existants à modifier (pas dans modified_by_user)"],
  "files_to_keep": ["liste des fichiers à ne pas toucher"],
  "summary": "résumé du plan en français"
}}

Réponds UNIQUEMENT avec le JSON, sans explication.'''

        result = self.llm.call(TaskType.ARCHITECTURE, prompt)
        result = result.strip().replace('```json','').replace('```','').strip()
        try:
            plan = json.loads(result)
        except Exception:
            plan = {'files_to_create': [], 'files_to_modify': [], 'files_to_keep': [], 'summary': result}

        plan['user_modified_files'] = mods.get('modified_files', [])
        print(f'  ✅ Plan : {len(plan.get("files_to_create", []))} nouveaux, {len(plan.get("files_to_modify", []))} à modifier')
        return plan

    def run(self, project_dir: Path, improvement_request: str) -> AgentOutput:
        plan = self.generate_diff_plan(project_dir, improvement_request)
        (project_dir / 'diff_plan.json').write_text(
            json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        return AgentOutput(agent_name=self.name, success=True, artifacts={'plan': plan})
