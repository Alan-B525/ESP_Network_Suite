"""
protocol_parser.py - Unified Entry Point for v5 Protocol Parsing
================================================================
Simplified facade that delegates to specialized sub-parsers.
"""

from typing import Optional, Union, List
from .protocol.frames import (
    DataFrame, TimingFrame, BeaconFrame, HelloFrame, JoinFrame,
    TimeoutFrame, LossFrame, AckFrame, BootFrame, WarnFrame, 
    StatsFrame, TelemetryFrame
)
from .protocol.binary_parser import BinaryParser
from .protocol.ascii_parser import AsciiParser

# Union type for all possible parsed frames
ParsedFrame = Union[
    DataFrame, TimingFrame, BeaconFrame, HelloFrame, JoinFrame,
    TimeoutFrame, LossFrame, StatsFrame, BootFrame, WarnFrame, 
    AckFrame, TelemetryFrame
]

__all__ = [
    "ProtocolParser", "DataFrame", "TimingFrame", "BeaconFrame", 
    "HelloFrame", "JoinFrame", "TimeoutFrame", "LossFrame", 
    "AckFrame", "BootFrame", "WarnFrame", "StatsFrame", "TelemetryFrame"
]

class ProtocolParser:
    """Facade for the ESP-NOW Sensor Protocol v5."""

    def __init__(self):
        self._binary = BinaryParser()
        self._ascii = AsciiParser()
        self._in_stats_block = False
        self._stats_lines: List[str] = []

    def parse_decoded(self, data: bytes) -> Optional[ParsedFrame]:
        """Parses a raw decoded (COBS-removed) byte buffer."""
        if not data:
            return None
            
        msg_type = data[0]
        payload = data[1:]
        
        if msg_type == 0x01: # ASCII Message
            try:
                line = payload.decode('utf-8', errors='replace')
                return self.parse_ascii(line)
            except:
                return None
                
        elif msg_type == 0x02: # Binary Data
            return self._binary.parse_data(payload)
            
        elif msg_type == 0x03: # Binary Timing
            return self._binary.parse_timing(payload)
            
        return None

    def parse_ascii(self, line: str) -> Optional[ParsedFrame]:
        """Parses a single ASCII line, handling multi-line blocks."""
        line = line.strip()
        if not line:
            return None

        # Handle multi-line Stats block
        if line == "STATS_BEGIN":
            self._in_stats_block = True
            self._stats_lines = []
            return None

        if self._in_stats_block:
            if line == "STATS_END":
                self._in_stats_block = False
                return self._ascii.parse_stats_block(self._stats_lines)
            self._stats_lines.append(line)
            return None

        # Handle individual ASCII commands/responses
        return self._ascii.parse_line(line)
