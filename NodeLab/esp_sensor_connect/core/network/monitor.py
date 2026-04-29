import threading
from typing import Dict, Optional

class NetworkMonitor:
    """
    Tracks network performance metrics like packet loss and throughput.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # {node_id: total_received}
        self.packets_received: Dict[int, int] = {}
        # {node_id: total_lost}
        self.packets_lost: Dict[int, int] = {}
        # {node_id: last_sequence}
        self._last_sequence: Dict[int, int] = {}

    def track_packet(self, node_id: int, sequence: int):
        with self._lock:
            if node_id not in self.packets_received:
                self.packets_received[node_id] = 0
                self.packets_lost[node_id] = 0
            
            self.packets_received[node_id] += 1

            if node_id in self._last_sequence:
                expected_seq = self._last_sequence[node_id] + 1
                # Handle sequence wrap-around if necessary (usually uint16)
                if sequence > expected_seq:
                    lost = sequence - expected_seq
                    self.packets_lost[node_id] += lost
            
            self._last_sequence[node_id] = sequence

    def update_from_stats(self, node_id: int, received: int, lost: int):
        """Update using ground truth from Gateway stats."""
        with self._lock:
            self.packets_received[node_id] = received
            self.packets_lost[node_id] = lost

    def get_loss_rate(self, node_id: int) -> float:
        with self._lock:
            rx = self.packets_received.get(node_id, 0)
            lost = self.packets_lost.get(node_id, 0)
            total = rx + lost
            if total == 0:
                return 0.0
            return (lost / total) * 100.0

    def reset(self):
        with self._lock:
            self.packets_received.clear()
            self.packets_lost.clear()
            self._last_sequence.clear()
