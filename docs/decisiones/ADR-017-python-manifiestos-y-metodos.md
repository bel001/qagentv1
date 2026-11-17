# ADR-017: Python desde sus manifiestos y métodos públicos de clases

- **Estado:** Propuesto (2026-11-17)
- **Fecha:** 2026-11-17
- **Ítem:** backlog 10 (HU · Preparar proyectos Python desde sus manifiestos) y backlog 11 (HU · Analizar y probar métodos públicos de clases Python)
- **Relacionado:** ADR-007 (adaptadores por lenguaje), ADR-009 (tree-sitter), ADR-013 (versión de Python del sandbox), ADR-016 (contrato inferido), AGENTS.md («Alcance» y «Reglas que no se rompen»)

---

## 1. Contexto

Dos limitaciones dejan fuera buena parte de los proyectos Python reales:

1. **Dependencias.** El sandbox instala solo lo que dice `requirements.txt`. Un proyecto que declara sus dependencias en `pyproject.toml` (PEP 621 o Poetry) o en `setup.cfg` llega al sandbox sin ellas: las pruebas fallan con `ModuleNotFoundError` y el informe lo atribuye al entorno. Con la estructura `src/` además falla el import del propio paquete.
2. **Métodos.** El analizador solo ofrece funciones de nivel superior. La lógica de un proyecto orientado a objetos vive en métodos, que hoy solo se listan como «todavía no seleccionables».

## 2. Decisión

### 2.1 Dependencias desde manifiestos (backlog 10)

Formatos admitidos, en este orden de preferencia (se usa el primero que exista):

| Formato | Qué se lee |
|---|---|
| `requirements.txt` | Igual que hoy. |
| `pyproject.toml` PEP 621 | `[project].dependencies`; si es `dynamic`, el archivo que indique `[tool.setuptools.dynamic].dependencies`. |
| `pyproject.toml` Poetry | `[tool.poetry.dependencies]`, traduciendo `^` y `~` a rangos PEP 440. Sin `python` ni las marcadas `optional`. |
| `setup.cfg` | `[options].install_requires`. |

De cualquiera de ellos se arma una lista PEP 508 que pasa por **la misma revisión** que `requirements.txt` (sin URLs, rutas locales, editables ni cambios de índice) y se instala igual: una orden de `pip` con `--only-binary=:all:`. La imagen se identifica por esa lista, así que dos manifiestos con las mismas dependencias comparten imagen.

**Nunca se instala el proyecto mismo** (`pip install .`): construirlo ejecutaría su backend de build con red. Por eso:

- **`src/`:** el sandbox agrega `/work/proyecto/src` al `PYTHONPATH`; los imports internos del paquete funcionan sin instalarlo.
- **Dependencias locales o de Git** (`path`, `file:`, `git+`): no se instalan. La Vista previa y la corrida lo dicen con el nombre de la dependencia («requiere configuración»).
- **`setup.py`:** no se lee. Leerlo de verdad es ejecutarlo; se pide declarar las dependencias en `pyproject.toml` o `requirements.txt`.
- **Grupos opcionales** (`[project.optional-dependencies]`, grupos de Poetry): no se instalan. Los extras de una dependencia (`requests[socks]`) sí.
- **Lockfiles** (`poetry.lock`, `uv.lock`, `Pipfile.lock`): no se usan. Se instalan los rangos declarados, igual que con `requirements.txt`; la reproducibilidad exacta queda para el backlog 16.

### 2.2 Métodos públicos de clases (backlog 11)

- **Qué se ofrece:** los métodos públicos (sin `_` inicial) de las clases de nivel superior: de instancia, `@staticmethod` y `@classmethod`. Su identidad es `Clase.metodo`. Las funciones anidadas siguen fuera.
- **Construcción controlada.** Un método de instancia necesita un objeto. El caso del contrato lleva `constructor`: los argumentos con que se construye la clase, que salen de la firma y la documentación del constructor, igual que el valor esperado sale del método. Solo se construyen clases cuyo constructor recibe **datos** (números, textos, booleanos, `None`, listas, diccionarios, tuplas, sus `Optional`) o tiene valores por defecto; un `@dataclass` usa sus campos.
- **Explicación cuando falta una dependencia.** Si el constructor recibe otra cosa (un repositorio, un cliente, una sesión), el método queda fuera con el nombre del parámetro y su tipo: QAgent no adivina cómo construir esa dependencia. Igual si la clase hereda el constructor de una clase que no se puede leer.
- **El oráculo no cambia:** el valor esperado sale de la firma, los tipos y el docstring del método (y del constructor para el estado inicial). El validador exige que la aserción compare el resultado de `Clase(...).metodo(...)`, `obj.metodo(...)` con `obj = Clase(...)`, o `Clase.metodo(...)` para estáticos y de clase.
- **Fuera por ahora:** contrato inferido para métodos sin docstring (ADR-016 queda para funciones), mutación de métodos (Profundizar no se ofrece) e integración interna desde métodos. Se muestran con su motivo.

## 3. Consecuencias

- Más proyectos reales llegan al sandbox con sus dependencias y su lógica orientada a objetos.
- La regla de no ejecutar código del usuario fuera del sandbox se mantiene: los manifiestos se leen como texto (TOML e INI) y las clases con tree-sitter.
- Las imágenes ya construidas siguen valiendo: un proyecto con `requirements.txt` produce la misma etiqueta que antes.
- El contrato `planner_contract.v3` gana el campo opcional `constructor` en los casos de funciones Python; los contratos guardados no lo tienen y siguen siendo válidos.
