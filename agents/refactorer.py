from pathlib import Path
from core.llm_client import LLMClient
from core.expert_profiles import get_profile
from schemas.agent_schemas import AgentOutput

class RefactorerAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'REFACTORER'

    def run(self, project_dir: Path) -> AgentOutput:
        print(f'🔄 [{self.name}] Refactoring en cours...')
        profile = get_profile('REFACTORER')
        py_files = [f for f in project_dir.rglob('*.py')
                   if 'node_modules' not in str(f) and 'test' not in f.name.lower()]

        refactored = []
        for filepath in py_files[:5]:
            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if len(content.splitlines()) < 20:
                continue
            prompt = f'''{profile["role"]}
Contraintes : {profile["constraints"]}

Refactore ce fichier Python en appliquant DRY, SOLID, patterns appropriés.
NE PAS changer le comportement externe.

{content[:3000]}

Retourne le fichier refactoré complet. AUCUN markdown.'''

            result = self.llm.call('code', prompt)
            try:
                from cyberia_sanitizer import strip_markdown_artifacts
                result = strip_markdown_artifacts(result)
            except ImportError:
                pass
            if result and len(result) > 100:
                backup = filepath.with_suffix('.py.bak')
                backup.write_text(content, encoding='utf-8')
                filepath.write_text(result, encoding='utf-8')
                refactored.append(filepath.name)
                print(f'  ✅ {filepath.name} refactoré')

        return AgentOutput(agent_name=self.name, success=True,
                          artifacts={'refactored': refactored, 'count': len(refactored)})
