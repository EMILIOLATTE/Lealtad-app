import os
from pathlib import Path
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    def get_db():
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn

    # Inicialización de tablas en PostgreSQL
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clientes (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    correo TEXT UNIQUE NOT NULL,
                    fecha_nacimiento DATE,
                    huellitas_saldo INTEGER DEFAULT 0
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transacciones (
                    id SERIAL PRIMARY KEY,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
                    tipo TEXT CHECK(tipo IN ('ACUMULACION', 'CANJE')),
                    cantidad INTEGER NOT NULL,
                    descripcion TEXT,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()

    PARAM = "%s"

else:
    import sqlite3

    DB_PATH = str(BASE_DIR / "lealtad.db")

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

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

    PARAM = "?"


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
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM clientes WHERE id = {PARAM}", (cliente_id,))
    cliente = cur.fetchone()
    
    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # 1. Obtener últimas 5 acumulaciones (visitas)
    cur.execute(
        f"""
        SELECT descripcion, cantidad, fecha 
        FROM transacciones 
        WHERE cliente_id = {PARAM} AND tipo = 'ACUMULACION' 
        ORDER BY fecha DESC LIMIT 5
        """,
        (cliente_id,)
    )
    visitas = cur.fetchall()

    # 2. Obtener historial de canjes
    cur.execute(
        f"""
        SELECT descripcion, cantidad, fecha 
        FROM transacciones 
        WHERE cliente_id = {PARAM} AND tipo = 'CANJE' 
        ORDER BY fecha DESC LIMIT 5
        """,
        (cliente_id,)
    )
    canjes = cur.fetchall()
    conn.close()

    cliente_dict = dict(cliente)
    saldo = cliente_dict.get("huellitas_saldo", 0)
    progreso = saldo % 10
    porcentaje = min(progreso * 10, 100)
    faltantes = 10 - progreso

    # Función auxiliar para formatear fecha a DD/MM
    def formatear_fecha(f):
        if not f:
            return ""
        if hasattr(f, "strftime"):
            return f.strftime("%d/%m")
        # Si viene como string de SQLite/Postgres (YYYY-MM-DD...)
        try:
            partes = str(f).split(" ")[0].split("-")
            return f"{partes[2]}/{partes[1]}"
        except Exception:
            return str(f)[:10]

    # Renderizado de visitas
    visitas_html = ""
    for item in visitas:
        f_str = formatear_fecha(item["fecha"])
        visitas_html += f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px solid #f0f0f0;">
            <div>
                <span style="font-weight:600; color:#333;">{item['descripcion']}</span>
                <span style="display:block; font-size:0.75rem; color:#888;">{f_str}</span>
            </div>
            <span style="font-weight:700; color:#bc6c25;">+{item['cantidad']} 🐾</span>
        </div>
        """
    if not visitas:
        visitas_html = '<p style="color:#999; font-size:0.8rem; margin:8px 0;">Aún no registras visitas.</p>'

    # Renderizado de canjes
    canjes_html = ""
    for item in canjes:
        f_str = formatear_fecha(item["fecha"])
        canjes_html += f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px solid #f0f0f0;">
            <div>
                <span style="font-weight:600; color:#2a9d8f;">{item['descripcion']}</span>
                <span style="display:block; font-size:0.75rem; color:#888;">{f_str}</span>
            </div>
            <span style="font-weight:700; color:#e76f51;">-{item['cantidad']} pts</span>
        </div>
        """
    if not canjes:
        canjes_html = '<p style="color:#999; font-size:0.8rem; margin:8px 0;">Aún no has realizado canjes.</p>'

    aviso_meta = '<p style="margin:8px 0 0; font-size:0.85rem; font-weight:bold; color:#2a9d8f;">¡Tienes recompensa disponible! 🎉</p>' if saldo >= 10 else f'<p style="margin:8px 0 0; font-size:0.8rem; color:#777;">Te faltan {faltantes} para tu cortesía</p>'

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mi Tarjeta Digital | Latte&Go</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background-color: #f7f4ef;
                color: #333;
                margin: 0;
                padding: 20px 16px;
                display: flex;
                justify-content: center;
                box-sizing: border-box;
            }}
            .card {{
                background: #ffffff;
                border-radius: 20px;
                box-shadow: 0 4px 18px rgba(0,0,0,0.08);
                width: 100%;
                max-width: 360px;
                padding: 24px;
                text-align: center;
                box-sizing: border-box;
            }}
            .saldo-box {{
                background: #fdf8f0;
                border: 2px dashed #d4a373;
                border-radius: 16px;
                padding: 16px;
                margin: 16px 0;
            }}
            .puntos {{
                font-size: 3rem;
                font-weight: 800;
                color: #bc6c25;
                line-height: 1;
            }}
            .barra-bg {{
                background: #e9ecef;
                border-radius: 10px;
                height: 12px;
                margin-top: 12px;
                overflow: hidden;
            }}
            .barra-fill {{
                background: #bc6c25;
                height: 100%;
                width: {porcentaje}%;
            }}
            #qrcode {{
                display: flex;
                justify-content: center;
                margin: 18px 0 10px;
            }}
            .section-hist {{
                text-align: left;
                margin-top: 22px;
            }}
            .section-title {{
                font-size: 0.85rem;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                font-weight: 700;
                color: #6b5b50;
                border-bottom: 2px solid #f0e6df;
                padding-bottom: 4px;
                margin-bottom: 8px;
            }}
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

            <!-- Sección de Visitas -->
            <div class="section-hist">
                <div class="section-title">🐾 Últimas Visitas</div>
                {visitas_html}
            </div>

            <!-- Sección de Canjes -->
            <div class="section-hist">
                <div class="section-title">🎁 Cortesías Canjeadas</div>
                {canjes_html}
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
    cur = conn.cursor()
    correo_limpio = datos.correo.lower().strip()
    try:
        # 1. Comprobar si el cliente ya existe previamente
        cur.execute(f"SELECT id FROM clientes WHERE correo = {PARAM}", (correo_limpio,))
        existente = cur.fetchone()
        if existente:
            conn.close()
            # Devuelve su ID existente para redirigirlo a su tarjeta sin error
            return {"cliente_id": existente["id"], "mensaje": "¡Bienvenido de vuelta!"}

        # 2. Si es cliente nuevo, registrarlo
        fecha_val = str(datos.fecha_nacimiento) if datos.fecha_nacimiento else None
        if DATABASE_URL:
            cur.execute(
                """
                INSERT INTO clientes (nombre, correo, fecha_nacimiento, huellitas_saldo) 
                VALUES (%s, %s, %s, 0) RETURNING id
                """,
                (datos.nombre.strip(), correo_limpio, fecha_val)
            )
            fila = cur.fetchone()
            cliente_id = fila["id"]
        else:
            cur.execute(
                """
                INSERT INTO clientes (nombre, correo, fecha_nacimiento, huellitas_saldo) 
                VALUES (?, ?, ?, 0)
                """,
                (datos.nombre.strip(), correo_limpio, fecha_val)
            )
            cliente_id = cur.lastrowid
        conn.commit()
        return {"cliente_id": cliente_id, "mensaje": "¡Registro exitoso!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {str(e)}")
    finally:
        conn.close()

