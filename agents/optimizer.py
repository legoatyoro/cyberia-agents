from pathlib import Path
from core.llm_client import LLMClient
from core.expert_profiles import get_profile
from schemas.agent_schemas import AgentOutput
import json

class OptimizerAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'OPTIMIZER'

    def analyze_file(self, filepath: Path) -> dict:
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return {'file': filepath.name, 'issues': [], 'lines': 0}
        issues = []
        if content.count('SELECT') > 0 and 'for ' in content.lower():
            issues.append({'type': 'N+1_risk', 'severity': 'high'})
        if '.all()' in content and 'limit' not in content.lower():
            issues.append({'type': 'missing_pagination', 'severity': 'medium'})
        if 'cache' not in content.lower() and content.count('def ') > 5:
            issues.append({'type': 'no_caching', 'severity': 'low'})
        return {'file': filepath.name, 'issues': issues, 'lines': len(content.splitlines())}

    def optimize_file(self, filepath: Path) -> tuple:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        profile = get_profile('OPTIMIZER')
        prompt = f'''{profile["role"]}

Analyse et optimise ce fichier. Contraintes : {profile["constraints"]}

FICHIER : {filepath.name}
CONTENU :
{content[:4000]}

Retourne le fichier optimisé complet. AUCUN markdown.
Liste les optimisations appliquées en commentaire en haut du fichier.'''

        optimized = self.llm.call('code', prompt)
        try:
            from cyberia_sanitizer import strip_markdown_artifacts
            optimized = strip_markdown_artifacts(optimized)
        except ImportError:
            pass
        return optimized, []

    def run(self, project_dir: Path, target_files: list = None) -> AgentOutput:
        print(f'⚡ [{self.name}] Optimisation du projet...')
        if target_files is None:
            py_files = list(project_dir.rglob('*.py'))
            ts_files = list(project_dir.rglob('*.ts'))
            target_files = [f for f in py_files + ts_files
                          if 'node_modules' not in str(f) and 'test' not in f.name.lower()]

        analysis = [self.analyze_file(f) for f in target_files]
        high_priority = [a for a in analysis if any(i['severity'] == 'high' for i in a['issues'])]

        optimized_count = 0
        for item in high_priority[:3]:
            filepath = project_dir / item['file']
            if not filepath.exists():
                # try finding by name in project_dir
                matches = list(project_dir.rglob(item['file']))
                if matches:
                    filepath = matches[0]
                else:
                    continue
            optimized, _ = self.optimize_file(filepath)
            if optimized and len(optimized) > 100:
                backup = filepath.with_suffix(filepath.suffix + '.bak')
                backup.write_text(filepath.read_text(encoding='utf-8'), encoding='utf-8')
                filepath.write_text(optimized, encoding='utf-8')
                optimized_count += 1
                print(f'  ✅ {item["file"]} optimisé')

        report = {'analyzed': len(analysis), 'optimized': optimized_count, 'analysis': analysis}
        (project_dir / 'optimization_report.json').write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        print(f'  ✅ {optimized_count} fichier(s) optimisé(s)')
        return AgentOutput(agent_name=self.name, success=True, artifacts=report)
