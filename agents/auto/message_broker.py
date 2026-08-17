import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, AgentStatus

class RoutingTable(BaseModel):
    """Table de routage des agents"""
    agent_routes: Dict[str, str] = Field(default_factory=lambda: {
        "SPEECH_PARSER": "intent_parsed",
        "RESPONSE_GENERATOR": "response_ready"
    })
    
    def get_route(self, agent_name: str) -> Optional[str]:
        return self.agent_routes.get(agent_name)

class MessageQueue(BaseModel):
    """File d'attente des messages"""
    queue: asyncio.Queue = Field(default_factory=asyncio.Queue)
    timeout: float = Field(default=30.0)
    
    async def put_message(self, message: Dict[str, Any]):
        await self.queue.put(message)
    
    async def get_message(self) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=self.timeout)
        except asyncio.TimeoutError:
            return None

class MessageBrokerAgent:
    """Agent orchestrateur de distribution des messages"""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.routing_table = RoutingTable()
        self.message_queues: Dict[str, MessageQueue] = {}
        self.agent_status: Dict[str, AgentStatus] = {}
        self._running = False
        
    async def run(self) -> AgentOutput:
        """Méthode principale d'exécution de l'agent"""
        try:
            self._running = True
            print(f"[MESSAGE_BROKER] Agent démarré à {datetime.now()}")
            
            # Souscrire aux événements
            await self.event_bus.subscribe("INTENT_PARSED", self._handle_intent_parsed)
            await self.event_bus.subscribe("RESPONSE_READY", self._handle_response_ready)
            
            # Initialiser les files d'attente
            self.message_queues["SPEECH_PARSER"] = MessageQueue()
            self.message_queues["RESPONSE_GENERATOR"] = MessageQueue()
            
            # Boucle principale de traitement
            while self._running:
                await self._process_queues()
                await asyncio.sleep(0.1)  # Éviter la surcharge CPU
                
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                message="Agent MESSAGE_BROKER terminé avec succès",
                data={"routing_table": self.routing_table.dict()}
            )
            
        except Exception as e:
            print(f"[MESSAGE_BROKER] Erreur: {str(e)}")
            return AgentOutput(
                status=AgentStatus.ERROR,
                message=f"Erreur dans MESSAGE_BROKER: {str(e)}",
                data={"error": str(e)}
            )
        finally:
            self._running = False
            await self._cleanup()
    
    async def _handle_intent_parsed(self, event: Event):
        """Gère l'événement INTENT_PARSED"""
        try:
            print(f"[MESSAGE_BROKER] Événement INTENT_PARSED reçu: {event.data}")
            
            # Extraire les informations de l'événement
            message_data = event.data.get("message", {})
            intent = event.data.get("intent", "")
            entities = event.data.get("entities", {})
            
            # Déterminer l'agent destinataire
            target_agent = self._determine_target_agent(intent)
            
            if target_agent:
                # Ajouter à la file d'attente
                queue_message = {
                    "source": "SPEECH_PARSER",
                    "target": target_agent,
                    "intent": intent,
                    "entities": entities,
                    "original_message": message_data,
                    "timestamp": datetime.now().isoformat()
                }
                
                await self.message_queues[target_agent].put_message(queue_message)
                
                # Publier événement MESSAGE_FORWARDED
                await self.event_bus.publish(Event(
                    type="MESSAGE_FORWARDED",
                    data={
                        "message_id": event.data.get("message_id"),
                        "source": "MESSAGE_BROKER",
                        "target": target_agent,
                        "status": "queued",
                        "timestamp": datetime.now().isoformat()
                    }
                ))
                print(f"[MESSAGE_BROKER] Message forwardé vers {target_agent}")
            else:
                print(f"[MESSAGE_BROKER] Aucun agent trouvé pour l'intent: {intent}")
                
        except Exception as e:
            print(f"[MESSAGE_BROKER] Erreur traitement INTENT_PARSED: {str(e)}")
    
    async def _handle_response_ready(self, event: Event):
        """Gère l'événement RESPONSE_READY"""
        try:
            print(f"[MESSAGE_BROKER] Événement RESPONSE_READY reçu: {event.data}")
            
            # Publier événement MESSAGE_DELIVERED
            await self.event_bus.publish(Event(
                type="MESSAGE_DELIVERED",
                data={
                    "message_id": event.data.get("message_id"),
                    "response": event.data.get("response"),
                    "source": "RESPONSE_GENERATOR",
                    "status": "delivered",
                    "timestamp": datetime.now().isoformat()
                }
            ))
            print(f"[MESSAGE_BROKER] Message délivré avec succès")
            
        except Exception as e:
            print(f"[MESSAGE_BROKER] Erreur traitement RESPONSE_READY: {str(e)}")
    
    def _determine_target_agent(self, intent: str) -> Optional[str]:
        """Détermine l'agent destinataire basé sur l'intention"""
        # Logique de routage basée sur l'intention
        if intent in ["greeting", "farewell", "help"]:
            return "RESPONSE_GENERATOR"
        elif intent in ["question", "command"]:
            return "RESPONSE_GENERATOR"
        else:
            return "RESPONSE_GENERATOR"  # Par défaut
    
    async def _process_queues(self):
        """Traite les files d'attente des messages"""
        for agent_name, queue in self.message_queues.items():
            message = await queue.get_message()
            if message:
                print(f"[MESSAGE_BROKER] Traitement message pour {agent_name}: {message}")
                # Logique de traitement supplémentaire si nécessaire
    
    async def _cleanup(self):
        """Nettoie les ressources"""
        print("[MESSAGE_BROKER] Nettoyage des ressources...")
        # Désabonner des événements
        await self.event_bus.unsubscribe("INTENT_PARSED", self._handle_intent_parsed)
        await self.event_bus.unsubscribe("RESPONSE_READY", self._handle_response_ready)
        
        # Vider les files d'attente
        for queue in self.message_queues.values():
            while not queue.queue.empty():
                try:
                    queue.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        
        print("[MESSAGE_BROKER] Nettoyage terminé")
    
    async def stop(self):
        """Arrête l'agent proprement"""
        self._running = False
        print("[MESSAGE_BROKER] Arrêt demandé")