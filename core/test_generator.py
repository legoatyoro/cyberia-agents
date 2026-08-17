from pathlib import Path
from core.multi_model_router import MultiModelRouter
import json, re


class TestGenerator:
    def __init__(self):
        self.router = MultiModelRouter()

    def generate_tests(self, source_file, test_framework='pytest'):
        content = Path(source_file).read_text(encoding='utf-8', errors='ignore')[:3000]
        prompt = f'''Genere des tests {test_framework} complets et realistes pour ce code Python.
REGLES:
- Tests unitaires pour chaque fonction/methode
- Au moins 1 test positif et 1 test negatif par fonction
- Utiliser pytest fixtures pour les dependances
- Mocker les appels externes (base de donnees, API, fichiers)
- Noms de tests descriptifs (test_xxx_should_yyy_when_zzz)
- Reponds avec UNIQUEMENT le code Python des tests, sans markdown

CODE SOURCE ({Path(source_file).name}):
{content}'''
        return self.router.call(prompt, task_type='test')

    def generate_project_tests(self, project_dir, max_files=5):
        path = Path(project_dir)
        test_dir = path / 'tests'
        test_dir.mkdir(exist_ok=True)
        conftest = test_dir / 'conftest.py'
        if not conftest.exists():
            conftest.write_text(
                'import pytest\nimport sys\nfrom pathlib import Path\n'
                'sys.path.insert(0, str(Path(__file__).parent.parent))\n',
                encoding='utf-8'
            )
        py_files = [
            f for f in path.rglob('*.py')
            if '__pycache__' not in str(f)
            and 'test' not in f.name
            and 'node_modules' not in str(f)
            and 'migrations' not in str(f)
        ][:max_files]
        generated = []
        for source_file in py_files:
            print(f'  [TEST_GEN] Generation tests pour {source_file.name}...')
            test_code = self.generate_tests(str(source_file))
            if test_code and len(test_code) > 50:
                test_file = test_dir / f'test_{source_file.stem}.py'
                test_file.write_text(test_code, encoding='utf-8')
                generated.append(str(test_file))
                print(f'  [TEST_GEN] OK {test_file.name}')
        return generated

    def run_tests(self, project_dir):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', str(Path(project_dir) / 'tests'), '-v', '--tb=short', '--no-header'],
            capture_output=True, text=True, cwd=str(project_dir), timeout=60
        )
        return result.stdout + result.stderr

    def validate_and_fix_tests(self, test_file):
        import ast
        try:
            ast.parse(Path(test_file).read_text(encoding='utf-8'))
            return True, 'OK'
        except SyntaxError as e:
            return False, f'Syntaxe: {e}'
