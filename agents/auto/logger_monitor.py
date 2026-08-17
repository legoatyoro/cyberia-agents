import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput

class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    agent_source: str
    data: Dict[str, Any]
    status: str = "info"

class AlertEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    alert_type: str
    severity: str
    message: str
    details: Dict[str, Any]

class LoggerMonitorAgent:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        self.logs: List[LogEntry] = []
        self.alerts: List[AlertEntry] = []
        self.agent_performance: Dict[str, Dict[str, Any]] = {}
        self.event_timestamps: Dict[str, datetime] = {}
        self.TIMEOUT_THRESHOLD = 30  # seconds
        self.MAX_EVENTS_PER_AGENT = 100
        
    async def run(self) -> AgentOutput:
        """Main execution method for the agent"""
        try:
            print("[LOGGER_MONITOR] Starting LoggerMonitorAgent...")
            
            # Subscribe to all relevant events
            await self._subscribe_to_events()
            
            # Start monitoring loop
            await self._monitoring_loop()
            
            # Generate output
            output = AgentOutput(
                agent_name="LOGGER_MONITOR",
                status="success",
                data={
                    "logs_count": len(self.logs),
                    "alerts_count": len(self.alerts),
                    "performance_metrics": self.agent_performance
                },
                timestamp=datetime.now()
            )
            
            print(f"[LOGGER_MONITOR] Completed with {len(self.logs)} logs and {len(self.alerts)} alerts")
            return output
            
        except Exception as e:
            error_msg = f"LoggerMonitorAgent failed: {str(e)}"
            print(f"[LOGGER_MONITOR] ERROR: {error_msg}")
            
            # Create alert for critical failure
            self.alerts.append(AlertEntry(
                alert_type="AGENT_FAILURE",
                severity="critical",
                message=error_msg,
                details={"error": str(e), "timestamp": datetime.now().isoformat()}
            ))
            
            return AgentOutput(
                agent_name="LOGGER_MONITOR",
                status="error",
                error=str(e),
                timestamp=datetime.now()
            )
    
    async def _subscribe_to_events(self):
        """Subscribe to all required events"""
        events_to_subscribe = [
            "INTENT_PARSED",
            "MESSAGE_FORWARDED", 
            "RESPONSE_READY",
            "MESSAGE_DELIVERED"
        ]
        
        for event_type in events_to_subscribe:
            await self.event_bus.subscribe(event_type, self._handle_event)
            print(f"[LOGGER_MONITOR] Subscribed to {event_type}")
    
    async def _handle_event(self, event: Event):
        """Handle incoming events from the bus"""
        try:
            # Log the event
            log_entry = LogEntry(
                event_type=event.type,
                agent_source=event.source or "unknown",
                data=event.data or {},
                status="info"
            )
            self.logs.append(log_entry)
            
            # Track performance
            agent_name = event.source or "unknown"
            if agent_name not in self.agent_performance:
                self.agent_performance[agent_name] = {
                    "events_processed": 0,
                    "last_event_time": None,
                    "average_response_time": 0.0,
                    "total_response_time": 0.0
                }
            
            perf = self.agent_performance[agent_name]
            perf["events_processed"] += 1
            
            # Calculate response time if we have previous event
            if event.type in self.event_timestamps:
                time_diff = (datetime.now() - self.event_timestamps[event.type]).total_seconds()
                perf["total_response_time"] += time_diff
                perf["average_response_time"] = perf["total_response_time"] / perf["events_processed"]
            
            self.event_timestamps[event.type] = datetime.now()
            perf["last_event_time"] = datetime.now()
            
            # Check for anomalies
            await self._detect_anomalies(event, agent_name)
            
            # Check for timeouts
            await self._check_timeouts(agent_name)
            
            # Manage log size
            if len(self.logs) > self.MAX_EVENTS_PER_AGENT * 10:
                self.logs = self.logs[-self.MAX_EVENTS_PER_AGENT * 5:]
            
            print(f"[LOGGER_MONITOR] Logged event: {event.type} from {agent_name}")
            
        except Exception as e:
            error_msg = f"Error handling event {event.type}: {str(e)}"
            print(f"[LOGGER_MONITOR] ERROR: {error_msg}")
            self.alerts.append(AlertEntry(
                alert_type="EVENT_HANDLING_ERROR",
                severity="high",
                message=error_msg,
                details={"event": event.dict() if hasattr(event, 'dict') else str(event)}
            ))
    
    async def _detect_anomalies(self, event: Event, agent_name: str):
        """Detect anomalies in event patterns"""
        anomalies = []
        
        # Check for rapid successive events from same agent
        if agent_name in self.agent_performance:
            perf = self.agent_performance[agent_name]
            if perf["events_processed"] > 10:  # Only check after enough data
                if perf["average_response_time"] < 0.001:  # Less than 1ms average
                    anomalies.append("Unusually fast response time detected")
        
        # Check for missing expected events
        expected_sequence = ["INTENT_PARSED", "MESSAGE_FORWARDED", "RESPONSE_READY", "MESSAGE_DELIVERED"]
        recent_events = [log.event_type for log in self.logs[-20:]]
        
        for i, expected in enumerate(expected_sequence):
            if expected not in recent_events:
                if i > 0 and expected_sequence[i-1] in recent_events:
                    anomalies.append(f"Missing expected event: {expected}")
        
        # Create alerts for anomalies
        for anomaly in anomalies:
            alert = AlertEntry(
                alert_type="ANOMALY_DETECTED",
                severity="medium",
                message=anomaly,
                details={
                    "agent": agent_name,
                    "event": event.type,
                    "timestamp": datetime.now().isoformat()
                }
            )
            self.alerts.append(alert)
            
            # Publish alert event
            await self.event_bus.publish(Event(
                type="ALERT_TRIGGERED",
                source="LOGGER_MONITOR",
                data=alert.dict()
            ))
            
            print(f"[LOGGER_MONITOR] Anomaly detected: {anomaly}")
    
    async def _check_timeouts(self, agent_name: str):
        """Check for agent timeouts"""
        if agent_name in self.agent_performance:
            perf = self.agent_performance[agent_name]
            if perf["last_event_time"]:
                time_since_last = (datetime.now() - perf["last_event_time"]).total_seconds()
                
                if time_since_last > self.TIMEOUT_THRESHOLD:
                    alert = AlertEntry(
                        alert_type="AGENT_TIMEOUT",
                        severity="high",
                        message=f"Agent {agent_name} has not responded for {time_since_last:.1f} seconds",
                        details={
                            "agent": agent_name,
                            "timeout_duration": time_since_last,
                            "threshold": self.TIMEOUT_THRESHOLD,
                            "last_event_time": perf["last_event_time"].isoformat()
                        }
                    )
                    self.alerts.append(alert)
                    
                    # Publish timeout alert
                    await self.event_bus.publish(Event(
                        type="ALERT_TRIGGERED",
                        source="LOGGER_MONITOR",
                        data=alert.dict()
                    ))
                    
                    print(f"[LOGGER_MONITOR] Timeout detected for {agent_name}: {time_since_last:.1f}s")
    
    async def _monitoring_loop(self):
        """Continuous monitoring loop"""
        while True:
            try:
                # Check overall system health
                total_events = len(self.logs)
                total_alerts = len(self.alerts)
                
                # Log system status periodically
                print(f"[LOGGER_MONITOR] System status: {total_events} events, {total_alerts} alerts")
                
                # Check for critical conditions
                if total_alerts > 50:
                    alert = AlertEntry(
                        alert_type="HIGH_ALERT_COUNT",
                        severity="critical",
                        message=f"Alert threshold exceeded: {total_alerts} alerts",
                        details={"alert_count": total_alerts, "threshold": 50}
                    )
                    self.alerts.append(alert)
                    await self.event_bus.publish(Event(
                        type="ALERT_TRIGGERED",
                        source="LOGGER_MONITOR",
                        data=alert.dict()
                    ))
                
                # Sleep before next check
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                print("[LOGGER_MONITOR] Monitoring loop cancelled")
                break
            except Exception as e:
                print(f"[LOGGER_MONITOR] Error in monitoring loop: {str(e)}")
                await asyncio.sleep(5)
    
    def get_logs(self, event_type: Optional[str] = None, limit: int = 100) -> List[LogEntry]:
        """Retrieve logs with optional filtering"""
        if event_type:
            filtered_logs = [log for log in self.logs if log.event_type == event_type]
            return filtered_logs[-limit:]
        return self.logs[-limit:]
    
    def get_alerts(self, severity: Optional[str] = None, limit: int = 50) -> List[AlertEntry]:
        """Retrieve alerts with optional filtering"""
        if severity:
            filtered_alerts = [alert for alert in self.alerts if alert.severity == severity]
            return filtered_alerts[-limit:]
        return self.alerts[-limit:]
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics for all agents"""
        return {
            agent: {
                "events_processed": perf["events_processed"],
                "average_response_time": f"{perf['average_response_time']:.3f}s",
                "last_event": perf["last_event_time"].isoformat() if perf["last_event_time"] else None
            }
            for agent, perf in self.agent_performance.items()
        }