from app.components.navbar_component import admin_sidebar_item


def navbar():
    return [
        admin_sidebar_item("Inicio", "/"),
        admin_sidebar_item("Pedidos", "/pedidos"),
        admin_sidebar_item("Ajustes", "/ajustes"),
    ]
