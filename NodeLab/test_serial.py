"""
Quick serial raw test — reads raw bytes from COM13 at different baud rates
"""
import serial
import time

PORT = "COM13"

for baud in [921600, 115200, 460800]:
    print(f"\n--- Testing {PORT} @ {baud} baud ---")
    try:
        ser = serial.Serial(port=PORT, baudrate=baud, timeout=0.5)
        time.sleep(0.5)
        
        total = 0
        sample = b""
        start = time.time()
        while time.time() - start < 3.0:
            w = ser.in_waiting
            if w > 0:
                d = ser.read(min(w, 512))
                total += len(d)
                if len(sample) < 200:
                    sample += d[:200 - len(sample)]
            else:
                time.sleep(0.05)
        
        ser.close()
        
        if total == 0:
            print(f"  Sin datos (0 bytes)")
        else:
            print(f"  Recibidos: {total} bytes")
            hex_show = " ".join(f"{b:02X}" for b in sample[:60])
            print(f"  Hex: {hex_show}")
            # Try ASCII interpretation
            try:
                txt = sample.decode('utf-8', errors='replace')[:80]
                print(f"  ASCII: {txt}")
            except:
                pass
    except Exception as e:
        print(f"  Error: {e}")

print("\n--- Done ---")
