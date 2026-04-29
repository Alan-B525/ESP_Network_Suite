import threading
import queue
import time
from typing import Optional, Callable, List

from core.protocol_parser import (
    ProtocolParser, DataFrame, TimingFrame, BeaconFrame, HelloFrame,
    JoinFrame, TimeoutFrame, LossFrame, StatsFrame, BootFrame, WarnFrame,
    AckFrame, TelemetryFrame
)
from core.network.state import NetworkState
from core.network.buffer import TelemetryBuffer
from core.network.monitor import NetworkMonitor
from core.network.service import SerialService

class NetworkManager:
    """
    High-level orchestrator for the ESP-NOW Sensor Network.
    Delegates responsibilities to specialized sub-services.
    """
    BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
    DEFAULT_BAUDRATE = 921600
    def __init__(self):
        # 1. Sub-services
        self.state = NetworkState()
        self.buffer = TelemetryBuffer(max_size=200)
        self.monitor = NetworkMonitor()
        self.serial = SerialService(
            on_frame_received=self._on_raw_frame,
            on_connection_change=self._on_connection_change_internal
        )
        self.parser = ProtocolParser()
        
        # 2. Shared Data Queue (for DataLogger)
        self.data_queue = queue.Queue(maxsize=50000)
        self.serial.data_queue = self.data_queue # Sync if needed
        
        # 3. Internal State
        self.is_acquiring = False
        self._manager_running = True
        self._basestation_verified = False
        
        # 4. Callbacks
        self._on_status_callback = None
        self._on_ack_callback = None
        self._on_connection_change = None
        self._on_node_event = None
        self._on_raw_line_callback = None

        # 5. Background Tasks
        self._auto_connect_thread = threading.Thread(target=self._auto_connect_loop, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._auto_connect_thread.start()
        self._watchdog_thread.start()

    # --- Property Proxies (for compatibility with existing UI) ---
    @property
    def is_connected(self) -> bool: return self.serial.is_connected
    
    @property
    def current_port(self) -> str: return self.serial.current_port


    @property
    def packets_received(self) -> Dict[int, int]: return self.monitor.packets_received

    @property
    def packets_lost(self) -> Dict[int, int]: return self.monitor.packets_lost

    # --- Compatibility / Helper Methods ---
    def get_node_data(self, node_id: int, channel_id: int, count: int = 100):
        return self.buffer.get_data(node_id, channel_id, count)

    def get_packet_loss_rate(self, node_id: int) -> float:
        return self.monitor.get_loss_rate(node_id)

    def get_all_node_ids(self) -> List[int]:
        return self.state.get_all_node_ids()

    def is_node_healthy(self, node_id: int) -> bool:
        return self.state.is_node_healthy(node_id)

    def get_node_mac(self, node_id: int) -> str:
        return self.state.get_node_mac(node_id)

    def set_node_alias(self, mac: str, alias: str):
        self.state.set_node_alias(mac, alias)

    def get_node_alias(self, mac: str) -> str:
        return self.state.get_node_alias(mac)

    @staticmethod
    def list_available_ports():
        return SerialService.list_ports()

    def set_sample_rate(self, rate_hz: int) -> bool:
        return self.serial.send(f"CMD_SET_RATE,{rate_hz}")

    def get_node_telemetry(self, node_id: int) -> Optional[TelemetryFrame]:
        # You might want to store this in state or a separate dict
        return self.state.get_telemetry(node_id)

    def set_on_raw_line(self, callback: Callable[[str], None]):
        self.serial.on_line_received = callback

    def send_command(self, cmd: str) -> bool:
        return self.serial.send(cmd)

    # --- Public API ---
    def connect(self, port: str, baudrate: int = 921600) -> bool:
        return self.serial.connect(port, baudrate)

    def disconnect(self):
        self.serial.disconnect()

    def start_acquisition(self) -> bool:
        now = time.time()
        for node_id in self.state.get_all_node_ids():
            self.state.mark_seen(node_id) # Reset health timers
        
        if self.serial.send("CMD_START"):
            self.is_acquiring = True
            return True
        return False

    def stop_acquisition(self) -> bool:
        self.serial.send("CMD_STOP")
        self.is_acquiring = False
        return True

    def send_command(self, command: str) -> bool:
        return self.serial.send(command)

    # --- Callback Registration ---
    def set_on_status(self, cb): self._on_status_callback = cb
    def set_on_ack(self, cb): self._on_ack_callback = cb
    def set_on_connection_change(self, cb): self._on_connection_change = cb
    def set_on_node_event(self, cb): self._on_node_event = cb
    def set_on_raw_line(self, cb): self._on_raw_line_callback = cb

    # --- Frame Dispatching ---
    def _on_raw_frame(self, decoded: bytes):
        self._basestation_verified = True
        
        # Handle ASCII logging for raw lines
        if decoded[0] == 0x01 and self._on_raw_line_callback:
            try:
                line = decoded[1:].decode('utf-8', errors='replace').strip()
                if not line.startswith("DATA,") and not line.startswith("BEACON,"):
                    self._on_raw_line_callback(line)
            except: pass

        frame = self.parser.parse_decoded(decoded)
        if frame:
            self._dispatch_frame(frame)

    def _dispatch_frame(self, frame):
        if isinstance(frame, DataFrame):
            self.state.mark_seen(frame.node_id)
            self.monitor.track_packet(frame.node_id, frame.sequence)
            self.buffer.append_samples(frame.node_id, frame.channel_id, frame.values)
            self._enqueue_for_logger(frame)
        
        elif isinstance(frame, TimingFrame):
            self._enqueue_for_logger(frame)
            
        elif isinstance(frame, (HelloFrame, JoinFrame)):
            self.state.register_node(frame.node_id, frame.mac)
            if self._on_node_event: self._on_node_event(frame)
            
        elif isinstance(frame, TimeoutFrame):
            self.state.update_health(frame.node_id, False)
            if self._on_node_event: self._on_node_event(frame)
            
        elif isinstance(frame, StatsFrame):
            for node in frame.nodes:
                self.monitor.update_from_stats(node.node_id, node.emit, node.lost)
            if self._on_status_callback: self._on_status_callback(frame)
            
        elif isinstance(frame, AckFrame):
            if self._on_ack_callback: self._on_ack_callback(frame)
            
        elif isinstance(frame, TelemetryFrame):
            self.state.update_telemetry(frame)

    def _enqueue_for_logger(self, frame):
        try:
            self.data_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.data_queue.get_nowait()
                self.data_queue.put_nowait(frame)
            except queue.Empty: pass

    # --- Background Loops ---
    def _auto_connect_loop(self):
        tested_ports = set()
        while self._manager_running:
            if self.serial.can_auto_connect():
                ports = self.serial.list_ports()
                available = [p['device'] for p in ports if p['device'] not in tested_ports]
                
                if not available:
                    tested_ports.clear()
                    time.sleep(3.0)
                    continue
                
                target = available[-1]
                # Smart heuristic
                for p in ports:
                    if p['device'] in available:
                        desc = p.get('description', '').upper()
                        if any(x in desc for x in ['CH340', 'SILICON', 'UART', 'CP210']):
                            target = p['device']
                            break
                
                if self.serial.connect(target, 921600):
                    self._basestation_verified = False
                    # Wait for verification
                    for _ in range(25):
                        time.sleep(0.1)
                        if self._basestation_verified: break
                    
                    if not self._basestation_verified:
                        self.serial.disconnect()
                        tested_ports.add(target)
                    else:
                        tested_ports.clear()
            time.sleep(2.0)

    def _watchdog_loop(self):
        while self._manager_running:
            if self.is_acquiring:
                now = time.time()
                for node_id in self.state.get_all_node_ids():
                    if self.state.is_node_healthy(node_id):
                        if now - self.state.get_last_seen(node_id) > 5.0:
                            self.state.update_health(node_id, False)
                            if self._on_node_event:
                                mac = self.state.get_node_mac(node_id)
                                self._on_node_event(TimeoutFrame(node_id=node_id, mac=mac))
            time.sleep(1.0)

    def _on_connection_change_internal(self, connected: bool):
        if self._on_connection_change:
            self._on_connection_change(connected)

    def cleanup(self):
        self._manager_running = False
        self.serial.disconnect()
        self.state.save_aliases()
