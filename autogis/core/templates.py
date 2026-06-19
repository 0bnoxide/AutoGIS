import re

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_WS = re.compile(r"\s+")
_FIELD = re.compile(r"\{([^}]+)\}")
UNKNOWN = "_unknown"


def sanitize(part: str) -> str:
    cleaned = _ILLEGAL.sub("", part)
    cleaned = _WS.sub("_", cleaned)
    cleaned = cleaned.strip("._ ")
    return cleaned or UNKNOWN


def render(template: str, attributes: dict) -> str:
    def repl(match):
        field = match.group(1)
        value = attributes.get(field)
        if value is None:
            return UNKNOWN
        return str(value)
    return _FIELD.sub(repl, template)


def render_path_component(template: str, attributes: dict) -> str:
    return sanitize(render(template, attributes))
