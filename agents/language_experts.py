from core.multi_model_router import MultiModelRouter
from pathlib import Path
import json


class LanguageExpert:
    def __init__(self, language, stack, rules, patterns):
        self.language = language
        self.stack = stack
        self.rules = rules
        self.patterns = patterns
        self.router = MultiModelRouter()

    def analyze(self, code, filename=''):
        prompt = f'''Tu es un expert {self.language} specialise.
REGLES CRITIQUES pour ce stack ({self.stack}):
{chr(10).join(f'- {r}' for r in self.rules)}

Analyse ce code et detecte les violations de ces regles ET les bugs generaux.
Reponds en JSON: [{{"line": N, "severity": "critical|high|medium", "rule": "...", "fix": "..."}}]
Si aucun probleme: []

FICHIER {filename}:
{code[:3000]}'''
        response = self.router.call(prompt, task_type='analysis')
        import re
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return []

    def generate_boilerplate(self, feature_name, description):
        prompt = f'''Tu es un expert {self.language}/{self.stack}.
Genere du code boilerplate production-ready pour: {feature_name}
Description: {description}
PATTERNS a utiliser: {', '.join(self.patterns)}
Reponds avec UNIQUEMENT le code, sans markdown ni explication.'''
        return self.router.call(prompt, task_type='code')

    def review_and_fix(self, code, error_message=''):
        prompt = f'''Expert {self.language}. Corrige ce code.
Erreur: {error_message}
Code: {code[:2000]}
Reponds avec le code corrige uniquement, sans explication.'''
        return self.router.call(prompt, task_type='fix')


DJANGO_EXPERT = LanguageExpert(
    language='Django/Python',
    stack='Django + DRF + PostgreSQL',
    rules=[
        'ROOT_URLCONF doit pointer vers un fichier qui existe',
        'Toutes les apps dans INSTALLED_APPS doivent avoir un dossier correspondant',
        'AUTH_USER_MODEL ne peut etre defini que dans une seule app',
        'Utiliser declarative_base depuis sqlalchemy.orm pas ext.declarative',
        'Toujours utiliser python-decouple pour les variables env',
        'Les migrations doivent etre crees avec makemigrations avant migrate',
    ],
    patterns=['ViewSet', 'Serializer', 'Permission', 'Signal', 'Manager']
)

FASTAPI_EXPERT = LanguageExpert(
    language='FastAPI/Python',
    stack='FastAPI + SQLAlchemy + Pydantic',
    rules=[
        'Toujours inclure uvicorn.run dans main.py',
        'Python 3.14 incompatible avec Jinja2 - utiliser HTMLResponse avec f-strings',
        'SQLAlchemy 2.0 : declarative_base depuis sqlalchemy.orm',
        'Les routes async doivent utiliser await pour les operations IO',
        'Pydantic v2 : model_validator au lieu de validator',
        'CORS doit etre configure avant les routes',
    ],
    patterns=['Router', 'Depends', 'BaseModel', 'AsyncSession', 'BackgroundTasks']
)

NODEJS_EXPERT = LanguageExpert(
    language='Node.js/Express',
    stack='Node.js + Express + PostgreSQL',
    rules=[
        'node_modules doit etre dans .gitignore',
        'Les cles API uniquement via variables environnement',
        'Procfile doit avoir web: node server.js sans syntaxe YAML',
        'Toujours gerer les erreurs avec try/catch dans les routes async',
        'Utiliser point-virgule comme separateur dans PowerShell pas &&',
    ],
    patterns=['Router', 'Middleware', 'Controller', 'Service', 'Model']
)

PYTHON_EXPERT = LanguageExpert(
    language='Python',
    stack='Python generique',
    rules=[
        'subprocess Windows : toujours bytes + decode utf-8 errors replace',
        'node_modules exclu de tous les rglob et scans',
        'requirements.txt jamais de modules locaux du projet',
        'Les imports circulaires doivent etre evites',
        'Toujours fermer les connexions SQLite avec conn.close()',
    ],
    patterns=['dataclass', 'contextmanager', 'generator', 'decorator', 'async/await']
)

EXPERTS = {
    'django': DJANGO_EXPERT,
    'fastapi': FASTAPI_EXPERT,
    'nodejs': NODEJS_EXPERT,
    'node': NODEJS_EXPERT,
    'python': PYTHON_EXPERT,
}


def detect_expert(project_dir):
    path = Path(project_dir)
    if (path / 'manage.py').exists():
        return DJANGO_EXPERT
    files = list(path.rglob('*.py'))[:20] + list(path.rglob('*.js'))[:10]
    content = ' '.join(
        f.read_text(encoding='utf-8', errors='ignore')[:500]
        for f in files
        if 'node_modules' not in str(f)
    )
    if 'fastapi' in content.lower() or 'from fastapi' in content.lower():
        return FASTAPI_EXPERT
    if 'express' in content.lower() or 'require("express")' in content.lower():
        return NODEJS_EXPERT
    return PYTHON_EXPERT


def expert_analyze_project(project_dir):
    expert = detect_expert(project_dir)
    print(f'  [EXPERT] Expert detecte : {expert.language}')
    path = Path(project_dir)
    all_issues = []
    py_files = [
        f for f in path.rglob('*.py')
        if '__pycache__' not in str(f) and 'node_modules' not in str(f)
    ][:10]
    js_files = [
        f for f in path.rglob('*.js')
        if 'node_modules' not in str(f)
    ][:5]
    for f in py_files + js_files:
        content = f.read_text(encoding='utf-8', errors='ignore')
        issues = expert.analyze(content, f.name)
        for issue in issues:
            issue['file'] = str(f)
            all_issues.append(issue)
    return expert, all_issues
