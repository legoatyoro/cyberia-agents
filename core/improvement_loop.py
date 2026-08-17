import json
from pathlib import Path
from cyberia_validator import validate_imports, auto_fix_imports
from core.ts_validator import validate_typescript
from core.metrics_manager import MetricsManager


class ImprovementLoop:
    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.name = 'IMPROVEMENT_LOOP'
        self.max_cycles = 5
        self.target_score = 9.0
        self.min_improvement = 0.02

    def compute_project_score(self, project_dir: Path) -> float:
        from core.metrics_manager import compute_project_score
        return compute_project_score(project_dir)

    def run(self, project_dir: Path) -> dict:
        print(f'\n🔄 [{self.name}] Démarrage boucle d\'amélioration sur {project_dir.name}...')
        initial_score = self.compute_project_score(project_dir)
        print(f'  📊 Score initial : {initial_score}/10')

        history = [{'cycle': 0, 'score': initial_score, 'fixes': []}]
        current_score = initial_score

        for cycle in range(1, self.max_cycles + 1):
            print(f'\n  🔁 Cycle {cycle}/{self.max_cycles}')
            fixes_applied = []

            py_errors = validate_imports(project_dir)
            if py_errors:
                fixed = auto_fix_imports(project_dir, py_errors)
                if fixed > 0:
                    fixes_applied.append(f'{fixed} imports Python corrigés')
                    print(f'  ✅ {fixed} imports corrigés')

            ts_report = validate_typescript(project_dir)
            if ts_report.get('error_count', 0) > 0 and self.orchestrator:
                try:
                    self.orchestrator.fixer.run(project_dir, ts_report.get('errors', []))
                    fixes_applied.append(f'{ts_report["error_count"]} erreurs TS corrigées')
                except Exception as e:
                    print(f'  ⚠️ Erreur fixer : {e}')

            for req_file in ['requirements.txt', '.gitignore', '.env.example']:
                if not (project_dir / req_file).exists():
                    if req_file == 'requirements.txt':
                        # Scan imports pour générer un requirements minimal
                        import ast as _ast
                        stdlib = {'os', 'sys', 'json', 'pathlib', 'datetime', 're', 'typing',
                                  'collections', 'functools', 'itertools', 'math', 'time',
                                  'hashlib', 'uuid', 'abc', 'copy', 'io', 'logging', 'enum',
                                  'dataclasses', 'contextlib', 'asyncio', 'threading', 'queue'}
                        detected = set()
                        for py in project_dir.rglob('*.py'):
                            if '__pycache__' in str(py):
                                continue
                            try:
                                tree = _ast.parse(py.read_text(encoding='utf-8', errors='ignore'))
                                for node in _ast.walk(tree):
                                    if isinstance(node, _ast.Import):
                                        for a in node.names:
                                            detected.add(a.name.split('.')[0])
                                    elif isinstance(node, _ast.ImportFrom) and node.module:
                                        detected.add(node.module.split('.')[0])
                            except Exception:
                                pass
                        third_party = sorted(detected - stdlib)
                        (project_dir / req_file).write_text('\n'.join(third_party) + '\n', encoding='utf-8')
                        fixes_applied.append('requirements.txt généré')
                    elif req_file == '.gitignore':
                        (project_dir / req_file).write_text(
                            '.env\n__pycache__/\n*.pyc\n*.sqlite\nnode_modules/\n.cyberia_cache/\n',
                            encoding='utf-8'
                        )
                        fixes_applied.append('.gitignore créé')
                    elif req_file == '.env.example':
                        (project_dir / req_file).write_text(
                            '# Copier en .env\n# DATABASE_URL=sqlite:///./app.db\n# SECRET_KEY=changeme\n',
                            encoding='utf-8'
                        )
                        fixes_applied.append('.env.example créé')

            new_score = self.compute_project_score(project_dir)
            improvement = (new_score - current_score) / max(current_score, 0.1)
            history.append({
                'cycle': cycle,
                'score': new_score,
                'fixes': fixes_applied,
                'improvement': round(improvement, 3)
            })
            print(f'  📊 Score cycle {cycle} : {new_score}/10 ({fixes_applied})')

            if new_score >= self.target_score and improvement < self.min_improvement:
                print(f'  🎯 Objectif atteint ! Score {new_score}/10 ≥ {self.target_score}/10')
                break
            if new_score >= self.target_score and not fixes_applied:
                print(f'  ✅ Aucune amélioration possible — projet optimal')
                break
            current_score = new_score

        final_score = history[-1]['score']
        gain = final_score - initial_score
        report = {
            'project': project_dir.name,
            'initial_score': initial_score,
            'final_score': final_score,
            'gain': round(gain, 1),
            'cycles_used': len(history) - 1,
            'history': history
        }
        (project_dir / 'improvement_report.json').write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        print(f'\n  ✅ AMÉLIORATION TERMINÉE : {initial_score}/10 → {final_score}/10 (+{gain})')
        return report
