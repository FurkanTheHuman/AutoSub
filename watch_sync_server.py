from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse


class RoomStore:
	def __init__(self):
		self.lock = Lock()
		self.rooms = {}

	def _room(self, code):
		return self.rooms.setdefault(
			code,
			{
				"next_id": 1,
				"events": [],
				"members": {},
				"state": None,
			},
		)

	def join(self, code, client_id, name):
		with self.lock:
			room = self._room(code)
			room["members"][client_id] = {"name": name, "last_seen": time.time()}
			self._prune(room)
			return self._snapshot(room)

	def add_event(self, code, client_id, event_type, payload):
		with self.lock:
			room = self._room(code)
			room["members"].setdefault(client_id, {"name": "Guest", "last_seen": time.time()})
			room["members"][client_id]["last_seen"] = time.time()
			event = {
				"id": room["next_id"],
				"type": event_type,
				"payload": payload,
				"client_id": client_id,
				"ts": time.time(),
			}
			room["next_id"] += 1
			room["events"].append(event)
			room["events"] = room["events"][-200:]
			room["state"] = event
			self._prune(room)
			return event["id"]

	def events_since(self, code, since, client_id):
		with self.lock:
			room = self._room(code)
			room["members"].setdefault(client_id, {"name": "Guest", "last_seen": time.time()})
			room["members"][client_id]["last_seen"] = time.time()
			self._prune(room)
			events = [e for e in room["events"] if e["id"] > since]
			return {
				"events": events,
				"latest_event_id": room["events"][-1]["id"] if room["events"] else 0,
				"members": list(room["members"].values()),
				"state": room["state"],
			}

	def _snapshot(self, room):
		return {
			"latest_event_id": room["events"][-1]["id"] if room["events"] else 0,
			"members": list(room["members"].values()),
			"state": room["state"],
		}

	def _prune(self, room):
		now = time.time()
		stale = [cid for cid, member in room["members"].items() if now - member["last_seen"] > 120]
		for cid in stale:
			room["members"].pop(cid, None)


STORE = RoomStore()


class Handler(BaseHTTPRequestHandler):
	server_version = "AutoSubWatchSync/0.1"

	def do_POST(self):
		path = self.path.rstrip("/")
		parts = path.split("/")
		if len(parts) != 4 or parts[1] != "rooms":
			self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
			return
		length = int(self.headers.get("Content-Length", "0"))
		try:
			body = json.loads(self.rfile.read(length) or b"{}")
		except json.JSONDecodeError:
			self._json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
			return
		room = parts[2]
		action = parts[3]
		client_id = body.get("client_id")
		if not client_id:
			self._json({"error": "client_id required"}, HTTPStatus.BAD_REQUEST)
			return
		if action == "join":
			name = body.get("name") or "Guest"
			self._json(STORE.join(room, client_id, name))
			return
		if action == "events":
			event_type = body.get("type")
			if not event_type:
				self._json({"error": "type required"}, HTTPStatus.BAD_REQUEST)
				return
			event_id = STORE.add_event(room, client_id, event_type, body.get("payload") or {})
			self._json({"ok": True, "event_id": event_id})
			return
		self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

	def do_GET(self):
		url = urlparse(self.path)
		path = url.path.rstrip("/")
		parts = path.split("/")
		if len(parts) != 4 or parts[1] != "rooms" or parts[3] != "events":
			self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
			return
		query = parse_qs(url.query)
		client_id = query.get("client_id", [""])[0]
		if not client_id:
			self._json({"error": "client_id required"}, HTTPStatus.BAD_REQUEST)
			return
		since = int(query.get("since", ["0"])[0] or 0)
		self._json(STORE.events_since(parts[2], since, client_id))

	def log_message(self, fmt, *args):
		return

	def _json(self, payload, status=HTTPStatus.OK):
		body = json.dumps(payload).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Access-Control-Allow-Origin", "*")
		self.end_headers()
		self.wfile.write(body)


if __name__ == "__main__":
	server = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
	print("Watch sync server running on http://0.0.0.0:8765", flush=True)
	server.serve_forever()
