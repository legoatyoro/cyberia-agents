import json, time
from pathlib import Path
from datetime import datetime
from core.learning_engine import record_generation_feedback, get_learning_stats, add_knowledge
from core.multi_model_router import get_router
from schemas.agent_schemas import AgentOutput

class ContinuousImprover:
    def __init__(self):
        self.router = get_router()
        self.name = 'CONTINUOUS_IMPROVER'

    def analyze_all_projects(self) -> dict:
        print(f'🔄 [{self.name}] Analyse de tous les projets...')
        generated = Path('generated')
        if not generated.exists():
            return {'projects_analyzed': 0}
        results = []
        for project_dir in generated.iterdir():
            if not project_dir.is_dir(): continue
            if 'node_modules' in str(project_dir): continue
            py_files = [f for f in project_dir.rglob('*.py') if 'node_modules' not in str(f) and '__pycache__' not in str(f)]
            broken = []
            import ast
            for f in py_files[:20]:
                try:
                    ast.parse(f.read_text(encoding='utf-8', errors='ignore'))
                except SyntaxError as e:
                    broken.append({'file': f.name, 'line': e.lineno, 'error': str(e)})
            metrics_file = project_dir / 'metrics.json'
            score = 0
            if metrics_file.exists():
                try:
                    score = json.loads(metrics_file.read_text()).get('final_score', 0)
                except: pass
            results.append({'project': project_dir.name, 'py_files': len(py_files), 'broken_files': len(broken), 'score': score})
            print(f'  📁 {project_dir.name}: {len(py_files)} fichiers Python, {len(broken)} erreurs, score {score}/10')
        return {'projects_analyzed': len(results), 'results': results}

    def extract_and_store_patterns(self, project_dir: Path) -> int:
        from cyberia_validator import validate_imports
        errors = validate_imports(project_dir)
        patterns_stored = 0
        for error in errors[:5]:
            if error.get('suggestion'):
                from core.learning_engine import record_fix_success
                record_fix_success(
                    error.get('missing', ''),
                    'import_error',
                    f'Remplacer {error["missing"]} par {error["suggestion"]}',
                    f'Auto-fix Levenshtein distance ≤ 2',
                    project_dir.name
                )
                patterns_stored += 1
        return patterns_stored

    def generate_improvement_report(self) -> str:
        stats = get_learning_stats()
        prompt = f'''Tu es un expert en amélioration de systèmes IA.
Voici les statistiques d'apprentissage de CYBERIA :
{json.dumps(stats, indent=2)}

Génère un rapport court (5 points max) sur :
1. Ce que CYBERIA a appris
2. Les patterns d'erreurs les plus fréquents
3. 3 recommandations d'amélioration prioritaires

Sois concis et actionnable.'''
        return self.router.call(prompt, task_type='analysis', temperature=0.4)

    def run(self, mode: str = 'quick') -> AgentOutput:
        print(f'\n🔄 [{self.name}] Mode {mode}...')
        if mode == 'full':
            analysis = self.analyze_all_projects()
            generated = Path('generated')
            patterns = 0
            if generated.exists():
                for p in generated.iterdir():
                    if p.is_dir():
                        patterns += self.extract_and_store_patterns(p)
            report = self.generate_improvement_report()
            report_path = Path('.cyberia/improvement_report.md')
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text(f'# Rapport CYBERIA — {datetime.now().strftime("%d/%m/%Y %H:%M")}\n\n{report}', encoding='utf-8')
            print(f'  ✅ Rapport sauvegardé dans .cyberia/improvement_report.md')
            return AgentOutput(agent_name=self.name, success=True, artifacts={'analysis': analysis, 'patterns_found': patterns, 'report': report})
        else:
            stats = get_learning_stats()
            print(f'  📊 {stats["known_fix_patterns"]} patterns · {stats["workshop_sessions"]} sessions atelier · {stats["successful_generations"]} générations réussies')
            return AgentOutput(agent_name=self.name, success=True, artifacts=stats)
