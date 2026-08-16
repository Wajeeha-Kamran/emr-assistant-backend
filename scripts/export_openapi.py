"""
Exports the API contract to docs/openapi.json.

WHY A FILE, WHEN THE SERVER ALREADY SERVES IT
/openapi.json is available from a running server, but a frontend developer should
not need the backend running -- and a repository should not need a live process to
document itself. This writes the same document to disk so it can be committed,
diffed, and read by client-generation tooling.

The diff matters. A pull request that silently changes a response shape is hard to
spot in Python; the same change in openapi.json is one line, visible in review.

Usage:
    python -m scripts.export_openapi
"""

import json
import os

OUT = os.path.join("docs", "openapi.json")


def main() -> None:
    from app.main import app

    spec = app.openapi()

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")

    paths = spec.get("paths", {})
    operations = sum(
        1 for methods in paths.values()
        for verb in methods
        if verb in {"get", "post", "put", "patch", "delete"}
    )
    schemas = len(spec.get("components", {}).get("schemas", {}))

    print(f"Wrote {OUT}")
    print(f"  title       {spec.get('info', {}).get('title')}")
    print(f"  version     {spec.get('info', {}).get('version')}")
    print(f"  paths       {len(paths)}")
    print(f"  operations  {operations}")
    print(f"  schemas     {schemas}")
    print()
    print("Undocumented operations (no summary and no description):")
    missing = [
        f"  {verb.upper():<6} {path}"
        for path, methods in sorted(paths.items())
        for verb, op in methods.items()
        if verb in {"get", "post", "put", "patch", "delete"}
        and not op.get("summary") and not op.get("description")
    ]
    print("\n".join(missing) if missing else "  none")


if __name__ == "__main__":
    main()
