import uuid
import httpx
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Reservation Service",
    description="""
## Contexto: Reservation

Administrador de la concurrencia. Gestiona la asignación exclusiva de switches
a un test durante una ventana de tiempo, garantizando que ningún otro proceso
pueda usar el mismo recurso simultáneamente.

**Responsabilidades:**
- Buscar switches AVAILABLE en **Inventory** basado en criterios técnicos
- Asignar un switch compatible al test de forma exclusiva
- Prevenir conflictos entre tests concurrentes
- Gestionar expiración y liberación de reservas

**Flujo de comunicación:**
1. Recibe criterios de búsqueda (plataforma, SKU, PoE, topología, puertos)
2. Consulta **Inventory** (puerto 8001) con `GET /switches/compatible`
3. Selecciona el primer switch disponible
4. Verifica que no está ya reservado
5. Crea la reserva con estado `ACTIVE`
    """,
    version="1.0.0",
)

INVENTORY_URL = "http://inventory:8001"

# ── Almacenamiento en memoria ──────────────────────────────────────────────────
reservations: dict[str, dict] = {}

# ── Modelos ────────────────────────────────────────────────────────────────────
class ReservationRequest(BaseModel):
    test_id: str
    plataforma: str  # Obligatorio: Aruba 800, 850, 900, 950
    sku: Optional[str] = None  # Opcional: 800.1, 800.2, etc
    requiere_poe: bool  # Obligatorio: true/false
    topologia: str  # Obligatorio: Standalone, Dual Link, Stack, PoE Bench
    numero_puertos_min: Optional[int] = None  # Opcional
    duracion_minutos: int = 60

class ReservationResponse(BaseModel):
    id: str
    test_id: str
    switch_ids: List[str]  # Lista de IDs (MACs) reservados
    estado: str
    creada_en: str
    expira_en: str
    liberada_en: Optional[str] = None

class ReleaseRequest(BaseModel):
    motivo: Optional[str] = "TestCompleted"


# ── Helpers ────────────────────────────────────────────────────────────────────
async def find_compatible_switches(
    plataforma: str,
    sku: Optional[str],
    requiere_poe: bool,
    topologia: str,
    numero_puertos_min: Optional[int],
) -> List[dict]:
    """
    Busca switches compatibles en Inventory usando /switches/compatible.
    Retorna lista de switches AVAILABLE que cumplen los criterios.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Construir query parameters
            params = {
                "plataforma": plataforma,
                "requiere_poe": requiere_poe,
                "topologia": topologia,
            }
            if sku:
                params["sku"] = sku
            if numero_puertos_min:
                params["numero_puertos_min"] = numero_puertos_min
            
            response = await client.get(
                f"{INVENTORY_URL}/switches/compatible",
                params=params,
                timeout=5.0,
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 503:
                raise HTTPException(status_code=503, detail="No se puede conectar con Inventory Service (8001)")
            else:
                return []
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="No se puede conectar con Inventory Service (8001)")


def switch_esta_reservado(switch_id: str) -> bool:
    for r in reservations.values():
        if r["estado"] == "ACTIVE" and switch_id in r["switch_ids"]:
            return True
    return False


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Health check del servicio")
def health():
    return {"service": "reservation", "status": "ok", "port": 8002}


@app.get(
    "/reservations",
    response_model=List[ReservationResponse],
    tags=["Reservations"],
    summary="Listar todas las reservas",
    description="Retorna todas las reservas registradas en el sistema (activas, liberadas y expiradas).",
)
def listar_reservations():
    return list(reservations.values())


@app.get(
    "/reservations/{reservation_id}",
    response_model=ReservationResponse,
    tags=["Reservations"],
    summary="Obtener una reserva por ID",
)
def obtener_reservation(reservation_id: str):
    if reservation_id not in reservations:
        raise HTTPException(status_code=404, detail=f"Reserva '{reservation_id}' no encontrada")
    return reservations[reservation_id]


@app.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=201,
    tags=["Reservations"],
    summary="Crear una nueva reserva",
    description="""
