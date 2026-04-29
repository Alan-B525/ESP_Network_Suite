from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any

@dataclass
class DataFrame:
    """Trama de datos de un nodo sensor."""
    node_id: int
    channel_id: int
    sequence: int
    encoding: int
    first_sample_index: int
    sample_count: int
    values: List[float]
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class TimingFrame:
    """Trama TIMING_INFO — sincronización temporal t0+dt."""
    node_id: int
    channel_id: int
    sample_rate_hz: int
    dt_us: int
    t0_epoch_ms: int
    t0_sample_index: int
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class BeaconFrame:
    """Trama de beacon v5 con system_state, RTC, schedule y rate."""
    beacon_sequence: int
    system_state: int = 0
    active_nodes: int = 0
    slot_us: int = 0
    sample_rate_hz: int = 0
    rtc_epoch_ms: int = 0
    schedule: List[int] = field(default_factory=list)
    ack_map: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class HelloFrame:
    """Trama HELLO v5 con multi-canal."""
    node_id: int
    mac: str
    channel_mask: int = 0
    sample_rate_hz: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class JoinFrame:
    """Trama NODE_JOIN."""
    node_id: int
    mac: str
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class TimeoutFrame:
    """Trama NODE_TIMEOUT."""
    node_id: int
    mac: str
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class LossFrame:
    """Trama LOSS — gap de secuencia detectado."""
    node_id: int
    expected: int
    got: int
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class AckFrame:
    """Trama ACK de comandos."""
    command: str
    result: int
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class BootFrame:
    """Trama BOOT."""
    key: str
    value: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class WarnFrame:
    """Trama WARN."""
    warning_type: str
    detail: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class NodeStat:
    """Sub-trama de estadísticas por nodo."""
    node_id: int
    emit: int
    lost: int

@dataclass
class StatsFrame:
    """Trama STATS global."""
    nodes: List[NodeStat] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class TelemetryFrame:
    """Trama de telemetría secundaria (batería, RSSI)."""
    node_id: int
    battery_pct: int
    rssi_dbm: int
    timestamp: datetime = field(default_factory=datetime.now)
