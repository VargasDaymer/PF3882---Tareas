import uuid
import json
import os
import httpx
import aio_pika
import strawberry
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

RESERVATION_URL = os.getenv("RESERVATION_URL", "http://reservation:8002")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://admin:admin@rabbitmq:5672/")
REINTENTO_INTERVAL_SEGUNDOS = 10

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


@strawberry.type
class ReleaseResult:
    success: bool
    message: str
    reservation: Optional[ReservationInfo]


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


async def liberar_reserva(reservation_id: str, motivo: str = "TestCompleted") -> Optional[dict]:
    """
    Libera una reserva en Reservation Service.
    Marca la reserva como RELEASED y devuelve el switch a estado AVAILABLE.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"{RESERVATION_URL}/reservations/{reservation_id}/release",
                json={"motivo": motivo},
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
    recursos a los tests en estado QUEUED. Actúa como respaldo del consumer
    de RabbitMQ en caso de que algún evento se pierda.
    """
    while True:
        try:
            await asyncio.sleep(REINTENTO_INTERVAL_SEGUNDOS)

            queued_tests = [
                (test_id, test)
                for test_id, test in test_requests.items()
                if test["estado"] == "QUEUED"
            ]

            for test_id, test in queued_tests:
                # Verificar que sigue en QUEUED antes de intentar reservar
                # (puede haber sido asignado por RabbitMQ entre iteraciones)
                if test_requests.get(test_id, {}).get("estado") != "QUEUED":
                    continue

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
                    test["estado"] = "SCHEDULED"
                    test["reservation_id"] = reserva["id"]
                    print(f"[Polling] Test '{test_id}' scheduled por polling de background")

        except Exception as e:
            print(f"[Polling] Error en procesar_cola_pendiente: {e}")


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
3. Si la reserva se confirma → Reservation publica `ReservationCreated` en RabbitMQ → estado `SCHEDULED`
4. Si no hay recursos disponibles → permanece en `QUEUED` hasta que RabbitMQ notifique disponibilidad
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

    @strawberry.mutation(description="""
Libera una reserva activa marcándola como RELEASED.

**Flujo:**
1. Llama a Reservation Service para liberar la reserva
2. Reservation publica el evento `ReservationReleased` en RabbitMQ
3. Scheduling consume el evento e inmediatamente:
   - Marca el test dueño de la reserva como `COMPLETED`
   - Re-intenta asignar recursos a tests en `QUEUED`
    """)
    async def release_reservation(self, reservation_id: str, motivo: str = "TestCompleted") -> ReleaseResult:
        resultado = await liberar_reserva(reservation_id, motivo)
        
        if not resultado:
            return ReleaseResult(
                success=False,
                message=f"No se pudo liberar la reserva '{reservation_id}'. Verifica que exista y esté activa.",
                reservation=None,
            )
        
        return ReleaseResult(
            success=True,
            message=f"Reserva '{reservation_id}' liberada correctamente. El switch está nuevamente disponible.",
            reservation=ReservationInfo(
                id=resultado["id"],
                test_id=resultado["test_id"],
                switch_ids=resultado["switch_ids"],
                estado=resultado["estado"],
                creada_en=resultado["creada_en"],
                expira_en=resultado["expira_en"],
                liberada_en=resultado.get("liberada_en"),
            ),
        )


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
- Escuchar eventos de Reservation vía **RabbitMQ** para reaccionar en tiempo real
    """,
    version="1.0.0",
)

app.include_router(graphql_app, prefix="/graphql")


# ── RabbitMQ Consumer ──────────────────────────────────────────────────────────
async def consumir_eventos_rabbitmq():
    """
    Consumer de eventos de RabbitMQ.
    Escucha el exchange 'testbed' (fanout) y reacciona a:

    - ReservationCreated: Actualiza el test a SCHEDULED con el reservation_id
    - ReservationReleased: Re-intenta asignar recursos a tests en QUEUED
    """
    # Reintentar conexión si RabbitMQ no está listo aún
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=10)
            print("[RabbitMQ] Scheduling conectado al broker ✓")
            break
        except Exception as e:
            print(f"[RabbitMQ] Esperando conexión... {e}")
            await asyncio.sleep(5)

    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            "testbed",
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )
        # Cola exclusiva para este consumer
        queue = await channel.declare_queue("scheduling_events", durable=True)
        await queue.bind(exchange)

        print("[RabbitMQ] Scheduling escuchando eventos en 'scheduling_events'...")

        async for message in queue:
            async with message.process():
                try:
                    body = json.loads(message.body.decode())
                    event_type = body.get("event_type")
                    print(f"[RabbitMQ] Evento recibido: {event_type} → {body}")

                    if event_type == "ReservationCreated":
                        # Actualizar el test con el reservation_id recibido
                        test_id = body.get("test_id")
                        reservation_id = body.get("reservation_id")
                        if test_id and test_id in test_requests:
                            test_requests[test_id]["estado"] = "SCHEDULED"
                            test_requests[test_id]["reservation_id"] = reservation_id
                            print(f"[RabbitMQ] Test '{test_id}' actualizado a SCHEDULED (reserva: {reservation_id})")

                    elif event_type == "ReservationReleased":
                        # 1. Marcar el test dueño de esa reserva como COMPLETED
                        reservation_id = body.get("reservation_id")
                        for tid, t in test_requests.items():
                            if t.get("reservation_id") == reservation_id and t["estado"] == "SCHEDULED":
                                t["estado"] = "COMPLETED"
                                print(f"[RabbitMQ] Test '{tid}' marcado como COMPLETED (reserva liberada: {reservation_id})")
                                break

                        # 2. Re-intentar tests en QUEUED ahora que hay un switch libre
                        print("[RabbitMQ] ReservationReleased: re-intentando tests en QUEUED...")
                        queued = [
                            (tid, t) for tid, t in test_requests.items()
                            if t["estado"] == "QUEUED"
                        ]
                        for test_id, test in queued:
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
                                test["estado"] = "SCHEDULED"
                                test["reservation_id"] = reserva["id"]
                                print(f"[RabbitMQ] Test '{test_id}' scheduled tras ReservationReleased")

                except Exception as e:
                    print(f"[RabbitMQ] Error procesando mensaje: {e}")


@app.on_event("startup")
async def startup_event():
    """
    Al iniciar la aplicación lanza dos tareas de background:
    1. procesar_cola_pendiente: reintenta QUEUED cada N segundos (polling).
    2. consumir_eventos_rabbitmq: escucha eventos de Reservation en tiempo real.
    """
    asyncio.create_task(procesar_cola_pendiente())
    asyncio.create_task(consumir_eventos_rabbitmq())


@app.get("/health", tags=["Health"], summary="Health check del servicio")
def health():
    return {"service": "scheduling", "status": "ok", "port": 8003, "graphql": "/graphql"}
