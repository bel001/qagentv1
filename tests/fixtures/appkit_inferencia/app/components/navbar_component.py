import reflex as rx


def admin_sidebar_item(text: str, href: str) -> rx.Component:
    return rx.link(text, href=href)
