import struct
from typing import Optional, List
from .frames import (
    DataFrame, TimingFrame, TelemetryFrame
)

class BinaryParser:
    """Handles parsing of structured binary COBS frames."""

    @staticmethod
    def parse_data(payload: bytes) -> Optional[DataFrame]:
        if len(payload) < 16:
            return None
            
        # uint8 type, version, node_id, channel_id, encoding, reserved
        # uint16 sequence_id, sample_count
        # uint32 first_sample_index
        # uint16 crc16
        header = struct.unpack('<BBBBBBHHIH', payload[:16])
        
        node_id = header[2]
        channel_id = header[3]
        encoding = header[4]
        sequence = header[6]
        sample_count = header[7]
        first_idx = header[8]
        
        samples_data = payload[16:]
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

    @staticmethod
    def parse_timing(payload: bytes) -> Optional[TimingFrame]:
        if len(payload) < 24:
            return None
        header = struct.unpack('<BBBBIIQI', payload[:24])
        return TimingFrame(
            node_id=header[2],
            channel_id=header[3],
            sample_rate_hz=header[4],
            dt_us=header[5],
            t0_epoch_ms=header[6],
            t0_sample_index=header[7]
        )
