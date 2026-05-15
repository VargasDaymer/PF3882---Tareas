# Tarea #3: Comunicación Asíncrona con RabbitMQ

Evolución de Tarea #2: se agrega **mensajería asíncrona con RabbitMQ** entre los servicios
**Reservation** (publicador) y **Scheduling** (consumidor).

En Tarea #2, Scheduling solo se enteraba de reservas al momento de crearlas.
Si una reserva era liberada, los tests permanecían en `QUEUED` hasta el siguiente ciclo de polling.

Con mensajería asíncrona, **Reservation publica eventos** y **Scheduling los consume en tiempo real**:

| Evento | Cuándo se publica | Qué hace Scheduling |
|--------|-------------------|---------------------|
| `ReservationCreated` | Al crear una reserva | Actualiza el test a `SCHEDULED` |
| `ReservationReleased` | Al liberar una reserva | Re-intenta tests en `QUEUED` inmediatamente |

---

## Servicios

| Servicio | Tipo | Puerto | Descripción |
|---|---|---|---|
| **Inventory** | REST | 8001 | Catálogo de switches con datos fijos desde JSON |
| **Reservation** | REST | 8002 | Reservas exclusivas de switches; consulta Inventory |
| **Scheduling** | GraphQL | 8003 | Cola de tests; solicita reservas a Reservation |

### Diagrama del sistema

```
                          TESTERS (Clientes GraphQL)
                                |
                                |
                ┌───────────────────────────────────┐
                |                                   |
                v                                   v
           ┌─────────────┐              ┌──────────────────┐
           | SCHEDULING  |              |    GraphQL       |
           | (Puerto 8003|              |   http://        |
           |  - Queue    |              |localhost:8003/   |
           |  - Priority |              |    graphql       |
           |  - Retries) |              └──────────────────┘
           └──────┬──────┘
                  |
                  | REST POST /reservations
                  | (busca criterios tecnicos)
                  |
                  v
           ┌─────────────┐
           | RESERVATION |
           | (Puerto 8002|
           |  - Valida   |
           |  - Asigna   |
           |  - Libera)  |
           └──────┬──────┘
                  |
                  | REST GET /switches/compatible
                  | (consulta segun criterios)
                  |
                  v
           ┌─────────────┐
           | INVENTORY   |
           | (Puerto 8001|
           |  - Catalogo |
           |  - Estados  |
           |  - Filtros) |
           └─────────────┘
```

---
## Levantar el sistema

```bash
# Construir y levantar los 3 servicios
docker compose up --build
```

---

## Documentación interactiva (Swagger / GraphiQL)

Una vez levantado el sistema:

| Servicio | URL de documentación |
|---|---|
| Inventory (Swagger) | http://localhost:8001/docs |
| Reservation (Swagger) | http://localhost:8002/docs |
| Scheduling (GraphiQL) | http://localhost:8003/graphql |

---

## Inventory Service — REST (Puerto 8001)

Inventory mantiene el catálogo de switches disponibles en el laboratorio. Cada switch tiene especificaciones técnicas como plataforma, SKU, soporte PoE, cantidad de puertos y topología. Este servicio no conoce sobre reservas; solo proporciona información sobre switches y sus disponibilidades.

### `GET /switches`
Lista todos los switches del catálogo. Acepta filtros opcionales para búsquedas.

### `GET /switches/compatible`
Endpoint principal usado por Reservation. Retorna switches en estado AVAILABLE que cumplen los criterios técnicos especificados. Los parámetros disponibles son:

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `plataforma` | string | Sí (para reservar) | Plataforma Aruba: 800, 850, 900, 950 |
| `sku` | string | No | Modelo específico: 800.1, 800.2, etc. |
| `soporte_poe` | boolean | Sí (para reservar) | Si el switch debe soportar Power over Ethernet |
| `topologia` | string | Sí (para reservar) | Standalone, Dual Link, Stack, PoE Bench |
| `numero_puertos_min` | integer | No | Cantidad mínima de puertos requerida |


**Estados posibles:** `AVAILABLE`, `RESERVED`, `POWERED_OFF`, `MAINTENANCE`

**Plataformas soportadas:** Aruba 800, Aruba 850, Aruba 900, Aruba 950

**Topologías soportadas:** Standalone, Dual Link, Stack, PoE Bench

---

## Reservation Service — REST (Puerto 8002)

