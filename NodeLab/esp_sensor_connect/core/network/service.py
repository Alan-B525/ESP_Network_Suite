import threading
import time
import serial
import serial.tools.list_ports
from typing import Optional, Callable, List, Dict

class SerialService:
    """
    Handles low-level serial communication, COBS decoding, and port lifecycle.
    """
    def __init__(self, on_frame_received: Callable[[bytes], None], 
                 on_connection_change: Optional[Callable[[bool], None]] = None):
        self._serial: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        
        self.is_connected = False
        self.current_port = ""
        self.current_baudrate = 0
        
        self._on_frame_received = on_frame_received
        self._on_connection_change = on_connection_change
        self.on_line_received: Optional[Callable[[str], None]] = None
        
        self.data_queue = None # For DataLogger compatibility

    @staticmethod
    def list_ports() -> List[Dict]:
        ports = serial.tools.list_ports.comports()
        return [
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
                "manufacturer": port.manufacturer or "Unknown",
            }
            for port in sorted(ports, key=lambda p: p.device)
        ]

    def connect(self, port: str, baudrate: int, timeout: float = 1.0) -> bool:
        if self.is_connected:
            self.disconnect()

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=timeout,
                write_timeout=0.5,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
            self.is_connected = True
            self.current_port = port
            self.current_baudrate = baudrate
            self._running.set()
            
            self._reader_thread = threading.Thread(
                target=self._reader_loop, name="SerialReader", daemon=True
            )
            self._reader_thread.start()
            
            if self._on_connection_change:
                self._on_connection_change(True)
            return True
        except serial.SerialException as e:
            print(f"[SERIAL] Connection error to {port}: {e}")
            return False

    def disconnect(self):
        self._running.clear()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        
        if self._serial and self._serial.is_open:
            try:
                self._serial.close()
            except:
                pass
        
        self._serial = None
        self.is_connected = False
        self.current_port = ""
        
        if self._on_connection_change:
            self._on_connection_change(False)

    def send(self, data: str) -> bool:
        if not self.is_connected or not self._serial:
            return False
        try:
            if not data.endswith('\n'):
                data += '\n'
            self._serial.write(data.encode('utf-8'))
            self._serial.flush()
            return True
        except Exception as e:
            print(f"[SERIAL] Send error: {e}")
            self._handle_disconnect()
            return False

    def _cobs_decode(self, data: bytes) -> bytes:
        if not data or len(data) < 2: return b''
        decoded = bytearray()
        i = 0
        try:
            while i < len(data):
                code = data[i]
                if code == 0: break
                i += 1
                for _ in range(1, code):
                    if i >= len(data): return b''
                    decoded.append(data[i])
                    i += 1
                if code < 0xFF and i < len(data):
                    decoded.append(0)
        except:
            return b''
        return bytes(decoded)

    def _reader_loop(self):
        while self._running.is_set():
            try:
                if not self._serial or not self._serial.is_open:
                    time.sleep(0.1)
                    continue

                if self._serial.in_waiting > 0:
                    # Read one byte to see if it's COBS or ASCII
                    peek = self._serial.read(1)
                    if not peek: continue

                    if peek == b'\x00': # Empty frame or separator
                        continue
                        
                    # If it's a typical ASCII start or not COBS code
                    if peek.isalnum() or peek in b' \r\n#[':
                        line = peek + self._serial.readline()
                        try:
                            decoded_line = line.decode('utf-8', errors='ignore').strip()
                            if decoded_line and self.on_line_received:
                                self.on_line_received(decoded_line)
                        except:
                            pass
                    else:
                        # Assume COBS
                        raw_data = peek + self._serial.read_until(b'\x00')
                        if raw_data[-1] == 0:
                            decoded = self._cobs_decode(raw_data[:-1])
                            if decoded:
                                self._on_frame_received(decoded)
                else:
                    time.sleep(0.001)
            except (PermissionError, OSError, serial.SerialException) as e:
                print(f"[SERIAL] Hardware disconnect: {e}")
                self._handle_disconnect()
                break
            except Exception as e:
                print(f"[SERIAL] Reader error: {e}")
                time.sleep(0.01)

    def _handle_disconnect(self):
        failed_port = self.current_port
        self.disconnect()
        self._auto_connect_cooldown = time.time() + 5.0
        self._last_failed_port = failed_port

    def can_auto_connect(self) -> bool:
        return not self.is_connected and time.time() >= self._auto_connect_cooldown
