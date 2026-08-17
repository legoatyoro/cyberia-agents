GENERATION_RULES = '''
RÈGLES ABSOLUES DE GÉNÉRATION — À RESPECTER IMPÉRATIVEMENT :

RÈGLE 1 — DÉMARRAGE SERVEUR OBLIGATOIRE :
Chaque main.py DOIT se terminer par exactement ce bloc :
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
Sans ce bloc, le projet ne démarre pas.

RÈGLE 2 — INTERDICTION ABSOLUE DE JINJA2 :
NE JAMAIS utiliser Jinja2Templates, TemplateResponse, ou Environment de Jinja2.
Python 3.14 est incompatible avec Jinja2. Toujours utiliser HTMLResponse avec du HTML généré en Python via f-strings.

RÈGLE 3 — SQLALCHEMY MODERNE OBLIGATOIRE :
TOUJOURS écrire : from sqlalchemy.orm import declarative_base
JAMAIS : from sqlalchemy.ext.declarative import declarative_base

RÈGLE 4 — ROUTE RACINE OBLIGATOIRE :
TOUJOURS définir @app.get("/", response_class=HTMLResponse) qui retourne une vraie interface HTML Bootstrap.

RÈGLE 5 — REQUIREMENTS.TXT PROPRE :
UNIQUEMENT des packages installables via pip. JAMAIS les modules locaux du projet (database, models, services, agents, api, utils).

RÈGLE 6 — FICHIERS COMPLETS :
Chaque fichier généré DOIT être complet et syntaxiquement valide. Jamais de code tronqué.

RÈGLE 7 — IMPORTS LOCAUX CORRECTS :
Utiliser des imports relatifs cohérents. Si models.py est à la racine, importer avec 'from models import X', pas 'from app.models import X'.
'''

KNOWN_ERRORS = [
    {
        'pattern': 'uvicorn.run',
        'check': lambda stderr, code: 'uvicorn.run' not in code,
        'description': 'uvicorn.run manquant dans main.py',
        'fix_type': 'append',
        'fix_content': "\n\nif __name__ == '__main__':\n    import uvicorn\n    uvicorn.run(app, host='0.0.0.0', port=8000)\n"
    },
    {
        'pattern': 'Jinja2',
        'check': lambda stderr, code: 'Jinja2' in stderr or 'TemplateResponse' in stderr,
        'description': 'Jinja2 incompatible Python 3.14',
        'fix_type': 'replace_jinja2',
        'fix_content': None
    },
    {
        'pattern': 'declarative_base',
        'check': lambda stderr, code: 'MovedIn20Warning' in stderr or 'sqlalchemy.ext.declarative' in code,
        'description': 'declarative_base déprécié',
        'fix_type': 'replace',
        'fix_old': 'from sqlalchemy.ext.declarative import declarative_base',
        'fix_new': 'from sqlalchemy.orm import declarative_base'
    },
    {
        'pattern': 'Address already in use',
        'check': lambda stderr, code: 'Address already in use' in stderr,
        'description': 'Port déjà utilisé',
        'fix_type': 'change_port',
        'fix_content': None
    },
    {
        'pattern': 'No module named',
        'check': lambda stderr, code: 'No module named' in stderr,
        'description': 'Module manquant',
        'fix_type': 'install_module',
        'fix_content': None
    },
    {
        'pattern': 'SyntaxError',
        'check': lambda stderr, code: 'SyntaxError' in stderr,
        'description': 'Erreur de syntaxe',
        'fix_type': 'deepseek_fix',
        'fix_content': None
    },
    {
        'pattern': 'templates',
        'check': lambda stderr, code: 'Jinja2Templates' in code or 'from fastapi.templating' in code,
        'description': 'Jinja2Templates détecté dans le code',
        'fix_type': 'replace_jinja2',
        'fix_content': None
    },
]

PORT_RANGE = list(range(8000, 8011))


CRITICAL_RULES = '''
RÈGLES CRITIQUES SUPPLÉMENTAIRES :
- requirements.txt : UNIQUEMENT fastapi, uvicorn, sqlalchemy, pydantic, python-jose[cryptography], passlib[bcrypt], python-dotenv, httpx. JAMAIS les noms de modules du projet.
- JAMAIS from fastapi.templating import Jinja2Templates
- JAMAIS templates = Jinja2Templates(...)
- JAMAIS return templates.TemplateResponse(...)
- TOUJOURS si __name__ == '__main__': uvicorn.run(app, host='0.0.0.0', port=8000) à la fin de main.py
- Les fichiers HTML, CSS, JS, .env.example et README.md ne sont PAS du Python — ne pas les parser avec ast.parse()
'''


def get_system_prompt_rules() -> str:
    return GENERATION_RULES + CRITICAL_RULES


def get_builder_system_prompt(base_prompt: str = '') -> str:
    return base_prompt + '\n\n' + GENERATION_RULES


def find_matching_error(stderr: str, code: str) -> dict | None:
    for error in KNOWN_ERRORS:
        try:
            if error['check'](stderr, code):
                return error
        except Exception:
            pass
    return None
