import json
from pathlib import Path
from datetime import datetime

DOMAIN_SLOTS = {
    'finance': {
        'questions': [
            'Pour qui est cette app ? (PME, freelance, grande entreprise)',
            'Tu veux gérer plusieurs devises ou uniquement EUR ?',
            'Paiement en ligne (Stripe) ou virement/chèque uniquement ?',
            'Tu veux aussi gérer les devis et avoir en plus des factures ?',
            'Export comptable nécessaire ? (FEC, CSV)'
        ],
        'slots': ['target', 'currency', 'payment', 'features', 'export']
    },
    'ecommerce': {
        'questions': [
            'Tu vends des produits physiques, numériques ou les deux ?',
            'Tu as combien de produits environ ?',
            'Tu veux intégrer Stripe ou PayPal ?',
            'Tu veux un système de codes promo ?',
            'Gestion des stocks nécessaire ?'
        ],
        'slots': ['product_type', 'catalog_size', 'payment', 'promo', 'stock']
    },
    'saas': {
        'questions': [
            'Tu proposes combien de plans tarifaires ?',
            'Tu veux un essai gratuit ? Combien de jours ?',
            'Multi-utilisateurs par compte ou un seul ?',
            'Tu veux un dashboard métriques SaaS (MRR, churn) ?',
            'Intégration Stripe Billing nécessaire ?'
        ],
        'slots': ['plans', 'trial', 'multi_user', 'metrics', 'billing']
    },
    'crm': {
        'questions': [
            "Tu veux gérer des leads, des clients, ou les deux ?",
            "Tu as besoin d'un pipeline de vente visuel (kanban) ?",
            'Intégration email (envoi depuis le CRM) ?',
            'Tu veux importer des contacts depuis Excel/CSV ?',
            'Rapports et statistiques commerciales nécessaires ?'
        ],
        'slots': ['contacts_type', 'pipeline', 'email', 'import', 'reports']
    },
    'dashboard': {
        'questions': [
            'Quelles données tu veux afficher ? (ventes, trafic, stocks...)',
            "Les données viennent d'où ? (base de données, API, fichiers)",
            'Tu veux des alertes automatiques sur les seuils ?',
            'Export PDF ou Excel des rapports ?',
            'Mise à jour temps réel ou toutes les X heures ?'
        ],
        'slots': ['data_type', 'data_source', 'alerts', 'export', 'refresh']
    },
    'rh': {
        'questions': [
            "Combien d'employés tu vas gérer ?",
            'Tu veux gérer les fiches de paie ?',
            'Gestion des congés et absences nécessaire ?',
            'Tu veux un portail employé self-service ?',
            'Suivi des évaluations annuelles ?'
        ],
        'slots': ['employee_count', 'payroll', 'leaves', 'portal', 'reviews']
    },
    'general': {
        'questions': [
            'Peux-tu me décrire plus précisément ce que tu veux faire ?',
            "C'est pour usage personnel ou professionnel ?",
            'Tu as une préférence technologique (Python, Node.js...) ?',
            "Combien d'utilisateurs vont utiliser cette app ?",
            "Tu as besoin d'une interface web ou juste une API ?"
        ],
        'slots': ['description', 'usage', 'tech', 'users', 'interface']
    }
}

DOMAIN_KEYWORDS = {
    'finance': ['facture', 'facturation', 'comptabilité', 'devis', 'paiement', 'tva', 'avoir', 'finance'],
    'ecommerce': ['boutique', 'shop', 'vente', 'produit', 'panier', 'commande', 'catalogue', 'ecommerce'],
    'saas': ['saas', 'abonnement', 'subscription', 'plan', 'tenant', 'mrr', 'billing'],
    'crm': ['crm', 'prospect', 'lead', 'commercial', 'pipeline', 'contact', 'client'],
    'dashboard': ['dashboard', 'tableau de bord', 'analytics', 'statistiques', 'graphique', 'kpi'],
    'rh': ['rh', 'employ', 'paie', 'cong', 'contrat', 'recrutement', 'ressources humaines'],
}

EXPERT_FOR_DOMAIN = {
    'finance': 'EXPERT_FINANCE',
    'ecommerce': 'EXPERT_ECOMMERCE',
    'saas': 'EXPERT_SAAS',
    'crm': 'EXPERT_CRM',
    'dashboard': 'EXPERT_DASHBOARD',
    'rh': 'EXPERT_RH',
    'general': 'EXPERT_PYTHON'
}

