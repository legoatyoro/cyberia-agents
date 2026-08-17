import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import networkx as nx
from pydantic import BaseModel, Field

from core.event_bus import EventBus, Event, EventType
from schemas.agent_schemas import AgentOutput, AgentStatus

logger = logging.getLogger(__name__)

class TaskNode(BaseModel):
    """Représente une sous-tâche dans le graphe de tâches"""
    task_id: str
    agent_type: str
    description: str
    dependencies: List[str] = Field(default_factory=list)
    status: str = "pending"
    timeout: int = 30
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[Any] = None

class TaskGraph(BaseModel):
    """Graphe de tâches complet"""
    query: str
    nodes: Dict[str, TaskNode] = Field(default_factory=dict)
    edges: List[tuple] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)

class PlannerAgent:
    """Agent planificateur qui décompose et orchestre les tâches de recherche"""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.task_graph: Optional[TaskGraph] = None
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._subscribed = False
        
    async def run(self, user_query: str) -> AgentOutput:
        """Méthode principale pour exécuter l'agent planificateur"""
        try:
            logger.info(f"PlannerAgent démarré avec la requête: {user_query}")
            
            # 1. Analyser et décomposer la requête
            task_graph = await self._decompose_query(user_query)
            
            # 2. Identifier les dépendances
            task_graph = await self._identify_dependencies(task_graph)
            
            # 3. Valider le graphe
            if not self._validate_task_graph(task_graph):
                raise ValueError("Graphe de tâches invalide")
            
            # 4. Publier l'événement TASK_GRAPH_READY
            await self._publish_task_graph_ready(task_graph)
            
            # 5. Ordonnancer l'exécution
            await self._schedule_execution(task_graph)
            
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                data=task_graph.dict(),
                message="Planification réussie"
            )
            
        except Exception as e:
            logger.error(f"Erreur dans PlannerAgent: {str(e)}")
            await self._publish_planning_failed(str(e))
            return AgentOutput(
                status=AgentStatus.FAILED,
                data={},
                message=f"Échec de la planification: {str(e)}"
            )
    
    async def _decompose_query(self, query: str) -> TaskGraph:
        """Décompose la requête utilisateur en sous-tâches"""
        task_graph = TaskGraph(query=query)
        
        # Analyse basique de la requête pour créer des sous-tâches
        # Dans un cas réel, cela utiliserait du NLP ou des règles plus sophistiquées
        keywords = query.lower().split()
        
        # Création des tâches basées sur les mots-clés
        if any(word in keywords for word in ["système", "systèmes", "network", "réseau"]):
            # Tâche d'extraction
            task_graph.nodes["extract_1"] = TaskNode(
                task_id="extract_1",
                agent_type="EXTRACTOR_AGENT",
                description=f"Extraire les informations sur: {query}"
            )
            
            # Tâche d'analyse
            task_graph.nodes["analyze_1"] = TaskNode(
                task_id="analyze_1",
                agent_type="ANALYZER_AGENT",
                description=f"Analyser les données extraites pour: {query}",
                dependencies=["extract_1"]
            )
            
            # Tâche de synthèse
            task_graph.nodes["synthesize_1"] = TaskNode(
                task_id="synthesize_1",
                agent_type="SYNTHESIZER_AGENT",
                description=f"Synthétiser les résultats pour: {query}",
                dependencies=["analyze_1"]
            )
            
            # Ajouter les arêtes
            task_graph.edges = [
                ("extract_1", "analyze_1"),
                ("analyze_1", "synthesize_1")
            ]
        
        return task_graph
    
    async def _identify_dependencies(self, task_graph: TaskGraph) -> TaskGraph:
        """Identifie et valide les dépendances entre les tâches"""
        # Créer un graphe NetworkX pour l'analyse
        G = nx.DiGraph()
        
        # Ajouter les nœuds
        for node_id, node in task_graph.nodes.items():
            G.add_node(node_id)
        
        # Ajouter les arêtes
        for edge in task_graph.edges:
            G.add_edge(edge[0], edge[1])
        
        # Vérifier les cycles
        try:
            cycles = list(nx.simple_cycles(G))
            if cycles:
                raise ValueError(f"Cycles détectés dans le graphe de tâches: {cycles}")
        except nx.NetworkXNoCycle:
            pass
        
        # Identifier les tâches parallélisables (sans dépendances)
        parallel_tasks = [node_id for node_id, node in task_graph.nodes.items() 
                         if not node.dependencies]
        
        logger.info(f"Tâches parallélisables: {parallel_tasks}")
        
        return task_graph
    
    def _validate_task_graph(self, task_graph: TaskGraph) -> bool:
        """Valide l'intégrité du graphe de tâches"""
        if not task_graph.nodes:
            logger.warning("Graphe de tâches vide")
            return False
        
        # Vérifier que toutes les dépendances existent
        for node_id, node in task_graph.nodes.items():
            for dep in node.dependencies:
                if dep not in task_graph.nodes:
                    logger.error(f"Dépendance manquante: {dep} pour {node_id}")
                    return False
        
        return True
    
    async def _publish_task_graph_ready(self, task_graph: TaskGraph):
        """Publie l'événement TASK_GRAPH_READY"""
        event = Event(
            type=EventType.TASK_GRAPH_READY,
            data=task_graph.dict(),
            source="PLANNER_AGENT",
            timestamp=datetime.now()
        )
        await self.event_bus.publish(event)
        logger.info("Événement TASK_GRAPH_READY publié")
    
    async def _publish_planning_failed(self, error_message: str):
        """Publie l'événement PLANNING_FAILED"""
        event = Event(
            type=EventType.PLANNING_FAILED,
            data={"error": error_message},
            source="PLANNER_AGENT",
            timestamp=datetime.now()
        )
        await self.event_bus.publish(event)
        logger.error(f"Événement PLANNING_FAILED publié: {error_message}")
    
    async def _schedule_execution(self, task_graph: TaskGraph):
        """Ordonnance l'exécution des tâches selon leurs dépendances"""
        # Créer un ordre topologique pour l'exécution
        G = nx.DiGraph()
        for node_id in task_graph.nodes:
            G.add_node(node_id)
        for edge in task_graph.edges:
            G.add_edge(edge[0], edge[1])
        
        try:
            execution_order = list(nx.topological_sort(G))
            logger.info(f"Ordre d'exécution: {execution_order}")
            
            # Stocker le graphe pour référence future
            self.task_graph = task_graph
            
            # Démarrer l'exécution des tâches
            for task_id in execution_order:
                task_node = task_graph.nodes[task_id]
                asyncio.create_task(self._execute_task_with_retry(task_node))
                
        except nx.NetworkXUnfeasible:
            logger.error("Impossible de déterminer un ordre d'exécution topologique")
            raise
    
    async def _execute_task_with_retry(self, task_node: TaskNode):
        """Exécute une tâche avec mécanisme de retry"""
        while task_node.retry_count < task_node.max_retries:
            try:
                # Simuler l'exécution de la tâche
                logger.info(f"Exécution de la tâche {task_node.task_id} (tentative {task_node.retry_count + 1})")
                
                # Publier l'événement pour l'agent concerné
                event = Event(
                    type=EventType.TASK_STARTED,
                    data=task_node.dict(),
                    source="PLANNER_AGENT",
                    timestamp=datetime.now()
                )
                await self.event_bus.publish(event)
                
                # Attendre la complétion (simulé)
                await asyncio.sleep(1)
                
                # Marquer comme complété
                task_node.status = "completed"
                logger.info(f"Tâche {task_node.task_id} complétée avec succès")
                return
                
            except asyncio.TimeoutError:
                task_node.retry_count += 1
                logger.warning(f"Timeout pour la tâche {task_node.task_id}, tentative {task_node.retry_count}")
                
                if task_node.retry_count >= task_node.max_retries:
                    task_node.status = "failed"
                    logger.error(f"Tâche {task_node.task_id} a échoué après {task_node.max_retries} tentatives")
                    
                    # Publier l'échec
                    await self._publish_task_failed(task_node)
                    return
                
                # Attendre avant de réessayer
                await asyncio.sleep(2 ** task_node.retry_count)  # Exponential backoff
                
            except Exception as e:
                logger.error(f"Erreur inattendue pour la tâche {task_node.task_id}: {str(e)}")
                task_node.status = "failed"
                await self._publish_task_failed(task_node)
                return
    
    async def _publish_task_failed(self, task_node: TaskNode):
        """Publie l'événement TASK_FAILED"""
        event = Event(
            type=EventType.TASK_FAILED,
            data=task_node.dict(),
            source="PLANNER_AGENT",
            timestamp=datetime.now()
        )
        await self.event_bus.publish(event)
        logger.error(f"Événement TASK_FAILED publié pour {task_node.task_id}")
    
    async def handle_event(self, event: Event):
        """Gère les événements reçus du bus d'événements"""
        if event.type == EventType.USER_QUERY_RECEIVED:
            query = event.data.get("query", "")
            await self.run(query)
            
        elif event.type == EventType.TASK_COMPLETED:
            task_id = event.data.get("task_id")
            if task_id and self.task_graph:
                if task_id in self.task_graph.nodes:
                    self.task_graph.nodes[task_id].status = "completed"
                    self.task_graph.nodes[task_id].result = event.data.get("result")
                    logger.info(f"Tâche {task_id} marquée comme complétée")
                    
        elif event.type == EventType.TASK_FAILED:
            task_id = event.data.get("task_id")
            if task_id and self.task_graph:
                if task_id in self.task_graph.nodes:
                    self.task_graph.nodes[task_id].status = "failed"
                    logger.error(f"Tâche {task_id} marquée comme échouée")
    
    async def subscribe_to_events(self):
        """S'abonne aux événements nécessaires"""
        if not self._subscribed:
            await self.event_bus.subscribe(EventType.USER_QUERY_RECEIVED, self.handle_event)
            await self.event_bus.subscribe(EventType.TASK_COMPLETED, self.handle_event)
            await self.event_bus.subscribe(EventType.TASK_FAILED, self.handle_event)
            self._subscribed = True
            logger.info("PlannerAgent abonné aux événements")
    
    async def cleanup(self):
        """Nettoie les ressources de l'agent"""
        if self._subscribed:
            await self.event_bus.unsubscribe(EventType.USER_QUERY_RECEIVED, self.handle_event)
            await self.event_bus.unsubscribe(EventType.TASK_COMPLETED, self.handle_event)
            await self.event_bus.unsubscribe(EventType.TASK_FAILED, self.handle_event)
            self._subscribed = False
        
        # Annuler les tâches en cours
        for task in self._running_tasks.values():
            task.cancel()
        
        logger.info("PlannerAgent nettoyé")