import subprocess, sys, json, time
from pathlib import Path
from schemas.agent_schemas import AgentOutput
from core.auto_installer import auto_install_project, auto_install_from_error

class RunnerAgent:
    def __init__(self):
        self.name = 'RUNNER'

    def _run_process(self, cmd: list, cwd: Path, timeout: int = 30) -> dict:
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            out, err = proc.communicate(timeout=timeout)
            return {'exit_code': proc.returncode, 'stdout': out, 'stderr': err, 'timeout': False}
        except subprocess.TimeoutExpired:
            proc.kill()
            return {'exit_code': -1, 'stdout': '', 'stderr': 'Timeout', 'timeout': True}
        except Exception as e:
            return {'exit_code': -1, 'stdout': '', 'stderr': str(e), 'timeout': False}

    def run(self, project_dir: Path, entry_point: str = 'main.py', run_tests: bool = True) -> AgentOutput:
        print(f'🏃 [{self.name}] Démarrage...')
        install_results = auto_install_project(project_dir)
        artifacts = {'install': install_results}

        if run_tests:
            test_files = list(project_dir.rglob('test_*.py')) + list(project_dir.rglob('tests/*.py'))
            if test_files:
                print(f'  🧪 Exécution des tests ({len(test_files)} fichier(s))...')
                result = self._run_process(
                    [sys.executable, '-m', 'pytest', str(project_dir), '-v', '--tb=short', '-q'],
                    project_dir
                )
                artifacts['test_result'] = result
                if result['exit_code'] == 0:
                    print(f'  ✅ Tests passés')
                else:
                    print(f'  ⚠️ Tests échoués, tentative de correction des imports...')
                    fixed = auto_install_from_error(result['stderr'])
                    if fixed:
                        result2 = self._run_process(
                            [sys.executable, '-m', 'pytest', str(project_dir), '-q'],
                            project_dir
                        )
                        artifacts['test_result_retry'] = result2

        report_path = project_dir / 'runner_report.json'
        report_path.write_text(json.dumps(artifacts, indent=2, ensure_ascii=False), encoding='utf-8')

        entry = project_dir / entry_point
        if entry.exists():
            print(f'  🔍 Vérification syntaxe de {entry_point}...')
            result = self._run_process([sys.executable, '-m', 'py_compile', str(entry)], project_dir)
            artifacts['syntax_check'] = result
            if result['exit_code'] == 0:
                print(f'  ✅ Syntaxe valide')
            else:
                print(f'  ❌ Erreur syntaxe : {result["stderr"][:200]}')

        success = artifacts.get('syntax_check', {}).get('exit_code', 0) == 0
        errors = []
        if not success and 'syntax_check' in artifacts:
            errors.append(artifacts['syntax_check']['stderr'][:500])

        print(f'  {"✅" if success else "❌"} RUNNER terminé')
        return AgentOutput(agent_name=self.name, success=success, artifacts=artifacts, errors=errors)
