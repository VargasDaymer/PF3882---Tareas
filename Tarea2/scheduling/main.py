import uuid
import httpx
import strawberry
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

RESERVATION_URL = "http://reservation:8002"
REINTENTO_INTERVAL_SEGUNDOS = 10  # Intenta cada 10 segundos

# ── Almacenamiento en memoria ──────────────────────────────────────────────────
test_requests: dict[str, dict] = {}  # Vacío inicialmente, se llena al enviar tests


# ── Tipos GraphQL ──────────────────────────────────────────────────────────────

@strawberry.type
class TestRequest:
    id: str
    tester_id: str
    firmware_minimo: str
    requiere_poe: bool
    topologia: str
    plataforma: str
    prioridad: int
    estado: str
    creada_en: str
    reservation_id: Optional[str]


@strawberry.type
class ReservationInfo:
    id: str
    test_id: str
    switch_ids: List[str]
    estado: str
    creada_en: str
    expira_en: str
    liberada_en: Optional[str]


@strawberry.type
class SubmitResult:
    success: bool
    message: str
    test_request: Optional[TestRequest]


@strawberry.type
class CancelResult:
    success: bool
    message: str


# ── Inputs GraphQL ─────────────────────────────────────────────────────────────

@strawberry.input
class TestRequestInput:
    tester_id: str
    sku: Optional[str] = None
    requiere_poe: bool
    topologia: str
    plataforma: str
    numero_puertos_min: Optional[int] = None
    duracion_minutos: int = 60
    prioridad: int = 5


# ── Helpers ────────────────────────────────────────────────────────────────────

def dict_to_test_request(d: dict) -> TestRequest:
    return TestRequest(
        id=d["id"],
        tester_id=d["tester_id"],
        firmware_minimo=d.get("firmware_minimo", ""),
        requiere_poe=d["requiere_poe"],
        topologia=d["topologia"],
        plataforma=d["plataforma"],
        prioridad=d["prioridad"],
        estado=d["estado"],
        creada_en=d["creada_en"],
        reservation_id=d.get("reservation_id"),
    )


async def solicitar_reserva(
    test_id: str,
    plataforma: str,
    sku: Optional[str],
    requiere_poe: bool,
    topologia: str,
    numero_puertos_min: Optional[int],
    duracion_minutos: int,
) -> Optional[dict]:
    """
    Solicita una reserva en Reservation Service con criterios técnicos.
    Reservation se encargará de buscar en Inventory los switches compatibles.
    """
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "test_id": test_id,
                "plataforma": plataforma,
                "requiere_poe": requiere_poe,
                "topologia": topologia,
                "duracion_minutos": duracion_minutos,
            }
            if sku:
                payload["sku"] = sku
            if numero_puertos_min:
                payload["numero_puertos_min"] = numero_puertos_min
            
            response = await client.post(
                f"{RESERVATION_URL}/reservations",
                json=payload,
                timeout=5.0,
            )
            if response.status_code == 201:
                return response.json()
            return None
        except httpx.ConnectError:
            return None


