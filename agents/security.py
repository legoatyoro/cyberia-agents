import re, ast, json
from pathlib import Path
from schemas.agent_schemas import AgentOutput

class SecurityAgent:
    def __init__(self):
        self.name = 'SECURITY'
        self.secret_patterns = [
            (r'(?i)(api_key|secret|password|token)\s*=\s*["\'][^"\']{8,}["\']', 'Secret hardcodé'),
            (r'debug\s*=\s*True', 'Debug mode activé'),
            (r'ssl\s*=\s*False', 'SSL désactivé'),
            (r'verify\s*=\s*False', 'Vérification SSL désactivée'),
        ]

    def run(self, project_dir: Path) -> AgentOutput:
        print(f'🔐 [{self.name}] Audit de sécurité...')
        issues = []
        for py_file in project_dir.rglob('*.py'):
            content = py_file.read_text(encoding='utf-8', errors='ignore')
            for pattern, label in self.secret_patterns:
                for m in re.finditer(pattern, content):
                    issues.append({
                        'file': py_file.name,
                        'line': content[:m.start()].count('\n') + 1,
                        'issue': label,
                        'severity': 'HIGH'
                    })
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.JoinedStr):
                        issues.append({
                            'file': py_file.name,
                            'line': node.lineno,
                            'issue': 'f-string dans query SQL possible',
                            'severity': 'MEDIUM'
                        })
            except Exception:
                pass
        gitignore = project_dir / '.gitignore'
        if not gitignore.exists():
            gitignore.write_text('.env\n__pycache__/\n*.pyc\n*.sqlite\n.cyberia_cache/\n', encoding='utf-8')
        env_example = project_dir / '.env.example'
        if not env_example.exists():
            env_example.write_text('# Copier ce fichier en .env et remplir les valeurs\n# API_KEY=votre_cle\n', encoding='utf-8')
        report = {'total_issues': len(issues), 'issues': issues}
        (project_dir / 'security_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'✅ [{self.name}] {len(issues)} problème(s) détecté(s)')
        return AgentOutput(agent_name=self.name, success=True, artifacts=report)
