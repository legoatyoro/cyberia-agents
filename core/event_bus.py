import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

class Event:
    def __init__(self, event_type: str, source: str, payload: dict):
        self.event_type = event_type
        self.source = source
        self.payload = payload
        self.timestamp = datetime.now().isoformat()
        self.id = f'{source}_{event_type}_{datetime.now().strftime("%H%M%S%f")}'

    def to_dict(self) -> dict:
        return {'id': self.id, 'type': self.event_type, 'source': self.source,
                'payload': self.payload, 'timestamp': self.timestamp}

EVENT_TYPES = {
    'FILE_GENERATED': 'Un fichier a été généré par BUILDER',
    'VALIDATION_ERROR': 'Une erreur de validation a été détectée',
    'FIX_APPLIED': 'Un fix a été appliqué par FIXER',
    'FIX_SUCCESS': 'Un fix a fonctionné — à mémoriser',
    'AGENT_CREATED': 'Un nouvel agent a été créé',
    'PATTERN_LEARNED': 'Un nouveau pattern d\'erreur a été appris',
    'GENERATION_COMPLETE': 'La génération d\'un projet est terminée',
    'SERVER_STARTED': 'Le serveur du projet a démarré',
    'SERVER_FAILED': 'Le serveur du projet a échoué',
    'COMPONENT_SAVED': 'Un composant validé a été sauvegardé',
    'RESEARCHER_UPDATE': 'Le RESEARCHER a mis à jour sa base',
}

class InMemoryEventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._history: list[dict] = []
        self._log_path = Path('.cyberia/event_log.jsonl')
        self._log_path.parent.mkdir(exist_ok=True)

    def subscribe(self, event_type: str, handler: Callable):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable):
        self.subscribe('*', handler)

    def publish(self, event: Event):
        self._history.append(event.to_dict())
        try:
            with open(self._log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + '\n')
        except Exception:
            pass
        handlers = self._subscribers.get(event.event_type, []) + self._subscribers.get('*', [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                print(f'  ⚠️ EventBus handler error : {e}')

    def get_history(self, event_type: str = None, limit: int = 50) -> list:
        if event_type:
            return [e for e in self._history if e['type'] == event_type][-limit:]
        return self._history[-limit:]

    def get_stats(self) -> dict:
        from collections import Counter
        types = Counter(e['type'] for e in self._history)
        return {'total_events': len(self._history), 'by_type': dict(types)}

_bus = None
def get_bus() -> InMemoryEventBus:
    global _bus
    if _bus is None:
        _bus = InMemoryEventBus()
    return _bus

def publish(event_type: str, source: str, payload: dict = None):
    get_bus().publish(Event(event_type, source, payload or {}))

def subscribe(event_type: str, handler: Callable):
    get_bus().subscribe(event_type, handler)
