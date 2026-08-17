import os, time, random
from openai import OpenAI
from schemas.agent_schemas import TaskType, LLMProfile

PROFILES = {
    TaskType.CODE: LLMProfile(temperature=0.2, max_tokens=4000, system_prompt='Tu es un developpeur Python senior. Genere uniquement du code propre, sans markdown, sans explication.'),
    TaskType.ARCHITECTURE: LLMProfile(temperature=0.7, max_tokens=3000, system_prompt='Tu es un architecte logiciel. Reponds uniquement en JSON valide.'),
    TaskType.DOC: LLMProfile(temperature=0.7, max_tokens=3000, system_prompt='Tu es un redacteur technique. Genere de la documentation claire et complete en markdown.'),
    TaskType.FIX: LLMProfile(temperature=0.2, max_tokens=4000, system_prompt='Tu es un debogueur expert. Corrige uniquement ce qui est demande, sans toucher au reste.'),
    TaskType.SECURITY: LLMProfile(temperature=0.3, max_tokens=2000, system_prompt='Tu es un expert securite. Analyse et liste les failles.'),
    TaskType.TEST: LLMProfile(temperature=0.2, max_tokens=3000, system_prompt='Tu es un expert QA. Genere des tests pytest complets et corrects.'),
    TaskType.DEPLOY: LLMProfile(temperature=0.4, max_tokens=2000, system_prompt='Tu es un expert DevOps. Genere des fichiers de deploiement optimises.')
}

# Routeur multi-providers avec fallback automatique
PROVIDERS = [
    {
        "name": "openrouter_sonnet",
        "client": OpenAI(
            api_key=os.getenv('OPENROUTER_API_KEY', ''),
            base_url='https://openrouter.ai/api/v1'
        ),
        "model": "anthropic/claude-sonnet-4-6",
        "use_for": [TaskType.CODE, TaskType.FIX, TaskType.ARCHITECTURE]
    },
    {
        "name": "openrouter_deepseek",
        "client": OpenAI(
            api_key=os.getenv('OPENROUTER_API_KEY', ''),
            base_url='https://openrouter.ai/api/v1'
        ),
        "model": "deepseek/deepseek-chat-v3-0324",
        "use_for": [TaskType.SECURITY, TaskType.DOC, TaskType.TEST, TaskType.DEPLOY]
    },
    {
        "name": "together_qwen",
        "client": OpenAI(
            api_key=os.getenv('TOGETHER_API_KEY', ''),
            base_url='https://api.together.xyz/v1'
        ),
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "use_for": [TaskType.CODE, TaskType.FIX]
    },
    {
        "name": "deepseek_direct",
        "client": OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY', ''),
            base_url='https://api.deepseek.com'
        ),
        "model": "deepseek-chat",
        "use_for": list(TaskType)
    }
]

def _get_providers_for(task_type):
    """Retourne les providers tries par priorite pour ce type de tache"""
    primary = [p for p in PROVIDERS if task_type in p.get("use_for", [])]
    fallback = [p for p in PROVIDERS if task_type not in p.get("use_for", [])]
    return primary + fallback

class LLMClient:
    def __init__(self):
        pass  # Pas de client unique  routage dynamique

    def _call_provider(self, provider, profile, user_prompt, temp):
        response = provider["client"].chat.completions.create(
            model=provider["model"],
            messages=[
                {'role': 'system', 'content': profile.system_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            temperature=temp,
            max_tokens=profile.max_tokens
        )
        return response.choices[0].message.content

    def call(self, task_type: TaskType, user_prompt: str, temperature_override: float = None, max_retries: int = 3) -> str:
        profile = PROFILES[task_type]
        temp = temperature_override if temperature_override is not None else profile.temperature
        providers = _get_providers_for(task_type)
        for provider in providers:
            if not provider["client"].api_key:
                continue
            for attempt in range(max_retries):
                try:
                    result = self._call_provider(provider, profile, user_prompt, temp)
                    print(f'  [ROUTER] {provider["name"]} -> OK')
                    return result
                except Exception as e:
                    err = str(e)[:60]
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) + random.random()
                        print(f'  [ROUTER] {provider["name"]} erreur ({err}) retry {attempt+1}...')
                        time.sleep(wait)
                    else:
                        print(f'  [ROUTER] {provider["name"]} abandonne -> fallback')
                        break
        raise RuntimeError("Tous les providers LLM ont echoue")

    def stream(self, task_type, user_prompt: str, temperature_override=None) -> str:
        profile = PROFILES[task_type]
        temp = temperature_override if temperature_override is not None else profile.temperature
        providers = _get_providers_for(task_type)
        for provider in providers:
            if not provider["client"].api_key:
                continue
            try:
                response = provider["client"].chat.completions.create(
                    model=provider["model"],
                    messages=[
                        {'role': 'system', 'content': profile.system_prompt},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    temperature=temp,
                    max_tokens=profile.max_tokens,
                    stream=True
                )
                full = ''
                for chunk in response:
                    delta = chunk.choices[0].delta.content or ''
                    print(delta, end='', flush=True)
                    full += delta
                print()
                return full
            except Exception as e:
                print(f'  [ROUTER] {provider["name"]} stream erreur -> fallback')
                continue
        raise RuntimeError("Tous les providers stream ont echoue")

    def call_with_stream(self, task_type, user_prompt: str, streaming: bool = False, temperature_override=None) -> str:
        if streaming:
            return self.stream(task_type, user_prompt, temperature_override)
        return self.call(task_type, user_prompt, temperature_override)

