#!/usr/bin/env python3
"""Shared secure runtime state for the SDR web API and scheduler."""

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import uuid
from datetime import datetime, timedelta, timezone


HOME = os.path.expanduser("~")
API_TOKENS_PATH = os.path.join(HOME, "sdr_api_tokens.json")
EVENTS_PATH = os.path.join(HOME, "sdr_scheduler_events.jsonl")
DEVICES_PATH = os.path.join(HOME, "sdr_mobile_devices.json")
NOTIFICATION_OUTBOX_PATH = os.path.join(HOME, "sdr_notification_outbox.jsonl")

ALLOWED_SCOPES = ("read", "control", "devices:manage", "tokens:manage", "*")


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextlib.contextmanager
def _file_lock(path):
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_json_unlocked(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _append_jsonl(path, record):
    line = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        offset = 0
        while offset < len(line):
            offset += os.write(fd, line[offset:])
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    records = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def normalize_scopes(scopes):
    if isinstance(scopes, str):
        scopes = [scope.strip() for scope in scopes.split(",") if scope.strip()]
    if not isinstance(scopes, list):
        raise ValueError("scopes must be a list or comma-separated string")
    normalized = []
    for scope in scopes:
        value = str(scope).strip()
        if value not in ALLOWED_SCOPES:
            raise ValueError(f"unsupported scope: {value}")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("at least one scope is required")
    return normalized


def _public_token(record):
    return {key: value for key, value in record.items() if key != "token_hash"}


def create_api_token(name, scopes=None):
    name = str(name or "").strip()
    if not name:
        raise ValueError("token name is required")
    scopes = normalize_scopes(scopes or ["*"])
    token_id = "tok_" + uuid.uuid4().hex[:16]
    token = f"sdr_{token_id}_{secrets.token_urlsafe(32)}"
    record = {
        "id": token_id,
        "name": name,
        "scopes": scopes,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "created_at": utc_now_iso(),
        "last_used_at": None,
        "revoked_at": None,
    }
    with _file_lock(API_TOKENS_PATH):
        data = _read_json(API_TOKENS_PATH, {"version": 1, "tokens": []})
        data.setdefault("tokens", []).append(record)
        _atomic_write_json_unlocked(API_TOKENS_PATH, data)
    return {**_public_token(record), "token": token}


def list_api_tokens():
    with _file_lock(API_TOKENS_PATH):
        data = _read_json(API_TOKENS_PATH, {"version": 1, "tokens": []})
    return [_public_token(record) for record in data.get("tokens", [])]


def revoke_api_token(token_id):
    revoked = None
    with _file_lock(API_TOKENS_PATH):
        data = _read_json(API_TOKENS_PATH, {"version": 1, "tokens": []})
        for record in data.get("tokens", []):
            if record.get("id") == token_id:
                if not record.get("revoked_at"):
                    record["revoked_at"] = utc_now_iso()
                revoked = _public_token(record)
                break
        if revoked:
            _atomic_write_json_unlocked(API_TOKENS_PATH, data)
    return revoked


def authenticate_api_token(token):
    if not token:
        return None
    token_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    principal = None
    with _file_lock(API_TOKENS_PATH):
        data = _read_json(API_TOKENS_PATH, {"version": 1, "tokens": []})
        for record in data.get("tokens", []):
            if hmac.compare_digest(str(record.get("token_hash", "")), token_hash):
                if record.get("revoked_at"):
                    return None
                principal = _public_token(record)
                last_used = record.get("last_used_at")
                should_update = True
                if last_used:
                    try:
                        previous = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                        should_update = datetime.now(timezone.utc) - previous >= timedelta(minutes=1)
                    except ValueError:
                        pass
                if should_update:
                    record["last_used_at"] = utc_now_iso()
                    principal["last_used_at"] = record["last_used_at"]
                    _atomic_write_json_unlocked(API_TOKENS_PATH, data)
                break
    return principal


def principal_has_scope(principal, required_scope):
    scopes = set((principal or {}).get("scopes", []))
    if "*" in scopes or required_scope in scopes:
        return True
    return required_scope == "read" and "control" in scopes


def emit_event(event_type, source, data=None, notification=None):
    event_type = str(event_type or "").strip()
    if not event_type:
        raise ValueError("event_type is required")
    event = {
        "id": "evt_" + uuid.uuid4().hex,
        "at": utc_now_iso(),
        "type": event_type,
        "source": str(source or "unknown"),
        "data": data or {},
    }
    _append_jsonl(EVENTS_PATH, event)
    if notification:
        notification_data = notification if isinstance(notification, dict) else {}
        outbox_record = {
            "id": "ntf_" + uuid.uuid4().hex,
            "event_id": event["id"],
            "created_at": event["at"],
            "status": "pending",
            "target": "all_enabled_devices",
            "title": notification_data.get("title") or event_type.replace(".", " ").title(),
            "body": notification_data.get("body") or "",
            "data": notification_data.get("data") or event["data"],
            "attempts": 0,
        }
        _append_jsonl(NOTIFICATION_OUTBOX_PATH, outbox_record)
    return event


def read_events(after=None, limit=100):
    limit = max(1, min(int(limit), 1000))
    records = _read_jsonl(EVENTS_PATH)
    if after:
        for index, record in enumerate(records):
            if record.get("id") == after:
                return records[index + 1:index + 1 + limit]
        return records[-limit:]
    return records[-limit:]


def read_notifications(limit=100, status=None):
    limit = max(1, min(int(limit), 1000))
    records = _read_jsonl(NOTIFICATION_OUTBOX_PATH)
    if status:
        records = [record for record in records if record.get("status") == status]
    return records[-limit:]


def _public_device(record):
    public = {key: value for key, value in record.items() if key != "push_token"}
    token = str(record.get("push_token") or "")
    public["push_token_suffix"] = token[-8:] if token else ""
    return public


def register_device(payload, owner_token_id=None):
    if not isinstance(payload, dict):
        raise ValueError("device must be an object")
    platform = str(payload.get("platform") or "").strip().lower()
    if platform not in {"ios", "android"}:
        raise ValueError("device.platform must be ios or android")
    push_token = str(payload.get("push_token") or "").strip()
    if not push_token:
        raise ValueError("device.push_token is required")
    preferences = payload.get("preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("device.preferences must be an object")
    requested_id = str(payload.get("id") or "").strip()
    now = utc_now_iso()
    saved = None
    with _file_lock(DEVICES_PATH):
        data = _read_json(DEVICES_PATH, {"version": 1, "devices": []})
        devices = data.setdefault("devices", [])
        existing = next(
            (
                device for device in devices
                if (requested_id and device.get("id") == requested_id)
                or device.get("push_token") == push_token
            ),
            None,
        )
        if existing:
            existing.update({
                "name": str(payload.get("name") or existing.get("name") or platform).strip(),
                "platform": platform,
                "push_token": push_token,
                "enabled": bool(payload.get("enabled", existing.get("enabled", True))),
                "preferences": preferences,
                "owner_token_id": owner_token_id or existing.get("owner_token_id"),
                "updated_at": now,
            })
            saved = existing
        else:
            saved = {
                "id": requested_id or "dev_" + uuid.uuid4().hex,
                "name": str(payload.get("name") or platform).strip(),
                "platform": platform,
                "push_token": push_token,
                "enabled": bool(payload.get("enabled", True)),
                "preferences": preferences,
                "owner_token_id": owner_token_id,
                "created_at": now,
                "updated_at": now,
            }
            devices.append(saved)
        _atomic_write_json_unlocked(DEVICES_PATH, data)
    return _public_device(saved)


def list_devices():
    with _file_lock(DEVICES_PATH):
        data = _read_json(DEVICES_PATH, {"version": 1, "devices": []})
    return [_public_device(record) for record in data.get("devices", [])]


def delete_device(device_id):
    removed = None
    with _file_lock(DEVICES_PATH):
        data = _read_json(DEVICES_PATH, {"version": 1, "devices": []})
        devices = data.get("devices", [])
        remaining = []
        for record in devices:
            if record.get("id") == device_id:
                removed = _public_device(record)
            else:
                remaining.append(record)
        if removed:
            data["devices"] = remaining
            _atomic_write_json_unlocked(DEVICES_PATH, data)
    return removed
