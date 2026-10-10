"""Small helpers for validating tool arguments before execution."""


class ValidationError(Exception):
    pass


def require(args: dict, *keys: str):
    missing = [k for k in keys if k not in args or args[k] in (None, "")]
    if missing:
        raise ValidationError(f"Missing required argument(s): {', '.join(missing)}")


def as_str(args: dict, key: str, default: str = "") -> str:
    return str(args.get(key, default))


def as_int(args: dict, key: str, default: int = 0) -> int:
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


def as_list(args: dict, key: str, default=None):
    val = args.get(key, default if default is not None else [])
    if isinstance(val, list):
        return val
    return [val]
