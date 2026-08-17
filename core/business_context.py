import sqlite3, json
from pathlib import Path
from datetime import datetime

DB = Path('.cyberia/business.db')


def init():
    DB.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS business_context (
            id INTEGER PRIMARY KEY, company TEXT UNIQUE,
            domain TEXT, priorities TEXT, existing_tools TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS user_priorities (
            id INTEGER PRIMARY KEY, priority TEXT,
            category TEXT, weight INTEGER DEFAULT 5,
            created_at TEXT
        );
    ''')
    conn.commit()
    conn.close()


def seed_yoro_context():
    init()
    companies = [
        (
            'Ecophone 44', 'telephonie retail Nantes',
            json.dumps(['gestion stock', 'SAV clients', 'facturation reparations']),
            json.dumps(['caisse enregistreuse', 'logiciel reparation']),
            'Boutique telephone Nantes, vente et reparation'
        ),
        (
            'TRANSPORTS GEANT', 'transport logistique Carquefou',
            json.dumps(['gestion planning', 'facturation clients', 'suivi livraisons', 'paie employes']),
            json.dumps(['logiciel paie']),
            'Societe de transport Carquefou - employe Hamza'
        ),
        (
            'REZICOM', 'telecom SAS Paris',
            json.dumps(['prospection B2B', 'gestion contrats', 'facturation']),
            json.dumps([]),
            'CA 558k, resultat net 172k en 2024'
        ),
        (
            'CYBERIA RedTeam Pro', 'cybersecurite SaaS',
            json.dumps(['stabiliser Blue Team', 'corriger webhook Stripe', 'fiabiliser parcours gratuit']),
            json.dumps(['Railway', 'PostgreSQL', 'Qdrant', 'Node.js']),
            'cyberiascan.fr - EN PAUSE - priorite technique avant monetisation'
        ),
        (
            'CYBERIA IA Autonome', 'IA generateur logiciels',
            json.dumps(['ameliorer intelligence', 'boucle test/fix autonome', 'deploiement Railway']),
            json.dumps(['DeepSeek', 'SQLite', 'Textual', 'sentence-transformers']),
            'Ce projet - en developpement actif'
        ),
    ]
    priorities = [
        ('Finir CYBERIA IA avant tout autre projet', 'technique', 10),
        ('Stabiliser CYBERIA RedTeam Pro Blue Team', 'technique', 8),
        ('Automatiser la paie TRANSPORTS GEANT', 'business', 7),
        ('Generer des revenus recurrents SaaS', 'business', 9),
        ('Ne jamais coder en dur les cles API', 'technique', 10),
        ('Toujours deployer via git push origin main', 'technique', 9),
        ('Preferer FastAPI pour les petites APIs', 'technique', 7),
    ]
    conn = sqlite3.connect(DB)
    for company, domain, prio, tools, notes in companies:
        conn.execute(
            'INSERT OR REPLACE INTO business_context (company, domain, priorities, existing_tools, notes) VALUES (?,?,?,?,?)',
            (company, domain, prio, tools, notes)
        )
    for priority, category, weight in priorities:
        conn.execute(
            'INSERT OR IGNORE INTO user_priorities (priority, category, weight, created_at) VALUES (?,?,?,?)',
            (priority, category, weight, datetime.now().isoformat())
        )
    conn.commit()
    conn.close()
    print('  [BUSINESS] Contexte Yoro initialise : 5 entreprises, 7 priorites')


def get_context_block():
    init()
    conn = sqlite3.connect(DB)
    companies = conn.execute(
        'SELECT company, domain, priorities, notes FROM business_context'
    ).fetchall()
    priorities = conn.execute(
        'SELECT priority, category FROM user_priorities ORDER BY weight DESC LIMIT 5'
    ).fetchall()
    conn.close()
    if not companies:
        return ''
    lines = ['CONTEXTE BUSINESS YORO:']
    for company, domain, prio_json, notes in companies:
        try:
            prios = json.loads(prio_json)
            prios_txt = ', '.join(prios[:2])
        except Exception:
            prios_txt = ''
        lines.append(f'  {company} ({domain}): {prios_txt}')
    lines.append('\nPRIORITES ACTUELLES:')
    for priority, category in priorities[:4]:
        lines.append(f'  [{category}] {priority}')
    return '\n'.join(lines)


def check_alignment(project_description):
    init()
    conn = sqlite3.connect(DB)
    priorities = conn.execute(
        'SELECT priority, weight FROM user_priorities ORDER BY weight DESC'
    ).fetchall()
    conn.close()
    if not priorities:
        return None
    top_priority = priorities[0][0] if priorities else ''
    desc_lower = project_description.lower()
    business_keywords = [
        'cyberia', 'transport', 'ecophone', 'rezicom',
        'facturation', 'paie', 'saas', 'api', 'scanner'
    ]
    is_aligned = any(kw in desc_lower for kw in business_keywords)
    if not is_aligned:
        return (f'Note: ta priorite principale est "{top_priority}". '
                f'Ce projet y contribue-t-il ? (continue quand meme si tu veux)')
    return None
