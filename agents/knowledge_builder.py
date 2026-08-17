import json, re
from pathlib import Path
from datetime import datetime
from core.knowledge_base import add_pattern, add_rule, get_kb_summary
from core.learning_engine import get_learning_stats
from core.multi_model_router import get_router
from schemas.agent_schemas import AgentOutput

class KnowledgeBuilderAgent:
    def __init__(self):
        self.router = get_router()
        self.name = 'KNOWLEDGE_BUILDER'

    def extract_from_project(self, project_dir: Path, score: float) -> int:
        print(f'📚 [{self.name}] Extraction de patterns depuis {project_dir.name} (score {score}/10)...')
        extracted = 0
        for py_file in project_dir.rglob('*.py'):
            if 'node_modules' in str(py_file) or '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                if 'declarative_base' in content:
                    if 'from sqlalchemy.orm import declarative_base' in content:
                        add_pattern('sqlalchemy', '2.0', 'base_correct', 'from sqlalchemy.orm import declarative_base', 'Import correct détecté dans projet fonctionnel', f'project:{project_dir.name}')
                        extracted += 1
                if 'uvicorn.run' in content and 'if __name__' in content:
                    add_pattern('fastapi', 'any', 'startup_correct', 'if __name__ == "__main__": uvicorn.run(app)', 'Pattern démarrage correct détecté', f'project:{project_dir.name}')
                    extracted += 1
                if 'HTMLResponse' in content and 'Jinja2' not in content:
                    add_pattern('fastapi', '0.100+', 'html_no_jinja2', 'HTMLResponse avec f-strings', 'Pas de Jinja2 → compatible Python 3.14', f'project:{project_dir.name}')
                    extracted += 1
            except Exception:
                pass
        if score >= 9.0:
            add_rule(f'Le projet {project_dir.name} avec score {score}/10 utilise FastAPI + SQLite avec succès', 'success_pattern', 'fastapi,sqlite', origin=f'project:{project_dir.name}', confidence=0.8)
        print(f'  ✅ {extracted} pattern(s) extraits et sauvegardés')
        return extracted

    def extract_from_fix(self, error: str, fix: str, worked: bool):
        if not worked:
            return
        error_lower = error.lower()
        if 'declarative_base' in error_lower:
            add_pattern('sqlalchemy', '2.0', 'fix_declarative', fix[:200], 'Fix declarative_base appliqué avec succès', 'fix_learned')
            add_rule('Toujours utiliser from sqlalchemy.orm import declarative_base', 'rule', 'sqlalchemy', confidence=0.95)
        elif 'jinja2' in error_lower or 'templateresponse' in error_lower:
            add_pattern('fastapi', 'any', 'fix_jinja2', 'HTMLResponse au lieu de TemplateResponse', 'Fix Jinja2 Python 3.14', 'fix_learned')
        elif 'uvicorn' in error_lower and 'run' in error_lower:
            add_pattern('fastapi', 'any', 'fix_uvicorn', 'if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8000)', 'Fix uvicorn.run manquant', 'fix_learned')

    def synthesize_rules(self) -> list:
        print(f'🧠 [{self.name}] Synthèse des règles depuis l\'historique...')
        stats = get_learning_stats()
        summary = get_kb_summary()
        prompt = f'''Analyse ces données d\'apprentissage de CYBERIA et génère de nouvelles règles.

Statistiques :
{json.dumps(stats, indent=2)}

Base de connaissances :
{json.dumps(summary, indent=2)}

Génère 3-5 règles nouvelles au format JSON :
[
  {{
    "rule": "texte de la règle",
    "type": "generation|fix|validation",
    "applies_to": "fastapi|django|all",
    "confidence": 0.7
  }}
]

UNIQUEMENT le JSON, sans explication.'''

        response = self.router.call(prompt, task_type='analysis', temperature=0.3)
        json_match = re.search(r'\[[\s\S]+\]', response)
        new_rules = []
        if json_match:
            try:
                rules = json.loads(json_match.group(0))
                for rule in rules:
                    add_rule(rule.get('rule', ''), rule.get('type', 'general'), rule.get('applies_to', 'all'), 'synthesized', rule.get('confidence', 0.5))
                    new_rules.append(rule['rule'])
            except Exception:
                pass
        print(f'  ✅ {len(new_rules)} règle(s) synthétisée(s)')
        return new_rules

    def run(self, project_dir: Path = None, score: float = 0) -> AgentOutput:
        extracted = 0
        if project_dir and project_dir.exists():
            extracted = self.extract_from_project(project_dir, score)
        new_rules = self.synthesize_rules()
        summary = get_kb_summary()
        return AgentOutput(agent_name=self.name, success=True,
                          artifacts={'extracted': extracted, 'new_rules': len(new_rules), 'kb_summary': summary})
