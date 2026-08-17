import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from prometheus_client import Counter, Gauge, Histogram

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, AgentStatus, AgentError
from agents.planner_agent import PlannerAgent


# Prometheus metrics
SUPERVISOR_REQUESTS = Counter('supervisor_requests_total', 'Total supervisor requests')
SUPERVISOR_ERRORS = Counter('supervisor_errors_total', 'Total supervisor errors')
SUPERVISOR_HEALTH = Gauge('supervisor_health', 'Supervisor health status', ['agent'])
SUPERVISOR_PROCESSING_TIME = Histogram('supervisor_processing_seconds', 'Supervisor processing time')


class SupervisorAgent:
    """Agent superviseur responsable de la validation, surveillance et orchestration des agents."""

    def __init__(self, event_bus: EventBus, config: Optional[Dict[str, Any]] = None):
        self.event_bus = event_bus
        self.config = config or {}
        self.logger = structlog.get_logger(__name__)
        self.agent_id = f"supervisor-{uuid.uuid4().hex[:8]}"
        self.running = False
        self.health_status: Dict[str, Dict[str, Any]] = {}
        self.planner_agent: Optional[PlannerAgent] = None
        self._subscriptions: List[str] = []
        self._tasks: List[asyncio.Task] = []

    async def initialize(self) -> None:
        """Initialise l'agent et ses souscriptions aux événements."""
        self.logger.info("supervisor.initializing", agent_id=self.agent_id)
        
        # Souscrire aux événements
        self._subscriptions = [
            "REPORT_READY",
            "PLANNING_FAILED",
            "EXTRACTION_FAILED",
            "ANALYSIS_FAILED",
            "SYNTHESIS_FAILED"
        ]
        
        for event_type in self._subscriptions:
            await self.event_bus.subscribe(event_type, self._handle_event)
        
        # Initialiser le planner agent
        self.planner_agent = PlannerAgent(self.event_bus, self.config)
        await self.planner_agent.initialize()
        
        # Initialiser les métriques de santé
        SUPERVISOR_HEALTH.labels(agent='supervisor').set(1)
        SUPERVISOR_HEALTH.labels(agent='planner').set(1)
        
        self.running = True
        self.logger.info("supervisor.initialized", agent_id=self.agent_id)

    async def run(self, user_query: str) -> AgentOutput:
        """Point d'entrée principal pour traiter une requête utilisateur."""
        start_time = time.time()
        SUPERVISOR_REQUESTS.inc()
        
        execution_log = {
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "agent": self.agent_id,
            "event_type": "USER_QUERY_RECEIVED",
            "data": {
                "query": user_query,
                "query_length": len(user_query)
            }
        }
        
        try:
            # Valider la requête
            validation_result = self._validate_query(user_query)
            if not validation_result["valid"]:
                raise ValueError(validation_result["error"])
            
            # Publier l'événement de réception de requête
            await self.event_bus.publish(Event(
                type="USER_QUERY_RECEIVED",
                data={"query": user_query, "agent_id": self.agent_id}
            ))
            
            # Surveiller la santé des agents
            health_report = await self._check_agent_health()
            if not health_report["healthy"]:
                await self._handle_system_error(health_report)
                raise RuntimeError(f"System unhealthy: {health_report['errors']}")
            
            # Déléguer au planner agent
            planner_output = await self.planner_agent.run(user_query)
            
            # Attendre le résultat final (via event bus)
            final_report = await self._wait_for_report()
            
            # Générer le rapport final
            report = self._generate_final_report(final_report, user_query)
            
            # Journaliser le succès
            execution_log["event_type"] = "EXECUTION_SUCCESS"
            execution_log["data"]["report_length"] = len(report)
            execution_log["duration_seconds"] = time.time() - start_time
            
            SUPERVISOR_PROCESSING_TIME.observe(time.time() - start_time)
            
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                data={
                    "final_report_markdown": report,
                    "execution_log_json": json.dumps(execution_log, indent=2)
                },
                metadata={
                    "agent_id": self.agent_id,
                    "processing_time": time.time() - start_time,
                    "query": user_query
                }
            )
            
        except Exception as e:
            SUPERVISOR_ERRORS.inc()
            self.logger.error("supervisor.execution_failed", error=str(e))
            
            # Journaliser l'erreur
            execution_log["event_type"] = "SYSTEM_ERROR"
            execution_log["data"]["error"] = str(e)
            execution_log["duration_seconds"] = time.time() - start_time
            
            # Publier l'événement d'erreur
            await self.event_bus.publish(Event(
                type="SYSTEM_ERROR",
                data={"error": str(e), "agent_id": self.agent_id}
            ))
            
            return AgentOutput(
                status=AgentStatus.FAILURE,
                error=AgentError(
                    code="SUPERVISOR_ERROR",
                    message=str(e),
                    details={"query": user_query}
                ),
                data={
                    "final_report_markdown": f"# Erreur\n\nUne erreur est survenue lors du traitement : {str(e)}",
                    "execution_log_json": json.dumps(execution_log, indent=2)
                },
                metadata={
                    "agent_id": self.agent_id,
                    "processing_time": time.time() - start_time,
                    "query": user_query
                }
            )

    def _validate_query(self, query: str) -> Dict[str, Any]:
        """Valide la requête utilisateur."""
        if not query or not query.strip():
            return {"valid": False, "error": "La requête ne peut pas être vide"}
        
        if len(query) > 10000:
            return {"valid": False, "error": "La requête est trop longue (max 10000 caractères)"}
        
        # Vérifier les caractères dangereux
        dangerous_chars = ['<', '>', '|', ';', '&', '$']
        for char in dangerous_chars:
            if char in query:
                return {"valid": False, "error": f"Caractère non autorisé: {char}"}
        
        return {"valid": True, "error": None}

    async def _check_agent_health(self) -> Dict[str, Any]:
        """Vérifie la santé de tous les agents."""
        health_report = {
            "healthy": True,
            "errors": [],
            "agents": {}
        }
        
        # Vérifier le supervisor lui-même
        self.health_status["supervisor"] = {
            "status": "healthy",
            "last_heartbeat": datetime.utcnow().isoformat(),
            "queue_size": 0
        }
        
        # Vérifier le planner agent
        if self.planner_agent:
            planner_health = await self.planner_agent.health_check()
            self.health_status["planner"] = planner_health
            SUPERVISOR_HEALTH.labels(agent='planner').set(1 if planner_health["status"] == "healthy" else 0)
            
            if planner_health["status"] != "healthy":
                health_report["healthy"] = False
                health_report["errors"].append(f"Planner agent unhealthy: {planner_health.get('error', 'Unknown')}")
        
        health_report["agents"] = self.health_status
        return health_report

    async def _handle_system_error(self, health_report: Dict[str, Any]) -> None:
        """Gère les erreurs système et les escalades."""
        self.logger.error("supervisor.system_error", health_report=health_report)
        
        # Publier l'événement d'erreur système
        await self.event_bus.publish(Event(
            type="SYSTEM_ERROR",
            data={
                "health_report": health_report,
                "agent_id": self.agent_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        # Tentative de reprise
        recovery_success = await self._attempt_recovery(health_report)
        if not recovery_success:
            self.logger.critical("supervisor.recovery_failed", health_report=health_report)
            await self.event_bus.publish(Event(
                type="SHUTDOWN",
                data={"reason": "Recovery failed", "agent_id": self.agent_id}
            ))

    async def _attempt_recovery(self, health_report: Dict[str, Any]) -> bool:
        """Tente de récupérer après une erreur."""
        try:
            for agent_name, agent_health in health_report["agents"].items():
                if agent_health["status"] != "healthy":
                    self.logger.info("supervisor.recovering_agent", agent=agent_name)
                    
                    if agent_name == "planner" and self.planner_agent:
                        await self.planner_agent.initialize()
                        SUPERVISOR_HEALTH.labels(agent='planner').set(1)
                    
                    await asyncio.sleep(1)  # Pause pour laisser le temps de récupérer
            
            # Vérifier à nouveau la santé
            new_health = await self._check_agent_health()
            return new_health["healthy"]
            
        except Exception as e:
            self.logger.error("supervisor.recovery_error", error=str(e))
            return False

    async def _wait_for_report(self, timeout: int = 300) -> Dict[str, Any]:
        """Attend le rapport final des agents."""
        report_event = await self.event_bus.wait_for_event(
            event_type="REPORT_READY",
            timeout=timeout
        )
        
        if report_event is None:
            raise TimeoutError("Timeout waiting for report")
        
        return report_event.data

    async def _handle_event(self, event: Event) -> None:
        """Gère les événements reçus du bus d'événements."""
        self.logger.info("supervisor.event_received", event_type=event.type, data=event.data)
        
        if event.type == "REPORT_READY":
            self.logger.info("supervisor.report_ready", report_id=event.data.get("report_id"))
            
        elif event.type in ["PLANNING_FAILED", "EXTRACTION_FAILED", "ANALYSIS_FAILED", "SYNTHESIS_FAILED"]:
            self.logger.error(f"supervisor.{event.type.lower()}", error=event.data.get("error"))
            
            # Tentative de reprise pour les échecs
            await self._handle_agent_failure(event)

    async def _handle_agent_failure(self, event: Event) -> None:
        """Gère les échecs d'agents spécifiques."""
        error_msg = event.data.get("error", "Unknown error")
        agent_type = event.type.replace("_FAILED", "").lower()
        
        self.logger.error(f"supervisor.agent_failure", agent=agent_type, error=error_msg)
        
        # Publier l'événement d'erreur
        await self.event_bus.publish(Event(
            type="SYSTEM_ERROR",
            data={
                "agent": agent_type,
                "error": error_msg,
                "original_event": event.type,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))

    def _generate_final_report(self, report_data: Dict[str, Any], original_query: str) -> str:
        """Génère le rapport final en format markdown."""
        report_parts = [
            f"# Rapport de Recherche",
            f"",
            f"**Requête originale :** {original_query}",
            f"**Date de génération :** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Agent superviseur :** {self.agent_id}",
            f"",
            f"---",
            f"",
        ]
        
        if report_data.get("sections"):
            for section in report_data["sections"]:
                report_parts.append(f"## {section.get('title', 'Section')}")
                report_parts.append("")
                report_parts.append(section.get("content", "Contenu non disponible"))
                report_parts.append("")
        
        if report_data.get("sources"):
            report_parts.append("---")
            report_parts.append("## Sources")
            report_parts.append("")
            for source in report_data["sources"]:
                report_parts.append(f"- {source}")
        
        return "\n".join(report_parts)

    async def health_check(self) -> Dict[str, Any]:
        """Retourne l'état de santé actuel de l'agent."""
        return {
            "status": "healthy" if self.running else "stopped",
            "agent_id": self.agent_id,
            "uptime": time.time() - self._start_time if hasattr(self, '_start_time') else 0,
            "subscriptions": self._subscriptions,
            "health_status": self.health_status
        }

    async def shutdown(self) -> None:
        """Arrête proprement l'agent superviseur."""
        self.logger.info("supervisor.shutting_down", agent_id=self.agent_id)
        self.running = False
        
        # Publier l'événement d'arrêt
        await self.event_bus.publish(Event(
            type="SHUTDOWN",
            data={"agent_id": self.agent_id, "reason": "Normal shutdown"}
        ))
        
        # Arrêter le planner agent
        if self.planner_agent:
            await self.planner_agent.shutdown()
        
        # Se désabonner des événements
        for event_type in self._subscriptions:
            await self.event_bus.unsubscribe(event_type, self._handle_event)
        
        # Annuler les tâches en cours
        for task in self._tasks:
            task.cancel()
        
        SUPERVISOR_HEALTH.labels(agent='supervisor').set(0)
        self.logger.info("supervisor.shutdown_complete", agent_id=self.agent_id)