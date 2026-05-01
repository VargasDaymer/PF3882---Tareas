import json
import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(
    title="Inventory Service",
    description="""
## Contexto: Inventory

Fuente de verdad del hardware disponible en el entorno de testing.
Gestiona el catálogo de switches **Aruba** (plataformas 800, 850, 900, 950) y sus capacidades técnicas.

**Responsabilidades:**
- Registrar switches con sus especificaciones técnicas (plataforma, SKU, PoE, puertos, topología)
- Mantener el estado físico de cada dispositivo
- Exponer una API de búsqueda filtrada por constraints técnicos
- Permitir reservas basadas en criterios de búsqueda

**Nota:** Este servicio NO conoce reservas, pruebas ni control de energía. Solo mantiene el catálogo.

**Topologías disponibles:**
- Standalone — 1 switch, loop entre puertos propios
- Dual Link — dos switches conectados entre sí
- Stack — 2 switches en stack, vistos como 1
- PoE Bench — 1 switch + 2 PDs conectados, ambiente de prueba con PoE
    """,
    version="1.0.0",
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "switches.json")

def load_switches() -> List[dict]:
    with open(DATA_PATH, "r") as f:
        return json.load(f)

# ── Modelos ────────────────────────────────────────────────────────────────────
class Switch(BaseModel):
    id: str
    plataforma: str
    sku: str
    firmware_version: str
    soporte_poe: bool
    numero_puertos: int
    estado_fisico: str
    topologia: str
    switch_ip: str
    hub_port: int


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Health check del servicio")
def health():
    return {"service": "inventory", "status": "ok", "port": 8001}


@app.get(
    "/switches",
    response_model=List[Switch],
    tags=["Switches"],
    summary="Listar todos los switches",
    description="Retorna todos los switches del inventario. Acepta filtros opcionales.",
)
def listar_switches(
    plataforma: Optional[str] = Query(None, description="Filtrar por plataforma: Aruba 800,Aruba 850,Aruba 900,Aruba 950"),
    sku: Optional[str] = Query(None, description="Filtrar por SKU específico (ej: 800.1, 850.2)"),
    soporte_poe: Optional[bool] = Query(None, description="Filtrar por soporte PoE (true/false)"),
    topologia: Optional[str] = Query(None, description="Filtrar por topología: Standalone, Dual Link, Stack, PoE Bench"),
    estado_fisico: Optional[str] = Query(None, description="Filtrar por estado: AVAILABLE, RESERVED, POWERED_OFF, MAINTENANCE"),
    numero_puertos_min: Optional[int] = Query(None, description="Número mínimo de puertos"),
):
    switches = load_switches()

    if plataforma:
        switches = [s for s in switches if plataforma.lower() in s["plataforma"].lower()]
    if sku:
        switches = [s for s in switches if s["sku"] == sku]
    if soporte_poe is not None:
        switches = [s for s in switches if s["soporte_poe"] == soporte_poe]
    if topologia:
        switches = [s for s in switches if s["topologia"].lower() == topologia.lower()]
    if estado_fisico:
        switches = [s for s in switches if s["estado_fisico"].upper() == estado_fisico.upper()]
    if numero_puertos_min:
        switches = [s for s in switches if s["numero_puertos"] >= numero_puertos_min]

    return switches


@app.get(
    "/switches/compatible",
    response_model=List[Switch],
    tags=["Switches"],
    summary="Buscar switches compatibles con un test",
    description="""
Endpoint principal consumido por **Reservation** y **Scheduling**.

Retorna únicamente switches con `estado_fisico = AVAILABLE` que cumplan
con todos los constraints técnicos especificados.

**Criterios de búsqueda:**
- **plataforma** (obligatorio): Aruba 800, 850, 900, 950
- **sku** (opcional): Si se especifica, filtra dentro de esa plataforma
- **requiere_poe**: Si es true, solo switches con soporte_poe=true
- **topologia** (obligatorio): Standalone, Dual Link, Stack, PoE Bench
- **numero_puertos_min** (opcional): Filtro adicional
    """,
)
def query_compatible_switches(
    plataforma: Optional[str] = Query(None, description="Plataforma requerida: Aruba 800,Aruba 850,Aruba 900,Aruba 950"),
    sku: Optional[str] = Query(None, description="SKU específico (opcional, ej: 800.1)"),
    requiere_poe: Optional[bool] = Query(None, description="El test requiere PoE (true/false)"),
    topologia: Optional[str] = Query(None, description="Topología requerida: Standalone, Dual Link, Stack, PoE Bench"),
    numero_puertos_min: Optional[int] = Query(None, description="Mínimo de puertos requeridos"),
):
    switches = load_switches()
    # Filtrar solo switches AVAILABLE
    switches = [s for s in switches if s["estado_fisico"] == "AVAILABLE"]

    if plataforma:
        switches = [s for s in switches if plataforma.lower() in s["plataforma"].lower()]
    if sku:
        switches = [s for s in switches if s["sku"] == sku]
    if requiere_poe is not None:
        switches = [s for s in switches if s["soporte_poe"] == requiere_poe]
    if topologia:
        switches = [s for s in switches if s["topologia"].lower() == topologia.lower()]
    if numero_puertos_min:
        switches = [s for s in switches if s["numero_puertos"] >= numero_puertos_min]

    return switches

