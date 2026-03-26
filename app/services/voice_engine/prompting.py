from __future__ import annotations

from typing import Any, Dict, Optional

import jinja2


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    """Render a Jinja2 template (safe, no file access)."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    t = env.from_string(template)
    return t.render(**variables)


def build_instructions(
    system_prompt: Optional[str],
    prompt_template: Optional[str],
    variables: Dict[str, Any],
) -> str:
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt.strip())
    if prompt_template:
        try:
            parts.append(render_prompt(prompt_template, variables).strip())
        except Exception:
            # If template fails (missing vars), fall back to raw template.
            parts.append(prompt_template.strip())
    return "\n\n".join([p for p in parts if p])