Solicita la reserva exclusiva de switches que cumplan los criterios especificados.

**Flujo interno:**
1. Busca switches AVAILABLE en **Inventory** que cumplen los criterios
2. Selecciona el primer switch compatible
3. Verifica que no está ya reservado
4. Crea la reserva con estado `ACTIVE` y tiempo de expiración

**Body:**
```json
{
  "test_id": "test-001",
  "plataforma": "Aruba 800",
  "sku": "800.1",
  "requiere_poe": true,
  "topologia": "Standalone",
  "numero_puertos_min": 24,
  "duracion_minutos": 60
}
```

Retorna error 404 si no hay switches disponibles, 409 si hay conflicto de reserva.
    """,
)
async def crear_reservation(body: ReservationRequest):
    # 1. Buscar switches compatibles en Inventory
    switches_compatibles = await find_compatible_switches(
        plataforma=body.plataforma,
        sku=body.sku,
        requiere_poe=body.requiere_poe,
        topologia=body.topologia,
        numero_puertos_min=body.numero_puertos_min,
    )
    
    if not switches_compatibles:
        raise HTTPException(
            status_code=404,
            detail=f"No hay switches disponibles que cumplan los criterios: plataforma={body.plataforma}, sku={body.sku}, poe={body.requiere_poe}, topologia={body.topologia}",
        )
    
    # 2. Seleccionar el primer switch que no esté reservado
    switch_seleccionado = None
    for switch in switches_compatibles:
        if not switch_esta_reservado(switch["id"]):
            switch_seleccionado = switch
            break
    
    if not switch_seleccionado:
        raise HTTPException(
            status_code=409,
            detail="Todos los switches compatibles ya están reservados. Intente más tarde.",
        )
    
    # 3. Crear reserva
    ahora = datetime.utcnow()
    reservation_id = f"res-{str(uuid.uuid4())[:8]}"
    reservation = {
        "id": reservation_id,
        "test_id": body.test_id,
        "switch_ids": [switch_seleccionado["id"]],  # Lista con el switch seleccionado
        "estado": "ACTIVE",
        "creada_en": ahora.isoformat() + "Z",
        "expira_en": (ahora + timedelta(minutes=body.duracion_minutos)).isoformat() + "Z",
        "liberada_en": None,
    }
    reservations[reservation_id] = reservation
    return reservation


@app.patch(
    "/reservations/{reservation_id}/release",
    response_model=ReservationResponse,
    tags=["Reservations"],
    summary="Liberar una reserva",
    description="""
Libera una reserva activa, marcándola como `RELEASED`.

Consumido por **Test Execution** al completar o fallar un test,
y por **Scheduling** al cancelar una solicitud.
    """,
)
def liberar_reservation(reservation_id: str, body: ReleaseRequest = ReleaseRequest()):
    if reservation_id not in reservations:
        raise HTTPException(status_code=404, detail=f"Reserva '{reservation_id}' no encontrada")

    reservation = reservations[reservation_id]

    if reservation["estado"] != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail=f"La reserva tiene estado '{reservation['estado']}' y no puede liberarse",
        )

    reservation["estado"] = "RELEASED"
    reservation["liberada_en"] = datetime.utcnow().isoformat() + "Z"
    return reservation


@app.delete(
    "/reservations/{reservation_id}",
    tags=["Reservations"],
    summary="Eliminar una reserva del registro",
    description="Elimina una reserva del registro en memoria. Solo para testing/limpieza.",
)
def eliminar_reservation(reservation_id: str):
    if reservation_id not in reservations:
        raise HTTPException(status_code=404, detail=f"Reserva '{reservation_id}' no encontrada")
    del reservations[reservation_id]
    return {"mensaje": f"Reserva '{reservation_id}' eliminada"}
