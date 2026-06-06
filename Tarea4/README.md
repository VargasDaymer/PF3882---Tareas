# Switch Testbed — Tarea #4: Pruebas de Contrato con Pact

Implementación de pruebas de contrato entre **Reservation** (consumer) e **Inventory** (provider)
utilizando el framework **Pact**. Ademas de test para verificar que se cumple el contrato.

Los servicios son una copia directa de Tarea #2, sin modificaciones, aunque no son utilizados.

---

## Estructura del proyecto

```
Tarea4/
├── inventory/                        ← Servicio Inventory (copia de Tarea2)
│   ├── main.py
│   ├── switches.json
│   ├── requirements.txt
│   └── Dockerfile
├── reservation/                      ← Servicio Reservation (copia de Tarea2)
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── consumer/
    ├── test_consumer.py              ← 7 pruebas del consumer (genera el contrato)
    └── requirements.txt

```

---

## Interacciones definidas en el contrato

| # | Descripción | Request | Respuesta esperada |
|---|-------------|---------|-------------------|
| 1 | Switches compatibles disponibles | `GET /switches/compatible?plataforma=Aruba 800&requiere_poe=true&topologia=Standalone` | 200 + lista con switch |
| 2 | Sin switches para plataforma inexistente | `GET /switches/compatible?plataforma=Aruba 999&requiere_poe=true&topologia=Standalone` | 200 + lista vacía `[]` |
| 3 | Listar todos los switches | `GET /switches` | 200 + lista con estructura correcta |

---

## Requisitos previos

- Python 3.11 o superior
- `pip` disponible en el sistema

---

## Configuración del entorno

### 1. Crear el entorno virtual

```bash
cd Tarea4
python3 -m venv .venv
```

### 2. Activar el entorno virtual

```bash
# Linux
source .venv/bin/activate
```

Una vez activado, el prompt del terminal muestra `(.venv)` al inicio.

### 3. Instalar los paquetes

```bash
pip install -r consumer/requirements.txt
pip install -r inventory/requirements.txt
```

> **Nota:** El directorio `.venv/` está en `.gitignore` y no se sube al repositorio.
> Cada persona debe crearlo localmente siguiendo estos pasos.

---

## Ejecutar las pruebas

Asegúrate de tener el entorno virtual **activado** antes de correr cualquier test.

```bash
pytest consumer/test_consumer.py -v
```

Al finalizar, se genera el archivo:
```
pacts/reservation-inventory.json
```

Ese archivo es el **contrato**: describe exactamente qué espera Reservation de Inventory.

---

## Resultado esperado

```
PASSED consumer/test_consumer.py::test_switches_compatibles_disponibles
PASSED consumer/test_consumer.py::test_switches_compatibles_sin_resultados
PASSED consumer/test_consumer.py::test_listar_todos_los_switches
PASSED consumer/test_consumer.py::test_switches_compatibles_con_sku_especifico
PASSED consumer/test_consumer.py::test_switches_compatibles_sin_poe
PASSED consumer/test_consumer.py::test_switches_compatibles_con_minimo_puertos
PASSED consumer/test_consumer.py::test_switches_compatibles_topologia_con_espacio

7 passed in X.XXs
```

---

## Qué valida cada prueba

### Consumer tests (`test_consumer.py`)

**test_switches_compatibles_disponibles**
Simula la llamada que Reservation hace cuando busca switches disponibles para asignar a un test.
Verifica que Inventory retorna una lista con switches en estado AVAILABLE y la estructura correcta.

**test_switches_compatibles_sin_resultados**
Simula la llamada cuando no hay switches para los criterios dados.
Verifica que Inventory retorna 200 con lista vacía (no un error 404).

**test_listar_todos_los_switches**
Simula la llamada a `GET /switches`.
Verifica que todos los campos del modelo Switch están presentes en la respuesta.

**test_switches_compatibles_con_sku_especifico**
Verifica el filtro por SKU: Inventory retorna solo switches con el SKU solicitado.

**test_switches_compatibles_sin_poe**
Verifica que el parámetro `requiere_poe=false` retorna switches con `soporte_poe=false`.

**test_switches_compatibles_con_minimo_puertos**
Verifica el filtro `numero_puertos_min`: todos los switches retornados deben tener al menos ese número de puertos.

**test_switches_compatibles_topologia_con_espacio**
Verifica que topologías con espacios (`Dual Link`) se manejan correctamente en la URL.

