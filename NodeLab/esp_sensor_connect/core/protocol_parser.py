"""
protocol_parser.py - Deserializador de tramas del Gateway TDMA ESP32
=====================================================================

Interpreta las tramas CSV recibidas por el puerto serie desde la
Base Station (Comunicacion_ESPNOW). Formato real del firmware v3.

Tramas soportadas:
  DATA_INT16  : DATA_INT16,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
  DATA_FLOAT  : DATA_FLOAT,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
  BEACON      : BEACON,seq,NODES=n,SLOT_US=us,REG_MS=ms,ACKS=id:seq;...
  HELLO       : HELLO,node_id,mac
  NODE_JOIN   : NODE_JOIN,node_id,mac
  NODE_TIMEOUT: NODE_TIMEOUT,node_id,mac
  LOSS        : LOSS,node_id,EXPECTED=x,GOT=y
  BOOT        : BOOT,key[,value]
  WARN        : WARN,type,detail
  STATS_BEGIN / NODE,... / STATS_END  (bloque multilinea)

Cada trama se convierte en un dataclass tipado para su consumo
seguro por el resto de la aplicacion.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union


# ============================================================
# Dataclasses para cada tipo de trama
# ============================================================

@dataclass
class DataFrame:
    """
    Trama de datos de un nodo sensor (DATA_INT16 o DATA_FLOAT).
    Contiene ID del nodo, secuencia, timestamps y valores.
    """
    node_id: int
    sequence: int
    values: list[float]
    gateway_rx_us: int = 0
    node_timestamp_us: int = 0
    encoding: str = "int16"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BeaconFrame:
    """Trama de beacon enviada por el gateway cada ciclo TDMA."""
    beacon_sequence: int
    active_nodes: int
    slot_us: int = 0
    registration_ms: int = 0
    ack_map: dict = field(default_factory=dict)  # {node_id: highest_acked_seq}
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HelloFrame:
    """Trama HELLO — un nodo se anuncio al gateway."""
    node_id: int
    mac: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class JoinFrame:
    """Trama NODE_JOIN — un nodo fue aceptado en la red."""
    node_id: int
    mac: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TimeoutFrame:
    """Trama NODE_TIMEOUT — un nodo fue removido por inactividad."""
    node_id: int
    mac: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class LossFrame:
    """Trama LOSS — el gateway detecto un gap de secuencia."""
    node_id: int
    expected_seq: int
    got_seq: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class NodeStatsEntry:
    """Estadisticas de un nodo individual dentro de un bloque STATS."""
    node_id: int
    mac: str = ""
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
    direct_ack_tx_err: int = 0
    nodes: list = field(default_factory=list)  # list[NodeStatsEntry]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BootFrame:
    """Trama BOOT — informacion de arranque del gateway."""
    key: str
    value: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class WarnFrame:
    """Trama WARN — advertencia del gateway."""
    warn_type: str
    detail: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AckFrame:
    """
    Trama de confirmacion de comando (compatibilidad con UI).
    El gateway actual no envia esto, pero se mantiene para la interfaz.
    """
    command: str
    result: str
    timestamp: datetime = field(default_factory=datetime.now)


# Tipo union para resultados del parser
ParsedFrame = Union[
    DataFrame, BeaconFrame, HelloFrame, JoinFrame, TimeoutFrame,
    LossFrame, StatsFrame, BootFrame, WarnFrame, AckFrame
]


# ============================================================
# Clase Parser
# ============================================================

class ProtocolParser:
    """
    Parser de protocolo para tramas del Gateway TDMA v3.

    Soporta tanto lineas individuales como bloques multilinea
    (STATS_BEGIN...STATS_END).

    Uso:
        parser = ProtocolParser()
        frame = parser.parse("DATA_INT16,1,105,483921,12340,2048,2100")
        if isinstance(frame, DataFrame):
            print(f"Nodo {frame.node_id}: {frame.values}")
    """

    def __init__(self):
        # Estado para parseo de bloques STATS multilinea
        self._in_stats_block = False
        self._stats_lines: list[str] = []

    def parse(self, raw_line: str) -> Optional[ParsedFrame]:
        """
        Parsea una linea cruda del puerto serie.

        Args:
            raw_line: Linea de texto recibida del puerto serie.

        Returns:
            Un objeto tipado segun el tipo de trama,
            o None si la linea no se reconoce o es invalida.
        """
        line = raw_line.strip()
        if not line:
            return None

        # ---- Manejo de bloque STATS multilinea ----
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

        # ---- Lineas individuales ----
        try:
            if line.startswith("DATA_INT16,"):
                return self._parse_data(line, "int16")
            elif line.startswith("DATA_FLOAT,"):
                return self._parse_data(line, "float32")
            elif line.startswith("BEACON,"):
                return self._parse_beacon(line)
            elif line.startswith("HELLO,"):
                return self._parse_node_event(line, "hello")
            elif line.startswith("NODE_JOIN,"):
                return self._parse_node_event(line, "join")
            elif line.startswith("NODE_TIMEOUT,"):
                return self._parse_node_event(line, "timeout")
            elif line.startswith("LOSS,"):
                return self._parse_loss(line)
            elif line.startswith("BOOT,"):
                return self._parse_boot(line)
            elif line.startswith("WARN,"):
                return self._parse_warn(line)
            else:
                return None

        except (ValueError, IndexError, KeyError) as e:
            print(f"[PARSER] Error parseando: '{line}' -> {e}")
            return None

    # ============================================================
    # Parsers internos
    # ============================================================

    @staticmethod
    def _parse_data(line: str, encoding: str) -> DataFrame:
        """
        Parsea DATA_INT16 o DATA_FLOAT.

        Formato: DATA_INT16,node_id,seq,gw_rx_us,node_ts_us,val1,val2,...
        """
        parts = line.split(",")
        # parts[0] = "DATA_INT16" o "DATA_FLOAT"
        node_id = int(parts[1])
        sequence = int(parts[2])
        gw_rx_us = int(parts[3])
        node_ts_us = int(parts[4])

        if encoding == "float32":
            values = [float(v) for v in parts[5:]]
        else:
            values = [float(int(v)) for v in parts[5:]]

        return DataFrame(
            node_id=node_id,
            sequence=sequence,
            values=values,
            gateway_rx_us=gw_rx_us,
            node_timestamp_us=node_ts_us,
            encoding=encoding,
        )

    @staticmethod
    def _parse_beacon(line: str) -> BeaconFrame:
        """
        Parsea linea BEACON.

        Formato: BEACON,seq,NODES=n,SLOT_US=us,REG_MS=ms,ACKS=id:seq;id:seq
        """
        parts = line.split(",")
        seq = int(parts[1])

        nodes = 0
        slot_us = 0
        reg_ms = 0
        ack_map = {}

        for part in parts[2:]:
            if part.startswith("NODES="):
                nodes = int(part.split("=")[1])
            elif part.startswith("SLOT_US="):
                slot_us = int(part.split("=")[1])
            elif part.startswith("REG_MS="):
                reg_ms = int(part.split("=")[1])
            elif part.startswith("ACKS="):
                acks_str = part.split("=")[1]
                if acks_str:
                    for entry in acks_str.split(";"):
                        if ":" in entry:
                            nid, aseq = entry.split(":")
                            ack_map[int(nid)] = int(aseq)

        return BeaconFrame(
            beacon_sequence=seq,
            active_nodes=nodes,
            slot_us=slot_us,
            registration_ms=reg_ms,
            ack_map=ack_map,
        )

    @staticmethod
    def _parse_node_event(line: str, event_type: str):
        """
        Parsea HELLO, NODE_JOIN, NODE_TIMEOUT.

        Formato: HELLO,node_id,mac
                 NODE_JOIN,node_id,mac
                 NODE_TIMEOUT,node_id,mac
        """
        parts = line.split(",", 2)
        # parts[0] = prefix, rest depends on type

        if event_type == "hello":
            # HELLO,node_id,mac
            node_id = int(parts[1])
            mac = parts[2] if len(parts) > 2 else ""
            return HelloFrame(node_id=node_id, mac=mac)

        elif event_type == "join":
            # NODE_JOIN,node_id,mac
            node_id = int(parts[1])
            mac = parts[2] if len(parts) > 2 else ""
            return JoinFrame(node_id=node_id, mac=mac)

        elif event_type == "timeout":
            # NODE_TIMEOUT,node_id,mac
            node_id = int(parts[1])
            mac = parts[2] if len(parts) > 2 else ""
            return TimeoutFrame(node_id=node_id, mac=mac)

    @staticmethod
    def _parse_loss(line: str) -> LossFrame:
        """
        Parsea linea LOSS.

        Formato: LOSS,node_id,EXPECTED=x,GOT=y
        """
        parts = line.split(",")
        node_id = int(parts[1])
        expected = 0
        got = 0

        for part in parts[2:]:
            if part.startswith("EXPECTED="):
                expected = int(part.split("=")[1])
            elif part.startswith("GOT="):
                got = int(part.split("=")[1])

        return LossFrame(
            node_id=node_id,
            expected_seq=expected,
            got_seq=got,
        )

    @staticmethod
    def _parse_boot(line: str) -> BootFrame:
        """
        Parsea linea BOOT.

        Formato: BOOT,key[,value]
        """
        parts = line.split(",", 2)
        key = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        return BootFrame(key=key, value=value)

    @staticmethod
    def _parse_warn(line: str) -> WarnFrame:
        """
        Parsea linea WARN.

        Formato: WARN,type,detail,...
        """
        parts = line.split(",", 2)
        warn_type = parts[1] if len(parts) > 1 else "UNKNOWN"
        detail = parts[2] if len(parts) > 2 else ""
        return WarnFrame(warn_type=warn_type, detail=detail)

    @staticmethod
    def _parse_stats_block(lines: list[str]) -> StatsFrame:
        """
        Parsea un bloque STATS_BEGIN...STATS_END completo.

        Lineas esperadas dentro del bloque:
          STATS,STATE,1
          STATS,ACTIVE_NODES,2
          STATS,SLOT_US,440000
          STATS,RX_OVERRUN,0
          STATS,BEACON_TX_ERR,0
          STATS,DIRECT_ACK_TX_ERR,0
          NODE,1,MAC=AA:BB:...,RX=320,EMIT=315,...
        """
        frame = StatsFrame()

        for line in lines:
            parts = line.split(",")

            if parts[0] == "STATS" and len(parts) >= 3:
                key = parts[1]
                val = parts[2]
                if key == "STATE":
                    frame.state = int(val)
                elif key == "ACTIVE_NODES":
                    frame.active_nodes = int(val)
                elif key == "SLOT_US":
                    frame.slot_us = int(val)
                elif key == "RX_OVERRUN":
                    frame.rx_overrun = int(val)
                elif key == "BEACON_TX_ERR":
                    frame.beacon_tx_err = int(val)
                elif key == "DIRECT_ACK_TX_ERR":
                    frame.direct_ack_tx_err = int(val)

            elif parts[0] == "NODE" and len(parts) >= 2:
                entry = NodeStatsEntry(node_id=int(parts[1]))
                for part in parts[2:]:
                    if "=" not in part:
                        continue
                    k, v = part.split("=", 1)
                    if k == "MAC":
                        entry.mac = v
                    elif k == "RX":
                        entry.rx = int(v)
                    elif k == "EMIT":
                        entry.emit = int(v)
                    elif k == "ACKED":
                        entry.acked = int(v)
                    elif k == "LOST":
                        entry.lost = int(v)
                    elif k == "INVALID":
                        entry.invalid = int(v)
                    elif k == "AGE_MS":
                        entry.age_ms = int(v)
                frame.nodes.append(entry)

        return frame
