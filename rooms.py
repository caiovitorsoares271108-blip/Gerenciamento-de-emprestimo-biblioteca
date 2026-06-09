"""
api/rooms.py
CRUD de Salas (turmas organizadas como salas físicas).
Cada sala tem: nome, código, descrição, capacidade.
Alunos são vinculados à sala via campo sala_id em alunos.
"""

from flask import Blueprint, request, jsonify
from utils import get_client, sb_exec, new_id
import json
from pathlib import Path

rooms_bp = Blueprint("rooms", __name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROOMS_FILE = DATA_DIR / "salas.json"


def _ensure_json(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def _read_local_rooms():
    _ensure_json(ROOMS_FILE)
    try:
        return json.loads(ROOMS_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _write_local_rooms(items):
    _ensure_json(ROOMS_FILE)
    ROOMS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _table_available(sb, table_name: str):
    try:
        sb_exec(sb.table(table_name).select("id").limit(1))
        return True
    except Exception as exc:
        return "could not find the table" not in str(exc).lower()


@rooms_bp.route("/", methods=["GET"])
def list_rooms():
    sb    = get_client()
    if _table_available(sb, "salas"):
        rooms = sb_exec(sb.table("salas").select("*").order("nome"))
    else:
        rooms = _read_local_rooms()

    # Enriquece com contagem de alunos
    for r in rooms:
        try:
            alunos = sb_exec(sb.table("alunos").select("id").eq("sala_id", r["id"]))
        except Exception:
            alunos = []
        r["total_alunos"] = len(alunos)
    return jsonify(rooms)


@rooms_bp.route("/<room_id>", methods=["GET"])
def get_room(room_id):
    sb   = get_client()
    if _table_available(sb, "salas"):
        rows = sb_exec(sb.table("salas").select("*").eq("id", room_id))
        if not rows:
            return jsonify({"error": "Sala não encontrada"}), 404
        room = rows[0]
    else:
        rooms = _read_local_rooms()
        room = next((r for r in rooms if r.get("id") == room_id), None)
        if not room:
            return jsonify({"error": "Sala não encontrada"}), 404

    try:
        room["alunos"] = sb_exec(sb.table("alunos").select("*").eq("sala_id", room_id).order("nome"))
    except Exception:
        room["alunos"] = []
    return jsonify(room)


@rooms_bp.route("/", methods=["POST"])
def create_room():
    body = request.get_json(force=True) or {}
    if not body.get("nome"):
        return jsonify({"error": "nome é obrigatório"}), 400

    payload = {
        "id":         new_id(),
        "nome":       body["nome"].strip(),
        "codigo":     body.get("codigo", "").strip().upper(),
        "descricao":  body.get("descricao", "").strip(),
        "capacidade": int(body.get("capacidade", 40)),
    }

    sb = get_client()
    if _table_available(sb, "salas"):
        rows = sb_exec(sb.table("salas").insert(payload))
        return jsonify(rows[0] if rows else payload), 201

    rooms = _read_local_rooms()
    rooms.append(payload)
    _write_local_rooms(rooms)
    return jsonify(payload), 201


@rooms_bp.route("/<room_id>", methods=["PUT"])
def update_room(room_id):
    body = request.get_json(force=True) or {}
    body.pop("id", None); body.pop("criado_em", None)
    sb   = get_client()
    if _table_available(sb, "salas"):
        rows = sb_exec(sb.table("salas").update(body).eq("id", room_id))
        if not rows:
            return jsonify({"error": "Sala não encontrada"}), 404
        return jsonify(rows[0])

    rooms = _read_local_rooms()
    updated = False
    for r in rooms:
        if r.get("id") == room_id:
            r.update(body)
            updated = True
            result = r
            break
    if not updated:
        return jsonify({"error": "Sala não encontrada"}), 404
    _write_local_rooms(rooms)
    return jsonify(result)


@rooms_bp.route("/<room_id>", methods=["DELETE"])
def delete_room(room_id):
    sb = get_client()
    if _table_available(sb, "salas"):
        try:
            sb_exec(sb.table("alunos").update({"sala_id": None}).eq("sala_id", room_id))
        except Exception:
            pass
        sb_exec(sb.table("salas").delete().eq("id", room_id))
        return jsonify({"success": True})

    rooms = _read_local_rooms()
    rooms = [r for r in rooms if r.get("id") != room_id]
    _write_local_rooms(rooms)
    return jsonify({"success": True})
