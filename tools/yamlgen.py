"""Kleiner YAML-Emitter (Standardbibliothek) mit Unterstützung für den HA-Tag !input."""
import json


class Inp:
    """Repräsentiert `!input name`."""

    def __init__(self, name):
        self.name = name


def _key(k):
    s = str(k)
    if s.replace("_", "").isalnum() and not s[0].isdigit() and s.isascii():
        return s
    return json.dumps(s, ensure_ascii=False)


def _scalar(v):
    if isinstance(v, Inp):
        return f"!input {v.name}"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if "\n" in s:
        return None
    return json.dumps(s, ensure_ascii=False)


def dump(obj, indent=0):
    pad = "  " * indent
    out = []
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}\n"
        for k, v in obj.items():
            key = _key(k)
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:\n{dump(v, indent + 1)}")
            elif isinstance(v, dict):
                out.append(f"{pad}{key}: {{}}\n")
            elif isinstance(v, list):
                out.append(f"{pad}{key}: []\n")
            else:
                s = _scalar(v)
                if s is None:
                    body = "\n".join(("  " * (indent + 1) + z) if z.strip() else "" for z in str(v).rstrip("\n").split("\n"))
                    out.append(f"{pad}{key}: >-\n{body}\n" if _is_template(v) else f"{pad}{key}: |-\n{body}\n")
                else:
                    out.append(f"{pad}{key}: {s}\n")
        return "".join(out)
    if isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)) and v:
                inner = dump(v, indent + 1)[len("  " * (indent + 1)):]
                out.append(f"{pad}- {inner}")
            elif isinstance(v, dict):
                out.append(f"{pad}- {{}}\n")
            elif isinstance(v, list):
                out.append(f"{pad}- []\n")
            else:
                s = _scalar(v)
                if s is None:
                    body = "\n".join(("  " * (indent + 1) + z) if z.strip() else "" for z in str(v).rstrip("\n").split("\n"))
                    out.append(f"{pad}- |-\n{body}\n")
                else:
                    out.append(f"{pad}- {s}\n")
        return "".join(out)
    return pad + str(_scalar(obj)) + "\n"


def _is_template(v):
    # Jinja-Templates als gefalteter Block (>-) ausgeben, damit Zeilenumbrüche zu Leerzeichen werden.
    s = str(v)
    return "{{" in s or "{%" in s
