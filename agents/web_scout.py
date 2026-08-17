import sys
from pathlib import Path
from core.knowledge_base import add_pattern, add_rule
from schemas.agent_schemas import AgentOutput

class WebScoutAgent:
    def __init__(self):
        self.name = 'WEB_SCOUT'
        self.pypi_base = 'https://pypi.org/pypi'

    def get_pypi_info(self, package: str) -> dict:
        try:
            import httpx
            response = httpx.get(f'{self.pypi_base}/{package}/json', timeout=10)
            if response.status_code == 200:
                data = response.json()
                info = data.get('info', {})
                return {
                    'name': info.get('name'),
                    'version': info.get('version'),
                    'summary': info.get('summary', '')[:200],
                    'requires_python': info.get('requires_python', ''),
                    'home_page': info.get('home_page', ''),
                }
        except Exception:
            pass
        return {}

    def check_compatibility(self, package: str, python_version: str = '3.14') -> dict:
        info = self.get_pypi_info(package)
        if not info:
            return {'package': package, 'compatible': None, 'note': 'Infos non disponibles'}
        requires = info.get('requires_python', '')
        compatible = True
        note = f'Version {info.get("version")} — '
        if requires:
            note += f'Python requis : {requires}'
            if '3.14' in python_version:
                if '<3.13' in requires or '<3.12' in requires:
                    compatible = False
                    note += ' — ⚠️ INCOMPATIBLE Python 3.14'
        return {'package': package, 'version': info.get('version'), 'compatible': compatible, 'note': note}

    def scout_for_stack(self, dependencies: list) -> str:
        print(f'🔭 [{self.name}] Recherche infos pour {len(dependencies)} dépendances...')
        python_ver = f'{sys.version_info.major}.{sys.version_info.minor}'
        results = []
        warnings = []
        for dep in dependencies[:10]:
            pkg = dep.split('>=')[0].split('==')[0].strip()
            if not pkg or len(pkg) < 2:
                continue
            info = self.check_compatibility(pkg, python_ver)
            if info.get('version'):
                results.append(f'{pkg} v{info["version"]}')
                if not info.get('compatible', True):
                    warnings.append(f'⚠️ {pkg} : {info["note"]}')
                    add_rule(f'{pkg} incompatible avec Python {python_ver} — utiliser alternative', 'compatibility', pkg, 'web_scout', 0.8)
                else:
                    add_pattern(pkg, info.get('version', ''), 'version_info', f'Version actuelle : {info["version"]}', info.get('note', ''), 'web_scout')
        summary = f'Versions vérifiées : {", ".join(results[:5])}\n'
        if warnings:
            summary += '\nALERTES COMPATIBILITÉ :\n' + '\n'.join(warnings)
        print(f'  ✅ {len(results)} packages vérifiés, {len(warnings)} alerte(s)')
        return summary

    def run(self, dependencies: list) -> AgentOutput:
        summary = self.scout_for_stack(dependencies)
        return AgentOutput(agent_name=self.name, success=True, artifacts={'summary': summary})