El servicio de Reservation gestiona la asignacion exclusiva de switches a tests. Cuando recibe una solicitud, busca switches disponibles en Inventory que cumplan los criterios tecnicos especificados, y si los encuentra, crea una reserva exclusiva para evitar conflictos entre tests concurrentes.

### `GET /reservations`
Lista todas las reservas activas, liberadas y expiradas:

```
GET http://localhost:8002/reservations
```

### `GET /reservations/{id}`
Detalle de una reserva específica:

```
GET http://localhost:8002/reservations/{reservation_id}
```

### `POST /reservations`
Crea una reserva exclusiva de switches. Busca en Inventory switches compatibles segun los criterios y asigna el primero disponible.

```
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

Retorna:
- Estado 201 con la reserva creada si se consiguio un switch
- Estado 404 si no hay switches disponibles que cumplan los criterios
- Estado 409 si todos los switches compatibles ya estan reservados

### `PATCH /reservations/{id}/release`
Libera una reserva activa.

### `DELETE /reservations/{id}`
Elimina una reserva del registro.


---

## Scheduling Service — GraphQL (Puerto 8003)

Scheduling actúa como orquestador de la cola de tests. Recibe solicitudes de tests, intenta asignarles recursos a través de Reservation, y mantiene los tests que no pudieron ser asignados en una cola de espera ordenada por prioridad. Un proceso de background intenta reintentar la asignacion cada 10 segundos para los tests en cola.

Acceder al playground interactivo: **http://localhost:8003/graphql**

### Queries

#### Listar todos los tests
```graphql
query {
  testRequests {
    id
    testerId
    estado
    prioridad
    topologia
    requierePoe
    plataforma
    reservationId
    creadaEn
  }
}
```

#### Filtrar por estado o tester
```graphql
query {
  testRequests(estado: "QUEUED") {
    id
    testerId
    prioridad
    estado
  }
}

