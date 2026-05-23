from __future__ import annotations

from pathlib import Path

import jinja2

from sitop_loxone_bridge.selection import Selection

_TEMPLATE_DIR = Path(__file__).parent / "web" / "templates"
_TEMPLATE_NAME = "loxone_template.xml.j2"


def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=jinja2.select_autoescape(default_for_string=False, default=False),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_loxone_template(selection: Selection) -> str:
    template = _env().get_template(_TEMPLATE_NAME)
    return template.render(
        parameters=selection.parameters,
        generated_at=selection.generated_at.isoformat(),
    )
