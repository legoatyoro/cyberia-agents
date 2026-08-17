import json, ast, re, shutil
from pathlib import Path
from datetime import datetime
from core.knowledge_base import get_rules, get_patterns, add_pattern, get_kb_summary
from core.multi_model_router import get_router
from core.learning_engine import get_learning_stats
from cyberia_sanitizer import strip_markdown_artifacts
from schemas.agent_schemas import AgentOutput

AUDIT_COUNTER_FILE = Path('.cyberia/audit_counter.json')
AUDIT_THRESHOLD = 5
FAILURE_THRESHOLD = 3

class SelfAuditorAgent:
    def __init__(self):
        self.router = get_router()
        self.name = 'SELF_AUDITOR'
        self._load_counter()

    def _load_counter(self):
        if AUDIT_COUNTER_FILE.exists():
            try:
                data = json.loads(AUDIT_COUNTER_FILE.read_text())
                self.project_count = data.get('projects', 0)
                self.failure_count = data.get('failures', 0)
                self.last_audit = data.get('last_audit', '')
            except Exception:
                self.project_count = 0
                self.failure_count = 0
                self.last_audit = ''
        else:
            self.project_count = 0
            self.failure_count = 0
            self.last_audit = ''

    def _save_counter(self):
        AUDIT_COUNTER_FILE.parent.mkdir(exist_ok=True)
        AUDIT_COUNTER_FILE.write_text(json.dumps({
            'projects': self.project_count,
            'failures': self.failure_count,
            'last_audit': self.last_audit
        }), encoding='utf-8')

    def record_project(self, success: bool):
        self.project_count += 1
        if not success:
            self.failure_count += 1
        else:
            self.failure_count = max(0, self.failure_count - 1)
        self._save_counter()

    def should_audit(self) -> tuple:
        if self.project_count > 0 and self.project_count % AUDIT_THRESHOLD == 0:
            return True, f'Batch de {AUDIT_THRESHOLD} projets atteint ({self.project_count} total)'
        if self.failure_count >= FAILURE_THRESHOLD:
            return True, f'{self.failure_count} échecs consécutifs détectés'
        return False, ''

    def audit_cyberia(self) -> dict:
        print(f'\n🔍 [{self.name}] Audit de CYBERIA en cours...')
        rules = get_rules(min_confidence=0.7)
        patterns = get_patterns(min_success=0.8)
        stats = get_learning_stats()
        kb_summary = get_kb_summary()
        core_files = []
        for f in Path('core').glob('*.py'):
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                core_files.append({'file': f.name, 'lines': len(content.splitlines()), 'preview': content[:300]})
            except Exception:
                pass
        prompt = f'''Tu es un auditeur expert de CYBERIA, un système IA de génération de code.
Analyse l\'état du système et propose des améliorations concrètes.

STATISTIQUES :
{json.dumps(stats, indent=2)}

BASE DE CONNAISSANCES :
{json.dumps(kb_summary, indent=2)}

RÈGLES VALIDÉES (extrait) :
{json.dumps([r["rule_text"] for r in rules[:5]], indent=2)}

FICHIERS CORE (aperçu) :
{json.dumps([{"file": f["file"], "lines": f["lines"]} for f in core_files[:10]], indent=2)}

Génère un audit JSON :
{{
  "score_global": 7.5,
  "points_forts": ["liste"],
  "faiblesses": ["liste"],
  "propositions": [
    {{
      "priorite": "haute|moyenne|basse",
      "fichier": "core/exemple.py",
      "description": "ce qui doit changer",
      "impact": "ce que ça améliore"
    }}
  ],
  "resume": "2 phrases de résumé"
}}

UNIQUEMENT le JSON.'''

        response = self.router.call(prompt, task_type='analysis', temperature=0.4)
        json_match = re.search(r'\{[\s\S]+\}', response)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except Exception:
                pass
        return {'score_global': 0, 'propositions': [], 'resume': 'Audit incomplet'}

    def _build_improve_prompt(self, filepath, content: str, proposition: dict) -> str:
        return f'''Améliore ce fichier selon cette proposition d\'audit CYBERIA :

PROPOSITION : {proposition.get("description", "")}
IMPACT ATTENDU : {proposition.get("impact", "")}

CODE ACTUEL ({filepath.name}) :
{content[:5000]}

RÈGLES CONNUES :
{chr(10).join([r["rule_text"] for r in get_rules()[:5]])}

IMPORTANT : génère le fichier entier, ne t\'arrête pas au milieu, pas de ... ni de pass comme placeholder.
Génère le fichier COMPLET amélioré. AUCUN markdown.'''

    def apply_proposition(self, proposition: dict) -> dict:
        filepath_str = proposition.get('fichier', '')
        filepath = None
        for f in Path('.').rglob(filepath_str):
            if 'generated' not in str(f) and '__pycache__' not in str(f):
                filepath = f
                break
        if not filepath or not filepath.exists():
            return {'success': False, 'error': f'Fichier {filepath_str} introuvable'}
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        original_line_count = len(content.splitlines())

        prompt = self._build_improve_prompt(filepath, content, proposition)
        new_code = strip_markdown_artifacts(self.router.call(prompt, task_type='fix', temperature=0.1))

        if len(new_code.splitlines()) < 50:
            print(f'[DEBUG] Code trop court ({len(new_code.splitlines())} lignes, original={original_line_count})')
            return {'success': False, 'error': 'Code trop court, génération incomplète'}

        try:
            ast.parse(new_code)
        except SyntaxError as e:
            print(f'[DEBUG] SyntaxError première tentative : {e} — retry temperature=0.05')
            retry_prompt = (
                self._build_improve_prompt(filepath, content, proposition)
                + '\n\nATTENTION : la tentative précédente avait une erreur de syntaxe.'
                  ' Génère le fichier COMPLET sans te tronquer.'
            )
            new_code = strip_markdown_artifacts(
                self.router.call(retry_prompt, task_type='fix', temperature=0.05)
            )
            if len(new_code.splitlines()) < 50:
                print(f'[DEBUG] Retry : code toujours trop court ({len(new_code.splitlines())} lignes)')
                return {'success': False, 'error': 'Code trop court après retry, génération incomplète'}
            try:
                ast.parse(new_code)
            except SyntaxError as e2:
                return {'success': False, 'error': f'Syntaxe invalide après retry : {e2}'}

        backup_dir = Path('.cyberia/audit_backups')
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(filepath, backup_dir / f'{filepath.stem}_{ts}{filepath.suffix}')
        filepath.write_text(new_code, encoding='utf-8')
        return {'success': True, 'file': str(filepath), 'lines': len(new_code.splitlines())}

    def run(self, force: bool = False) -> AgentOutput:
        should, reason = self.should_audit()
        if not should and not force:
            return AgentOutput(agent_name=self.name, success=True,
                             artifacts={'skipped': True, 'next_audit_in': AUDIT_THRESHOLD - (self.project_count % AUDIT_THRESHOLD)})
        print(f'\n🔍 [{self.name}] Déclenchement : {reason if not force else "Manuel"}')
        audit = self.audit_cyberia()
        self.last_audit = datetime.now().isoformat()
        self.failure_count = 0
        self._save_counter()
        for prop in audit.get('propositions', []):
            if prop.get('priorite') == 'haute':
                add_pattern('cyberia', 'self', 'improvement', prop.get('description', ''), prop.get('impact', ''), 'self_audit')
        print(f'  📊 Score global : {audit.get("score_global", 0)}/10')
        print(f'  💡 {len(audit.get("propositions", []))} proposition(s) d\'amélioration')
        return AgentOutput(agent_name=self.name, success=True, artifacts={'audit': audit, 'trigger': reason})
