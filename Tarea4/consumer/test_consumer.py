"""
Consumer Contract Tests — Reservation como consumer de Inventory

Estas pruebas definen el contrato desde el punto de vista de Reservation:
"Esto es lo que yo (Reservation) espero que Inventory me devuelva."

Al ejecutarse, generan el archivo: pacts/reservation-inventory.json
"""

import os
import requests
import pytest
from pact import Consumer, Provider, EachLike

# Directorio donde se guardará el contrato generado
PACT_DIR = os.path.join(os.path.dirname(__file__), "..", "pacts")

# Puerto del mock server que Pact levanta para simular Inventory
MOCK_PORT = 9001
MOCK_URL = f"http://localhost:{MOCK_PORT}"


@pytest.fixture(scope="module")
def pact():
    """
    Configura el objeto Pact:
    - Consumer: Reservation (el que llama)
    - Provider: Inventory (el que responde)
    """
    pact = Consumer("Reservation").has_pact_with(
        Provider("Inventory"),
        host_name="localhost",
        port=MOCK_PORT,
        pact_dir=PACT_DIR,
    )
    pact.start_service()
    yield pact
    pact.stop_service()


# ── Interacción 1 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_disponibles(pact):
    """
    Cuando Reservation busca switches Aruba 800 con PoE en topología Standalone,
    Inventory debe retornar una lista con al menos un switch disponible.
    """
    expected_switch = {
        "id": "MAC-A001",
        "plataforma": "Aruba 800",
        "sku": "800.1",
        "firmware_version": "8.11",
        "soporte_poe": True,
        "numero_puertos": 24,
        "estado_fisico": "AVAILABLE",
        "topologia": "Standalone",
        "switch_ip": "192.168.1.101",
        "hub_port": 1,
    }

    (
        pact.given("existen switches Aruba 800 con PoE en topología Standalone disponibles")
        .upon_receiving("una solicitud de switches compatibles con Aruba 800, PoE y Standalone")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 800",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 800",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == "MAC-A001"
    assert data[0]["soporte_poe"] is True
    assert data[0]["estado_fisico"] == "AVAILABLE"
    assert data[0]["topologia"] == "Standalone"


# ── Interacción 2 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_sin_resultados(pact):
    """
    Cuando Reservation busca una plataforma inexistente,
    Inventory debe retornar una lista vacía (no un error).
    """
    (
        pact.given("no existen switches para la plataforma Aruba 999")
        .upon_receiving("una solicitud de switches compatibles para plataforma inexistente")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 999",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=[],
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 999",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )

    assert response.status_code == 200
    assert response.json() == []


# ── Interacción 3 ──────────────────────────────────────────────────────────────
def test_listar_todos_los_switches(pact):
    """
    Cuando Reservation llama a GET /switches,
    Inventory debe retornar una lista con la estructura correcta de Switch.
    """
    expected_switch = {
        "id": "MAC-A001",
        "plataforma": "Aruba 800",
        "sku": "800.1",
        "firmware_version": "8.11",
        "soporte_poe": True,
        "numero_puertos": 24,
        "estado_fisico": "AVAILABLE",
        "topologia": "Standalone",
        "switch_ip": "192.168.1.101",
        "hub_port": 1,
    }

    (
        pact.given("existen switches en el inventario")
        .upon_receiving("una solicitud para listar todos los switches")
        .with_request(
            method="GET",
            path="/switches",
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(f"{MOCK_URL}/switches")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Verificar que la estructura del switch tiene todos los campos esperados
    switch = data[0]
    assert "id" in switch
    assert "plataforma" in switch
    assert "sku" in switch
    assert "firmware_version" in switch
    assert "soporte_poe" in switch
    assert "numero_puertos" in switch
    assert "estado_fisico" in switch
    assert "topologia" in switch
    assert "switch_ip" in switch
    assert "hub_port" in switch


# ── Interacción 4 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_con_sku_especifico(pact):
    """
    Cuando Reservation busca con un SKU específico (800.1),
    Inventory debe retornar únicamente switches con ese SKU.
    Cubre el parámetro opcional 'sku' que Reservation puede enviar.
    """
    expected_switch = {
        "id": "MAC-A001",
        "plataforma": "Aruba 800",
        "sku": "800.1",
        "firmware_version": "8.11",
        "soporte_poe": True,
        "numero_puertos": 24,
        "estado_fisico": "AVAILABLE",
        "topologia": "Standalone",
        "switch_ip": "192.168.1.101",
        "hub_port": 1,
    }

    (
        pact.given("existen switches Aruba 800 con SKU 800.1 disponibles")
        .upon_receiving("una solicitud de switches compatibles filtrando por SKU 800.1")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 800",
                "sku": "800.1",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 800",
                "sku": "800.1",
                "requiere_poe": "true",
                "topologia": "Standalone",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Todos los switches retornados deben tener exactamente el SKU solicitado
    for switch in data:
        assert switch["sku"] == "800.1"


# ── Interacción 5 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_sin_poe(pact):
    """
    Cuando Reservation busca switches SIN requisito de PoE (requiere_poe=false),
    Inventory debe retornar switches con soporte_poe=false.
    Cubre el caso donde el parámetro bool es false, no solo true.
    """
    expected_switch = {
        "id": "MAC-A004",
        "plataforma": "Aruba 800",
        "sku": "800.3",
        "firmware_version": "8.11",
        "soporte_poe": False,
        "numero_puertos": 24,
        "estado_fisico": "AVAILABLE",
        "topologia": "Stack",
        "switch_ip": "192.168.1.104",
        "hub_port": 4,
    }

    (
        pact.given("existen switches Aruba 800 sin PoE en topología Stack disponibles")
        .upon_receiving("una solicitud de switches compatibles sin requisito de PoE")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 800",
                "requiere_poe": "false",
                "topologia": "Stack",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 800",
                "requiere_poe": "false",
                "topologia": "Stack",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Todos los switches retornados deben tener soporte_poe=false
    for switch in data:
        assert switch["soporte_poe"] is False


# ── Interacción 6 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_con_minimo_puertos(pact):
    """
    Cuando Reservation busca switches con un mínimo de 48 puertos,
    Inventory debe retornar solo switches que cumplan ese mínimo.
    Cubre el parámetro opcional 'numero_puertos_min' de Reservation.
    """
    expected_switch = {
        "id": "MAC-A006",
        "plataforma": "Aruba 850",
        "sku": "850.1",
        "firmware_version": "8.11",
        "soporte_poe": True,
        "numero_puertos": 48,
        "estado_fisico": "AVAILABLE",
        "topologia": "Standalone",
        "switch_ip": "192.168.1.106",
        "hub_port": 6,
    }

    (
        pact.given("existen switches Aruba 850 con al menos 48 puertos disponibles")
        .upon_receiving("una solicitud de switches compatibles con mínimo 48 puertos")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 850",
                "requiere_poe": "true",
                "topologia": "Standalone",
                "numero_puertos_min": "48",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 850",
                "requiere_poe": "true",
                "topologia": "Standalone",
                "numero_puertos_min": "48",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Todos los switches deben tener al menos 48 puertos
    for switch in data:
        assert switch["numero_puertos"] >= 48


# ── Interacción 7 ──────────────────────────────────────────────────────────────
def test_switches_compatibles_topologia_con_espacio(pact):
    """
    Cuando Reservation busca switches con topología 'Dual Link' (tiene espacio),
    Inventory debe retornar switches con esa topología sin errores de parsing.
    Verifica que topologías con espacios en el nombre se manejan correctamente.
    """
    expected_switch = {
        "id": "MAC-A003",
        "plataforma": "Aruba 800",
        "sku": "800.2",
        "firmware_version": "8.11",
        "soporte_poe": True,
        "numero_puertos": 24,
        "estado_fisico": "AVAILABLE",
        "topologia": "Dual Link",
        "switch_ip": "192.168.1.103",
        "hub_port": 3,
    }

    (
        pact.given("existen switches Aruba 800 con topología Dual Link disponibles")
        .upon_receiving("una solicitud de switches compatibles con topología Dual Link")
        .with_request(
            method="GET",
            path="/switches/compatible",
            query={
                "plataforma": "Aruba 800",
                "requiere_poe": "true",
                "topologia": "Dual Link",
            },
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=EachLike(expected_switch),
        )
    )

    with pact:
        response = requests.get(
            f"{MOCK_URL}/switches/compatible",
            params={
                "plataforma": "Aruba 800",
                "requiere_poe": "true",
                "topologia": "Dual Link",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Todos los switches deben tener exactamente la topología solicitada
    for switch in data:
        assert switch["topologia"] == "Dual Link"
