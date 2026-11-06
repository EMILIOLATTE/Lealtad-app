import os
import uuid
from pathlib import Path
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
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

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clientes (
                    id SERIAL PRIMARY KEY,
                    token_qr TEXT UNIQUE NOT NULL,
                    nombre TEXT NOT NULL,
                    correo TEXT UNIQUE NOT NULL,
                    fecha_nacimiento DATE,
                    huellitas_saldo INTEGER DEFAULT 0
                );
            """)
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='clientes' AND column_name='token_qr') THEN 
                        ALTER TABLE clientes ADD COLUMN token_qr TEXT UNIQUE;
                    END IF; 
                END $$;
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
                token_qr TEXT UNIQUE NOT NULL,
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
    token: Optional[str] = None
    cliente_id: Optional[int] = None
    tipo_accion: str

HUELLITAS_CANJE = 10
HUELLITAS_BIENVENIDA = 2

# ----------------- RECURSOS PWA (MANIFEST & ICONO) -----------------

@app.get("/manifest.json")
def pwa_manifest():
    manifest_data = {
        "name": "Latte&Go Lealtad",
        "short_name": "Latte&Go",
        "start_url": "/registro",
        "display": "standalone",
        "background_color": "#f7f4ef",
        "theme_color": "#2b1e16",
        "icons": [
            {
                "src": "/icon.svg",
                "sizes": "192x192 512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }
    return JSONResponse(content=manifest_data)

@app.get("/icon.svg")
def pwa_icon():
    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
      <rect width="512" height="512" rx="110" fill="#2b1e16"/>
      <circle cx="256" cy="335" r="75" fill="#d4a373"/>
      <circle cx="170" cy="205" r="42" fill="#d4a373"/>
      <circle cx="342" cy="205" r="42" fill="#d4a373"/>
      <circle cx="215" cy="120" r="38" fill="#bc6c25"/>
      <circle cx="297" cy="120" r="38" fill="#bc6c25"/>
    </svg>"""
    return Response(content=svg_content, media_type="image/svg+xml")

# ----------------- VISTAS WEB -----------------

@app.get("/", response_class=HTMLResponse)
@app.get("/registro", response_class=HTMLResponse)
def vista_registro(request: Request):
    return templates.TemplateResponse(request=request, name="registro.html", context={})

