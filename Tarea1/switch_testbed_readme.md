
# Switch Testbed Reservation System

## Descripción

En un entorno real de testing de redes, los ingenieros suelen enfrentarse a un proceso altamente manual y poco eficiente. Antes de ejecutar una prueba, deben buscar switches disponibles, verificar que cumplan con los requisitos técnicos (como versión de firmware, soporte de PoE o tipo de plataforma), configurar manualmente la topología y coordinar el uso de recursos con otros testers para evitar conflicto.

Este flujo de trabajo no solo consume tiempo, sino que también es propenso a errores humanos y difícil de escalar cuando múltiples pruebas deben ejecutarse de forma concurrente, en un hardware límitado.

El Management Switch Reservation System surge como una solución a este problema, proporcionando una plataforma centralizada que automatiza completamente este proceso. Desde la perspectiva del tester, la interacción con el sistema es simple: únicamente debe definir un test especificando sus requisitos técnicos del test, como:
- Necesidad de PoE
- Versión requerida de firmware
- Topología
- Tipo de plataforma

A partir de esta información, el sistema se encarga automáticamente de:
- Identificar switches compatibles
- Reservar los recursos necesarios
- Encender los dispositivos si es requerido
- Ejecutar la prueba de forma automatizada

Durante la ejecución, el usuario puede monitorear el progreso mediante logs en tiempo real y estados claros del test. Una vez finalizada la prueba, el sistema libera los recursos utilizados, puede apagar los dispositivos para optimizar energía y actualiza métricas que permiten analizar el rendimiento del entorno de testing.

Este enfoque permite resolver problemas clave, como conflictos entre testers o entre test automatizados, dificultad en el debbuging al ser muchas pruebas, optimizacion de los rescursos, ejecuciones fuera de supervisión humana.

---

## Funcionalidades

### Inventory
Indica el hardware disponible. Registra switches con sus specs técnicas (firmware, PoE, plataforma) y expone una API de búsqueda por constraints para que otros contextos consulten candidatos compatibles.
- Registro y actualización de switches
- Filtrado por requisitos técnicos
- Ciclo de vida del dispositivo (`AVAILABLE`, `RESERVED`, `POWERED_OFF`, `MAINTENANCE`)

### Reservation
Árbitro de la concurrencia. Asigna switches a un test de forma exclusiva, evitando que dos pruebas usen el mismo recurso simultáneamente.
- Asignación automática basada en disponibilidad
- Prevención de conflictos con bloqueo por tiempo
- Liberación automática al finalizar o expirar el test

### Scheduling
Gestiona la cola de pruebas pendientes cuando no hay recursos disponibles de inmediato. Decide el orden de ejecución según prioridad y tiempo de espera.
- Cola de tests con priorización configurable
- Re-intento automático al liberarse recursos
- Prevención de starvation para tests de baja prioridad

### Power Management
Controla el encendido y apagado de los dispositivos físicos. Optimiza el consumo energético apagando switches que no están en uso.
- Encendido secuencial con validación de boot
- Apagado automático al liberar una reserva
- Control de secuencias de arranque por topología


### Test Execution
Orquesta la ejecución de la prueba sobre los switches reservados. Aplica la topología, corre el test y reporta el resultado.
- Configuración automática de topología
- Estados del test: `PENDING`, `RUNNING`, `PASSED`, `FAILED`
- Streaming de logs en tiempo real durante la ejecución


### Observability
Consumidor de eventos de todos los contextos. Agrega logs, métricas y estados para dar visibilidad global del sistema sin acoplarse al flujo principal.
- Logs centralizados por test y por dispositivo
- Métricas de utilización de hardware y duración de pruebas
- Alertas ante fallos o recursos bloqueados por tiempo excesivo

---

## Diagrama de interacción entre contextos

```mermaid
graph TD
    subgraph INV ["Inventory"]
        INV_E["Eventos: SwitchRegistered\nSwitchUpdated · SwitchRetired"]
        INV_B["API: query_compatible_switches()"]
    end

    subgraph RES ["Reservation"]
        RES_E["Eventos: ReservationCreated\nReservationReleased · ReservationExpired"]
    end

    subgraph SCH ["Scheduling"]
        SCH_E["Eventos: TestQueued\nTestDequeued · PriorityChanged"]
    end

    subgraph PWR ["Power Management"]
        PWR_E["Eventos: DevicePoweredOn\nDevicePoweredOff · DevicesReady"]
    end

    subgraph EXE ["Test Execution"]
        EXE_E["Eventos: TestStarted\nTestCompleted · TestFailed"]
    end

    subgraph OBS ["Observability"]
        OBS_E["Suscrito a todos los eventos\nLogs · Métricas · Estados"]
    end

    %% API calls (sync)
    SCH -->|"API: query switches"| INV
    SCH -->|"API: request_reservation()"| RES

    %% Async events
    RES -.->|"ReservationCreated"| PWR
    PWR -.->|"DevicesReady"| EXE
    EXE -.->|"TestCompleted"| RES

    %% Observability listens to all
    RES -.->|"domain events"| OBS
    EXE -.->|"domain events"| OBS
    PWR -.->|"domain events"| OBS
    SCH -.->|"domain events"| OBS

    %% Styles
    classDef inventory     fill:#0d2044,stroke:#1f6feb,color:#58a6ff
    classDef reservation   fill:#0d1c3b,stroke:#388bfd,color:#79c0ff
    classDef scheduling    fill:#1a0f35,stroke:#8957e5,color:#bc8cff
    classDef power         fill:#2b1f04,stroke:#e3b341,color:#e3b341
    classDef execution     fill:#2b1008,stroke:#f78166,color:#ffa198
    classDef observability fill:#0c2317,stroke:#3fb950,color:#56d364

    class INV,INV_E,INV_B inventory
    class RES,RES_E reservation
    class SCH,SCH_E scheduling
    class PWR,PWR_E power
    class EXE,EXE_E execution
    class OBS,OBS_E observability
```

## Flujo de eventos

```mermaid
sequenceDiagram
    autonumber
    actor T as Tester
    participant SCH as Scheduling
    participant INV as Inventory
    participant RES as Reservation
    participant PWR as Power Mgmt
    participant EXE as Test Execution
    participant OBS as Observability

    T->>SCH: submit_test(firmware, poe, topology, platform)

    SCH->>INV: query_compatible_switches(requirements)
    INV-->>SCH: [switch_ids[]]

    SCH->>RES: request_reservation(switch_ids, duration)
    RES-)OBS: ReservationCreated (event)

    RES-)PWR: ReservationCreated (event)
    PWR->>PWR: power_on(switch_ids)
    PWR-)RES: DevicesReady (event)
    PWR-)OBS: DevicesReady (event)

    RES->>SCH: reservation confirmed
    SCH->>EXE: dispatch_test(reservation_id, topology)
    EXE-)OBS: TestStarted (event)

    EXE->>EXE: run test + stream logs
    EXE-)OBS: logs en tiempo real
    EXE-)OBS: TestCompleted (event)
    EXE-->>T: result available

    EXE-)RES: TestCompleted → ReservationReleased
    RES-)PWR: ReservationReleased (event)
    PWR->>PWR: power_off(switch_ids)
    PWR-)OBS: DevicesPoweredOff (event)
```