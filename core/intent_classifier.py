import json, re, os
from core.multi_model_router import MultiModelRouter

SYSTEM_PROMPT = '''Tu es le classificateur d intentions officiel de CYBERIA.
Analyse le message utilisateur et determine l intention parmi :
GENERATE_PROJECT, ANALYZE_PROJECT, FIX_ERRORS, ASK_QUESTION,
SHOW_PROJECTS, SWITCH_PROJECT, RUN_PROJECT, GENERATE_TESTS,
COUNCIL_AGENTS, EVOLUTION_MODE, SCAN_MODE, IMPORT_PROJECT,
DASHBOARD, MEMORY_QUERY, GENERAL_CHAT

Regles :
1. Reponds STRICTEMENT en JSON valide, sans texte autour.
2. Format exact :
{
  "intent": "GENERATE_PROJECT",
  "arguments": {"project_name": "api", "stack": "fastapi", "flags": []},
  "confidence": 0.92
}
3. Si pas sur -> intent: GENERAL_CHAT'''

FALLBACK_PATTERNS = {
    'GENERATE_PROJECT': ['genere', 'cree', 'nouveau projet', 'fais moi', 'construis', 'api', 'application', 'besoin d'],
    'ANALYZE_PROJECT': ['analyse', 'analyser', 'regarde', 'inspecte', 'score', 'verifie', 'lis le projet', 'analyse le resultat', 'voir le resultat', 'resultat', 'rapport', 'bilan', 'qualite'],
    'FIX_ERRORS': ['corrige', 'repare', 'fixe', 'bug', 'erreur', 'ne marche pas'],
    'SHOW_PROJECTS': ['projets', 'liste', 'mes projets', 'voir projets'],
    'RUN_PROJECT': ['lance', 'demarre', 'execute', 'start', 'run'],
    'GENERATE_TESTS': ['test', 'teste', 'pytest', 'valide'],
    'COUNCIL_AGENTS': ['conseil', 'avis', 'agents', 'debat'],
    'DASHBOARD': ['dashboard', 'tableau de bord', 'stats'],
    'MEMORY_QUERY': ['souviens', 'memoire', 'qui suis je', 'rappelle'],
    'IMPORT_PROJECT': ['importe', 'charge le projet', 'copie'],
    'EVOLUTION_MODE': ['ameliore toi', 'evolution', 'ton code', 'ameliore cyberia'],
    'SCAN_MODE': ['scan', 'auto scan', 'scanne'],
    'SWITCH_PROJECT': ['passe sur', 'change de projet', 'utilise le projet'],
}


def classify_intent(message: str, use_llm: bool = True) -> dict:
    if use_llm:
        try:
            router = MultiModelRouter()
            response = router.call(
                f'{SYSTEM_PROMPT}\n\nMessage utilisateur: {message}',
                task_type='analysis'
            )
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                result = json.loads(match.group())
                if 'intent' in result:
                    return result
        except Exception:
            pass

    text = message.lower()
    scores = {}
    for intent, keywords in FALLBACK_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[intent] = score

    if scores:
        best = max(scores, key=scores.get)
        return {'intent': best, 'arguments': {}, 'confidence': min(0.7, scores[best] * 0.2)}

    return {'intent': 'GENERAL_CHAT', 'arguments': {}, 'confidence': 0.5}