@app.get("/tarjeta/{token}", response_class=HTMLResponse)
def vista_tarjeta(request: Request, token: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM clientes WHERE token_qr = {PARAM}", (token,))
    cliente = cur.fetchone()
    
    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada o enlace inválido.")
    
    cliente_dict = dict(cliente)
    cliente_id = cliente_dict["id"]

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

    saldo = cliente_dict.get("huellitas_saldo", 0)
    progreso = saldo % 10
    porcentaje = min(progreso * 10, 100)
    faltantes = 10 - progreso

    def formatear_fecha(f):
        if not f:
            return ""
        if hasattr(f, "strftime"):
            return f.strftime("%d/%m")
        try:
            partes = str(f).split(" ")[0].split("-")
            return f"{partes[2]}/{partes[1]}"
        except Exception:
            return str(f)[:10]

    visitas_html = ""
    for item in visitas:
        f_str = formatear_fecha(item["fecha"])
        visitas_html += f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid #f0f0f0;">
            <div>
                <span style="font-weight:600; color:#333; font-size:0.95rem;">{item['descripcion']}</span>
                <span style="display:block; font-size:0.75rem; color:#888;">{f_str}</span>
            </div>
            <span style="font-weight:700; color:#bc6c25;">+{item['cantidad']} 🐾</span>
        </div>
        """
    if not visitas:
        visitas_html = '<p style="color:#999; font-size:0.8rem; margin:8px 0;">Aún no registras visitas.</p>'

    canjes_html = ""
    for item in canjes:
        f_str = formatear_fecha(item["fecha"])
        canjes_html += f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid #f0f0f0;">
            <div>
                <span style="font-weight:600; color:#2a9d8f; font-size:0.95rem;">{item['descripcion']}</span>
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Mi Tarjeta Digital | Latte&Go</title>
        
        <!-- PWA Meta tags -->
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#2b1e16">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="Latte&Go">
        <link rel="apple-touch-icon" href="/icon.svg">
        <link rel="icon" type="image/svg+xml" href="/icon.svg">

        <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                background-color: #f7f4ef;
                color: #333;
                margin: 0;
                padding: 20px 16px 40px;
                display: flex;
                flex-direction: column;
                align-items: center;
                box-sizing: border-box;
            }}
            .card {{
                background: #ffffff;
                border-radius: 24px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
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
            .btn-pwa {{
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                background: #2b1e16;
                color: #f7f4ef;
                border: none;
                border-radius: 14px;
                padding: 12px 16px;
                font-size: 0.88rem;
                font-weight: 700;
                cursor: pointer;
                width: 100%;
                margin: 18px 0 6px;
                transition: opacity 0.2s;
            }}
            .btn-pwa:active {{
                opacity: 0.9;
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

            /* Modal de Instrucciones */
            .modal-backdrop {{
                display: none;
                position: fixed;
                top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.6);
                z-index: 999;
                align-items: flex-end;
                justify-content: center;
            }}
            .modal-sheet {{
                background: #fff;
                width: 100%;
                max-width: 400px;
                border-radius: 24px 24px 0 0;
                padding: 24px 20px 32px;
                box-sizing: border-box;
                text-align: center;
                animation: slideUp 0.25s ease-out;
            }}
            @keyframes slideUp {{
                from {{ transform: translateY(100%); }}
                to {{ transform: translateY(0); }}
            }}
            .modal-sheet h3 {{
                margin: 0 0 12px;
                color: #2b1e16;
                font-size: 1.15rem;
            }}
            .step-item {{
                display: flex;
                align-items: center;
                text-align: left;
                gap: 12px;
                margin: 14px 0;
                font-size: 0.92rem;
                color: #444;
            }}
            .step-num {{
                background: #fdf8f0;
                color: #bc6c25;
                font-weight: 800;
                width: 28px;
                height: 28px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }}
            .btn-close-modal {{
                background: #f0e6df;
                color: #555;
                border: none;
                border-radius: 12px;
                padding: 12px;
                width: 100%;
                font-weight: 700;
                margin-top: 14px;
                cursor: pointer;
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

            <!-- Botón para guardar en pantalla de inicio -->
            <button class="btn-pwa" onclick="abrirGuiaInstalacion()">
                📲 Guardar tarjeta en mi teléfono
            </button>

            <div class="section-hist">
                <div class="section-title">🐾 Últimas Visitas</div>
                {visitas_html}
            </div>

            <div class="section-hist">
                <div class="section-title">🎁 Cortesías Canjeadas</div>
                {canjes_html}
            </div>
        </div>

        <!-- Modal con instrucciones según iOS o Android -->
        <div id="modal-guia" class="modal-backdrop" onclick="cerrarGuia(event)">
            <div class="modal-sheet" onclick="event.stopPropagation()">
                <div style="font-size:2rem; margin-bottom:6px;">☕📱</div>
                <h3>Ten tu tarjeta siempre a la mano</h3>
                <div id="instrucciones-dinamicas"></div>
                <button class="btn-close-modal" onclick="cerrarGuia()">¡Entendido!</button>
            </div>
        </div>

        <script>
            new QRCode(document.getElementById("qrcode"), {{
                text: "{cliente_dict['token_qr']}",
                width: 140,
                height: 140,
                colorDark: "#2b1e16",
                colorLight: "#ffffff"
            }});

            let deferredPrompt = null;
            window.addEventListener('beforeinstallprompt', (e) => {{
                e.preventDefault();
                deferredPrompt = e;
            }});

            function abrirGuiaInstalacion() {{
                if (deferredPrompt) {{
                    deferredPrompt.prompt();
                    deferredPrompt.userChoice.then((choiceResult) => {{
                        if (choiceResult.outcome === 'accepted') {{
                            console.log('Cliente instaló la app');
                        }}
                        deferredPrompt = null;
                    }});
                    return;
                }}

                const esIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
                const contenedor = document.getElementById("instrucciones-dinamicas");

                if (esIOS) {{
                    contenedor.innerHTML = `
                        <div class="step-item">
                            <div class="step-num">1</div>
                            <div>Toca el botón <b>Compartir</b> en Safari (el icono de cuadro con flecha hacia arriba ⎋).</div>
                        </div>
                        <div class="step-item">
                            <div class="step-num">2</div>
                            <div>Baja y selecciona <b>"Agregar a inicio"</b> ➕.</div>
                        </div>
                    `;
                }} else {{
                    contenedor.innerHTML = `
                        <div class="step-item">
                            <div class="step-num">1</div>
                            <div>Toca los <b>tres puntos (⋮)</b> arriba a la derecha en Chrome.</div>
                        </div>
                        <div class="step-item">
                            <div class="step-num">2</div>
                            <div>Elige <b>"Instalar aplicación"</b> o <b>"Agregar a la pantalla principal"</b> 📲.</div>
                        </div>
                    `;
                }}

                document.getElementById("modal-guia").style.display = "flex";
            }}

            function cerrarGuia() {{
                document.getElementById("modal-guia").style.display = "none";
            }}
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
        cur.execute(f"SELECT token_qr FROM clientes WHERE correo = {PARAM}", (correo_limpio,))
        existente = cur.fetchone()
        if existente:
            token = existente["token_qr"]
            if not token:
                token = str(uuid.uuid4())
                cur.execute(f"UPDATE clientes SET token_qr = {PARAM} WHERE correo = {PARAM}", (token, correo_limpio))
                conn.commit()
            conn.close()
            return {"token": token, "mensaje": "¡Bienvenido de vuelta!"}

        fecha_val = str(datos.fecha_nacimiento) if datos.fecha_nacimiento else None
        nuevo_token = str(uuid.uuid4())

        if DATABASE_URL:
            cur.execute(
                """
                INSERT INTO clientes (token_qr, nombre, correo, fecha_nacimiento, huellitas_saldo) 
                VALUES (%s, %s, %s, %s, %s) RETURNING id, token_qr
                """,
                (nuevo_token, datos.nombre.strip(), correo_limpio, fecha_val, HUELLITAS_BIENVENIDA)
            )
            fila = cur.fetchone()
            cliente_id = fila["id"]
            token = fila["token_qr"]

            cur.execute(
                """
                INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) 
                VALUES (%s, 'ACUMULACION', %s, 'Regalo de bienvenida')
                """,
                (cliente_id, HUELLITAS_BIENVENIDA)
            )
        else:
            cur.execute(
                """
                INSERT INTO clientes (token_qr, nombre, correo, fecha_nacimiento, huellitas_saldo) 
                VALUES (?, ?, ?, ?, ?)
                """,
                (nuevo_token, datos.nombre.strip(), correo_limpio, fecha_val, HUELLITAS_BIENVENIDA)
            )
            cliente_id = cur.lastrowid
            token = nuevo_token

            cur.execute(
                """
                INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) 
                VALUES (?, 'ACUMULACION', ?, 'Regalo de bienvenida')
                """,
                (cliente_id, HUELLITAS_BIENVENIDA)
            )

        conn.commit()
        return {"token": token, "mensaje": "¡Registro exitoso! Disfruta tus primeras 2 huellitas."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error en base de datos: {str(e)}")
    finally:
        conn.close()

@app.get("/api/cliente/{identificador}")
def obtener_cliente(identificador: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"SELECT id, token_qr, nombre, huellitas_saldo FROM clientes WHERE token_qr = {PARAM}", (identificador,))
    cliente = cur.fetchone()
    if not cliente and identificador.isdigit():
        cur.execute(f"SELECT id, token_qr, nombre, huellitas_saldo FROM clientes WHERE id = {PARAM}", (int(identificador),))
        cliente = cur.fetchone()
    conn.close()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return dict(cliente)

@app.post("/api/transaccion")
def procesar_transaccion(datos: SolicitudTransaccion):
    conn = get_db()
    cur = conn.cursor()
    
    cliente = None
    if datos.token:
        cur.execute(f"SELECT id, huellitas_saldo FROM clientes WHERE token_qr = {PARAM}", (datos.token,))
        cliente = cur.fetchone()
    elif datos.cliente_id:
        cur.execute(f"SELECT id, huellitas_saldo FROM clientes WHERE id = {PARAM}", (datos.cliente_id,))
        cliente = cur.fetchone()

    if not cliente:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    cliente_id = cliente["id"]
    saldo = cliente["huellitas_saldo"]

    if datos.tipo_accion in ["VISITA", "BEBIDA", "PAN"]:
        desc = "Visita"
        cur.execute(f"UPDATE clientes SET huellitas_saldo = huellitas_saldo + 1 WHERE id = {PARAM}", (cliente_id,))
        cur.execute(
            f"INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES ({PARAM}, 'ACUMULACION', 1, {PARAM})",
            (cliente_id, desc)
        )
        conn.commit()
        conn.close()
        return {"mensaje": "¡Huellita registrada!", "nuevo_saldo": saldo + 1}

    elif datos.tipo_accion in ["CANJE_BEBIDA", "CANJE_PAN", "CANJE"]:
        if saldo < HUELLITAS_CANJE:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Tiene {saldo} de 10 huellitas.")
        desc = "Bebida de cortesía"
        cur.execute(f"UPDATE clientes SET huellitas_saldo = huellitas_saldo - {PARAM} WHERE id = {PARAM}", (HUELLITAS_CANJE, cliente_id))
        cur.execute(
            f"INSERT INTO transacciones (cliente_id, tipo, cantidad, descripcion) VALUES ({PARAM}, 'CANJE', {PARAM}, {PARAM})",
            (cliente_id, HUELLITAS_CANJE, desc)
        )
        conn.commit()
        conn.close()
        return {"mensaje": "¡Canje exitoso!", "nuevo_saldo": saldo - HUELLITAS_CANJE}

    conn.close()
    raise HTTPException(status_code=400, detail="Acción no válida")
