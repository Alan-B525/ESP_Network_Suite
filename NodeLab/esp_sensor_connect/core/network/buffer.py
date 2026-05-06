import threading
from typing import Dict, List
from collections import deque

class TelemetryBuffer:
    """
    Manages circular buffers of sensor data for UI visualization.
    
    Stores actual sample values (not averages) for faithful signal reproduction.
    Uses deque for efficient append/trim operations.
    """
    def __init__(self, max_size: int = 2000):
        self._lock = threading.Lock()
        self._max_size = max_size
        # Structure: {node_id: {channel_id: deque([float, ...])}}
        self._buffers: Dict[int, Dict[int, deque]] = {}

    def append_samples(self, node_id: int, channel_id: int, values: List[float]):
        """
        Appends ALL sample values to the buffer (no averaging).
        This preserves the actual waveform for faithful visualization.
        """
        if not values:
            return

        with self._lock:
            if node_id not in self._buffers:
                self._buffers[node_id] = {}
            if channel_id not in self._buffers[node_id]:
                self._buffers[node_id][channel_id] = deque(maxlen=self._max_size)

            buf = self._buffers[node_id][channel_id]
            buf.extend(values)

    def get_data(self, node_id: int, channel_id: int, count: int = 500) -> List[float]:
        with self._lock:
            node_channels = self._buffers.get(node_id, {})
            buffer = node_channels.get(channel_id, deque())
            # Return the last 'count' elements
            if len(buffer) <= count:
                return list(buffer)
            return list(buffer)[-count:]

    def clear(self):
        with self._lock:
            self._buffers.clear()
