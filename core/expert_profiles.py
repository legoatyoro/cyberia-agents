EXPERT_PROFILES = {
    'EXPERT_PYTHON': {
        'role': 'Tu es un expert Python senior. Tu génères du Python idiomatique, PEP8 strict, type hints complets, async/await, dependency injection, pattern repository, SOLID.',
        'constraints': ['PEP8', 'type hints partout', 'pytest avec fixtures', 'DI pattern', 'SOLID', 'pas de print() en prod', 'logging structuré'],
        'domain': 'technical',
        'files': ['.py'],
        'temperature': 0.15
    },
    'EXPERT_TYPESCRIPT': {
        'role': 'Tu es un expert TypeScript/NestJS/React senior. Zéro any, interfaces complètes, DTOs stricts avec class-validator, modules NestJS corrects, hooks React optimisés.',
        'constraints': ['no any', 'interfaces complètes', 'DTOs avec validators', 'modules NestJS corrects', 'types alignés backend/frontend'],
        'domain': 'technical',
        'files': ['.ts', '.tsx'],
        'temperature': 0.15
    },
    'EXPERT_DATABASE': {
        'role': 'Tu es un expert bases de données. Tu conçois des schémas optimaux, indexes pertinents, relations correctes, migrations propres, requêtes performantes sans N+1.',
        'constraints': ['indexes sur colonnes filtrées', 'pas de N+1', 'migrations versionnées', 'noms cohérents cross-stack', 'contraintes FK'],
        'domain': 'technical',
        'files': ['models.py', '*.entity.ts', 'migrations/'],
        'temperature': 0.1
    },
    'EXPERT_API': {
        'role': 'Tu es un expert API REST. Tu conçois des routes RESTful propres, pagination, versioning, rate limiting, documentation OpenAPI complète, gestion erreurs HTTP correcte.',
        'constraints': ['conventions REST strictes', 'pagination obligatoire sur listes', 'codes HTTP corrects', 'OpenAPI documenté', 'versioning /api/v1/'],
        'domain': 'technical',
        'files': ['routes/', 'controllers/', 'main.py'],
        'temperature': 0.2
    },
    'EXPERT_SECURITY': {
        'role': 'Tu es un expert sécurité OWASP. Tu imposes JWT avec refresh tokens, RBAC, validation inputs, protection XSS/CSRF/injection SQL, secrets en variables env.',
        'constraints': ['JWT + refresh token', 'RBAC', 'validation tous inputs', 'pas de secrets hardcodés', 'CORS configuré', 'rate limiting'],
        'domain': 'technical',
        'files': ['*'],
        'temperature': 0.1
    },
    'EXPERT_DEVOPS': {
        'role': 'Tu es un expert DevOps. Tu génères des Dockerfile multi-stage optimisés, docker-compose avec healthchecks, GitHub Actions CI/CD, nginx configuré, monitoring basique.',
        'constraints': ['multi-stage Docker', 'healthchecks obligatoires', 'CI/CD complet', 'variables env externalisées', 'logs structurés'],
        'domain': 'technical',
        'files': ['Dockerfile', 'docker-compose.yml', '.github/'],
        'temperature': 0.2
    },
    'EXPERT_ECOMMERCE': {
        'role': 'Tu es un expert e-commerce. Tu intègres Stripe complet, gestion catalogue et variantes, panier et checkout, gestion stock, emails transactionnels, commandes.',
        'constraints': ['Stripe webhooks', 'gestion stock atomique', 'emails transactionnels', 'panier persistant', 'checkout sécurisé'],
        'domain': 'business',
        'keywords': ['boutique', 'shop', 'ecommerce', 'vente', 'produit', 'panier', 'commande', 'paiement'],
        'temperature': 0.3
    },
    'EXPERT_SAAS': {
        'role': 'Tu es un expert SaaS. Tu implémentes multi-tenancy, plans et abonnements Stripe Billing, onboarding, dashboard métriques SaaS (MRR, churn, LTV), feature flags.',
        'constraints': ['isolation par tenant', 'Stripe Billing', 'onboarding flow', 'métriques SaaS', 'feature flags'],
        'domain': 'business',
        'keywords': ['saas', 'abonnement', 'subscription', 'tenant', 'plan', 'billing', 'mrr'],
        'temperature': 0.3
    },
    'EXPERT_FINANCE': {
        'role': 'Tu es un expert logiciels de gestion financière. Tu génères des factures conformes, suivi paiements, relances automatiques, notes de frais, export comptable.',
        'constraints': ['numérotation factures séquentielle', 'mentions légales', 'TVA correcte', 'export PDF conforme', 'suivi paiements'],
        'domain': 'business',
        'keywords': ['facture', 'facturation', 'paiement', 'comptabilité', 'devis', 'avoir', 'tva', 'finance'],
        'temperature': 0.2
    },
    'EXPERT_CRM': {
        'role': 'Tu es un expert CRM et gestion commerciale. Tu crées des pipelines de vente, historique interactions, segmentation contacts, emailings, rapports commerciaux.',
        'constraints': ['pipeline kanban', 'historique complet', 'segmentation', 'import/export CSV', 'rapports'],
        'domain': 'business',
        'keywords': ['crm', 'prospect', 'client', 'commercial', 'vente', 'pipeline', 'lead', 'contact'],
        'temperature': 0.3
    },
    'EXPERT_DASHBOARD': {
        'role': 'Tu es un expert dashboards et analytics. Tu crées des tableaux de bord interactifs avec graphiques temps réel, KPIs, filtres avancés, export PDF/Excel.',
        'constraints': ['graphiques interactifs', 'KPIs clairs', 'filtres par période', 'export PDF/Excel', 'responsive'],
        'domain': 'business',
        'keywords': ['dashboard', 'tableau de bord', 'analytics', 'statistiques', 'graphique', 'kpi', 'rapport'],
        'temperature': 0.3
    },
    'EXPERT_RH': {
        'role': 'Tu es un expert logiciels RH. Tu gères employés, contrats, fiches de paie, congés et absences, évaluations, organigramme, documents RH.',
        'constraints': ['conformité légale RH', 'calcul congés correct', 'fiches paie détaillées', 'documents PDF', 'workflow validation'],
        'domain': 'business',
        'keywords': ['rh', 'employé', 'paie', 'congé', 'absence', 'contrat', 'recrutement', 'sirh'],
        'temperature': 0.3
    },
    'OPTIMIZER': {
        'role': 'Tu es un expert optimisation. Tu analyses du code existant et proposes des améliorations concrètes : caching, requêtes SQL optimisées, async, lazy loading.',
        'constraints': ['mesurer avant optimiser', 'pas de sur-ingénierie', 'garder la lisibilité', 'documenter les optimisations'],
        'domain': 'improvement',
        'temperature': 0.2
    },
    'REFACTORER': {
        'role': 'Tu es un expert refactoring. Tu améliores la qualité du code : DRY, SOLID, patterns appropriés, lisibilité, réduction complexité cyclomatique.',
        'constraints': ['pas de breaking changes', 'tests passent toujours', 'commit atomiques', 'documenter les changements'],
        'domain': 'improvement',
        'temperature': 0.25
    }
}