async def obtener_reserva(reservation_id: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{RESERVATION_URL}/reservations/{reservation_id}",
                timeout=5.0,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.ConnectError:
            return None


async def procesar_cola_pendiente():
    """
    Tarea de background que cada REINTENTO_INTERVAL_SEGUNDOS intenta asignar
    recursos a los tests que están en estado QUEUED.
    
    Esto asegura que si Reservation Service estaba sin recursos, cuando haya
    switches disponibles, los tests en cola sean scheduled automáticamente.
    """
    while True:
        try:
            await asyncio.sleep(REINTENTO_INTERVAL_SEGUNDOS)
            
            # Obtener todos los tests en QUEUED
            queued_tests = [
                (test_id, test) 
                for test_id, test in test_requests.items() 
                if test["estado"] == "QUEUED"
            ]
            
            for test_id, test in queued_tests:
                # Intentar reservar para este test
                reserva = await solicitar_reserva(
                    test_id=test_id,
                    plataforma=test["plataforma"],
                    sku=test.get("sku"),
                    requiere_poe=test["requiere_poe"],
                    topologia=test["topologia"],
                    numero_puertos_min=test.get("numero_puertos_min"),
                    duracion_minutos=test.get("duracion_minutos", 60),
                )
                
                if reserva:
                    # Si logró la reserva, actualizar el test
                    test["estado"] = "SCHEDULED"
                    test["reservation_id"] = reserva["id"]
                    print(f"✓ Test {test_id} fue scheduled automáticamente")
                    
        except Exception as e:
            print(f"Error en procesar_cola_pendiente: {e}")
            # Continuar intentando aunque haya error


# ── Queries ────────────────────────────────────────────────────────────────────

@strawberry.type
class Query:

    @strawberry.field(description="Retorna todas las solicitudes de test. Filtrables por estado o tester.")
    def test_requests(
        self,
        estado: Optional[str] = None,
        tester_id: Optional[str] = None,
    ) -> List[TestRequest]:
        results = list(test_requests.values())

        if estado:
            results = [r for r in results if r["estado"].upper() == estado.upper()]
        if tester_id:
            results = [r for r in results if r["tester_id"] == tester_id]

        # Ordenar por prioridad
        results.sort(key=lambda r: r["prioridad"])
        return [dict_to_test_request(r) for r in results]

    @strawberry.field(description="Retorna una solicitud de test por su ID.")
    def test_request(self, id: str) -> Optional[TestRequest]:
        if id not in test_requests:
            return None
        return dict_to_test_request(test_requests[id])

    @strawberry.field(description="Retorna solo los tests en cola (estado QUEUED), ordenados por prioridad.")
    def cola_pendiente(self) -> List[TestRequest]:
        queued = [r for r in test_requests.values() if r["estado"] == "QUEUED"]
        queued.sort(key=lambda r: r["prioridad"])
        return [dict_to_test_request(r) for r in queued]

    @strawberry.field(description="Consulta el detalle de una reserva en Reservation Service.")
    async def reserva(self, reservation_id: str) -> Optional[ReservationInfo]:
        data = await obtener_reserva(reservation_id)
        if not data:
            return None
        return ReservationInfo(
            id=data["id"],
            test_id=data["test_id"],
            switch_ids=data["switch_ids"],
            estado=data["estado"],
            creada_en=data["creada_en"],
            expira_en=data["expira_en"],
            liberada_en=data.get("liberada_en"),
        )


# ── Mutations ──────────────────────────────────────────────────────────────────

@strawberry.type
class Mutation:

    @strawberry.mutation(description="""
Recibe una nueva solicitud de test del tester.

**Flujo:**
1. Crea la TestRequest con estado `QUEUED`
2. Intenta solicitar una reserva en **Reservation Service** con criterios técnicos
3. Si la reserva se confirma → estado `SCHEDULED`
4. Si no hay recursos disponibles → permanece en `QUEUED`
    """)
    async def submit_test(self, input: TestRequestInput) -> SubmitResult:
        req_id = f"req-{str(uuid.uuid4())[:8]}"
        nueva = {
            "id": req_id,
            "tester_id": input.tester_id,
            "requiere_poe": input.requiere_poe,
            "topologia": input.topologia,
            "plataforma": input.plataforma,
            "sku": input.sku,
            "numero_puertos_min": input.numero_puertos_min,
            "prioridad": input.prioridad,
            "estado": "QUEUED",
            "creada_en": datetime.utcnow().isoformat() + "Z",
            "reservation_id": None,
        }
        test_requests[req_id] = nueva

        # Intentar reservar con los criterios técnicos
        reserva = await solicitar_reserva(
            test_id=req_id,
            plataforma=input.plataforma,
            sku=input.sku,
            requiere_poe=input.requiere_poe,
            topologia=input.topologia,
            numero_puertos_min=input.numero_puertos_min,
            duracion_minutos=input.duracion_minutos,
        )

        if reserva:
            nueva["estado"] = "SCHEDULED"
            nueva["reservation_id"] = reserva["id"]
            return SubmitResult(
                success=True,
                message=f"Test encolado y reserva confirmada: {reserva['id']}",
                test_request=dict_to_test_request(nueva),
            )

        return SubmitResult(
            success=True,
            message="Test encolado. Sin recursos disponibles aún, esperando en cola.",
            test_request=dict_to_test_request(nueva),
        )

    @strawberry.mutation(description="Cancela una solicitud de test que esté en estado QUEUED o SCHEDULED.")
    def cancel_test(self, test_id: str) -> CancelResult:
        if test_id not in test_requests:
            return CancelResult(success=False, message=f"Test '{test_id}' no encontrado")

        req = test_requests[test_id]
        if req["estado"] not in ("QUEUED", "SCHEDULED"):
            return CancelResult(
                success=False,
                message=f"No se puede cancelar un test con estado '{req['estado']}'",
            )

        req["estado"] = "CANCELLED"
        return CancelResult(success=True, message=f"Test '{test_id}' cancelado correctamente")


# ── App FastAPI + GraphQL ──────────────────────────────────────────────────────

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_app = GraphQLRouter(schema)

app = FastAPI(
    title="Scheduling Service",
    description="""
## Contexto: Scheduling (GraphQL)

Gestiona la cola de tests pendientes y decide el orden de ejecución
cuando los recursos no están disponibles de inmediato.

**GraphQL endpoint:** `/graphql`
**GraphiQL (UI interactiva):** `/graphql`

**Responsabilidades:**
- Recibir y encolar solicitudes de tests
- Solicitar reservas a Reservation cuando hay recursos disponibles
- Priorizar y ordenar la cola de tests pendientes
    """,
    version="1.0.0",
)

app.include_router(graphql_app, prefix="/graphql")


@app.on_event("startup")
async def startup_event():
    """
    Al iniciar la aplicación, lanza la tarea de background
    que intenta procesar la cola cada REINTENTO_INTERVAL_SEGUNDOS segundos.
    """
    asyncio.create_task(procesar_cola_pendiente())


@app.get("/health", tags=["Health"], summary="Health check del servicio")
def health():
    return {"service": "scheduling", "status": "ok", "port": 8003, "graphql": "/graphql"}
