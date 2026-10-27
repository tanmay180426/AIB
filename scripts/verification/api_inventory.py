"""Generate a source/OpenAPI route inventory without initializing application data."""
import ast
from collections import Counter
import inspect
import json
import os
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENABLE_LLM_ASSISTANT"] = "false"
from app.main import app
from fastapi.routing import APIRoute


def dependencies(dependant):
    result = []
    for dep in dependant.dependencies:
        call = dep.call
        name = getattr(call, "__name__", type(call).__name__)
        roles = inspect.getclosurevars(call).nonlocals.get("roles") if inspect.isfunction(call) else None
        result.append(name + (f"{roles}" if roles else ""))
        result.extend(dependencies(dep))
    return sorted(set(result))


schema = app.openapi()
def status_code(node):
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        match = re.search(r'HTTP_(\d+)', node.attr)
        if match:
            return match.group(1)
    return None

routes = []
for route in app.routes:
    for method in sorted(route.methods or []):
        if isinstance(route, APIRoute):
            op = schema["paths"][route.path][method.lower()]
            deps = dependencies(route.dependant)
            admin = "require_admin" in deps or "checker('admin',)" in deps
            protected = any(d in deps for d in ("get_current_user", "require_admin", "require_bi_user", "auth_gate"))
            source = inspect.getsource(route.endpoint)
            tree = ast.parse(source)
            keys = sorted({key.value for node in ast.walk(tree) if isinstance(node, ast.Return)
                           and isinstance(node.value, ast.Dict) for key in node.value.keys
                           if isinstance(key, ast.Constant) and isinstance(key.value, str)})
            codes = set(op.get("responses", {}))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HTTPException":
                    if node.args and status_code(node.args[0]):
                        codes.add(status_code(node.args[0]))
                    for kw in node.keywords:
                        if kw.arg == "status_code" and status_code(kw.value):
                            codes.add(status_code(kw.value))
            if protected:
                codes.add("401")
            if admin or "require_bi_user" in deps:
                codes.add("403")
            routes.append({"method": method, "path": route.path, "module": route.endpoint.__module__,
                "handler": route.endpoint.__name__, "classification": "admin" if admin else "authenticated" if protected else "public",
                "dependencies": deps, "parameters": op.get("parameters", []),
                "requestBody": op.get("requestBody"), "responses": op.get("responses", {}),
                "source_return_keys": keys, "source_status_codes": sorted(codes),
                "description": op.get("description") or op.get("summary"),
                "response_model": str(route.response_model) if route.response_model else None})
        else:
            routes.append({"method": method, "path": route.path, "module": "FastAPI documentation",
                "handler": route.name, "classification": "public", "dependencies": [],
                "parameters": [], "requestBody": None, "responses": {},
                "description": "Framework documentation/schema route (not a business API)."})
output = {"counting": "One entry per explicit registered method/path; docs HEAD counted separately; CORS OPTIONS is middleware, not an endpoint.",
          "counts": {"total": len(routes), "methods": dict(Counter(r["method"] for r in routes)),
                     "modules": dict(Counter(r["module"] for r in routes)),
                     "access": dict(Counter(r["classification"] for r in routes))},
          "routes": routes, "schemas": schema.get("components", {}).get("schemas", {})}
path = ROOT / "docs" / "API_ROUTE_INVENTORY.json"
path.write_text(json.dumps(output, indent=2), encoding="utf-8")
print(json.dumps(output["counts"]))
