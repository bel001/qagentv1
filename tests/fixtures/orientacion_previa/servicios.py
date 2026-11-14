"""Banco controlado de orientación; no se ejecuta en el host."""


class FileValidationService:
    def validar(self, tamano: int) -> bool:
        return tamano <= 1024


def get_file_validation_service() -> FileValidationService:
    return FileValidationService()


def validar_tamano(tamano: int, limite: int) -> bool:
    return 0 <= tamano <= limite


def calcular_total(precio: int, cantidad: int) -> int:
    return precio * cantidad


def leer_archivo(ruta: str) -> str:
    with open(ruta, encoding="utf-8") as archivo:
        return archivo.read()
