from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from datetime import date
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DB_PATH = str(BASE_DIR / "lealtad.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Inicialización de tablas en la base de datos
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

# Vistas Web (Sintaxis moderna compatible con FastAPI 0.110+)
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
    return templates.TemplateResponse(
        request=request, 
        name="cliente.html", 
        context={"cliente": cliente, "historial": historial}
    )

@app.get("/caja", response_class=HTMLResponse)
def vista_caja(request: Request):
    return templates.TemplateResponse(request=request, name="barista.html", context={})

# Endpoints de API
@app.post("/api/clientes/registro")
def registrar_cliente(datos: ClienteAlta):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO clientes (nombre, correo, fecha_nacimiento, huellitas_saldo) VALUES (?, ?, ?, 0)",
            (datos.nombre, datos.correo.lower().strip(), datos.fecha_nacimiento)
        )
        cliente_id = cursor.lastrowid
        conn.commit()
        return {"cliente_id": cliente_id}
    except sqlite3.IntegrityError:
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
