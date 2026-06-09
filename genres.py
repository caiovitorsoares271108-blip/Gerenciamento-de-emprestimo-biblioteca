"""
api/genres.py
CRUD de Gêneros/Tipos de livro (ex: Comédia, Ficção, Técnico...).
Livros têm campo genero_id.
"""

from flask import Blueprint, request, jsonify
from utils import get_client, sb_exec, new_id
import json
from pathlib import Path

genres_bp = Blueprint("genres", __name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GENRES_FILE = DATA_DIR / "generos.json"


def _ensure_json(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def _read_local_genres():
    _ensure_json(GENRES_FILE)
    try:
        return json.loads(GENRES_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _write_local_genres(items):
    _ensure_json(GENRES_FILE)
    GENRES_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _table_available(sb, table_name: str):
    try:
        sb_exec(sb.table(table_name).select("id").limit(1))
        return True
    except Exception as exc:
        return "could not find the table" not in str(exc).lower()


def _load_genres(sb):
    if _table_available(sb, "generos"):
        return sb_exec(sb.table("generos").select("*").order("nome"))
    return _read_local_genres()


@genres_bp.route("/", methods=["GET"])
def list_genres():
    sb     = get_client()
    genres = _load_genres(sb)
    for g in genres:
        try:
            livros = sb_exec(sb.table("livros").select("id").eq("genero_id", g["id"]))
        except Exception:
            livros = []
        g["total_livros"] = len(livros)
    return jsonify(genres)


@genres_bp.route("/", methods=["POST"])
def create_genre():
    body = request.get_json(force=True) or {}
    if not body.get("nome"):
        return jsonify({"error": "nome é obrigatório"}), 400

    sb      = get_client()
    payload = {
        "id":    new_id(),
        "nome":  body["nome"].strip(),
        "icone": body.get("icone", "ti-book").strip(),
        "cor":   body.get("cor", "#6366f1").strip(),
    }
    if _table_available(sb, "generos"):
        rows = sb_exec(sb.table("generos").insert(payload))
        return jsonify(rows[0] if rows else payload), 201

    genres = _read_local_genres()
    genres.append(payload)
    _write_local_genres(genres)
    return jsonify(payload), 201


@genres_bp.route("/<genre_id>", methods=["PUT"])
def update_genre(genre_id):
    body = request.get_json(force=True) or {}
    body.pop("id", None); body.pop("criado_em", None)
    sb   = get_client()
    if _table_available(sb, "generos"):
        rows = sb_exec(sb.table("generos").update(body).eq("id", genre_id))
        if not rows:
            return jsonify({"error": "Gênero não encontrado"}), 404
        return jsonify(rows[0])

    genres = _read_local_genres()
    updated = False
    for g in genres:
        if g.get("id") == genre_id:
            g.update(body)
            updated = True
            result = g
            break
    if not updated:
        return jsonify({"error": "Gênero não encontrado"}), 404
    _write_local_genres(genres)
    return jsonify(result)


@genres_bp.route("/<genre_id>", methods=["DELETE"])
def delete_genre(genre_id):
    sb = get_client()
    try:
        sb_exec(sb.table("livros").update({"genero_id": None}).eq("genero_id", genre_id))
    except Exception:
        pass

    if _table_available(sb, "generos"):
        sb_exec(sb.table("generos").delete().eq("id", genre_id))
        return jsonify({"success": True})

    genres = _read_local_genres()
    genres = [g for g in genres if g.get("id") != genre_id]
    _write_local_genres(genres)
    return jsonify({"success": True})
