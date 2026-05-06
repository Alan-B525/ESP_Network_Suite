"""
analyze_signals.py — Análisis comparativo de señales entre 3 nodos
===================================================================
Señal esperada: senoidal 200Hz, 2Vpp, 1V offset
ADC: 12-bit (0-4095), rango 0-3.3V
"""
import csv
import os
import glob
import numpy as np

BASE_DIR = r"C:\Users\Becario 4\Documents\PlatformIO\Projects\ESP_Network_Suite\NodeLab\esp_sensor_connect\data_sessions"
sessions = sorted(glob.glob(os.path.join(BASE_DIR, "*")), key=os.path.getmtime, reverse=True)
SESSION = sessions[0]

MV_TO_V = 1.0 / 1000.0
SAMPLE_RATE = 1000  # Hz

print(f"Analizando sesión: {os.path.basename(SESSION)}")

def load_csv(filepath):
    """Load CSV, return arrays of sample_index and value."""
    indices = []
    values = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('timestamp'):
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                try:
                    indices.append(int(parts[1]))
                    values.append(int(parts[2]))
                except ValueError:
                    continue
    return np.array(indices), np.array(values, dtype=np.float64)

print(f"\n{'='*70}")
print(f"  ANALISIS COMPARATIVO DE SENALES - 3 NODOS")
print(f"  Senal esperada: 200Hz senoidal, 2Vpp, 1V offset")
print(f"{'='*70}")

# Load data
nodes = {}
for nid in [1, 2, 3]:
    fpath = os.path.join(SESSION, f"node_{nid}_ch0.csv")
    idx, vals = load_csv(fpath)
    nodes[nid] = {'idx': idx, 'vals': vals, 'volts': vals * MV_TO_V}
    print(f"\n--- Nodo {nid} ---")
    print(f"  Muestras: {len(vals)}")
    print(f"  ADC min/max (mV): {vals.min():.0f} / {vals.max():.0f}")
    print(f"  Voltaje min/max: {vals.min()*MV_TO_V:.3f}V / {vals.max()*MV_TO_V:.3f}V")
    print(f"  Voltaje medio: {vals.mean()*MV_TO_V:.3f}V")
    print(f"  Vpp: {(vals.max()-vals.min())*MV_TO_V:.3f}V")
    print(f"  Indices: [{idx[0]} .. {idx[-1]}]")

# Estadisticas por segmentos de 5 muestras (1 ciclo a 200Hz con 1kHz sample)
print(f"\n{'='*70}")
print(f"  VERIFICACION DE FORMA DE ONDA")
print(f"{'='*70}")

for nid in [1, 2, 3]:
    vals = nodes[nid]['vals']
    # Primeros 25 samples (5 ciclos)
    seg = vals[:25]
    volts = seg * MV_TO_V
    print(f"\n  Nodo {nid} - Primeros 25 valores (5 ciclos):")
    for i in range(0, min(25, len(seg)), 5):
        chunk = volts[i:i+5]
        s = "  ".join(f"{v:.3f}" for v in chunk)
        print(f"    [{i:3d}-{i+4:3d}]: {s}")

# Comparacion directa: mismos indices de muestra
print(f"\n{'='*70}")
print(f"  COMPARACION ENTRE NODOS (mismos indices)")
print(f"{'='*70}")

# Find common range
min_samples = min(len(nodes[n]['vals']) for n in [1,2,3])
compare_count = min(1000, min_samples)

print(f"\n  Comparando primeros {compare_count} samples...")

# Correlacion cruzada
from numpy.fft import fft, ifft

for a, b in [(1,2), (1,3), (2,3)]:
    va = nodes[a]['vals'][:compare_count]
    vb = nodes[b]['vals'][:compare_count]
    
    # Diferencia directa
    diff = va - vb
    
    # Correlacion
    va_norm = va - va.mean()
    vb_norm = vb - vb.mean()
    if va_norm.std() > 0 and vb_norm.std() > 0:
        corr = np.corrcoef(va_norm, vb_norm)[0, 1]
    else:
        corr = 0.0
    
    # Cross-correlation para detectar desfase
    cross = np.correlate(va_norm, vb_norm, mode='full')
    lag = np.argmax(cross) - (compare_count - 1)
    
    print(f"\n  Nodo {a} vs Nodo {b}:")
    print(f"    Correlacion: {corr:.6f}")
    print(f"    Desfase estimado: {lag} muestras ({lag*1000/SAMPLE_RATE:.1f} ms)")
    print(f"    Diferencia media: {diff.mean()*MV_TO_V:.4f} V")
    print(f"    Diferencia max: {abs(diff).max()*MV_TO_V:.4f} V")
    print(f"    Diferencia RMS: {np.sqrt((diff**2).mean())*MV_TO_V:.4f} V")

# Analisis FFT para verificar frecuencia
print(f"\n{'='*70}")
print(f"  ANALISIS FFT - Frecuencia dominante")
print(f"{'='*70}")

for nid in [1, 2, 3]:
    vals = nodes[nid]['vals']
    # Use a window of ~1 second (1000 samples)
    segment = vals[:min(1000, len(vals))]
    segment = segment - segment.mean()  # Remove DC
    
    N = len(segment)
    fft_vals = np.abs(fft(segment))[:N//2]
    freqs = np.arange(N//2) * SAMPLE_RATE / N
    
    # Find dominant frequency (skip DC at index 0)
    dominant_idx = np.argmax(fft_vals[1:]) + 1
    dominant_freq = freqs[dominant_idx]
    
    # Top 3 frequencies
    top3_idx = np.argsort(fft_vals[1:])[-3:][::-1] + 1
    
    print(f"\n  Nodo {nid}:")
    print(f"    Frecuencia dominante: {dominant_freq:.1f} Hz")
    print(f"    Top 3 frecuencias:")
    for ti in top3_idx:
        print(f"      {freqs[ti]:.1f} Hz (magnitud: {fft_vals[ti]:.0f})")

# Tabla de 10 muestras en paralelo
print(f"\n{'='*70}")
print(f"  COMPARACION MUESTRA A MUESTRA (primeros 20 samples)")
print(f"{'='*70}")
print(f"\n  {'idx':>5} | {'Nodo1(V)':>8} | {'Nodo2(V)':>8} | {'Nodo3(V)':>8} | {'Max diff':>8}")
print(f"  {'-'*5}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

for i in range(min(20, min_samples)):
    v1 = nodes[1]['vals'][i] * MV_TO_V
    v2 = nodes[2]['vals'][i] * MV_TO_V
    v3 = nodes[3]['vals'][i] * MV_TO_V
    maxd = max(abs(v1-v2), abs(v1-v3), abs(v2-v3))
    print(f"  {i:5d} | {v1:8.3f} | {v2:8.3f} | {v3:8.3f} | {maxd:8.3f}")

print(f"\n{'='*70}")
print(f"  ANALISIS COMPLETADO")
print(f"{'='*70}\n")
