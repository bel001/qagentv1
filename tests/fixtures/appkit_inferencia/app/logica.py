def producto(a: int, b: int) -> int:
    return a * b


def total_con_impuesto(subtotal: int, porcentaje: int) -> int:
    return subtotal + subtotal * porcentaje // 100


def hay_stock(disponible: int, solicitado: int) -> bool:
    return 0 < solicitado <= disponible
