import ast
import importlib.util
import sys
import json
from pathlib import Path
from core.llm_client import LLMClient
from core.agent_registry import register_agent, get_agent
from schemas.agent_schemas import TaskType
import pytest
import subprocess
import tempfile
import os
import traceback
import datetime

ALLOWED_IMPORTS = {
    'pathlib', 'json', 're', 'os', 'datetime', 'typing',
    'dataclasses', 'enum', 'functools', 'itertools',
    'collections', 'math', 'random', 'time', 'hashlib',
    'fastapi', 'pydantic', 'sqlalchemy', 'httpx', 'aiohttp',
    'schemas', 'core', 'cyberia_sanitizer', 'cyberia_validator'
}

FORBIDDEN_NODES = {'Exec', 'Global', 'Nonlocal'}
FORBIDDEN_CALLS = {'exec', 'eval', '__import__', 'compile', 'open'}


class AgentFactory:
    def __init__(self):
        self.llm = LLMClient()
        self.auto_dir = Path('agents/auto')
        self.auto_dir.mkdir(parents=True, exist_ok=True)
        init_file = self.auto_dir / '__init__.py'
        if not init_file.exists():
            init_file.touch()
        self.validated_rules = 0
        self.successful_generations = 0
        self.failed_generations = 0
        self.test_results = []
        self.known_fix_patterns = self._load_known_fix_patterns()

    def _load_known_fix_patterns(self) -> list:
        patterns_file = Path('patterns/known_fix_patterns.json')
        if patterns_file.exists():
            try:
                with open(patterns_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save_known_fix_patterns(self):
        patterns_file = Path('patterns/known_fix_patterns.json')
        patterns_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(patterns_file, 'w') as f:
                json.dump(self.known_fix_patterns, f, indent=2)
        except IOError as e:
            print(f"Erreur lors de la sauvegarde des patterns de correction: {e}")

    def _add_fix_pattern(self, pattern: dict, success: bool):
        pattern_entry = {
            'pattern': pattern,
            'success': success,
            'timestamp': datetime.datetime.now().isoformat(),
            'test_count': 0,
            'success_count': 1 if success else 0,
            'failure_count': 0 if success else 1
        }
        
        existing = [p for p in self.known_fix_patterns if p.get('pattern', {}).get('name') == pattern.get('name')]
        if existing:
            existing[0]['success_count'] += 1 if success else 0
            existing[0]['failure_count'] += 0 if success else 1
            existing[0]['test_count'] += 1
            existing[0]['success'] = existing[0]['success_count'] > existing[0]['failure_count']
        else:
            pattern_entry['test_count'] = 1
            self.known_fix_patterns.append(pattern_entry)
        
        self._save_known_fix_patterns()

    def _generate_test_code(self, pattern: dict) -> str:
        test_code = f"""
import pytest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

def test_pattern_{pattern.get('name', 'unknown')}():
    \"\"\"Test automatisé pour le pattern {pattern.get('name', 'unknown')}\"\"\"
    try:
        code = {repr(pattern.get('code', ''))}
        exec_globals = {{}}
        exec_locals = {{}}
        exec(code, exec_globals, exec_locals)
        
        if 'run' in exec_locals:
            result = exec_locals['run']()
            assert result is not None, "La fonction run doit retourner une valeur"
            return True
        elif 'validate' in exec_locals:
            result = exec_locals['validate']()
            assert result is not None, "La fonction validate doit retourner une valeur"
            return True
        else:
            pytest.skip("Aucune fonction run ou validate trouvée")
            return False
    except Exception as e:
        pytest.fail(f"Erreur lors de l'exécution du pattern: {{e}}")
        return False

def test_pattern_syntax_{pattern.get('name', 'unknown')}():
    \"\"\"Vérification syntaxique du pattern {pattern.get('name', 'unknown')}\"\"\"
    code = {repr(pattern.get('code', ''))}
    try:
        compile(code, '<test>', 'exec')
    except SyntaxError as e:
        pytest.fail(f"Erreur de syntaxe: {{e}}")

def test_pattern_imports_{pattern.get('name', 'unknown')}():
    \"\"\"Vérification des imports du pattern {pattern.get('name', 'unknown')}\"\"\"
    code = {repr(pattern.get('code', ''))}
    import ast
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                pkg = alias.name.split('.')[0]
                if pkg not in {repr(list(ALLOWED_IMPORTS))}:
                    pytest.fail(f"Import non autorisé: {{alias.name}}")
"""
        return test_code

    def _run_automated_tests(self, pattern: dict) -> tuple[bool, str, dict]:
        test_code = self._generate_test_code(pattern)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(test_code)
            test_file = f.name
        
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', test_file, '-v', '--tb=short', '--no-header'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            test_metrics = {
                'passed': 0,
                'failed': 0,
                'skipped': 0,
                'errors': 0,
                'total': 0
            }
            
            for line in result.stdout.split('\n'):
                if 'PASSED' in line:
                    test_metrics['passed'] += 1
                    test_metrics['total'] += 1
                elif 'FAILED' in line:
                    test_metrics['failed'] += 1
                    test_metrics['total'] += 1
                elif 'ERROR' in line:
                    test_metrics['errors'] += 1
                    test_metrics['total'] += 1
                elif 'SKIPPED' in line:
                    test_metrics['skipped'] += 1
                    test_metrics['total'] += 1
            
            success = result.returncode == 0
            feedback = {
                'success': success,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'return_code': result.returncode,
                'metrics': test_metrics,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            return success, result.stdout if success else result.stderr, feedback
            
        except subprocess.TimeoutExpired:
            return False, "Timeout lors de l'exécution des tests", {'success': False, 'error': 'timeout'}
        except Exception as e:
            return False, f"Erreur lors de l'exécution des tests: {str(e)}", {'success': False, 'error': str(e)}
        finally:
            try:
                os.unlink(test_file)
                pycache = test_file + 'c'
                if os.path.exists(pycache):
                    os.unlink(pycache)
            except OSError:
                pass

    def _validate_agent_code(self, code: str) -> tuple[bool, str]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f'Erreur syntaxe : {e}'

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = alias.name.split('.')[0]
                    if pkg not in ALLOWED_IMPORTS:
                        return False, f'Import non autorisé : {alias.name}'
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    pkg = node.module.split('.')[0]
                    if pkg not in ALLOWED_IMPORTS:
                        return False, f'Import non autorisé : {node.module}'
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in FORBIDDEN_CALLS:
                        return False, f'Appel interdit : {node.func.id}()'
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    if node.value.id in ('os', 'sys', 'subprocess'):
                        dangerous = {'system', 'popen', 'exec', 'run', 'call', 'Popen', 'exit', 'path'}
                        if node.attr in dangerous:
                            return False, f'Appel dangereux : {node.value.id}.{node.attr}'

        return True, 'OK'

    def _has_run_method(self, code: str) -> bool:
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == 'run':
                    return True
        except Exception:
            pass
        return False

    def _validate_pattern(self, pattern: dict) -> tuple[bool, str]:
        required_fields = ['name', 'description', 'code', 'type']
        
        for field in required_fields:
            if field not in pattern:
                return False, f'Champ obligatoire manquant : {field}'
        
        allowed_types = ['agent', 'workflow', 'validation', 'transformation']
        if pattern['type'] not in allowed_types:
            return False, f'Type de pattern non valide : {pattern["type"]}. Types autorisés : {allowed_types}'
        
        if 'code' in pattern and pattern['code']:
            valid, reason = self._validate_agent_code(pattern['code'])
            if not valid:
                return False, f'Code invalide dans le pattern : {reason}'
        
        if 'description' in pattern and len(pattern['description']) < 10:
            return False, 'La description du pattern est trop courte (minimum 10 caractères)'
        
        if 'metadata' in pattern:
            metadata = pattern['metadata']
            if not isinstance(metadata, dict):
                return False, 'Les métadonnées doivent être un dictionnaire'
            
            if 'tags' in metadata:
                if not isinstance(metadata['tags'], list):
                    return False, 'Les tags doivent être une liste'
                for tag in metadata['tags']:
                    if not isinstance(tag, str) or len(tag) < 2:
                        return False, f'Tag invalide : {tag}'
        
        return True, 'Pattern valide'

    def _save_validated_pattern(self, pattern: dict) -> bool:
        try:
            patterns_file = Path('patterns/validated_patterns.json')
            patterns_file.parent.mkdir(parents=True, exist_ok=True)
            
            if patterns_file.exists():
                with open(patterns_file, 'r') as f:
                    patterns = json.load(f)
            else:
                patterns = []
            
            patterns.append(pattern)
            
            with open(patterns_file, 'w') as f:
                json.dump(patterns, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Erreur lors de la sauvegarde du pattern: {e}")
            return False

    def validate_and_test_pattern(self, pattern: dict) -> dict:
        result = {
            'pattern_name': pattern.get('name', 'unknown'),
            'validation_passed': False,
            'tests_passed': False,
            'validation_errors': [],
            'test_results': None,
            'feedback': None,
            'timestamp': datetime.datetime.now().isoformat()
        }
        
        valid, reason = self._validate_pattern(pattern)
        if not valid:
            result['validation_errors'].append(reason)
            result['validation_passed'] = False
            self._add_fix_pattern(pattern, False)
            return result
        
        result['validation_passed'] = True
        self.validated_rules += 1
        
        test_success, test_output, test_feedback = self._run_automated_tests(pattern)
        
        result['tests_passed'] = test_success
        result['test_results'] = test_output
        result['feedback'] = test_feedback
        
        if test_success:
            self.successful_generations += 1
            self._add_fix_pattern(pattern, True)
            self._save_validated_pattern(pattern)
        else:
            self.failed_generations += 1
            self._add_fix_pattern(pattern, False)
        
        self.test_results.append(result)
        
        return result

    def get_metrics(self) -> dict:
        return {
            'validated_rules': self.validated_rules,
            'successful_generations': self.successful_generations,
            'failed_generations': self.failed_generations,
            'total_generations': self.successful_generations + self.failed_generations,
            'success_rate': (self.successful_generations / max(1, self.successful_generations + self.failed_generations)) * 100,
            'known_fix_patterns_count': len(self.known_fix_patterns),
            'test_results_count': len(self.test_results),
            'last_test_timestamp': self.test_results[-1]['timestamp'] if self.test_results else None
        }

    def get_known_fix_patterns(self) -> list:
        return self.known_fix_patterns

    def get_test_results(self) -> list:
        return self.test_results

    def create_agent(self, pattern) -> dict:
        """Accept str | dict, generate agent file in agents/auto/, return {success, agent_name, code_lines, error}."""
        import re as _re
        # Normalize str → dict
        if isinstance(pattern, str):
            desc = pattern
            first_word = desc.split()[0].lower() if desc.split() else 'agent'
            name = _re.sub(r'[^a-z0-9_]', '_', first_word)[:30] or 'custom_agent'
            pattern = {'name': name, 'description': desc, 'type': 'agent', 'code': ''}

        desc = pattern.get('description', '')
        name = _re.sub(r'[^a-z0-9_]', '_', pattern.get('name', 'custom_agent').lower())[:30] or 'custom_agent'
        class_name = ''.join(w.capitalize() for w in name.split('_') if w) + 'Agent'

        prompt = (
            f'Génère une classe Python nommée {class_name}. '
            f'Elle doit avoir une méthode run(self, **kwargs) -> dict. '
            f'Description du rôle : {desc}. '
            f'Imports autorisés seulement : json, os, pathlib, datetime, re, typing. '
            f'IMPORTANT : génère le fichier Python entier, pas de markdown, pas de blocs ```.'
        )
        try:
            code = self.llm.call(TaskType.CODE, prompt, temperature_override=0.3)
        except Exception as e:
            return {'success': False, 'agent_name': name, 'code_lines': 0, 'error': f'LLM: {e}'}

        # Strip markdown fences if any
        if '```' in code:
            code = '\n'.join(l for l in code.split('\n') if not l.strip().startswith('```'))

        # Validate syntax before writing
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {'success': False, 'agent_name': name, 'code_lines': 0, 'error': f'SyntaxError: {e}'}

        target = self.auto_dir / f'{name}.py'
        try:
            target.write_text(code, encoding='utf-8')
        except Exception as e:
            return {'success': False, 'agent_name': name, 'code_lines': 0, 'error': f'Write: {e}'}

        self.successful_generations += 1
        return {'success': True, 'agent_name': name, 'code_lines': len(code.splitlines()), 'error': ''}