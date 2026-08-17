import ast
import json
import re
from pathlib import Path
from core.multi_model_router import get_router
from schemas.agent_schemas import AgentOutput

DOMAIN_UI_TEMPLATES = {
    'finance': {'color': '#10b981', 'icon': '💰', 'accent': 'success'},
    'project': {'color': '#3b82f6', 'icon': '📋', 'accent': 'primary'},
    'sport': {'color': '#3b82f6', 'icon': '⚽', 'accent': 'primary'},
    'crm': {'color': '#8b5cf6', 'icon': '👥', 'accent': 'purple'},
    'ecommerce': {'color': '#f59e0b', 'icon': '🛍️', 'accent': 'warning'},
    'rh': {'color': '#ef4444', 'icon': '👤', 'accent': 'danger'},
    'analytics': {'color': '#06b6d4', 'icon': '📊', 'accent': 'info'},
    'default': {'color': '#7c3aed', 'icon': '🚀', 'accent': 'secondary'},
}


def detect_domain(cdc: str, blueprint: dict) -> str:
    cdc_lower = cdc.lower()
    project_name = blueprint.get('project_name', '').lower()
    combined = cdc_lower + ' ' + project_name

    domains = {
        'finance': ['facture', 'facturation', 'comptabilité', 'paiement', 'devis', 'avoir', 'tva', 'invoice', 'billing'],
        'project': ['projet', 'tâche', 'task', 'kanban', 'sprint', 'équipe', 'team', 'management', 'gestion de projet', 'project'],
        'sport': ['football', 'sport', 'match', 'score', 'probabilité', 'league', 'équipe sportive', 'goal'],
        'crm': ['client', 'prospect', 'crm', 'contact', 'commercial', 'lead', 'pipeline'],
        'ecommerce': ['boutique', 'produit', 'commande', 'stock', 'vente', 'panier', 'shop'],
        'rh': ['employé', 'congé', 'paie', 'recrutement', 'rh', 'sirh', 'contrat'],
        'analytics': ['dashboard', 'analytics', 'statistique', 'graphique', 'kpi', 'rapport', 'métrique'],
    }

    scores = {}
    for domain, keywords in domains.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[domain] = score

    if scores:
        return max(scores, key=scores.get)
    return 'default'


def extract_routes_from_ast(main_file: Path) -> list:
    routes = []
    try:
        content = main_file.read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        method = dec.func.attr.upper()
                        if method in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
                            path = dec.args[0].s if dec.args and isinstance(dec.args[0], ast.Constant) else '/'
                            routes.append({'method': method, 'path': path, 'func': node.name})
    except Exception:
        pass
    return routes


class UIGeneratorAgent:
    def __init__(self):
        self.router = get_router()
        self.name = 'UI_GENERATOR'

    def run(self, project_dir: Path, blueprint: dict = None, cdc: str = '') -> AgentOutput:
        print(f'\n🎨 [{self.name}] Génération de l\'interface...')
        main_file = project_dir / 'main.py'
        if not main_file.exists():
            return AgentOutput(agent_name=self.name, success=False, artifacts={},
                               errors=['main.py introuvable'])

        domain = detect_domain(cdc, blueprint or {})
        theme = DOMAIN_UI_TEMPLATES.get(domain, DOMAIN_UI_TEMPLATES['default'])
        routes = extract_routes_from_ast(main_file)
        api_routes = [r for r in routes if '/api/' in r['path'] or r['method'] in ['POST', 'PUT', 'DELETE']]
        project_name = project_dir.name.replace('-', ' ').replace('_', ' ').title()

        print(f'  🎨 Domaine : {domain} | Routes API : {len(api_routes)}')

        prompt = f'''Génère une interface web Bootstrap 5 complète pour cette application.

PROJET : {project_name}
DOMAINE : {domain}
COULEUR PRINCIPALE : {theme["color"]}
ICÔNE : {theme["icon"]}

ROUTES API DISPONIBLES :
{json.dumps(api_routes[:10], indent=2)}

GÉNÈRE UNE FONCTION Python nommée generate_html_interface() qui retourne une string HTML complète avec :

1. Navbar sombre avec le nom du projet et l'icône
2. Dashboard avec 3-4 cartes de statistiques (compteurs à 0 par défaut)
3. Section principale avec formulaire de création/recherche adapté au domaine
4. Tableau ou liste pour afficher les données (vide par défaut avec message)
5. JavaScript vanilla pour appeler les routes API et afficher les résultats
6. Design Bootstrap 5 via CDN, fond sombre (#0a0a0f), cartes (#1e1e2e)
7. Responsive mobile

La fonction doit être autonome et retourner le HTML complet.
La fonction doit appeler les vraies routes API du projet.
AUCUN markdown, AUCUNE explication, uniquement le code Python.'''

        code = self.router.call(prompt, task_type='code', temperature=0.2)
        try:
            from cyberia_sanitizer import strip_markdown_artifacts
            code = strip_markdown_artifacts(code)
        except ImportError:
            pass

        ui_file = project_dir / 'ui_interface.py'
        ui_file.write_text(code, encoding='utf-8')

        content = main_file.read_text(encoding='utf-8', errors='ignore')
        if 'generate_html_interface' not in content:
            injection = '''
from ui_interface import generate_html_interface

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(generate_html_interface())

'''
            old_route_pattern = '@app.get("/")'
            if old_route_pattern in content:
                content = re.sub(
                    r'@app\.get\("/"\).*?(?=\n@app|\nif __name__)',
                    injection,
                    content,
                    flags=re.DOTALL
                )
            else:
                insert_before = 'if __name__'
                if insert_before in content:
                    content = content.replace(insert_before, injection + insert_before)
            main_file.write_text(content, encoding='utf-8')

        print(f'  ✅ Interface générée et injectée dans main.py')
        return AgentOutput(agent_name=self.name, success=True,
                           artifacts={'domain': domain, 'theme': theme,
                                      'routes_detected': len(routes)})
