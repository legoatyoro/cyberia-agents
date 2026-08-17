from core.llm_client import LLMClient
from schemas.agent_schemas import TaskType, AgentOutput

class CDCGeneratorAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'CDC_GENERATOR'

    def is_simple_phrase(self, text: str) -> bool:
        return len(text.split()) < 20 and '\n' not in text

    def run(self, input_text: str) -> tuple[AgentOutput, str]:
        if not self.is_simple_phrase(input_text):
            return AgentOutput(
                agent_name=self.name,
                success=True,
                artifacts={'cdc': input_text, 'enriched': False}
            ), input_text

        print(f'📝 [{self.name}] Enrichissement du CDC depuis : {input_text[:60]}...')
        prompt = f'''Tu reçois une phrase décrivant une application.
Génère un cahier des charges complet en français.

Phrase : {input_text}

Structure obligatoire :
1. NOM DU PROJET (snake_case)
2. DESCRIPTION (3-5 phrases)
3. FONCTIONNALITÉS (minimum 8, numérotées)
4. STACK TECHNIQUE (backend, DB, frontend, auth, tests)
5. MODÈLES DE DONNÉES (champs + types)
6. ROUTES API (méthode + chemin + description)
7. INTERFACE UTILISATEUR (pages et composants)
8. CONTRAINTES (sécurité, performance, compatibilité)

Réponds uniquement avec le CDC structuré, sans introduction.'''

        cdc = self.llm.call(TaskType.ARCHITECTURE, prompt)
        print(f'  ✅ CDC enrichi ({len(cdc.split())} mots)')
        return AgentOutput(
            agent_name=self.name,
            success=True,
            artifacts={'cdc': cdc, 'enriched': True, 'original': input_text}
        ), cdc
