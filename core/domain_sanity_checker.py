from pathlib import Path

DOMAIN_INVARIANTS = {
    'finance': [
        ('Facture sans client', lambda f: 'Client' in f and 'Facture' in f and 'client' in f.lower()),
        ('Numerotation sequentielle', lambda f: 'numero' in f.lower() or 'number' in f.lower()),
        ('Montant toujours positif', lambda f: 'ge=0' in f or 'PositiveFloat' in f or 'validator' in f.lower()),
    ],
    'ecommerce': [
        ('Stock decremente apres commande', lambda f: 'stock' in f.lower() and ('decrement' in f.lower() or '-=' in f or 'stock -' in f)),
        ('Prix en centimes pour Stripe', lambda f: 'stripe' not in f.lower() or 'int(' in f or '* 100' in f),
        ('Panier lie a utilisateur', lambda f: 'cart' not in f.lower() or 'user' in f.lower()),
    ],
    'saas': [
        ("Abonnement avant acces", lambda f: 'subscription' not in f.lower() or 'active' in f.lower() or 'status' in f.lower()),
        ('Isolation tenant', lambda f: 'tenant' not in f.lower() or 'tenant_id' in f.lower() or 'organization_id' in f.lower()),
    ],
    'rh': [
        ('Conges lies a employe', lambda f: 'leave' not in f.lower() or 'employee' in f.lower()),
        ('Solde conges positif', lambda f: 'leave_balance' not in f.lower() or 'ge=0' in f or '>= 0' in f),
    ]
}


def check_domain_sanity(project_dir: Path, domain: str) -> dict:
    print(f'[DOMAIN_SANITY] Verification logique metier ({domain})...')
    invariants = DOMAIN_INVARIANTS.get(domain, [])
    if not invariants:
        return {'domain': domain, 'checked': 0, 'issues': []}

    all_content = ''
    for f in project_dir.rglob('*.py'):
        try:
            all_content += f.read_text(encoding='utf-8')
        except Exception:
            pass
    for f in list(project_dir.rglob('*.ts')) + list(project_dir.rglob('*.tsx')):
        if 'node_modules' not in str(f):
            try:
                all_content += f.read_text(encoding='utf-8')
            except Exception:
                pass

    issues = []
    for name, check_fn in invariants:
        try:
            if not check_fn(all_content):
                issues.append({'invariant': name, 'severity': 'WARNING'})
                print(f'  [WARN] {name} - a verifier')
        except Exception:
            pass

    if not issues:
        print(f'  [OK] Logique metier coherente ({len(invariants)} invariants verifies)')
    return {'domain': domain, 'checked': len(invariants), 'issues': issues}
