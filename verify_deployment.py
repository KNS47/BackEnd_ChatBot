"""Run a smoke test against a real deployment, with an optional corpus check."""

import argparse
import os
from urllib.parse import urlsplit

import httpx


def verify(client: httpx.Client, question: str | None, expected: str | None) -> None:
    health = client.get("/health")
    health.raise_for_status()
    if health.json() != {"status": "ok"}:
        raise RuntimeError("Unexpected health payload")

    for page in ("/", "/login.html", "/admin.html", "/stats.html", "/icons.svg"):
        client.get(page).raise_for_status()
    if client.get("/pdfs").status_code != 401:
        raise RuntimeError("Expected PDF list to reject an unauthenticated client")

    for prompt, phrase in (
        ("เบอร์โทรของเทศบาล", "043-246505"),
        (question, expected),
    ):
        if prompt is None:
            continue
        response = client.post("/chat", json={"message": prompt, "no_save": True})
        response.raise_for_status()
        if phrase not in response.json().get("answer", ""):
            raise RuntimeError("A chat response did not contain the expected answer")
        if client.cookies.get("session_id"):
            raise RuntimeError("Anonymous chat unexpectedly created a session")

    username = os.getenv("SMOKE_ADMIN_USERNAME")
    password = os.getenv("SMOKE_ADMIN_PASSWORD")
    if username and password:
        client.post("/api/login", data={"username": username, "password": password}).raise_for_status()
        try:
            if not client.get("/api/check-admin").json().get("authenticated"):
                raise RuntimeError("Admin session was not retained")
            client.get("/pdfs").raise_for_status()
        finally:
            client.post("/api/logout").raise_for_status()
        if client.get("/pdfs").status_code != 401:
            raise RuntimeError("Logout did not close the admin session")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="HTTPS origin of the deployed app")
    parser.add_argument("--question", help="Optional public municipal question that requires retrieval")
    parser.add_argument("--expected", help="Verified phrase expected in the answer")
    args = parser.parse_args()
    if bool(args.question) != bool(args.expected):
        parser.error("--question and --expected must be supplied together")
    origin = urlsplit(args.origin)
    if origin.username or origin.password or origin.path not in {"", "/"} or origin.query or origin.fragment:
        parser.error("Supply an origin only, without a path or credentials")
    local = origin.hostname in {"127.0.0.1", "localhost", "::1"}
    if not origin.hostname or not (origin.scheme == "https" or local and origin.scheme == "http"):
        parser.error("HTTPS is required except for local tests")
    with httpx.Client(base_url=args.origin, timeout=95) as client:
        verify(client, args.question, args.expected)
    print("Deployment smoke checks passed.")


if __name__ == "__main__":
    main()
