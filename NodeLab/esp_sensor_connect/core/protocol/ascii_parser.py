from typing import Optional, List
from .frames import (
    DataFrame, TimingFrame, BeaconFrame, HelloFrame, JoinFrame,
    TimeoutFrame, LossFrame, AckFrame, BootFrame, WarnFrame, 
    TelemetryFrame, StatsFrame, NodeStat
)

class AsciiParser:
    """Handles parsing of human-readable comma-separated ASCII lines."""

    @staticmethod
    def parse_line(line: str) -> Optional[any]:
        line = line.strip()
        if not line: return None
        
        try:
            if line.startswith("DATA,"): return AsciiParser._parse_data(line)
            if line.startswith("TIMING,"): return AsciiParser._parse_timing(line)
            if line.startswith("BEACON,"): return AsciiParser._parse_beacon(line)
            if line.startswith("HELLO,"): return AsciiParser._parse_hello(line)
            if line.startswith("NODE_JOIN,"): return AsciiParser._parse_node_event(line, "join")
            if line.startswith("NODE_TIMEOUT,"): return AsciiParser._parse_node_event(line, "timeout")
            if line.startswith("LOSS,"): return AsciiParser._parse_loss(line)
            if line.startswith("ACK,"): return AsciiParser._parse_ack(line)
            if line.startswith("BOOT,"): return AsciiParser._parse_boot(line)
            if line.startswith("WARN,"): return AsciiParser._parse_warn(line)
            if line.startswith("TELEMETRY,"): return AsciiParser._parse_telemetry(line)
        except Exception as e:
            print(f"[ASCII_PARSER] Error: {line} -> {e}")
        return None

    @staticmethod
    def _parse_data(line: str) -> DataFrame:
        parts = line.split(",")
        return DataFrame(
            node_id=int(parts[1]),
            channel_id=int(parts[2]),
            sequence=int(parts[3]),
            encoding=int(parts[4]),
            first_sample_index=int(parts[5]),
            sample_count=int(parts[6]),
            values=[float(v) for v in parts[7:] if v]
        )

    @staticmethod
    def _parse_timing(line: str) -> TimingFrame:
        parts = line.split(",")
        return TimingFrame(
            node_id=int(parts[1]),
            channel_id=int(parts[2]),
            sample_rate_hz=int(parts[3]),
            dt_us=int(parts[4]),
            t0_epoch_ms=int(parts[5]),
            t0_sample_index=int(parts[6])
        )

    @staticmethod
    def _parse_beacon(line: str) -> BeaconFrame:
        parts = line.split(",")
        seq = int(parts[1])
        frame = BeaconFrame(beacon_sequence=seq)
        for part in parts[2:]:
            if "=" not in part: continue
            k, v = part.split("=", 1)
            if k == "STATE": frame.system_state = int(v)
            elif k == "NODES": frame.active_nodes = int(v)
            elif k == "SLOT_US": frame.slot_us = int(v)
            elif k == "RATE": frame.sample_rate_hz = int(v)
            elif k == "RTC": frame.rtc_epoch_ms = int(v)
            elif k == "SCHED" and v: frame.schedule = [int(s) for s in v.split(";") if s]
            elif k == "ACKS" and v:
                for entry in v.split(";"):
                    if ":" in entry:
                        nid, aseq = entry.split(":")
                        frame.ack_map[int(nid)] = int(aseq)
        return frame

    @staticmethod
    def _parse_hello(line: str) -> HelloFrame:
        parts = line.split(",")
        node_id = int(parts[1])
        mac = parts[2] if len(parts) > 2 else ""
        frame = HelloFrame(node_id=node_id, mac=mac)
        for part in parts[3:]:
            if "=" not in part: continue
            k, v = part.split("=", 1)
            if k == "CH": frame.channel_mask = int(v, 0)
            elif k == "RATE": frame.sample_rate_hz = int(v)
        return frame

    @staticmethod
    def _parse_node_event(line: str, event_type: str):
        parts = line.split(",")
        node_id = int(parts[1])
        mac = parts[2] if len(parts) > 2 else ""
        return JoinFrame(node_id, mac) if event_type == "join" else TimeoutFrame(node_id, mac)

    @staticmethod
    def _parse_loss(line: str) -> LossFrame:
        parts = line.split(",")
        node_id = int(parts[1])
        expected, got = 0, 0
        for part in parts[2:]:
            if "=" not in part: continue
            k, v = part.split("=", 1)
            if k == "EXPECTED": expected = int(v)
            elif k == "GOT": got = int(v)
        return LossFrame(node_id, expected, got)

    @staticmethod
    def _parse_ack(line: str) -> AckFrame:
        parts = line.split(",", 2)
        command = parts[1] if len(parts) > 1 else ""
        result_str = parts[2] if len(parts) > 2 else "0"
        try:
            result = int(result_str)
        except ValueError:
            result = 1 if result_str.upper() == "OK" else 0
        return AckFrame(command, result)

    @staticmethod
    def _parse_boot(line: str) -> BootFrame:
        parts = line.split(",", 2)
        return BootFrame(parts[1] if len(parts)>1 else "", parts[2] if len(parts)>2 else "")

    @staticmethod
    def _parse_warn(line: str) -> WarnFrame:
        parts = line.split(",", 2)
        return WarnFrame(parts[1] if len(parts)>1 else "WARN", parts[2] if len(parts)>2 else "")

    @staticmethod
    def _parse_telemetry(line: str) -> TelemetryFrame:
        parts = line.split(",")
        return TelemetryFrame(int(parts[1]), int(parts[3]), int(parts[2]))

    @staticmethod
    def parse_stats_block(lines: List[str]) -> StatsFrame:
        frame = StatsFrame()
        for line in lines:
            parts = line.split(",")
            if parts[0] == "NODE" and len(parts) >= 2:
                node = NodeStat(int(parts[1]), 0, 0)
                for part in parts[2:]:
                    if "=" not in part: continue
                    k, v = part.split("=", 1)
                    if k == "EMIT": node.emit = int(v)
                    elif k == "LOST": node.lost = int(v)
                frame.nodes.append(node)
        return frame