EXPERT_ROLES = {
    'EXPERT_FINANCE': 'Tu es un expert en logiciels de facturation et gestion financière pour PME. Tu poses des questions précises, tu conseilles sur les fonctionnalités essentielles, et tu construis progressivement un cahier des charges complet. Tu es chaleureux et professionnel.',
    'EXPERT_ECOMMERCE': "Tu es un expert en e-commerce et boutiques en ligne. Tu connais Stripe, la gestion catalogue, le checkout. Tu poses des questions pour comprendre le besoin exact et proposes des solutions adaptées.",
    'EXPERT_SAAS': 'Tu es un expert SaaS et modèles par abonnement. Tu maîtrises Stripe Billing, multi-tenancy, métriques SaaS. Tu aides à définir les plans et fonctionnalités clés.',
    'EXPERT_CRM': 'Tu es un expert CRM et gestion commerciale. Tu aides à définir les workflows de vente, la gestion des contacts et les rapports commerciaux.',
    'EXPERT_DASHBOARD': 'Tu es un expert tableaux de bord et analytics. Tu aides à identifier les bonnes métriques et à concevoir une interface claire et utile.',
    'EXPERT_RH': "Tu es un expert logiciels RH. Tu connais la législation du travail française, la gestion des congés, les fiches de paie. Tu poses des questions précises sur le contexte RH.",
    'EXPERT_PYTHON': "Tu es un assistant développeur senior. Tu aides à clarifier les besoins techniques et fonctionnels pour générer la meilleure application possible."
}


class ConversationState:
    STATE_FILE = Path('.cyberia/conversation_context.json')

    def __init__(self):
        self.state = self._load()

    def _load(self) -> dict:
        if self.STATE_FILE.exists():
            try:
                return json.loads(self.STATE_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        return self._default_state()

    def _default_state(self) -> dict:
        return {
            'mode': 'CHAT',
            'domain': 'general',
            'expert_assigned': 'EXPERT_PYTHON',
            'confirmed_features': [],
            'rejected_features': [],
            'preferences': {},
            'slots_filled': {},
            'questions_asked': [],
            'current_question_index': 0,
            'cdc_ready': False,
            'ready_to_generate': False,
            'messages': [],
            'created_at': datetime.now().isoformat()
        }

    def save(self):
        self.STATE_FILE.parent.mkdir(exist_ok=True)
        self.STATE_FILE.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def reset(self):
        self.state = self._default_state()
        self.save()
        return 'Conversation reinitalisee. Dis-moi ce que tu veux creer !'

    def detect_domain(self, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[domain] = score
        if scores:
            return max(scores, key=scores.get)
        return 'general'

    def add_message(self, role: str, content: str):
        self.state['messages'].append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        if len(self.state['messages']) > 20:
            self.state['messages'] = self.state['messages'][-20:]

    def update_domain(self, text: str):
        domain = self.detect_domain(text)
        if domain != 'general' or self.state['domain'] == 'general':
            self.state['domain'] = domain
            self.state['expert_assigned'] = EXPERT_FOR_DOMAIN.get(domain, 'EXPERT_PYTHON')

    def add_feature(self, feature: str, confirmed: bool = True):
        if confirmed:
            if feature not in self.state['confirmed_features']:
                self.state['confirmed_features'].append(feature)
            if feature in self.state['rejected_features']:
                self.state['rejected_features'].remove(feature)
        else:
            if feature not in self.state['rejected_features']:
                self.state['rejected_features'].append(feature)
            if feature in self.state['confirmed_features']:
                self.state['confirmed_features'].remove(feature)

    def get_next_question(self):
        domain = self.state['domain']
        slots_config = DOMAIN_SLOTS.get(domain, DOMAIN_SLOTS['general'])
        questions = slots_config['questions']
        idx = self.state['current_question_index']
        if idx < len(questions):
            self.state['questions_asked'].append(questions[idx])
            self.state['current_question_index'] += 1
            return questions[idx]
        return None

    def build_cdc_from_state(self) -> str:
        domain = self.state['domain']
        expert = self.state['expert_assigned']
        features = self.state['confirmed_features']
        prefs = self.state['preferences']
        messages_context = '\n'.join([
            f"{m['role']}: {m['content']}"
            for m in self.state['messages'][-10:]
        ])
        cdc = f'Domaine : {domain}\n'
        cdc += f'Expert : {expert}\n'
        if features:
            cdc += f'Fonctionnalites confirmees : {", ".join(features)}\n'
        if prefs:
            cdc += f'Preferences : {json.dumps(prefs, ensure_ascii=False)}\n'
        cdc += f'Contexte conversation :\n{messages_context}'
        return cdc

    def get_status(self) -> str:
        return (
            f'Mode : {self.state["mode"]} | '
            f'Domaine : {self.state["domain"]} | '
            f'Expert : {self.state["expert_assigned"]} | '
            f'Fonctionnalites : {len(self.state["confirmed_features"])}'
        )


if __name__ == '__main__':
    state = ConversationState()
    tests = [
        ('je veux une app de facturation', 'finance'),
        ('boutique en ligne avec panier', 'ecommerce'),
        ('logiciel crm pour mes prospects', 'crm'),
        ('dashboard avec kpi et graphiques', 'dashboard'),
        ('gestion des employes et conges', 'rh'),
        ('saas avec abonnement mensuel', 'saas'),
        ('je veux un projet web', 'general'),
    ]
    print('=== Test detect_domain ===')
    for text, expected in tests:
        result = state.detect_domain(text)
        status = 'OK' if result == expected else 'FAIL'
        print(f'  [{status}] "{text}" -> {result} (expected: {expected})')
