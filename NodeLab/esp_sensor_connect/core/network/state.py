import json
import os
import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from core.protocol_parser import TelemetryFrame

@dataclass
class NodeMetadata:
    node_id: int
    mac: str
    alias: str = ""
    is_healthy: bool = False
    last_seen: float = 0.0

class NetworkState:
    """
    Handles node discovery, identification, health tracking and persistent aliases.
    """
    def __init__(self, aliases_file: str = "aliases.json"):
        self._lock = threading.Lock()
        self._nodes: Dict[int, NodeMetadata] = {}
        self._mac_to_id: Dict[str, int] = {}
        self._aliases: Dict[str, str] = {}
        self._telemetry: Dict[int, TelemetryFrame] = {}
        self._aliases_file = aliases_file
        self._load_aliases()

    def _load_aliases(self):
        if os.path.exists(self._aliases_file):
            try:
                with open(self._aliases_file, "r") as f:
                    self._aliases = json.load(f)
            except Exception as e:
                print(f"[STATE] Error loading aliases: {e}")

    def save_aliases(self):
        with self._lock:
            try:
                with open(self._aliases_file, "w") as f:
                    json.dump(self._aliases, f, indent=4)
            except Exception as e:
                print(f"[STATE] Error saving aliases: {e}")

    def register_node(self, node_id: int, mac: str):
        with self._lock:
            if node_id not in self._nodes:
                alias = self._aliases.get(mac, "")
                self._nodes[node_id] = NodeMetadata(node_id=node_id, mac=mac, alias=alias)
            
            node = self._nodes[node_id]
            node.mac = mac
            node.last_seen = time.time()
            node.is_healthy = True
            self._mac_to_id[mac] = node_id

    def set_node_alias(self, mac: str, alias: str):
        with self._lock:
            if alias:
                self._aliases[mac] = alias
            else:
                self._aliases.pop(mac, None)
            
            # Update live nodes if present
            if mac in self._mac_to_id:
                node_id = self._mac_to_id[mac]
                if node_id in self._nodes:
                    self._nodes[node_id].alias = alias
        
        self.save_aliases()

    def get_node_alias(self, mac: str) -> str:
        with self._lock:
            return self._aliases.get(mac, "")

    def get_node_mac(self, node_id: int) -> str:
        with self._lock:
            node = self._nodes.get(node_id)
            return node.mac if node else ""

    def update_health(self, node_id: int, is_healthy: bool):
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].is_healthy = is_healthy

    def is_node_healthy(self, node_id: int) -> bool:
        with self._lock:
            node = self._nodes.get(node_id)
            return node.is_healthy if node else False

    def get_active_nodes_count(self) -> int:
        with self._lock:
            return sum(1 for n in self._nodes.values() if n.is_healthy)

    def get_all_node_ids(self) -> List[int]:
        with self._lock:
            return sorted(self._nodes.keys())

    def get_node_metadata(self, node_id: int) -> Optional[NodeMetadata]:
        with self._lock:
            return self._nodes.get(node_id)

    def update_telemetry(self, frame: TelemetryFrame):
        with self._lock:
            self._telemetry[frame.node_id] = frame

    def get_telemetry(self, node_id: int) -> Optional[TelemetryFrame]:
        with self._lock:
            return self._telemetry.get(node_id)

    def mark_seen(self, node_id: int):
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].last_seen = time.time()
                self._nodes[node_id].is_healthy = True

    def get_last_seen(self, node_id: int) -> float:
        with self._lock:
            node = self._nodes.get(node_id)
            return node.last_seen if node else 0.0