query {
  testRequests(testerId: "tester-ana") {
    id
    estado
    reservationId
  }
}
```

#### Ver la cola pendiente (ordenada por prioridad)
```graphql
query {
  colaPendiente {
    id
    testerId
    prioridad
    topologia
  }
}
```

#### Ver un test específico
```graphql
query {
  testRequest(id: "req-demo-01") {
    id
    estado
    reservationId
    plataforma
    topologia
  }
}
```

#### Consultar detalle de una reserva (llama a Reservation Service)
```graphql
query {
  reserva(reservationId: "res-abc123") {
    id
    testId
    switchIds
    estado
    creadaEn
    expiraEn
  }
}
```

### Mutations

#### Enviar un nuevo test
```graphql
mutation {
  submitTest(input: {
    testerId: "tester-carlos"
    plataforma: "Aruba 800"
    sku: "800.1"
    requierePoe: true
    topologia: "Standalone"
    numeroPuertosMin: 24
    duracionMinutos: 60
    prioridad: 1
  }) {
    success
    message
    testRequest {
      id
      estado
      reservationId
    }
  }
}
```

Si hay switches disponibles que cumplan los criterios, el test pasa directamente a estado SCHEDULED. Si no, queda en QUEUED esperando en la cola.

#### Cancelar un test
```graphql
mutation {
  cancelTest(testId: "req-demo-02") {
    success
    message
  }
}
```

Solo se pueden cancelar tests que estén en estado QUEUED o SCHEDULED.

#### Liberar una reserva
```graphql
mutation {
  releaseReservation(reservationId: "res-abc123", motivo: "TestCompleted") {
    success
    message
    reservation {
      id
      testId
      switchIds
      estado
      liberadaEn
    }
  }
}
```

Esta mutation libera un switch que estaba en uso, lo marca como RELEASED y lo devuelve a estado AVAILABLE. Automáticamente, el proceso de background de Scheduling intentará asignar ese switch a tests en QUEUED en el próximo ciclo de reintentos (cada 10 segundos).

---

## Flujo completo de ejemplo

El flujo de trabajo es el siguiente:

1. Un tester envía una solicitud de test a Scheduling, especificando los criterios técnicos que necesita (plataforma, PoE, topología, etc).

2. Scheduling intenta crear una reserva en Reservation Service con esos criterios (REST).

3. Reservation consulta a Inventory para buscar switches disponibles que cumplan los criterios (REST).

4. Si Inventory retorna switches disponibles, Reservation asigna el primero, crea la reserva y **publica el evento `ReservationCreated` en RabbitMQ**.

5. Scheduling **consume el evento `ReservationCreated`** y actualiza el test a estado `SCHEDULED` en tiempo real.

6. Si no hay switches disponibles en el paso 3, el test queda en estado `QUEUED`.

7. Al terminar el test, la reserva es liberada desde Scheduling (`releaseReservation`). Reservation **publica el evento `ReservationReleased` en RabbitMQ**.

8. Scheduling **consume el evento `ReservationReleased`** e inmediatamente re-intenta asignar recursos a los tests en `QUEUED`, sin esperar el ciclo de polling.

---

## Demo — Verificación de mensajería asíncrona

> Todo el flujo se realiza desde **GraphiQL** en http://localhost:8003/graphql  
> y desde la **RabbitMQ Management UI** en http://localhost:15672 (admin / admin)

---

### Paso 1 — Verificar que el broker está activo

Abrir http://localhost:15672, ir a la pestaña **Queues and Streams**.

Debe aparecer la cola `scheduling_events` con un state de Running, esto confirma que Scheduling se conectó a RabbitMQ.

---

### Paso 2 — Saturar los switches disponibles

Envía tests hasta que uno quede en `QUEUED`. Los switches Aruba 800 / Standalone / PoE tienen 3 unidades disponibles, así que con 4 submissions el último quedará sin recurso.

Ejecuta esta mutation **4 veces** en GraphiQL (cambia el `testerId` y `prioridad` en cada ejecución):

```graphql
mutation {
  submitTest(input: {
    testerId: "tester-ana"
    plataforma: "Aruba 800"
    sku: "800.1"
    requierePoe: true
    topologia: "Standalone"
    duracionMinutos: 60
    prioridad: 1
  }) {
    success
    message
    testRequest {
      id
      estado
      reservationId
    }
  }
}
```

Los primeros 3 devolverán `estado: SCHEDULED`.  
El 4to devolverá `estado: QUEUED` — **no hay switch disponible**.

---

### Paso 3 — Confirmar tests en cola

```graphql
query {
  colaPendiente {
    id
    testerId
    prioridad
    estado
  }
}
```

Debe aparecer al menos un test en `QUEUED`.

---

### Paso 4 — Obtener el ID de una reserva activa

```graphql
query {
  testRequests(estado: "SCHEDULED") {
    id
    testerId
    estado
    reservationId
  }
}
```

Copia el `reservationId` de uno de los tests (ej: `res-abc12345`).

---

### Paso 5 — Liberar la reserva desde Scheduling (GraphQL)

Usa la mutation `releaseReservation` con el ID copiado en el paso anterior:

```graphql
mutation {
  releaseReservation(reservationId: "res-abc12345", motivo: "TestCompleted") {
    success
    message
    reservation {
      id
      estado
      switchIds
      liberadaEn
    }
  }
}
```

La respuesta debe mostrar `estado: RELEASED`.

---

### Paso 6 — Observar los eventos en los logs

En la terminal donde corre Docker Compose verás:

**Logs de `reservation`:**
```
[RabbitMQ] Evento publicado: ReservationReleased → {"event_type": "ReservationReleased", "reservation_id": "res-abc12345", ...}
```

**Logs de `scheduling`:**
```
[RabbitMQ] Evento recibido: ReservationReleased → {...}
[RabbitMQ] Test 'req-xxxxxxxx' scheduled tras ReservationReleased
```

Esto confirma que **Reservation publicó el evento** y **Scheduling lo consumió en tiempo real**.

---

### Paso 7 — Confirmar que el test QUEUED pasó a SCHEDULED

```graphql
query {
  colaPendiente {
    id
    testerId
    estado
  }
}
```

La cola debe estar vacía (o con un test menos).

```graphql
query {
  testRequests(estado: "SCHEDULED") {
    id
    testerId
    estado
    reservationId
  }
}
```

El test que estaba en `QUEUED` ahora debe estar en `SCHEDULED` con un `reservationId` nuevo asignado.

---

### Paso 8 — Verificar métricas en RabbitMQ Management UI

En http://localhost:15672 → **Queues** → `scheduling_events`:

| Métrica | Qué indica |
|---------|------------|
| **Messages published** | Eventos enviados por Reservation |
| **Messages delivered** | Eventos procesados por Scheduling |

Ambos contadores deben incrementarse con cada reserva creada o liberada.