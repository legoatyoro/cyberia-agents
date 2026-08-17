import re
from pathlib import Path
from enum import Enum

class Intent(str, Enum):
    CREATE = 'create'
    IMPROVE = 'improve'
    FIX = 'fix'
    QUESTION = 'question'
    COMMAND = 'command'
    ANALYZE = 'analyze'

INTENT_RULES = {
    Intent.COMMAND: ['/fix', '/status', '/retry', '/help', '/autopilot', '/sandbox'],
    Intent.CREATE: ['crée', 'cree', 'génère', 'genere', 'nouvelle app', 'nouveau projet', 'build', 'create', 'construis', 'développe', 'developpe', 'fais une', 'fais un'],
    Intent.IMPROVE: ['améliore', 'ameliore', 'ajoute', 'modifie', 'refactor', 'upgrade', 'étend', 'etend', 'enrichis', 'optimise', 'mets à jour'],
    Intent.FIX: ['corrige', 'fix', 'répare', 'repare', 'bug', 'erreur', 'error', 'problème', 'probleme', 'cassé', 'casse', 'marche pas'],
    Intent.QUESTION: ['pourquoi', 'comment', 'qu est ce', 'c est quoi', 'explique', 'quel est', 'quelle est', 'dis moi', 'what', 'why', 'how'],
    Intent.ANALYZE: ['analyse', 'inspecte', 'vérifie', 'verifie', 'scan', 'audite', 'regarde', 'montre moi'],
}

def normalize(text: str) -> str:
    text = text.lower().strip()
    for a, b in [('é','e'),('è','e'),('ê','e'),('à','a'),('ô','o'),('û','u'),('î','i'),('ù','u'),("'", ' ')]:
        text = text.replace(a, b)
    return text

def detect_project_reference(text: str) -> str | None:
    generated = Path('generated')
    if generated.exists():
        for p in generated.iterdir():
            if p.is_dir() and p.name.lower().replace('-','_') in normalize(text).replace('-','_'):
                return p.name
    return None

def detect_file_reference(text: str) -> str | None:
    match = re.search(r'[\w/\-]+\.(py|ts|tsx|js|json|yml|yaml|html|css|md)', text)
    return match.group(0) if match else None

def classify_intent(user_input: str) -> dict:
    norm = normalize(user_input)
    words = norm.split()

    for keyword in INTENT_RULES[Intent.COMMAND]:
        if norm.startswith(keyword):
            return {'intent': Intent.COMMAND, 'command': keyword, 'raw': user_input}

    project_ref = detect_project_reference(norm)
    file_ref = detect_file_reference(user_input)

    scores = {intent: 0 for intent in Intent}
    for intent, keywords in INTENT_RULES.items():
        if intent == Intent.COMMAND:
            continue
        for kw in keywords:
            if kw in norm:
                scores[intent] += 2 if norm.startswith(kw) else 1

    if project_ref:
        scores[Intent.IMPROVE] += 3
    if file_ref:
        scores[Intent.FIX] += 2
        scores[Intent.ANALYZE] += 1
    # Short-phrase bonus for CREATE only when no other intent has a signal yet
    other_signal = any(scores[i] > 0 for i in Intent if i not in (Intent.CREATE, Intent.COMMAND))
    if len(words) < 8 and not project_ref and not other_signal:
        scores[Intent.CREATE] += 2

    best = max(scores, key=lambda x: scores[x])
    confidence = scores[best]

    return {
        'intent': best,
        'confidence': confidence,
        'project_ref': project_ref,
        'file_ref': file_ref,
        'raw': user_input,
        'is_simple_phrase': len(words) < 15
    }

def run_tests():
    tests = [
        ('crée une app de facturation', Intent.CREATE),
        ('améliore le projet facturation_pme', Intent.IMPROVE),
        ('corrige le bug dans main.py', Intent.FIX),
        ('comment fonctionne SQLAlchemy ?', Intent.QUESTION),
        ('/status', Intent.COMMAND),
        ('analyse mon projet', Intent.ANALYZE),
    ]
    for text, expected in tests:
        result = classify_intent(text)
        status = '✅' if result['intent'] == expected else '❌'
        print(f'{status} [{expected}] {text} → {result["intent"]}')

if __name__ == '__main__':
    run_tests()