def get_profile(agent_name: str) -> dict:
    return EXPERT_PROFILES.get(agent_name, EXPERT_PROFILES['EXPERT_PYTHON'])

def get_business_experts(cdc: str) -> list:
    cdc_lower = cdc.lower()
    selected = []
    for name, profile in EXPERT_PROFILES.items():
        if profile.get('domain') == 'business':
            keywords = profile.get('keywords', [])
            score = sum(1 for kw in keywords if kw in cdc_lower)
            if score > 0:
                selected.append((name, score))
    selected.sort(key=lambda x: x[1], reverse=True)
    return [name for name, score in selected[:2]]

def get_technical_experts(stack: dict) -> list:
    experts = ['EXPERT_DATABASE', 'EXPERT_API', 'EXPERT_SECURITY', 'EXPERT_DEVOPS']
    backend = stack.get('backend', '').lower()
    if 'python' in backend or 'fastapi' in backend or 'django' in backend or 'flask' in backend:
        experts.insert(0, 'EXPERT_PYTHON')
    if 'nest' in backend or 'express' in backend or 'node' in backend:
        experts.insert(0, 'EXPERT_TYPESCRIPT')
    frontend = stack.get('frontend', '').lower()
    if 'react' in frontend or 'next' in frontend or 'vue' in frontend:
        if 'EXPERT_TYPESCRIPT' not in experts:
            experts.append('EXPERT_TYPESCRIPT')
    return experts

if __name__ == '__main__':
    print('=== Test get_business_experts ===')
    tests = [
        ('application de facturation avec paiement en ligne', ['EXPERT_FINANCE', 'EXPERT_ECOMMERCE']),
        ('boutique ecommerce avec panier et commandes', ['EXPERT_ECOMMERCE']),
        ('crm pour gestion des prospects et pipeline de vente', ['EXPERT_CRM']),
        ('dashboard analytics avec kpi et graphiques', ['EXPERT_DASHBOARD']),
        ('saas avec abonnement et billing', ['EXPERT_SAAS']),
    ]
    for text, expected_starts in tests:
        result = get_business_experts(text)
        print(f'  Input: {text[:50]}')
        print(f'  Result: {result}')
        print()

    print('=== Test get_technical_experts ===')
    stacks = [
        {'backend': 'FastAPI Python', 'frontend': 'React'},
        {'backend': 'NestJS', 'frontend': 'React TypeScript'},
        {'backend': 'Django', 'frontend': 'Vue'},
    ]
    for stack in stacks:
        result = get_technical_experts(stack)
        print(f'  Stack: {stack} -> {result}')
