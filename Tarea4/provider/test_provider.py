"""
Provider Contract Tests — Inventory como provider

Estas pruebas verifican que Inventory (el provider) cumple el contrato
definido por Reservation (el consumer) en pacts/reservation-inventory.json.

Pact levanta el servicio real de Inventory y reproduce cada interacción
del contrato, verificando que las respuestas coincidan con lo pactado.
"""

import os
import subprocess
import time
import requests
import pytest
from pact import Verifier

# Ruta al contrato generado por el consumer
PACT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "pacts", "reservation-inventory.json"
)

# Puerto donde se levantará el Inventory real para la verificación
PROVIDER_PORT = 9002
PROVIDER_URL = f"http://localhost:{PROVIDER_PORT}"

# Ruta al directorio del servicio Inventory
INVENTORY_DIR = os.path.join(os.path.dirname(__file__), "..", "inventory")


@pytest.fixture(scope="module")
def inventory_server():
    """
    Levanta el servicio real de Inventory en el puerto 9002
    antes de correr las verificaciones del provider.
    Lo detiene al finalizar.
    """
    process = subprocess.Popen(
        [
            "uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", str(PROVIDER_PORT),
        ],
        cwd=INVENTORY_DIR,
    )

    # Esperar hasta que el servidor esté listo (máx 10 segundos)
    for _ in range(20):
        try:
            response = requests.get(f"{PROVIDER_URL}/health", timeout=1)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)

    yield process

    process.terminate()
    process.wait()


def test_provider_cumple_contrato(inventory_server):
    """
    Verifica que Inventory cumple todas las interacciones definidas
    en el contrato generado por Reservation.

    Reproduce cada interacción del archivo pacts/reservation-inventory.json
    contra el servicio real y valida las respuestas.
    """
    assert os.path.exists(PACT_FILE), (
        f"Contrato no encontrado en {PACT_FILE}. "
        "Ejecuta primero: pytest consumer/test_consumer.py"
    )

    verifier = Verifier(
        provider="Inventory",
        provider_base_url=PROVIDER_URL,
    )

    output, _ = verifier.verify_pacts(
        PACT_FILE,
        verbose=True,
    )

    assert output == 0, (
        "El provider Inventory NO cumple el contrato definido por Reservation. "
        "Revisa los logs para ver qué interacción falló."
    )
