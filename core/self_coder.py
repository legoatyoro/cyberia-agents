import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime
from core.multi_model_router import get_router

PROTECTED_FILES = {
    'core/agent_factory.py',
    'core\\agent_factory.py',
    '.env',
    '.cyberia/agent_registry.db',
    '.cyberia\\agent_registry.db',
}


class SelfCoder:
    def __init__(self):
        self.router = get_router()
        self.name = 'SELF_CODER'
        self.backup_dir = Path('.cyberia/backups')
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _is_protected(self, filepath: Path) -> bool:
        normalized = str(filepath).replace('\\', '/')
        return normalized in PROTECTED_FILES or str(filepath) in PROTECTED_FILES

    def _backup_file(self, filepath: Path) -> Path:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup = self.backup_dir / f'{filepath.name}.{ts}.bak'
        shutil.copy2(filepath, backup)
        return backup

    def _validate_python(self, code: str) -> tuple[bool, str]:
        try:
            ast.parse(code)
            return True, 'OK'
        except SyntaxError as e:
            return False, str(e)

    def analyze_self(self, target_file: Path) -> str:
        if not target_file.exists():
            return f'Fichier {target_file} introuvable'
        content = target_file.read_text(encoding='utf-8', errors='ignore')
        prompt = f'''Analyse ce fichier Python qui fait partie de CYBERIA, un système IA de génération de code.

FICHIER : {target_file.name}
CONTENU :
{content[:6000]}

Identifie :
1. Les fonctions lentes ou inefficaces
2. La gestion d'erreurs manquante
3. Le code dupliqué
4. Les imports inutiles
5. Les opportunités d'amélioration

Sois précis avec les numéros de lignes.'''

        return self.router.call(prompt, task_type='analysis', temperature=0.2)

    def improve_file(self, target_file: Path, analysis: str = '') -> dict:
        if self._is_protected(target_file):
            return {'success': False, 'reason': 'Fichier protégé'}

        content = target_file.read_text(encoding='utf-8', errors='ignore')
        prompt = f'''Améliore ce fichier Python. Partie de CYBERIA (système IA autonome).

FICHIER : {target_file.name}
ANALYSE : {analysis[:1000] if analysis else "Améliore la qualité générale"}

CODE ACTUEL :
{content[:6000]}

Génère le fichier COMPLET amélioré. Règles :
- Garder EXACTEMENT les mêmes fonctions et signatures
- Améliorer : gestion erreurs, performance, lisibilité
- Ajouter logging là où c'est utile
- AUCUN markdown, code Python pur uniquement'''

        improved = self.router.call(prompt, task_type='debug', temperature=0.15)
        from cyberia_sanitizer import strip_markdown_artifacts
        improved = strip_markdown_artifacts(improved)

        valid, reason = self._validate_python(improved)
        if not valid:
            return {'success': False, 'reason': f'Syntaxe invalide : {reason}'}

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_file = Path(tmp_dir) / target_file.name
            tmp_file.write_text(improved, encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-m', 'py_compile', str(tmp_file)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return {'success': False, 'reason': f'Erreur compilation : {result.stderr}'}

        backup = self._backup_file(target_file)
        target_file.write_text(improved, encoding='utf-8')
        original_lines = len(content.splitlines())
        new_lines = len(improved.splitlines())
        return {
            'success': True,
            'file': str(target_file),
            'backup': str(backup),
            'original_lines': original_lines,
            'new_lines': new_lines,
            'change': new_lines - original_lines
        }

    def self_improve_cyberia(self, targets: list = None) -> dict:
        print(f'\n[{self.name}] Auto-amélioration de CYBERIA...')
        if targets is None:
            targets = [
                Path('core/chat_engine.py'),
                Path('core/context_manager.py'),
                Path('core/auto_installer.py'),
                Path('agents/builder.py'),
                Path('agents/fixer.py'),
            ]
        results = []
        for filepath in targets:
            if not filepath.exists():
                continue
            if self._is_protected(filepath):
                print(f'  {filepath.name} — protégé, ignoré')
                continue
            print(f'  Amélioration de {filepath.name}...')
            analysis = self.analyze_self(filepath)
            result = self.improve_file(filepath, analysis)
            results.append({'file': filepath.name, **result})
            if result['success']:
                change = result['change']
                sign = '+' if change >= 0 else ''
                print(f'  OK {filepath.name} ({sign}{change} lignes, backup créé)')
            else:
                print(f'  Echec {filepath.name} : {result["reason"]}')

        success_count = sum(1 for r in results if r['success'])
        print(f'\n  {success_count}/{len(results)} fichiers améliorés')
        return {'results': results, 'success_count': success_count, 'total': len(results)}
