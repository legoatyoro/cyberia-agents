import ast, json
from pathlib import Path
from schemas.agent_schemas import AgentOutput, ValidationReport
from cyberia_validator import validate_imports, build_symbol_table

class ValidatorAgent:
    def __init__(self):
        self.name = 'VALIDATOR'

    def run(self, project_dir: Path) -> tuple[AgentOutput, list]:
        print(f'🔍 [{self.name}] Validation du projet...')
        errors = []
        warnings = []

        # Vérification syntaxique
        for py_file in project_dir.rglob('*.py'):
            try:
                ast.parse(py_file.read_text(encoding='utf-8'))
            except SyntaxError as e:
                errors.append({'file': py_file.name, 'type': 'SyntaxError', 'message': str(e)})

        # Vérification cohérence des imports
        symbol_table = build_symbol_table(project_dir)
        import_errors = validate_imports(project_dir)
        for err in import_errors:
            err['available'] = list(symbol_table.get(err['from'], set()))
            errors.append({
                'file': err['file'],
                'line': err['line'],
                'type': 'ImportError',
                'message': f"'{err['missing']}' introuvable dans {err['from']}"
            })

        # Détection fichiers vides
        for py_file in project_dir.rglob('*.py'):
            if py_file.stat().st_size < 10:
                warnings.append({'file': py_file.name, 'type': 'EmptyFile', 'message': 'Fichier vide ou quasi-vide'})

        total = len(list(project_dir.rglob('*.py')))
        score = max(0.0, 10.0 - len(errors) * 1.5 - len(warnings) * 0.3)

        report = ValidationReport(
            total_files=total,
            errors=errors,
            warnings=warnings,
            score=round(score, 1)
        )
        (project_dir / 'validation_report.json').write_text(
            json.dumps(report.dict(), indent=2, ensure_ascii=False), encoding='utf-8'
        )
        status = '✅' if not errors else '⚠️'
        print(f'  {status} {total} fichiers — {len(errors)} erreur(s) — score {report.score}/10')
        return AgentOutput(
            agent_name=self.name,
            success=len(errors) == 0,
            artifacts={'report': report.dict()},
            errors=[f"{e['file']}: {e['message']}" for e in errors]
        ), import_errors
