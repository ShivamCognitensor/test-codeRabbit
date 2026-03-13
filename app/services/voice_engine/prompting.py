from __future__ import annotations

from typing import Any, Dict, Optional

import jinja2


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    """
    Render a Jinja2 template string using StrictUndefined and autoescape disabled.
    
    Parameters:
        template (str): The Jinja2 template text to render.
        variables (Dict[str, Any]): Mapping of names to values provided to the template.
    
    Returns:
        str: The rendered template string.
    
    Raises:
        jinja2.UndefinedError: If the template references a variable not present in `variables`.
    """
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    t = env.from_string(template)
    return t.render(**variables)


def build_instructions(
    system_prompt: Optional[str],
    prompt_template: Optional[str],
    variables: Dict[str, Any],
) -> str:
    """
    Builds an instruction string by combining an optional system prompt and an optional prompt template rendered with provided variables.
    
    Parameters:
        system_prompt (Optional[str]): Optional system-level prompt to include first; will be stripped of leading/trailing whitespace.
        prompt_template (Optional[str]): Optional Jinja2 template string to render with `variables`; if rendering fails, the raw template (stripped) is used.
        variables (Dict[str, Any]): Mapping of values used to render `prompt_template`.
    
    Returns:
        str: The combined, non-empty parts joined by two newlines ("\n\n"), with each part stripped of surrounding whitespace.
    """
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
