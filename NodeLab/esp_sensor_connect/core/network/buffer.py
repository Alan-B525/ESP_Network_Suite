import threading
from typing import Dict, List

class TelemetryBuffer:
    """
    Manages circular buffers of sensor data for UI visualization.
    Implements downsampling/decimation logic to keep UI responsive.
    """
    def __init__(self, max_size: int = 200):
        self._lock = threading.Lock()
        self._max_size = max_size
        # Structure: {node_id: {channel_id: [float, float, ...]}}
        self._buffers: Dict[int, Dict[int, List[float]]] = {}

    def append_samples(self, node_id: int, channel_id: int, values: List[float]):
        """
        Appends a list of values to the buffer. 
        Calculates average for decimation to keep the buffer size under control.
        """
        if not values:
            return

        with self._lock:
            if node_id not in self._buffers:
                self._buffers[node_id] = {}
            if channel_id not in self._buffers[node_id]:
                self._buffers[node_id][channel_id] = []

            # Decimation: for plotting purposes, we often only need a trend
            # In the original code, it took the average of the packet
            avg_val = sum(values) / len(values)
            
            node_buf = self._buffers[node_id][channel_id]
            node_buf.append(avg_val)

            if len(node_buf) > self._max_size:
                # Keep only the last max_size elements
                self._buffers[node_id][channel_id] = node_buf[-self._max_size:]

    def get_data(self, node_id: int, channel_id: int, count: int = 100) -> List[float]:
        with self._lock:
            node_channels = self._buffers.get(node_id, {})
            buffer = node_channels.get(channel_id, [])
            return list(buffer[-count:])

    def clear(self):
        with self._lock:
            self._buffers.clear()
