"""La vigilancia de disco no recorre el proyecto sin pausa en proyectos grandes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from qagent.sandbox import vigilancia
from qagent.sandbox.vigilancia import VigilanciaDisco


def _vigilar(monkeypatch, tmp_path: Path, duracion_medicion: float, vueltas: int):
    """Corre el bucle con un reloj falso; devuelve (mediciones, revisiones de reserva)."""
    reloj = {"t": 0.0}
    conteo = {"mediciones": 0, "reservas": 0, "vueltas": 0}
    vigilante = VigilanciaDisco(Mock(), [tmp_path])

    def esperar(segundos: float) -> bool:
        conteo["vueltas"] += 1
        reloj["t"] += segundos
        return conteo["vueltas"] > vueltas

    def medir(_carpeta, _limite) -> int:
        conteo["mediciones"] += 1
        reloj["t"] += duracion_medicion
        return 0

    def reserva() -> bool:
        conteo["reservas"] += 1
        return True

    monkeypatch.setattr(vigilancia.time, "monotonic", lambda: reloj["t"])
    monkeypatch.setattr(vigilancia, "tamano_carpeta", medir)
    monkeypatch.setattr(vigilante._fin, "wait", esperar)
    monkeypatch.setattr(vigilante, "_hay_reserva", reserva)
    vigilante._vigilar()
    return conteo["mediciones"], conteo["reservas"]


def test_con_una_medicion_rapida_se_mide_en_cada_vuelta(monkeypatch, tmp_path) -> None:
    mediciones, _ = _vigilar(monkeypatch, tmp_path, duracion_medicion=0.0, vueltas=20)
    assert mediciones == 20


def test_con_una_medicion_lenta_se_espacian_las_mediciones(
    monkeypatch, tmp_path
) -> None:
    mediciones, reservas = _vigilar(
        monkeypatch, tmp_path, duracion_medicion=0.3, vueltas=60
    )
    # Cada medición tarda 0,3 s: la siguiente espera 1,2 s (4 veces), no 0,1 s.
    assert 3 <= mediciones <= 6
    # Entre mediciones se sigue vigilando la reserva del disco, que no recorre nada.
    assert reservas >= 40


def test_la_espera_entre_mediciones_tiene_tope(monkeypatch, tmp_path) -> None:
    mediciones, _ = _vigilar(monkeypatch, tmp_path, duracion_medicion=5.0, vueltas=100)
    # 100 vueltas de 0,1 s son 10 s de espera: con el tope de 2 s caben unas 5.
    assert mediciones >= 4


def test_sin_reserva_entre_mediciones_se_corta(monkeypatch, tmp_path) -> None:
    reloj = {"t": 0.0}
    contenedor = Mock()
    vigilante = VigilanciaDisco(contenedor, [tmp_path])
    reservas = iter([True, False])

    def medir(_carpeta, _limite) -> int:
        reloj["t"] += 1.0
        return 0

    monkeypatch.setattr(vigilancia.time, "monotonic", lambda: reloj["t"])
    monkeypatch.setattr(vigilancia, "tamano_carpeta", medir)
    monkeypatch.setattr(vigilante._fin, "wait", lambda _s: False)
    monkeypatch.setattr(vigilante, "_hay_reserva", lambda: next(reservas))

    vigilante._vigilar()

    contenedor.kill.assert_called_once()
    assert "disco" in vigilante.motivo
