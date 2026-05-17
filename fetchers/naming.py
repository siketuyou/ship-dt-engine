import re


def normalize_fetcher_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\.py$", "", name, flags=re.IGNORECASE)
    # Accept the common misspelling "_fecther" so uploaded filenames
    # still map to the intended fetcher/class name.
    name = re.sub(r"_(fetcher|fecther)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
    return name.strip("_").lower()


def fetcher_class_name(fetcher_name: str) -> str:
    parts = [part for part in fetcher_name.split("_") if part]
    return "".join(part.capitalize() for part in parts) + "Fetcher"
