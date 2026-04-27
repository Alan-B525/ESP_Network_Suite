"""
protocol_parser.py - Deserializador de tramas del Gateway TDMA v4
=====================================================================

Interpreta las tramas CSV recibidas por el puerto serie desde la
Base Station (Comunicacion_ESPNOW). Formato del firmware v4.

Tramas soportadas:
  DATA      : DATA,node_id,ch_id,seq,encoding,first_idx,count,val1,...
  TIMING    : TIMING,node_id,ch_id,sample_rate_hz,dt_us,t0_epoch_ms,t0_idx
  BEACON    : BEACON,seq,STATE=s,NODES=n,SLOT_US=us,RTC=ms,SCHED=...,ACKS=...
  HELLO     : HELLO,node_id,mac,CH=mask,RATE=hz
  NODE_JOIN : NODE_JOIN,node_id,mac
  NODE_TIMEOUT: NODE_TIMEOUT,node_id,mac
  LOSS      : LOSS,node_id,EXPECTED=x,GOT=y
  ACK       : ACK,command,result
  BOOT      : BOOT,key[,value]
  WARN      : WARN,type,detail
  STATS_BEGIN / NODE,... / STATS_END
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union
import struct


# ============================================================
# Dataclasses para cada tipo de trama
# ============================================================

@dataclass
class DataFrame:
    """Trama de datos de un nodo sensor (v4: con channel_id y first_sample_index)."""
    node_id: int
    channel_id: int
    sequence: int
    encoding: int
    first_sample_index: int
    sample_count: int
    values: list[float]
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
    """Trama de beacon v4 con system_state, RTC, schedule y rate."""
    beacon_sequence: int
    system_state: int = 0
    active_nodes: int = 0
    slot_us: int = 0
    sample_rate_hz: int = 0
    rtc_epoch_ms: int = 0
    schedule: list[int] = field(default_factory=list)
    ack_map: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HelloFrame:
    """Trama HELLO v4 con multi-canal."""
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
    expected_seq: int
    got_seq: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AckFrame:
    """Trama ACK — respuesta a un comando."""
    command: str
    result: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class NodeStatsEntry:
    """Estadísticas de un nodo en un bloque STATS."""
    node_id: int
    mac: str = ""
    channel_mask: int = 0
    sample_rate_hz: int = 0
    rx: int = 0
    emit: int = 0
    acked: int = 0
    lost: int = 0
    invalid: int = 0
    age_ms: int = 0


@dataclass
class StatsFrame:
    """Bloque STATS_BEGIN...STATS_END completo."""
    state: int = 0
    active_nodes: int = 0
    slot_us: int = 0
    rx_overrun: int = 0
    beacon_tx_err: int = 0
    tx_err: int = 0
    nodes: list = field(default_factory=list)
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
    warn_type: str
    detail: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TelemetryFrame:
    """Trama TELEMETRY."""
    node_id: int
    rssi_dbm: int
    battery_pct: int
    temperature_c: int
    buffer_usage_pct: int
    overflow_count: int
    tx_errors: int
    uptime_s: int
    timestamp: datetime = field(default_factory=datetime.now)


# Tipo unión
ParsedFrame = Union[
    DataFrame, TimingFrame, BeaconFrame, HelloFrame, JoinFrame,
    TimeoutFrame, LossFrame, StatsFrame, BootFrame, WarnFrame, AckFrame, TelemetryFrame
]


# ============================================================
# Clase Parser
# ============================================================

class ProtocolParser:
    """Parser de protocolo para tramas del Gateway TDMA v4."""

    def __init__(self):
        self._in_stats_block = False
        self._stats_lines: list[str] = []

    def parse_decoded(self, data: bytes) -> Optional[ParsedFrame]:
        if not data:
            return None
            
        msg_type = data[0]
        payload = data[1:]
        
        if msg_type == 0x01: # SER_MSG_ASCII
            try:
                line = payload.decode('utf-8', errors='replace')
                return self.parse(line)
            except Exception as e:
                print(f"[PARSER] Error decoding ASCII: {e}")
                return None
                
        elif msg_type == 0x02: # SER_MSG_DATA
            if len(payload) < 14:
                return None
            # uint8 type, version, node_id, channel_id, encoding, reserved
            # uint16 sequence_id, sample_count
            # uint32 first_sample_index
            header = struct.unpack('<BBBBBBHHI', payload[:14])
            
            node_id = header[2]
            channel_id = header[3]
            encoding = header[4]
            sequence = header[6]
            sample_count = header[7]
            first_idx = header[8]
            
            samples_data = payload[14:]
            values = []
            if encoding == 2: # FLOAT32
                if len(samples_data) >= sample_count * 4:
                    values = list(struct.unpack(f'<{sample_count}f', samples_data[:sample_count*4]))
            elif encoding == 3: # DELTA_8BIT
                if sample_count > 0 and len(samples_data) >= 2 + (sample_count - 1):
                    base_val = struct.unpack('<h', samples_data[:2])[0]
                    values.append(float(base_val))
                    if sample_count > 1:
                        deltas = struct.unpack(f'<{sample_count-1}b', samples_data[2:2+(sample_count-1)])
                        current = base_val
                        for d in deltas:
                            current += d
                            values.append(float(current))
            else: # INT16
                if len(samples_data) >= sample_count * 2:
                    values = list(struct.unpack(f'<{sample_count}h', samples_data[:sample_count*2]))
                    
            return DataFrame(node_id, channel_id, sequence, encoding, first_idx, sample_count, values)
            
        elif msg_type == 0x03: # SER_MSG_TIMING
            if len(payload) < 24:
                return None
            # uint8 type, version, node_id, channel_id
            # uint32 sample_rate, dt_us
            # uint64 t0_epoch
            # uint32 t0_sample_idx
            header = struct.unpack('<BBBBIIQI', payload[:24])
            return TimingFrame(
                node_id=header[2],
                channel_id=header[3],
                sample_rate_hz=header[4],
                dt_us=header[5],
                t0_epoch_ms=header[6],
                t0_sample_index=header[7]
            )
            
        return None

    def parse(self, raw_line: str) -> Optional[ParsedFrame]:
        line = raw_line.strip()
        if not line:
            return None

        # ---- Bloque STATS multilinea ----
        if line == "STATS_BEGIN":
            self._in_stats_block = True
            self._stats_lines = []
            return None

        if self._in_stats_block:
            if line == "STATS_END":
                self._in_stats_block = False
                return self._parse_stats_block(self._stats_lines)
            else:
                self._stats_lines.append(line)
                return None

        # ---- Líneas individuales ----
        try:
            if line.startswith("DATA,"):
                return self._parse_data(line)
            elif line.startswith("TIMING,"):
                return self._parse_timing(line)
            elif line.startswith("BEACON,"):
                return self._parse_beacon(line)
            elif line.startswith("HELLO,"):
                return self._parse_hello(line)
            elif line.startswith("NODE_JOIN,"):
                return self._parse_node_event(line, "join")
            elif line.startswith("NODE_TIMEOUT,"):
                return self._parse_node_event(line, "timeout")
            elif line.startswith("LOSS,"):
                return self._parse_loss(line)
            elif line.startswith("ACK,"):
                return self._parse_ack(line)
            elif line.startswith("BOOT,"):
                return self._parse_boot(line)
            elif line.startswith("WARN,"):
                return self._parse_warn(line)
            elif line.startswith("TELEMETRY,"):
                return self._parse_telemetry(line)
            else:
                return None

        except (ValueError, IndexError, KeyError) as e:
            print(f"[PARSER] Error parseando: '{line}' -> {e}")
            return None

    # ============================================================
    # Parsers internos
    # ============================================================

    @staticmethod
    def _parse_data(line: str) -> DataFrame:
        """
        DATA,node_id,ch_id,seq,encoding,first_idx,count,val1,val2,...
        """
        parts = line.split(",")
        node_id = int(parts[1])
        channel_id = int(parts[2])
        sequence = int(parts[3])
        encoding = int(parts[4])
        first_idx = int(parts[5])
        count = int(parts[6])

        if encoding == 2:  # FLOAT32
            values = [float(v) for v in parts[7:] if v]
        else:  # INT16
            values = [float(int(v)) for v in parts[7:] if v]

        return DataFrame(
            node_id=node_id,
            channel_id=channel_id,
            sequence=sequence,
            encoding=encoding,
            first_sample_index=first_idx,
            sample_count=count,
            values=values,
        )

    @staticmethod
    def _parse_timing(line: str) -> TimingFrame:
        """
        TIMING,node_id,ch_id,sample_rate_hz,dt_us,t0_epoch_ms,t0_idx
        """
        parts = line.split(",")
        return TimingFrame(
            node_id=int(parts[1]),
            channel_id=int(parts[2]),
            sample_rate_hz=int(parts[3]),
            dt_us=int(parts[4]),
            t0_epoch_ms=int(parts[5]),
            t0_sample_index=int(parts[6]),
        )

    @staticmethod
    def _parse_beacon(line: str) -> BeaconFrame:
        """
        BEACON,seq,STATE=s,NODES=n,SLOT_US=us,RTC=ms,SCHED=id;id;...,ACKS=id:seq;...
        """
        parts = line.split(",")
        seq = int(parts[1])
        state = 0
        nodes = 0
        slot_us = 0
        rate = 0
        rtc = 0
        schedule = []
        ack_map = {}

        for part in parts[2:]:
            if part.startswith("STATE="):
                state = int(part.split("=")[1])
            elif part.startswith("NODES="):
                nodes = int(part.split("=")[1])
            elif part.startswith("SLOT_US="):
                slot_us = int(part.split("=")[1])
            elif part.startswith("RATE="):
                rate = int(part.split("=")[1])
            elif part.startswith("RTC="):
                rtc = int(part.split("=")[1])
            elif part.startswith("SCHED="):
                sched_str = part.split("=")[1]
                if sched_str:
                    schedule = [int(s) for s in sched_str.split(";") if s]
            elif part.startswith("ACKS="):
                acks_str = part.split("=")[1]
                if acks_str:
                    for entry in acks_str.split(";"):
                        if ":" in entry:
                            nid, aseq = entry.split(":")
                            ack_map[int(nid)] = int(aseq)

        return BeaconFrame(
            beacon_sequence=seq,
            system_state=state,
            active_nodes=nodes,
            slot_us=slot_us,
            sample_rate_hz=rate,
            rtc_epoch_ms=rtc,
            schedule=schedule,
            ack_map=ack_map,
        )

    @staticmethod
    def _parse_hello(line: str) -> HelloFrame:
        """
        HELLO,node_id,mac,CH=mask,RATE=hz
        """
        parts = line.split(",")
        node_id = int(parts[1])
        mac = parts[2] if len(parts) > 2 else ""
        ch_mask = 0
        rate = 0

        for part in parts[3:]:
            if part.startswith("CH="):
                ch_mask = int(part.split("=")[1], 0)  # Supports 0x prefix
            elif part.startswith("RATE="):
                rate = int(part.split("=")[1])

        return HelloFrame(
            node_id=node_id, mac=mac,
            channel_mask=ch_mask, sample_rate_hz=rate,
        )

    @staticmethod
    def _parse_node_event(line: str, event_type: str):
        parts = line.split(",", 2)
        node_id = int(parts[1])
        mac = parts[2] if len(parts) > 2 else ""

        if event_type == "join":
            return JoinFrame(node_id=node_id, mac=mac)
        elif event_type == "timeout":
            return TimeoutFrame(node_id=node_id, mac=mac)

    @staticmethod
    def _parse_loss(line: str) -> LossFrame:
        parts = line.split(",")
        node_id = int(parts[1])
        expected = 0
        got = 0
        for part in parts[2:]:
            if part.startswith("EXPECTED="):
                expected = int(part.split("=")[1])
            elif part.startswith("GOT="):
                got = int(part.split("=")[1])
        return LossFrame(node_id=node_id, expected_seq=expected, got_seq=got)

    @staticmethod
    def _parse_ack(line: str) -> AckFrame:
        parts = line.split(",", 2)
        command = parts[1] if len(parts) > 1 else ""
        result = parts[2] if len(parts) > 2 else ""
        return AckFrame(command=command, result=result)

    @staticmethod
    def _parse_boot(line: str) -> BootFrame:
        parts = line.split(",", 2)
        key = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        return BootFrame(key=key, value=value)

    @staticmethod
    def _parse_warn(line: str) -> WarnFrame:
        parts = line.split(",", 2)
        warn_type = parts[1] if len(parts) > 1 else "UNKNOWN"
        detail = parts[2] if len(parts) > 2 else ""
        return WarnFrame(warn_type=warn_type, detail=detail)

    @staticmethod
    def _parse_telemetry(line: str) -> TelemetryFrame:
        parts = line.split(',')
        return TelemetryFrame(
            node_id=int(parts[1]),
            rssi_dbm=int(parts[2]),
            battery_pct=int(parts[3]),
            temperature_c=int(parts[4]),
            buffer_usage_pct=int(parts[5]),
            overflow_count=int(parts[6]),
            tx_errors=int(parts[7]),
            uptime_s=int(parts[8])
        )

    @staticmethod
    def _parse_stats_block(lines: list[str]) -> StatsFrame:
        frame = StatsFrame()
        for line in lines:
            parts = line.split(",")
            if parts[0] == "STATS" and len(parts) >= 3:
                key, val = parts[1], parts[2]
                if key == "STATE":        frame.state = int(val)
                elif key == "ACTIVE_NODES": frame.active_nodes = int(val)
                elif key == "SLOT_US":    frame.slot_us = int(val)
                elif key == "RX_OVERRUN": frame.rx_overrun = int(val)
                elif key == "BEACON_TX_ERR": frame.beacon_tx_err = int(val)
                elif key == "TX_ERR":     frame.tx_err = int(val)

            elif parts[0] == "NODE" and len(parts) >= 2:
                entry = NodeStatsEntry(node_id=int(parts[1]))
                for part in parts[2:]:
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    if k == "MAC":     entry.mac = v
                    elif k == "CH":    entry.channel_mask = int(v, 0)
                    elif k == "RATE":  entry.sample_rate_hz = int(v)
                    elif k == "RX":    entry.rx = int(v)
                    elif k == "EMIT":  entry.emit = int(v)
                    elif k == "ACKED": entry.acked = int(v)
                    elif k == "LOST":  entry.lost = int(v)
                    elif k == "INVALID": entry.invalid = int(v)
                    elif k == "AGE_MS": entry.age_ms = int(v)
                frame.nodes.append(entry)

        return frame
