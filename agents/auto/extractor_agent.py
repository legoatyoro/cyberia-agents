import json
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import re
from datetime import datetime

import httpx
import yaml
from bs4 import BeautifulSoup
from lxml import etree

from core.event_bus import EventBus, Event
from schemas.agent_schemas import AgentOutput, TaskSpec, ExtractedData


class ExtractorAgent:
    """Agent responsible for extracting technical data from external sources."""
    
    def __init__(self, event_bus: EventBus, agent_id: str = "extractor_agent"):
        self.event_bus = event_bus
        self.agent_id = agent_id
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
        
        # Subscribe to events
        self.event_bus.subscribe("TASK_GRAPH_READY", self._handle_task_graph_ready)
        self.event_bus.subscribe("RETRY_EXTRACTION", self._handle_retry_extraction)
        
        # Patterns for entity extraction
        self.ip_pattern = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        self.port_pattern = re.compile(r'\bport\s*[:=]?\s*(\d{1,5})\b', re.IGNORECASE)
        self.protocol_pattern = re.compile(r'\b(TCP|UDP|HTTP|HTTPS|FTP|SSH|SMTP|DNS|DHCP|SNMP|ICMP)\b', re.IGNORECASE)
        self.version_pattern = re.compile(r'\bv?(\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9._-]*)?)\b')
        
    async def _ensure_client(self):
        """Ensure HTTP client is initialized."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
            
    async def _close_client(self):
        """Close HTTP client if exists."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            
    async def run(self, task_spec_json: str, source_urls_list: List[str]) -> AgentOutput:
        """
        Main execution method for the extractor agent.
        
        Args:
            task_spec_json: JSON string containing task specification
            source_urls_list: List of URLs to extract data from
            
        Returns:
            AgentOutput containing extracted data or error information
        """
        self._running = True
        start_time = datetime.utcnow()
        
        try:
            # Parse task specification
            task_spec = TaskSpec.from_json(task_spec_json)
            print(f"[{self.agent_id}] Starting extraction for task: {task_spec.task_id}")
            
            # Initialize HTTP client
            await self._ensure_client()
            
            # Collect data from all sources
            raw_data = await self._collect_from_sources(source_urls_list)
            
            # Parse and extract entities
            parsed_data = await self._parse_data(raw_data)
            
            # Extract named entities
            extracted_entities = self._extract_entities(parsed_data)
            
            # Normalize and structure data
            structured_data = self._normalize_data(extracted_entities, task_spec)
            
            # Create output
            output = AgentOutput(
                agent_id=self.agent_id,
                task_id=task_spec.task_id,
                status="success",
                data=structured_data.to_dict(),
                timestamp=datetime.utcnow().isoformat(),
                metadata={
                    "sources_processed": len(source_urls_list),
                    "entities_extracted": len(extracted_entities),
                    "processing_time": (datetime.utcnow() - start_time).total_seconds()
                }
            )
            
            # Publish success event
            await self.event_bus.publish(Event(
                event_type="DATA_EXTRACTED",
                source=self.agent_id,
                data=output.to_json()
            ))
            
            print(f"[{self.agent_id}] Extraction completed successfully")
            return output
            
        except Exception as e:
            error_msg = f"Extraction failed: {str(e)}"
            print(f"[{self.agent_id}] ERROR: {error_msg}")
            
            # Create error output
            output = AgentOutput(
                agent_id=self.agent_id,
                task_id=task_spec.task_id if 'task_spec' in locals() else "unknown",
                status="error",
                data={},
                error=str(e),
                timestamp=datetime.utcnow().isoformat(),
                metadata={"failed_sources": source_urls_list}
            )
            
            # Publish failure event
            await self.event_bus.publish(Event(
                event_type="EXTRACTION_FAILED",
                source=self.agent_id,
                data=output.to_json()
            ))
            
            return output
            
        finally:
            self._running = False
            await self._close_client()
            
    async def _collect_from_sources(self, urls: List[str]) -> Dict[str, Any]:
        """Collect data from multiple sources concurrently."""
        print(f"[{self.agent_id}] Collecting data from {len(urls)} sources")
        
        tasks = []
        for url in urls:
            tasks.append(self._fetch_source(url))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        collected_data = {}
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                print(f"[{self.agent_id}] Failed to fetch {url}: {result}")
                collected_data[url] = {"error": str(result)}
            else:
                collected_data[url] = result
                
        return collected_data
        
    async def _fetch_source(self, url: str) -> Dict[str, Any]:
        """Fetch data from a single source."""
        parsed_url = urlparse(url)
        
        if parsed_url.scheme in ('http', 'https'):
            return await self._fetch_http_source(url)
        elif url.endswith('.yaml') or url.endswith('.yml'):
            return await self._fetch_yaml_source(url)
        elif url.endswith('.xml'):
            return await self._fetch_xml_source(url)
        else:
            return await self._fetch_generic_source(url)
            
    async def _fetch_http_source(self, url: str) -> Dict[str, Any]:
        """Fetch data from HTTP/HTTPS source."""
        response = await self._http_client.get(url)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '')
        
        if 'application/json' in content_type:
            return {"type": "json", "data": response.json()}
        elif 'text/html' in content_type:
            soup = BeautifulSoup(response.text, 'lxml')
            return {"type": "html", "data": soup.get_text(), "soup": soup}
        elif 'application/xml' in content_type or 'text/xml' in content_type:
            return {"type": "xml", "data": response.text}
        else:
            return {"type": "text", "data": response.text}
            
    async def _fetch_yaml_source(self, url: str) -> Dict[str, Any]:
        """Fetch and parse YAML source."""
        response = await self._http_client.get(url)
        response.raise_for_status()
        
        yaml_data = yaml.safe_load(response.text)
        return {"type": "yaml", "data": yaml_data}
        
    async def _fetch_xml_source(self, url: str) -> Dict[str, Any]:
        """Fetch and parse XML source."""
        response = await self._http_client.get(url)
        response.raise_for_status()
        
        root = etree.fromstring(response.content)
        return {"type": "xml", "data": etree.tostring(root, pretty_print=True).decode()}
        
    async def _fetch_generic_source(self, url: str) -> Dict[str, Any]:
        """Fetch generic source (logs, configs, etc.)."""
        response = await self._http_client.get(url)
        response.raise_for_status()
        
        return {"type": "generic", "data": response.text}
        
    async def _parse_data(self, raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse collected data into structured format."""
        print(f"[{self.agent_id}] Parsing collected data")
        
        parsed_results = []
        
        for source_url, source_data in raw_data.items():
            if "error" in source_data:
                continue
                
            parsed_entry = {
                "source": source_url,
                "timestamp": datetime.utcnow().isoformat(),
                "content": source_data.get("data", ""),
                "type": source_data.get("type", "unknown")
            }
            
            # Parse based on type
            if source_data.get("type") == "html":
                soup = source_data.get("soup")
                if soup:
                    # Extract code blocks, tables, and technical content
                    code_blocks = soup.find_all(['code', 'pre'])
                    parsed_entry["code_blocks"] = [block.get_text() for block in code_blocks]
                    
                    tables = soup.find_all('table')
                    parsed_entry["tables"] = []
                    for table in tables:
                        rows = []
                        for row in table.find_all('tr'):
                            cells = [cell.get_text(strip=True) for cell in row.find_all(['td', 'th'])]
                            rows.append(cells)
                        parsed_entry["tables"].append(rows)
                        
            elif source_data.get("type") == "yaml":
                parsed_entry["structured_data"] = source_data.get("data", {})
                
            parsed_results.append(parsed_entry)
            
        return parsed_results
        
    def _extract_entities(self, parsed_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract named entities from parsed data."""
        print(f"[{self.agent_id}] Extracting named entities")
        
        extracted_entities = []
        
        for entry in parsed_data:
            content = str(entry.get("content", ""))
            
            # Extract IP addresses
            ips = self.ip_pattern.findall(content)
            for ip in ips:
                if self._is_valid_ip(ip):
                    extracted_entities.append({
                        "type": "ip_address",
                        "value": ip,
                        "source": entry["source"],
                        "context": self._get_context(content, ip)
                    })
                    
            # Extract ports
            ports = self.port_pattern.findall(content)
            for port in ports:
                extracted_entities.append({
                    "type": "port",
                    "value": int(port),
                    "source": entry["source"],
                    "context": self._get_context(content, port)
                })
                
            # Extract protocols
            protocols = self.protocol_pattern.findall(content)
            for protocol in set(protocols):
                extracted_entities.append({
                    "type": "protocol",
                    "value": protocol.upper(),
                    "source": entry["source"],
                    "context": self._get_context(content, protocol)
                })
                
            # Extract software versions
            versions = self.version_pattern.findall(content)
            for version in versions:
                if self._is_valid_version(version):
                    extracted_entities.append({
                        "type": "software_version",
                        "value": version,
                        "source": entry["source"],
                        "context": self._get_context(content, version)
                    })
                    
            # Extract from structured data if available
            if "structured_data" in entry:
                structured_entities = self._extract_from_structured(entry["structured_data"], entry["source"])
                extracted_entities.extend(structured_entities)
                
        return extracted_entities
        
    def _extract_from_structured(self, data: Dict[str, Any], source: str) -> List[Dict[str, Any]]:
        """Extract entities from structured data (YAML, JSON)."""
        entities = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    # Check for IPs in values
                    ips = self.ip_pattern.findall(value)
                    for ip in ips:
                        if self._is_valid_ip(ip):
                            entities.append({
                                "type": "ip_address",
                                "value": ip,
                                "source": source,
                                "field": key
                            })
                            
                elif isinstance(value, (list, dict)):
                    entities.extend(self._extract_from_structured(value, source))
                    
        elif isinstance(data, list):
            for item in data:
                entities.extend(self._extract_from_structured(item, source))
                
        return entities
        
    def _normalize_data(self, entities: List[Dict[str, Any]], task_spec: TaskSpec) -> ExtractedData:
        """Normalize and structure extracted data."""
        print(f"[{self.agent_id}] Normalizing extracted data")
        
        # Group entities by type
        grouped_entities = {}
        for entity in entities:
            entity_type = entity["type"]
            if entity_type not in grouped_entities:
                grouped_entities[entity_type] = []
            grouped_entities[entity_type].append(entity)
            
        # Create structured output
        structured_data = ExtractedData(
            task_id=task_spec.task_id,
            extraction_time=datetime.utcnow().isoformat(),
            ip_addresses=[e["value"] for e in grouped_entities.get("ip_address", [])],
            ports=list(set([e["value"] for e in grouped_entities.get("port", [])])),
            protocols=list(set([e["value"] for e in grouped_entities.get("protocol", [])])),
            software_versions=list(set([e["value"] for e in grouped_entities.get("software_version", [])])),
            raw_entities=entities,
            metadata={
                "total_entities": len(entities),
                "entity_types": list(grouped_entities.keys()),
                "source_count": len(set(e["source"] for e in entities))
            }
        )
        
        return structured_data
        
    def _is_valid_ip(self, ip: str) -> bool:
        """Validate IP address."""
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False
            
    def _is_valid_version(self, version: str) -> bool:
        """Validate software version string."""
        # Basic validation - should be at least X.Y format
        parts = version.split('.')
        return len(parts) >= 2 and all(p.isdigit() or p.isalnum() for p in parts)
        
    def _get_context(self, text: str, entity: str, window: int = 50) -> str:
        """Get surrounding context for an entity."""
        index = text.find(str(entity))
        if index == -1:
            return ""
            
        start = max(0, index - window)
        end = min(len(text), index + len(str(entity)) + window)
        
        context = text[start:end].strip()
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
            
        return context
        
    async def _handle_task_graph_ready(self, event: Event):
        """Handle TASK_GRAPH_READY event."""
        print(f"[{self.agent_id}] Received TASK_GRAPH_READY event")
        
        if not self._running:
            task_data = event.data
            if isinstance(task_data, dict):
                task_spec = task_data.get("task_spec", "")
                sources = task_data.get("sources", [])
                
                if task_spec and sources:
                    await self.run(task_spec, sources)
                    
    async def _handle_retry_extraction(self, event: Event):
        """Handle RETRY_EXTRACTION event."""
        print(f"[{self.agent_id}] Received RETRY_EXTRACTION event")
        
        retry_data = event.data
        if isinstance(retry_data, dict):
            task_spec = retry_data.get("task_spec", "")
            sources = retry_data.get("sources", [])
            retry_count = retry_data.get("retry_count", 0)
            
            if retry_count < 3:  # Max 3 retries
                print(f"[{self.agent_id}] Retrying extraction (attempt {retry_count + 1})")
                await self.run(task_spec, sources)
            else:
                print(f"[{self.agent_id}] Max retries reached for extraction")
                
    async def cleanup(self):
        """Cleanup resources."""
        await self._close_client()
        self.event_bus.unsubscribe("TASK_GRAPH_READY", self._handle_task_graph_ready)
        self.event_bus.unsubscribe("RETRY_EXTRACTION", self._handle_retry_extraction)