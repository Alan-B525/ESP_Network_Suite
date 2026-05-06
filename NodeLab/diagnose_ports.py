"""
diagnose_ports.py — Diagnóstico rápido de puertos seriales
============================================================
Escanea todos los COM ports, intenta conectar a 921600 baud,
y muestra los primeros bytes recibidos de cada uno.
"""
import serial
import serial.tools.list_ports
import time
import sys

def scan_ports():
    ports = serial.tools.list_ports.comports()
    print(f"\n{'='*60}")
    print(f"  PUERTOS SERIALES DETECTADOS: {len(ports)}")
    print(f"{'='*60}")
    
    for p in sorted(ports, key=lambda x: x.device):
        print(f"\n  {p.device}")
        print(f"    Descripcion : {p.description}")
        print(f"    HWID        : {p.hwid}")
        print(f"    Fabricante  : {p.manufacturer or 'Desconocido'}")
    
    print(f"\n{'='*60}")
    print(f"  PROBANDO CADA PUERTO A 921600 BAUD (BaseStation)")
    print(f"{'='*60}")
    
    for p in sorted(ports, key=lambda x: x.device):
        port = p.device
        print(f"\n  [{port}] Conectando a 921600...")
        try:
            ser = serial.Serial(
                port=port,
                baudrate=921600,
                timeout=0.5,
                write_timeout=0.5,
            )
            time.sleep(0.3)  # Esperar a que el dispositivo envíe algo
            
            total_bytes = 0
            raw_sample = b""
            start = time.time()
            
            # Leer durante 3 segundos
            while time.time() - start < 3.0:
                waiting = ser.in_waiting
                if waiting > 0:
                    data = ser.read(min(waiting, 256))
                    total_bytes += len(data)
                    if len(raw_sample) < 100:
                        raw_sample += data[:100 - len(raw_sample)]
                else:
                    time.sleep(0.05)
            
            ser.close()
            
            if total_bytes == 0:
                print(f"    ❌ Sin datos (0 bytes en 3s)")
            else:
                # Check for COBS delimiter (0x00)
                null_count = raw_sample.count(0x00)
                hex_preview = " ".join(f"{b:02X}" for b in raw_sample[:40])
                
                # Try to find ASCII content after COBS decode
                ascii_hint = ""
                for i, b in enumerate(raw_sample):
                    if b == 0x00 and i > 2:
                        # Try COBS decode of first frame
                        frame = raw_sample[:i]
                        try:
                            decoded = cobs_decode(frame)
                            if decoded and decoded[0] == 0x01:
                                ascii_hint = decoded[1:50].decode('utf-8', errors='replace')
                        except:
                            pass
                        break
                
                print(f"    ✅ Recibidos: {total_bytes} bytes en 3s")
                print(f"    Delimitadores COBS (0x00): {null_count}")
                print(f"    Hex: {hex_preview}")
                if ascii_hint:
                    print(f"    🎯 BASESTATION DETECTADA: \"{ascii_hint}\"")
                elif null_count >= 2:
                    print(f"    ⚠️  Posible BaseStation (tiene COBS frames)")
                else:
                    print(f"    ❓ Datos pero sin COBS — probablemente un NODO")
                    
        except serial.SerialException as e:
            print(f"    ⛔ No se pudo abrir: {e}")
        except Exception as e:
            print(f"    ⛔ Error: {e}")
    
    print(f"\n{'='*60}")
    print(f"  DIAGNÓSTICO COMPLETADO")
    print(f"{'='*60}\n")

def cobs_decode(data):
    if not data or len(data) < 2:
        return b''
    decoded = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        if code == 0:
            break
        i += 1
        for _ in range(1, code):
            if i >= len(data):
                return b''
            decoded.append(data[i])
            i += 1
        if code < 0xFF and i < len(data):
            decoded.append(0)
    return bytes(decoded)

if __name__ == "__main__":
    scan_ports()