@app.get("/api/cliente/{cliente_id}")
def obtener_cliente(cliente_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT id, nombre, huellitas_saldo FROM clientes WHERE id = {PARAM}", (cliente_id,))
    cliente = cur.fetchone()
    conn.close()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return dict(cliente)

@app.post("/api/transaccion")
def procesar_transaccion(datos: SolicitudTransaccion):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT huellitas_saldo FROM clientes WHERE id = {PARAM}", (datos.cliente_id,))
    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    saldo = cliente["huellitas_saldo"]

    if datos.tipo_accion in ["BEBIDA", "PAN"]:
        desc = "Compra de bebida" if datos.tipo_accion == "BEBIDA" else "Compra de pan"
        cur.execute(f"UPDATE clientes SET huellitas_saldo = huellitas_saldo + 1 WHERE id = {PARAM}", (datos.cliente_id,))
        cur.execute(
            f"INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES ({PARAM}, 'ACUMULACION', 1, {PARAM})",
            (datos.cliente_id, desc)
        )
        conn.commit()
        conn.close()
        return {"mensaje": "¡Huellita registrada!", "nuevo_saldo": saldo + 1}

    elif datos.tipo_accion in ["CANJE_BEBIDA", "CANJE_PAN"]:
        if saldo < HUELLITAS_CANJE:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Tiene {saldo} de 10 huellitas.")
        desc = "Canje: Bebida de cortesía" if datos.tipo_accion == "CANJE_BEBIDA" else "Canje: Pan de cortesía"
        cur.execute(f"UPDATE clientes SET huellitas_saldo = huellitas_saldo - {PARAM} WHERE id = {PARAM}", (HUELLITAS_CANJE, datos.cliente_id))
        cur.execute(
            f"INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES ({PARAM}, 'CANJE', {PARAM}, {PARAM})",
            (datos.cliente_id, HUELLITAS_CANJE, desc)
        )
        conn.commit()
        conn.close()
        return {"mensaje": "¡Canje exitoso!", "nuevo_saldo": saldo - HUELLITAS_CANJE}

    conn.close()
    raise HTTPException(status_code=400, detail="Acción no válida")
