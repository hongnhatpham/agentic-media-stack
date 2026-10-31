import http.client
import json
import threading
from http.server import ThreadingHTTPServer

from agentic_media_stack.api import make_handler
from agentic_media_stack.config import Config
from agentic_media_stack.service import build_service


def test_authenticated_mock_api_and_static_console(tmp_path):
    service = build_service(
        Config(
            state_path=str(tmp_path / "state.db"),
            audit_path=str(tmp_path / "audit.jsonl"),
            auth_token="operator-token",
            mock_mode=True,
        )
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request("GET", "/api/status")
        assert connection.getresponse().status == 401

        connection.request(
            "POST",
            "/api/auth/login",
            body=json.dumps({"token": "operator-token"}),
            headers={"Content-Type": "application/json"},
        )
        login = connection.getresponse()
        assert login.status == 200
        cookie = login.getheader("Set-Cookie").split(";", 1)[0]

        connection.request("GET", "/", headers={"Cookie": cookie})
        page = connection.getresponse()
        assert page.status == 200 and b"Shared media graph" in page.read()

        connection.request(
            "POST",
            "/api/requests",
            body=json.dumps({"title": "Cosmic Princess Kaguya", "kind": "movie"}),
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        request = json.loads(connection.getresponse().read())
        service.jobs.futures[request["job_id"]].result(timeout=2)
        connection.request(
            "GET", f"/api/requests/{request['id']}/candidates", headers={"Cookie": cookie}
        )
        candidates = json.loads(connection.getresponse().read())["items"]
        assert candidates and candidates[0]["title"] == "Cosmic Princess Kaguya"
    finally:
        connection.close()
        server.shutdown()
        service.jobs.shutdown()
