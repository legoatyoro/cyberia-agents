import asyncio
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, AgentStatus

# Response templates for different intents
RESPONSE_TEMPLATES = {
    "greeting": {
        "default": "Hello! How can I help you today?",
        "morning": "Good morning! How can I assist you?",
        "evening": "Good evening! What can I do for you?"
    },
    "farewell": {
        "default": "Goodbye! Have a great day!",
        "formal": "Thank you for your time. Goodbye.",
        "casual": "See you later! Take care!"
    },
    "question": {
        "default": "That's an interesting question. Let me think about it.",
        "unknown": "I'm not sure I have the answer to that right now.",
        "clarification": "Could you please provide more details?"
    },
    "command": {
        "default": "Processing your request...",
        "completed": "Task completed successfully.",
        "failed": "I'm sorry, I couldn't complete that task."
    },
    "unknown": {
        "default": "I'm not sure I understand. Could you rephrase that?"
    }
}

class ResponseGeneratorAgent:
    """Agent responsible for generating contextual responses based on parsed intents."""
    
    def __init__(self, agent_id: str = "response_generator_001"):
        self.agent_id = agent_id
        self.event_bus = EventBus.get_instance()
        self.running = False
        self._subscriptions = []
        
    async def run(self) -> None:
        """Main execution loop for the agent."""
        self.running = True
        print(f"[{self.agent_id}] Response Generator Agent started")
        
        # Subscribe to MESSAGE_FORWARDED events
        subscription = await self.event_bus.subscribe(
            event_type="MESSAGE_FORWARDED",
            callback=self.handle_message_forwarded
        )
        self._subscriptions.append(subscription)
        
        try:
            # Keep the agent running
            while self.running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            print(f"[{self.agent_id}] Agent cancelled")
        finally:
            await self.cleanup()
    
    async def handle_message_forwarded(self, event: Event) -> None:
        """Handle incoming MESSAGE_FORWARDED events."""
        try:
            print(f"[{self.agent_id}] Received MESSAGE_FORWARDED event: {event.event_id}")
            
            # Extract intent data from event payload
            intent_data = event.payload.get("intent_parsed_event", {})
            if not intent_data:
                print(f"[{self.agent_id}] No intent data found in event payload")
                return
            
            # Generate response based on intent
            response = await self.generate_response(intent_data)
            
            # Create and publish response ready event
            response_event = Event(
                event_type="RESPONSE_READY",
                payload={
                    "response_generator_agent": self.agent_id,
                    "response": response,
                    "original_intent": intent_data,
                    "correlation_id": event.payload.get("correlation_id", event.event_id)
                }
            )
            
            await self.event_bus.publish(response_event)
            print(f"[{self.agent_id}] Published RESPONSE_READY event: {response_event.event_id}")
            
        except Exception as e:
            print(f"[{self.agent_id}] Error handling message forwarded: {str(e)}")
            await self.handle_error(event, str(e))
    
    async def generate_response(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a contextual response based on the parsed intent."""
        try:
            # Extract intent information
            intent = intent_data.get("intent", "unknown")
            entities = intent_data.get("entities", {})
            confidence = intent_data.get("confidence", 0.0)
            context = intent_data.get("context", {})
            
            print(f"[{self.agent_id}] Generating response for intent: {intent} (confidence: {confidence})")
            
            # Get template for the intent
            templates = RESPONSE_TEMPLATES.get(intent, RESPONSE_TEMPLATES["unknown"])
            
            # Select appropriate template based on context
            template_key = self._select_template(templates, context)
            response_text = templates.get(template_key, templates["default"])
            
            # Personalize response with entities if available
            if entities:
                response_text = self._personalize_response(response_text, entities)
            
            # Build response structure
            response = {
                "text": response_text,
                "intent": intent,
                "confidence": confidence,
                "entities_used": entities,
                "template_used": template_key,
                "agent_id": self.agent_id
            }
            
            print(f"[{self.agent_id}] Generated response: {response_text[:50]}...")
            return response
            
        except Exception as e:
            print(f"[{self.agent_id}] Error generating response: {str(e)}")
            return {
                "text": "I apologize, but I encountered an error processing your request.",
                "intent": "error",
                "confidence": 0.0,
                "entities_used": {},
                "template_used": "error",
                "agent_id": self.agent_id
            }
    
    def _select_template(self, templates: Dict[str, str], context: Dict[str, Any]) -> str:
        """Select the appropriate template based on context."""
        # Check for time-based context
        time_of_day = context.get("time_of_day", "")
        if time_of_day == "morning" and "morning" in templates:
            return "morning"
        elif time_of_day == "evening" and "evening" in templates:
            return "evening"
        
        # Check for formality context
        formality = context.get("formality", "default")
        if formality in templates:
            return formality
        
        # Check for status context (for commands)
        status = context.get("status", "")
        if status in templates:
            return status
        
        return "default"
    
    def _personalize_response(self, response_text: str, entities: Dict[str, Any]) -> str:
        """Personalize the response with entity information."""
        try:
            # Replace entity placeholders in the response
            for entity_key, entity_value in entities.items():
                placeholder = f"{{{entity_key}}}"
                if placeholder in response_text:
                    response_text = response_text.replace(placeholder, str(entity_value))
            
            # Add entity information if not already present
            if entities and "{entities}" in response_text:
                entity_list = ", ".join([f"{k}: {v}" for k, v in entities.items()])
                response_text = response_text.replace("{entities}", entity_list)
            
            return response_text
            
        except Exception as e:
            print(f"[{self.agent_id}] Error personalizing response: {str(e)}")
            return response_text
    
    async def handle_error(self, event: Event, error_message: str) -> None:
        """Handle errors by publishing an error event."""
        try:
            error_event = Event(
                event_type="AGENT_ERROR",
                payload={
                    "agent_id": self.agent_id,
                    "error": error_message,
                    "original_event_id": event.event_id,
                    "correlation_id": event.payload.get("correlation_id", event.event_id)
                }
            )
            
            await self.event_bus.publish(error_event)
            print(f"[{self.agent_id}] Published error event: {error_message}")
            
        except Exception as e:
            print(f"[{self.agent_id}] Critical error in error handler: {str(e)}")
    
    async def cleanup(self) -> None:
        """Clean up subscriptions and resources."""
        print(f"[{self.agent_id}] Cleaning up resources")
        
        # Unsubscribe from all events
        for subscription in self._subscriptions:
            await self.event_bus.unsubscribe(subscription)
        
        self._subscriptions.clear()
        self.running = False
        print(f"[{self.agent_id}] Cleanup complete")
    
    async def stop(self) -> None:
        """Stop the agent gracefully."""
        print(f"[{self.agent_id}] Stopping agent")
        self.running = False

# Factory function to create agent instance
def create_agent() -> ResponseGeneratorAgent:
    """Create and return a new ResponseGeneratorAgent instance."""
    return ResponseGeneratorAgent()

# Main entry point for running the agent standalone
async def main():
    agent = create_agent()
    try:
        await agent.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await agent.stop()

if __name__ == "__main__":
    asyncio.run(main())