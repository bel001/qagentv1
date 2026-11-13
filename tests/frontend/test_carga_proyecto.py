"""Aviso mientras se analiza un proyecto al abrirlo y protección contra doble clic.

En proyectos reales el análisis de la Vista previa tarda varios segundos: la pantalla no
cambiaba, el aviso «Proyecto abierto» salía antes de tiempo y un segundo clic lanzaba otro
análisis en paralelo.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "src" / "qagent" / "frontend"
VISTA = (FRONTEND / "componentes" / "vista-previa" / "vista-previa.js").read_text(
    encoding="utf-8"
)
CSS = (FRONTEND / "componentes" / "vista-previa" / "vista-previa.css").read_text(
    encoding="utf-8"
)
ABRIR = (FRONTEND / "componentes" / "inicio" / "modal-abrir.js").read_text(
    encoding="utf-8"
)
INICIO = (FRONTEND / "componentes" / "inicio" / "inicio.js").read_text(encoding="utf-8")


def _envoltorio() -> str:
    return VISTA[
        VISTA.index("async function loadProject") : VISTA.index(
            "async function cargarProyecto"
        )
    ]


def test_load_project_ignora_un_segundo_intento_mientras_analiza() -> None:
    cuerpo = _envoltorio()
    assert "if(analizandoProyecto)" in cuerpo
    assert "return false" in cuerpo
    assert cuerpo.index("analizandoProyecto = true") < cuerpo.index("cargarProyecto(")


def test_el_aviso_se_muestra_y_siempre_se_oculta() -> None:
    cuerpo = _envoltorio()
    assert "mostrarAnalizando(name)" in cuerpo
    fin = cuerpo[cuerpo.index("finally") :]
    assert "analizandoProyecto = false" in fin
    assert "ocultarAnalizando()" in fin
    assert "role', 'status'" in VISTA
    assert ".carga-proyecto.show{display:flex}" in CSS


def test_proyecto_abierto_solo_se_anuncia_si_la_carga_termino_bien() -> None:
    for js in (ABRIR, INICIO):
        assert "if (await loadProject(" in js or "if(await loadProject(" in js


PUENTE = (FRONTEND / "js" / "puente-python.js").read_text(encoding="utf-8")


def test_la_recomendacion_de_la_ia_llega_despues_por_evento() -> None:
    assert "event.type === 'recomendacion_ia'" in PUENTE
    assert "recibirRecomendacionIA(event.data)" in PUENTE
    assert "RECO_IA_PENDIENTE = !!res.recomendacion_ia_pendiente" in VISTA
    cuerpo = VISTA[VISTA.index("function recibirRecomendacionIA") :]
    cuerpo = cuerpo[: cuerpo.index("\n}\n")]
    # Si la persona ya abrió otro proyecto, la respuesta tardía no lo pisa.
    assert "rutaComparable(projectPath)" in cuerpo
    assert "RECO_IA_PENDIENTE = false" in cuerpo
