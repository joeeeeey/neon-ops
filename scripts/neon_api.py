#!/usr/bin/env python3
from safety import SafeError, secret, scrub, api_url, request
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE = "https://console.neon.tech/api/v2"

SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "apikey",
    "api_key",
    "connection_uri",
    "connection_string",
    "dsn",
)


class NeonError(SafeError):
    pass


def default_team():
    return "explicit-credential"


def neon_base():
    return DEFAULT_BASE


def token_file_for_team(team, area="uptime"):
    return os.environ.get("NEON_TOKEN_FILE", "explicit environment/file only")


def read_token(team=None):
    return secret("NEON_API_KEY", "NEON_API_KEY_FILE"), "explicit environment/file"


def parse_params(params: list[str]) -> dict:
    parsed = {}
    for item in params:
        if "=" not in item:
            raise NeonError(f"--param must be key=value, got: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed


def make_url(path, params=None):
    return api_url(neon_base(), path, params)


def request_json(path, *, method="GET", params=None, body=None, timeout=30):
    token, _ = read_token()
    return request(make_url(path, params), method=method, body=body, timeout=timeout, headers={"Authorization": "Bearer " + token})


def contains_secret_like_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            low = str(key).lower()
            if any(marker in low for marker in SECRET_MARKERS):
                return True
            if contains_secret_like_key(nested):
                return True
    elif isinstance(value, list):
        return any(contains_secret_like_key(item) for item in value)
    return False


def summarize_item(item: object) -> object:
    if not isinstance(item, dict):
        return item
    keys = (
        "id",
        "name",
        "project_id",
        "branch_id",
        "parent_id",
        "endpoint_id",
        "region_id",
        "platform_id",
        "type",
        "status",
        "state",
        "created_at",
        "updated_at",
        "default",
        "primary",
        "role_name",
        "database_name",
    )
    return {key: item[key] for key in keys if key in item}


def summarize_payload(payload: object) -> object:
    if isinstance(payload, dict):
        for collection_key in (
            "projects",
            "branches",
            "endpoints",
            "operations",
            "databases",
            "roles",
            "organizations",
        ):
            if isinstance(payload.get(collection_key), list):
                return {
                    "count": len(payload[collection_key]),
                    "sample": [summarize_item(item) for item in payload[collection_key][:10]],
                }
        for single_key in ("project", "branch", "endpoint", "operation", "database", "role"):
            if isinstance(payload.get(single_key), dict):
                return summarize_item(payload[single_key])
        if contains_secret_like_key(payload):
            return {"keys": sorted(payload.keys()), "warning": "payload contains secret-like keys; raw output suppressed in summary"}
        return {key: payload[key] for key in sorted(payload.keys())[:30]}
    if isinstance(payload, list):
        return {"count": len(payload), "sample": [summarize_item(item) for item in payload[:10]]}
    return {"data_type": type(payload).__name__}


def print_json(payload: object) -> None:
    print(json.dumps(scrub(payload), indent=2, ensure_ascii=False))


def cmd_doctor(_args: argparse.Namespace) -> int:
    team = default_team()
    print(f"neon_team={team}")
    print(f"neon_api_base={neon_base()}")
    print(f"token_file={token_file_for_team(team)}")
    try:
        _token, source = read_token(team)
        print(f"api_key=present({source})")
    except (SafeError, OSError, ValueError) as exc:
        print(f"api_key=missing_or_invalid({exc})")
        return 1
    return 0


def cmd_validate(_args: argparse.Namespace) -> int:
    results = []
    for label, path in (("projects", "/projects?limit=1"),):
        status, payload = request_json(path)
        ok = 200 <= status < 300
        entry = {"label": label, "path": path, "http_status": status, "ok": ok}
        if ok:
            entry["summary"] = summarize_payload(payload)
        else:
            entry["error"] = payload.get("message") or payload.get("error") or payload.get("detail") or payload
        results.append(entry)

    project_ok = any(item["label"] == "projects" and item["ok"] for item in results)
    print_json({"team": default_team(), "base": neon_base(), "results": results})
    return 0 if project_ok else 1


def cmd_projects(args: argparse.Namespace) -> int:
    params = parse_params(args.param)
    params.setdefault("limit", str(args.limit))
    status, payload = request_json("/projects", params=params)
    output = summarize_payload(payload) if args.summary else payload
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": output})
    return 0 if 200 <= status < 300 else 1


def cmd_project_collection(args: argparse.Namespace) -> int:
    if args.command in ("databases", "roles"):
        path = f"/projects/{args.project_id}/branches/{args.branch_id}/{args.command}"
    else:
        path = f"/projects/{args.project_id}/{args.command}"
    status, payload = request_json(path, params=parse_params(args.param))
    output = summarize_payload(payload) if args.summary else payload
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": output})
    return 0 if 200 <= status < 300 else 1


def cmd_get(args: argparse.Namespace) -> int:
    status, payload = request_json(args.path, params=parse_params(args.param))
    output = summarize_payload(payload) if args.summary else payload
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": output})
    return 0 if 200 <= status < 300 else 1


def load_json_file(path: str | None) -> object:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NeonError(f"JSON body file is invalid: {path}") from exc


def cmd_mutate(args: argparse.Namespace) -> int:
    body = load_json_file(args.json_file)
    preview = {
        "dry_run": not args.execute,
        "method": args.method.upper(),
        "path": args.path,
        "body_keys": sorted(body.keys()) if isinstance(body, dict) else "non-object",
    }
    if not args.execute:
        print_json(preview)
        return 0

    status, payload = request_json(args.path, method=args.method.upper(), body=body)
    output = summarize_payload(payload)
    print_json({"http_status": status, "ok": 200 <= status < 300, "data": output})
    return 0 if 200 <= status < 300 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Neon API helper for explicit account operations.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show local config without printing token")
    doctor.set_defaults(func=cmd_doctor)

    validate = sub.add_parser("validate", help="Validate API key against Neon projects API")
    validate.set_defaults(func=cmd_validate)

    projects = sub.add_parser("projects", help="List Neon projects")
    projects.add_argument("--limit", type=int, default=20)
    projects.add_argument("--param", action="append", default=[], help="Query parameter key=value")
    projects.add_argument("--summary", action="store_true")
    projects.set_defaults(func=cmd_projects)

    for name in ("branches", "endpoints", "operations"):
        p = sub.add_parser(name, help=f"List project {name}")
        p.add_argument("--project-id", required=True)
        p.add_argument("--param", action="append", default=[], help="Query parameter key=value")
        p.add_argument("--summary", action="store_true")
        p.set_defaults(func=cmd_project_collection)

    for name in ("databases", "roles"):
        p = sub.add_parser(name, help=f"List branch {name}")
        p.add_argument("--project-id", required=True)
        p.add_argument("--branch-id", required=True)
        p.add_argument("--param", action="append", default=[], help="Query parameter key=value")
        p.add_argument("--summary", action="store_true")
        p.set_defaults(func=cmd_project_collection)

    get = sub.add_parser("get", help="GET an arbitrary Neon API path")
    get.add_argument("path")
    get.add_argument("--param", action="append", default=[], help="Query parameter key=value")
    get.add_argument("--summary", action="store_true")
    get.set_defaults(func=cmd_get)

    for method in ("post", "patch", "put", "delete"):
        p = sub.add_parser(method, help=f"{method.upper()} an arbitrary API path; dry-run by default")
        p.add_argument("path")
        p.add_argument("--json-file", help="JSON request body file")
        p.add_argument("--execute", action="store_true", help="Actually send the write request")
        p.set_defaults(func=cmd_mutate, method=method)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (SafeError, OSError, ValueError) as exc:
        print("ERROR: " + (str(exc) if isinstance(exc, SafeError) else "Invalid input or file; sensitive details suppressed"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
