import subprocess
import sys
from pathlib import Path


class StyleEnforcerAgent:
    def __init__(self):
        self.name = 'STYLE_ENFORCER'

    def _run_tool(self, tool: str, args: list, cwd: Path):
        try:
            result = subprocess.run(
                [sys.executable, '-m', tool] + args,
                capture_output=True, text=True, cwd=str(cwd), timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _ensure_tool(self, tool: str):
        try:
            subprocess.run(
                [sys.executable, '-m', tool, '--version'],
                capture_output=True, timeout=10
            )
        except Exception:
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', tool, '-q'],
                timeout=120
            )

    def run(self, project_dir: Path):
        print(f'[{self.name}] Application des standards de style...')
        results = {}

        try:
            py_files = [f for f in project_dir.rglob('*.py')
                       if 'node_modules' not in str(f) and '__pycache__' not in str(f)]
            if not py_files:
                print(f'  ℹ️ Aucun fichier Python à formater')
                return {'agent_name': self.name, 'success': True, 'artifacts': {}, 'errors': []}
            self._ensure_tool('ruff')
            ok, output = self._run_tool('ruff', ['check', '--fix', str(project_dir)], project_dir)
            results['ruff'] = {'success': ok}
            print(f'  {"✅" if ok else "⚠️"} Ruff: {len(py_files)} fichiers Python')
            if not ok:
                ok2, output2 = self._run_tool('ruff', ['format', str(project_dir)], project_dir)
                results['ruff_format'] = {'success': ok2}
                print(f'  [{"OK" if ok2 else "WARN"}] Ruff format applique')
        except Exception as e:
            print(f'  ⚠️ Style enforcer ignoré : {e}')

        ts_files = [
            f for f in list(project_dir.rglob('*.ts')) + list(project_dir.rglob('*.tsx'))
            if 'node_modules' not in str(f)
        ]
        if ts_files:
            src_dir = project_dir / 'src'
            target = str(src_dir) if src_dir.exists() else str(project_dir)
            prettier_result = subprocess.run(
                ['npx', 'prettier', '--write', target, '--ignore-unknown'],
                capture_output=True, text=True, cwd=str(project_dir), timeout=60
            )
            results['prettier'] = {'success': prettier_result.returncode == 0}
            print(f'  [{"OK" if prettier_result.returncode == 0 else "WARN"}] Prettier : {len(ts_files)} fichiers TS/TSX')

        # Return a simple dict for compatibility -- caller handles AgentOutput wrapping
        return {'agent_name': self.name, 'success': True, 'artifacts': results, 'errors': []}
