import os
from pathlib import Path
from datetime import date
from typing import Optional
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DB_PATH = str(BASE_DIR / "lealtad.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Inicialización de tablas
with get_db() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            fecha_nacimiento DATE,
            huellitas_saldo INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            tipo TEXT CHECK(tipo IN ('ACUMULACION', 'CANJE')),
            cantidad INTEGER NOT NULL,
            descripcion TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        )
    """)

class ClienteAlta(BaseModel):
    nombre: str
    correo: str
    fecha_nacimiento: Optional[date] = None

class SolicitudTransaccion(BaseModel):
    cliente_id: int
    tipo_accion: str  # 'BEBIDA', 'PAN', 'CANJE_BEBIDA', 'CANJE_PAN'

HUELLITAS_CANJE = 10

# ----------------- VISTAS WEB -----------------

@app.get("/", response_class=HTMLResponse)
@app.get("/registro", response_class=HTMLResponse)
def vista_registro(request: Request):
    return templates.TemplateResponse(request=request, name="registro.html", context={})

@app.get("/tarjeta/{cliente_id}", response_class=HTMLResponse)
def vista_tarjeta(request: Request, cliente_id: int):
    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    historial = conn.execute(
        "SELECT * FROM transacciones WHERE cliente_id = ? ORDER BY fecha DESC LIMIT 5",
        (cliente_id,)
    ).fetchall()
    conn.close()

    cliente_dict = dict(cliente)
    saldo = cliente_dict.get("huellitas_saldo", 0)
    progreso = saldo % 10
    porcentaje = min(progreso * 10, 100)
    faltantes = 10 - progreso

    historial_html = ""
    for item in historial:
        signo = "+" if item["tipo"] == "ACUMULACION" else "-"
        historial_html += f"""
        <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #eee;">
            <span>{item['descripcion']}</span>
            <span>{signo}{item['cantidad']}</span>
        </div>
        """
    if not historial:
        historial_html = '<p style="color:#999; font-size:0.8rem; margin:8px 0 0;">Aún no tienes movimientos registrados.</p>'

    aviso_meta = f'<p style="margin:8px 0 0; font-size:0.85rem; font-weight:bold; color:#2a9d8f;">¡Tienes recompensa disponible! 🎉</p>' if saldo >= 10 else f'<p style="margin:8px 0 0; font-size:0.8rem; color:#777;">Te faltan {faltantes} para tu cortesía</p>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mi Tarjeta Digital | Latte&Go</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
        <style>
            body {{ font-family: -apple-system, sans-serif; background-color: #f7f4ef; color: #333; margin: 0; padding: 20px 16px; display: flex; justify-content: center; box-sizing: border-box; }}
            .card {{ background: #fff; border-radius: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); width: 100%; max-width: 360px; padding: 24px; text-align: center; box-sizing: border-box; }}
            .saldo-box {{ background: #fdf8f0; border: 2px dashed #d4a373; border-radius: 16px; padding: 16px; margin: 16px 0; }}
            .puntos {{ font-size: 3rem; font-weight: 800; color: #bc6c25; line-height: 1; }}
            .barra-bg {{ background: #e9ecef; border-radius: 10px; height: 12px; margin-top: 12px; overflow: hidden; }}
            .barra-fill {{ background: #bc6c25; height: 100%; width: {porcentaje}%; }}
            #qrcode {{ display: flex; justify-content: center; margin: 18px 0 10px; }}
            .hist {{ text-align: left; margin-top: 20px; font-size: 0.85rem; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1 style="font-size:1.3rem; margin:0; color:#4a3427;">¡Hola, {cliente_dict['nombre']}! 🐾</h1>
            <p style="margin:4px 0 0; font-size:0.8rem; color:#777;">Muestra tu QR en barra al ordenar</p>
            <div class="saldo-box">
                <div class="puntos">{cliente_dict['huellitas_saldo']}</div>
                <div style="font-size:0.85rem; color:#6b5b50; margin-top:4px;">Huellitas acumuladas</div>
                <div class="barra-bg"><div class="barra-fill"></div></div>
                {aviso_meta}
            </div>
            <div id="qrcode"></div>
            <div class="hist">
                <strong>Últimas visitas</strong>
                {historial_html}
            </div>
        </div>
        <script>
            new QRCode(document.getElementById("qrcode"), {{
                text: "{cliente_dict['id']}",
                width: 140,
                height: 140,
                colorDark: "#2b1e16",
                colorLight: "#ffffff"
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/caja", response_class=HTMLResponse)
def vista_caja(request: Request):
    return templates.TemplateResponse(request=request, name="barista.html", context={})

# ----------------- ENDPOINTS DE API -----------------

@app.post("/api/clientes/registro")
def registrar_cliente(datos: ClienteAlta):
    conn = get_db()
    cursor = conn.cursor()
    try:
        fecha_val = str(datos.fecha_nacimiento) if datos.fecha_nacimiento else None
        cursor.execute(
            "INSERT INTO clientes (nombre, correo, fecha_nacimiento, huellitas_saldo) VALUES (?, ?, ?, 0)",
            (datos.nombre.strip(), datos.correo.lower().strip(), fecha_val)
        )
        cliente_id = cursor.lastrowid
        conn.commit()
        return {"cliente_id": cliente_id}
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Este correo ya se encuentra registrado.")
    finally:
        conn.close()

@app.get("/api/cliente/{cliente_id}")
def obtener_cliente(cliente_id: int):
    conn = get_db()
    cliente = conn.execute("SELECT id, nombre, huellitas_saldo FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    conn.close()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return dict(cliente)

@app.post("/api/transaccion")
def procesar_transaccion(datos: SolicitudTransaccion):
    conn = get_db()
    cursor = conn.cursor()
    cliente = cursor.execute("SELECT huellitas_saldo FROM clientes WHERE id = ?", (datos.cliente_id,)).fetchone()

    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    saldo = cliente["huellitas_saldo"]

    if datos.tipo_accion in ["BEBIDA", "PAN"]:
        desc = "Compra de bebida" if datos.tipo_accion == "BEBIDA" else "Compra de pan"
        cursor.execute("UPDATE clientes SET huellitas_saldo = huellitas_saldo + 1 WHERE id = ?", (datos.cliente_id,))
        cursor.execute("INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES (?, 'ACUMULACION', 1, ?)", (datos.cliente_id, desc))
        conn.commit()
        conn.close()
        return {"mensaje": "¡Huellita registrada!", "nuevo_saldo": saldo + 1}

    elif datos.tipo_accion in ["CANJE_BEBIDA", "CANJE_PAN"]:
        if saldo < HUELLITAS_CANJE:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Tiene {saldo} de 10 huellitas.")
        desc = "Canje: Bebida de cortesía" if datos.tipo_accion == "CANJE_BEBIDA" else "Canje: Pan de cortesía"
        cursor.execute("UPDATE clientes SET huellitas_saldo = huellitas_saldo - ? WHERE id = ?", (HUELLITAS_CANJE, datos.cliente_id))
        cursor.execute("INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES (?, 'CANJE', ?, ?)", (datos.cliente_id, HUELLITAS_CANJE, desc))
        conn.commit()
        conn.close()
        return {"mensaje": "¡Canje exitoso!", "nuevo_saldo": saldo - HUELLITAS_CANJE}

    conn.close()
    raise HTTPException(status_code=400, detail="Acción no válida")
