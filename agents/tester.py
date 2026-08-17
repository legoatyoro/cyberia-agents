import subprocess
from pathlib import Path
from cyberia_test_generator import extract_routes, generate_tests
from schemas.agent_schemas import AgentOutput

class TesterAgent:
    def __init__(self):
        self.name = 'TESTER'

    def run(self, project_dir: Path) -> AgentOutput:
        print(f'🧪 [{self.name}] Génération et exécution des tests...')
        main_file = project_dir / 'main.py'
        if not main_file.exists():
            return AgentOutput(agent_name=self.name, success=False, artifacts={}, errors=['main.py introuvable'])
        routes = extract_routes(main_file)
        test_file = generate_tests(project_dir, routes)
        print(f'  ✅ {len(routes)} routes testées → {test_file}')
        try:
            result = subprocess.run(
                ['python', '-m', 'pytest', test_file, '-v', '--tb=short'],
                capture_output=True, text=True, cwd=project_dir, timeout=60
            )
            passed = 'passed' in result.stdout
            print(f'  {"✅" if passed else "❌"} Tests : {result.stdout[-500:]}')
            return AgentOutput(
                agent_name=self.name,
                success=passed,
                artifacts={'test_output': result.stdout[-1000:]}
            )
        except Exception as e:
            return AgentOutput(agent_name=self.name, success=False, artifacts={}, errors=[str(e)])
