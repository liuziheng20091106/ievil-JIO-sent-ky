"""Room removal must revoke access without changing the role cards."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import auth, storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


class RoomAccess(unittest.TestCase):
    def test_host_can_remove_spectators_and_players_without_resetting_cards(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
            TestClient(app) as client,
        ):
            client.post("/api/host/login", json={"password": "114514"}).raise_for_status()
            host = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}
            game = client.post("/api/games", json={"codex": DEFAULT_CODEX}).json()
            root = f"/api/games/{game['id']}"
            for kind, seat_id, block in (("spectator", None, True), ("player", "1", False)):
                with self.subTest(kind=kind):
                    invitation = client.post(
                        root + "/invites",
                        headers=host,
                        json={"kind": kind, "seat_id": seat_id},
                    )
                    invitation.raise_for_status()
                    client.cookies.clear()
                    joined = client.post(
                        "/api/join", json={"code": invitation.json()["code"], "name": kind}
                    )
                    joined.raise_for_status()
                    participant_id = joined.json()["actor"]["id"]
                    before = client.get(root + "/state", headers=host).json()
                    command = {
                        "expected_version": before["version"],
                        "action": "room.kick",
                        "payload": {"participant_id": participant_id, "block": block},
                    }
                    self.assertEqual(client.post(root + "/commands", json=command).status_code, 403)
                    removed = client.post(root + "/commands", headers=host, json=command)
                    self.assertEqual(removed.status_code, 200, removed.text)
                    self.assertEqual(client.get(root + "/state").status_code, 401)
                    after = removed.json()
                    self.assertEqual(
                        [seat["cards"] for seat in before["seats"]],
                        [seat["cards"] for seat in after["seats"]],
                    )
                    if seat_id:
                        self.assertFalse(
                            next(s for s in after["seats"] if s["id"] == seat_id)["occupied"]
                        )
                    target = next(
                        p for p in after["host"]["participants"] if p["id"] == participant_id
                    )
                    self.assertFalse(target["active"])
                    self.assertEqual(target["blocked"], block)


if __name__ == "__main__":
    unittest.main()
