# ============================================================
# core/__init__.py - Paquete de logica central
# ============================================================
# Este paquete contiene toda la logica de negocio separada de la UI:
#   - serial_manager: Comunicacion serie en hilo dedicado
#   - protocol_parser: Deserializacion de tramas del Gateway TDMA v3
#   - data_logger: Persistencia robusta de datos a CSV
# ============================================================

from core.protocol_parser import (
    ProtocolParser, DataFrame, BeaconFrame, HelloFrame, JoinFrame,
    TimeoutFrame, LossFrame, StatsFrame, BootFrame, WarnFrame, AckFrame,
)
from core.serial_manager import SerialManager
from core.data_logger import DataLogger

__all__ = [
    "ProtocolParser",
    "DataFrame",
    "BeaconFrame",
    "HelloFrame",
    "JoinFrame",
    "TimeoutFrame",
    "LossFrame",
    "StatsFrame",
    "BootFrame",
    "WarnFrame",
    "AckFrame",
    "SerialManager",
    "DataLogger",
]
