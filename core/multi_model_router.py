import os
import time
import random
from openai import OpenAI
from enum import Enum


class ModelProfile(str, Enum):
    CHAT = 'deepseek-chat'
    REASONER = 'deepseek-reasoner'


REASONER_TRIGGERS = {
    'min_prompt_tokens': 500,
    'keywords': [
        'architecture', 'conception', 'système complexe', 'optimise',
        'debug', 'analyse multi-fichiers', 'décompose', 'planifie',
        'pourquoi', 'comment résoudre', 'stratégie', 'décide'
    ],
    'task_types': ['architecture', 'debug', 'planning', 'analysis']
}


class MultiModelRouter:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv('DEEPSEEK_API_KEY'),
            base_url='https://api.deepseek.com'
        )
        self.stats = {'chat_calls': 0, 'reasoner_calls': 0}

    def select_model(self, prompt: str, task_type: str = 'code', force: str = None) -> ModelProfile:
        if force:
            return ModelProfile(force)

        if task_type in REASONER_TRIGGERS['task_types']:
            return ModelProfile.REASONER

        prompt_tokens_approx = len(prompt) // 4
        if prompt_tokens_approx > REASONER_TRIGGERS['min_prompt_tokens']:
            prompt_lower = prompt.lower()
            keyword_hits = sum(1 for kw in REASONER_TRIGGERS['keywords'] if kw in prompt_lower)
            if keyword_hits >= 2:
                return ModelProfile.REASONER

        return ModelProfile.CHAT

    def call(self, prompt: str, system: str = '', task_type: str = 'code',
             temperature: float = 0.2, streaming: bool = False, force_model: str = None) -> str:
        model = self.select_model(prompt, task_type, force_model)
        model_suffix = model.value.split('-')[1]
        self.stats[f'{model_suffix}_calls'] += 1
        label = 'Reasoner' if model == ModelProfile.REASONER else 'Chat'
        print(f'  [{label}]', end=' ', flush=True)

        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        for attempt in range(5):
            try:
                if streaming:
                    response = self.client.chat.completions.create(
                        model=model.value, messages=messages,
                        temperature=temperature, max_tokens=4000, stream=True
                    )
                    full = ''
                    for chunk in response:
                        delta = chunk.choices[0].delta.content or ''
                        if delta:
                            print(delta, end='', flush=True)
                            full += delta
                    print()
                    return full
                else:
                    response = self.client.chat.completions.create(
                        model=model.value, messages=messages,
                        temperature=temperature, max_tokens=4000
                    )
                    return response.choices[0].message.content
            except Exception as e:
                if attempt == 4:
                    return f'Erreur : {e}'
                time.sleep(2 ** attempt + random.random())
        return ''

    def search_and_answer(self, question, context=''):
        from core.web_search import safe_search
        search_result = safe_search(question)
        if '[WEB_SEARCH_UNAVAILABLE]' in search_result:
            enriched = f'Contexte: {context[:500]}\nQuestion: {question}'
        else:
            enriched = f'Resultat recherche web:\n{search_result}\n\nContexte: {context[:500]}\nQuestion: {question}'
        return self.call(enriched, task_type='analysis')

    def get_stats(self) -> dict:
        total = self.stats['chat_calls'] + self.stats['reasoner_calls']
        return {
            **self.stats,
            'total': total,
            'reasoner_ratio': round(self.stats['reasoner_calls'] / max(total, 1) * 100, 1)
        }


def select_model(task_type: str, context_size: int = 0) -> str:
    if task_type in ('architecture', 'debugging', 'analysis'):
        return 'deepseek-reasoner'
    return 'deepseek-chat'


_router = None


def get_router() -> MultiModelRouter:
    global _router
    if _router is None:
        _router = MultiModelRouter()
    return _router


if __name__ == '__main__':
    router = MultiModelRouter()
    print('MultiModelRouter initialisé')
    print(f'Stats : {router.get_stats()}')
    print(f'Modèle pour "code" : {router.select_model("Hello", "code")}')
    print(f'Modèle pour "planning" : {router.select_model("Décompose et planifie cette architecture complexe", "planning")}')
