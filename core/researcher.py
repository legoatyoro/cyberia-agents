import json
from pathlib import Path

KNOWLEDGE_BASE = {
    'fastapi_auth': {
        'tags': ['python', 'fastapi', 'auth', 'jwt'],
        'libraries': ['fastapi', 'python-jose', 'passlib', 'bcrypt'],
        'patterns': ['OAuth2PasswordBearer', 'JWT access + refresh tokens', 'password hashing passlib'],
        'pitfalls': ['SECRET_KEY jamais en dur', 'tokens non revocables sans blacklist', 'expire_delta trop long'],
        'prompt': "Pour l'auth FastAPI : utiliser OAuth2PasswordBearer + python-jose pour JWT + passlib pour hash. Toujours access token (15min) + refresh token (7j)."
    },
    'sqlalchemy_models': {
        'tags': ['python', 'sqlalchemy', 'models', 'orm'],
        'libraries': ['sqlalchemy', 'alembic'],
        'patterns': ['declarative_base', 'relationship lazy loading', 'cascade delete'],
        'pitfalls': ["N+1 sur les relations", "pas de index sur colonnes filtrees", "session non fermee"],
        'prompt': 'SQLAlchemy : toujours index sur colonnes de recherche. Utiliser selectinload() pour eviter N+1. Fermer la session avec try/finally.'
    },
    'fastapi_html_python314': {
        'tags': ['python', 'fastapi', 'html', 'python3.14'],
        'libraries': ['fastapi'],
        'patterns': ['HTMLResponse avec f-strings', 'fonctions render_*', 'Bootstrap CDN'],
        'pitfalls': ['Jinja2 incompatible Python 3.14', 'TemplateResponse crash'],
        'prompt': 'Python 3.14 + FastAPI : JAMAIS Jinja2. Toujours HTMLResponse avec fonctions Python generant du HTML via f-strings. Inclure Bootstrap via CDN.'
    },
    'nestjs_structure': {
        'tags': ['typescript', 'nestjs', 'structure'],
        'libraries': ['@nestjs/common', '@nestjs/core', '@nestjs/mapped-types', '@nestjs/config', 'class-validator'],
        'patterns': ['Module/Controller/Service trinity', 'DTO avec class-validator', 'Guards JWT'],
        'pitfalls': ['DTOs manquants = erreurs TS', '@nestjs/config toujours installe', 'module non importe dans AppModule'],
        'prompt': 'NestJS : toujours generer les DTOs (create + update) AVANT les controllers. Installer @nestjs/config et @nestjs/mapped-types. Chaque module dans AppModule.imports.'
    },
    'react_structure': {
        'tags': ['typescript', 'react', 'hooks', 'context'],
        'libraries': ['react', 'react-router-dom', 'axios'],
        'patterns': ['Context + useReducer', 'custom hooks', 'lazy loading routes'],
        'pitfalls': ['prop drilling', 'useEffect sans cleanup', 'state non initialise'],
        'prompt': 'React : Context API pour state global. Custom hooks pour logic reutilisable. Toujours cleanup dans useEffect. TypeScript strict (no any).'
    },
    'stripe_integration': {
        'tags': ['payment', 'stripe', 'saas', 'ecommerce'],
        'libraries': ['stripe'],
        'patterns': ['Webhook signature verification', 'idempotency keys', 'Stripe Checkout'],
        'pitfalls': ['webhook sans verification signature = faille critique', 'prix en centimes pas en euros', "pas de gestion des erreurs carte"],
        'prompt': "Stripe : TOUJOURS verifier la signature des webhooks avec stripe.Webhook.construct_event(). Prix en centimes. Gerer les erreurs CardError, InvalidRequestError."
    },
    'docker_best_practices': {
        'tags': ['devops', 'docker', 'deployment'],
        'libraries': ['docker'],
        'patterns': ['multi-stage build', '.dockerignore', 'non-root user', 'healthcheck'],
        'pitfalls': ['image trop lourde', 'secrets dans le Dockerfile', 'pas de healthcheck'],
        'prompt': 'Docker : multi-stage build (builder + runtime). Toujours .dockerignore. Utiliser un utilisateur non-root. Ajouter HEALTHCHECK. Jamais de secrets dans le Dockerfile.'
    },
    'security_basics': {
        'tags': ['security', 'owasp', 'auth'],
        'libraries': ['python-jose', 'passlib', 'cryptography'],
        'patterns': ['HTTPS only en prod', 'CORS strict', 'rate limiting', 'input validation'],
        'pitfalls': ['CORS wildcard en prod', 'pas de rate limiting', "erreurs qui exposent des details"],
        'prompt': "Securite : CORS strict (pas de wildcard), rate limiting sur auth, valider tous les inputs, messages d'erreur generiques (pas de stacktrace)."
    }
}


def find_relevant_knowledge(cdc: str, stack: dict) -> list:
    cdc_lower = cdc.lower()
    stack_str = json.dumps(stack).lower()
    combined = cdc_lower + ' ' + stack_str
    selected = []
    for key, knowledge in KNOWLEDGE_BASE.items():
        score = sum(1 for tag in knowledge['tags'] if tag in combined)
        if score >= 2:
            selected.append((score, key, knowledge))
    selected.sort(reverse=True)
    return [(k, v) for _, k, v in selected[:5]]


def generate_research_report(cdc: str, stack: dict, project_dir: Path) -> str:
    print(f'[RESEARCHER] Analyse de la base de connaissance...')
    relevant = find_relevant_knowledge(cdc, stack)

    if not relevant:
        print(f'  [INFO] Pas de fiche specifique - utilisation des defaults')
        return ''

    prompt_parts = ['\n\nFICHES TECHNIQUES (base de connaissance CYBERIA) :']
    for key, knowledge in relevant:
        prompt_parts.append(f'\n[{key.upper()}]')
        prompt_parts.append(knowledge['prompt'])
        if knowledge['pitfalls']:
            prompt_parts.append(f'Pieges a eviter : {"; ".join(knowledge["pitfalls"])}')

    report_text = '\n'.join(prompt_parts)
    (project_dir / 'research_report.json').write_text(
        json.dumps({'fiches': [k for k, _ in relevant], 'prompt_injection': report_text}, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    print(f'  [OK] {len(relevant)} fiche(s) technique(s) injectee(s)')
    return report_text


if __name__ == '__main__':
    print('=== Test find_relevant_knowledge ===')
    tests = [
        ('application fastapi avec auth jwt et sqlalchemy', {'backend': 'fastapi python'}),
        ('boutique ecommerce avec stripe et react', {'frontend': 'react', 'payment': 'stripe'}),
        ('deployment docker nestjs typescript', {'backend': 'nestjs', 'devops': 'docker'}),
        ('application simple sans tech specifique', {}),
    ]
    for cdc, stack in tests:
        result = find_relevant_knowledge(cdc, stack)
        print(f'  CDC: "{cdc[:50]}"')
        print(f'  Fiches: {[k for k, _ in result]}')
        print()
