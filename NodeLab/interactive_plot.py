"""
interactive_plot.py — Visualización interactiva de señales
==========================================================
Este script genera un gráfico interactivo HTML con las señales
de los 3 nodos superpuestas.

Puedes hacer zoom, pan y encender/apagar señales desde la leyenda.
"""
import os
import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Usaremos la sesión más reciente
BASE_DIR = r"C:\Users\Becario 4\Documents\PlatformIO\Projects\ESP_Network_Suite\NodeLab\esp_sensor_connect\data_sessions"
sessions = sorted(glob.glob(os.path.join(BASE_DIR, "*")), key=os.path.getmtime, reverse=True)
SESSION = sessions[0]

MV_TO_V = 1.0 / 1000.0

print(f"Cargando datos de la sesión: {os.path.basename(SESSION)}")

fig = make_subplots(rows=1, cols=1)

colors = ['#1f77b4', '#ff7f0e', '#2ca02c'] # Azul, Naranja, Verde

# Cargamos los datos
for i, nid in enumerate([1, 2, 3]):
    fpath = os.path.join(SESSION, f"node_{nid}_ch0.csv")
    if not os.path.exists(fpath):
        print(f"No se encontró archivo para nodo {nid}")
        continue
        
    print(f"Cargando nodo {nid}...")
    # Leer CSV ignorando comentarios
    df = pd.read_csv(fpath, comment='#')
    
    # Limitar a los primeros 2000 puntos para que la visualización sea fluida y clara
    df = df.head(2000)
    
    # Convertir a voltios
    volts = df['value'] * MV_TO_V
    
    fig.add_trace(
        go.Scatter(
            x=df['sample_index'], 
            y=volts,
            mode='lines+markers',
            name=f'Nodo {nid}',
            line=dict(width=2, color=colors[i]),
            marker=dict(size=4)
        )
    )

fig.update_layout(
    title="Análisis Comparativo de Señales (Primeros 2000 puntos)",
    xaxis_title="Sample Index",
    yaxis_title="Voltaje (V)",
    template="plotly_dark",
    hovermode="x unified",
    legend=dict(
        yanchor="top",
        y=0.99,
        xanchor="left",
        x=0.01
    )
)

output_file = "comparativa_nodos.html"
fig.write_html(output_file)
print(f"\n¡Gráfico generado exitosamente en {output_file}!")

# Abrir en el navegador automáticamente
import webbrowser
webbrowser.open('file://' + os.path.realpath(output_file))
