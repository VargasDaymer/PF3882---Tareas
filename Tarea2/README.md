# Switch Testbed — Tarea #2: APIs REST y GraphQL

Implementación de 3 microservicios del sistema **Switch Testbed Reservation System**:

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
           | (Puerto 8003|              |   http://       |
           |  - Queue    |              |localhost:8003/  |
           |  - Priority |              |    graphql      |
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

2. Scheduling intenta crear una reserva en Reservation Service con esos criterios.

3. Reservation consulta a Inventory para buscar switches disponibles que cumplan los criterios.

4. Si Inventory retorna switches disponibles, Reservation asigna el primero y crea la reserva. El test pasa a estado SCHEDULED.

5. Si no hay switches disponibles, el test queda en estado QUEUED.

6. Un proceso de background en Scheduling intenta reintentar cada 10 segundos los tests en QUEUED. Cuando un switch se libera, los tests esperando son automáticamente asignados.

7. Al terminar el test, la reserva es liberada y el switch vuelve a estar AVAILABLE.

---

## Demo

Para demostrar cómo funciona el sistema, sigue estos pasos:

**Paso 1: Levanta los contenedores**

Abre http://localhost:8003/graphql en tu navegador.

**Paso 2: Verifica que la cola está vacía**

En GraphQL, ejecuta:

```graphql
query {
  colaPendiente {
    id
    testerId
    estado
  }
}
```

Resultado esperado: lista vacía.

**Paso 3: Envía un primer test que debe conseguir recurso**

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
    prioridad: 2
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

Resultado esperado: estado SCHEDULED con un reservationId asignado, porque hay switches disponibles.

**Paso 4: Envía varios tests más para saturar**

Ejecuta dos o tres veces más la siguiente mutación con diferentes testerId y prioridades:

```graphql
mutation {
  submitTest(input: {
    testerId: "tester-maria"
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

Resultado esperado: algunos tests quedarán en estado QUEUED porque ya no hay más switches Aruba 800 disponibles.

**Paso 5: Observa la cola de espera**

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

Resultado esperado: los tests en QUEUED aparecen ordenados por prioridad (números menores primero).

**Paso 6: Libera una reserva para ver los reintentos automáticos**

Primero obtén el ID (reservationId) de una reserva activa. 

```graphql
query {
  testRequests {
    id
    testerId
    estado
    prioridad
    plataforma
    topologia
    reservationId
    creadaEn
  }
}
```

Luego, libera una reserva utilizando su ID:

```graphql
mutation {
  releaseReservation(reservationId: "reservationId", motivo: "TestCompleted") {
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

**Paso 7: Verifica que los tests en QUEUED fueron asignados**

Espera 10 segundos (intervalo de reintentos) y ejecuta nuevamente:

```graphql
query {
  colaPendiente {
    id
    testerId
    estado
  }
}
```

Resultado esperado: al menos uno de los tests que estaba en QUEUED ahora debe estar en SCHEDULED, porque el switch que se liberó fue reasignado automáticamente por el proceso de background. Deberias ver que hay un test menos en la cola.

---

## Estructura del proyecto

```
switch-testbed/
├── docker-compose.yml
├── README.md
├── inventory/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   └── switches.json          ← Base de datos hardcodeada
├── reservation/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
└── scheduling/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py
```
