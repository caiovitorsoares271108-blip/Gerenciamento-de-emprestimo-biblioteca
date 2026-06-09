"""
api/books.py
CRUD de livros com suporte a genero_id e geração de QR automático.
"""

from flask import Blueprint, request, jsonify
from utils import get_client, sb_exec, new_id, today_str
import json
from pathlib import Path

books_bp = Blueprint("books", __name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GENRES_FILE = DATA_DIR / "generos.json"


def _load_local_genres():
    if not GENRES_FILE.exists():
        return []
    try:
        return json.loads(GENRES_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _local_genre_exists(genre_id):
    if not genre_id:
        return False
    genres = _load_local_genres()
    return any(g.get("id") == genre_id for g in genres)


def _table_available(sb, table_name: str):
    try:
        sb_exec(sb.table(table_name).select("id").limit(1))
        return True
    except Exception as exc:
        return "could not find the table" not in str(exc).lower()



@books_bp.route("/", methods=["GET"])
def list_books():
    sb     = get_client()
    q      = request.args.get("q", "").strip().lower()
    genre  = request.args.get("genre", "").strip()

    try:
        books = sb_exec(sb.table("livros").select("*, generos(nome, cor, icone)").order("titulo"))
    except Exception:
        books = sb_exec(sb.table("livros").select("*").order("titulo"))

    if q:
        books = [
            b for b in books
            if q in (b.get("titulo") or "").lower()
            or q in (b.get("autor") or "").lower()
            or q in (b.get("isbn") or "").lower()
            or q in (b.get("id") or "").lower()
        ]
    if genre:
        books = [b for b in books if b.get("genero_id") == genre]

    # Flatten genero info
    for b in books:
        gen = b.pop("generos", None) or {}
        b["genero_nome"] = gen.get("nome", "")
        b["genero_cor"]  = gen.get("cor", "")
        b["genero_icone"]= gen.get("icone", "")

    return jsonify(books)


@books_bp.route("/<book_id>", methods=["GET"])
def get_book(book_id):
    sb   = get_client()
    try:
        rows = sb_exec(sb.table("livros").select("*, generos(nome, cor, icone)").eq("id", book_id))
        if not rows:
            rows = sb_exec(sb.table("livros").select("*, generos(nome, cor, icone)").eq("isbn", book_id))
    except Exception:
        rows = sb_exec(sb.table("livros").select("*").eq("id", book_id))
        if not rows:
            rows = sb_exec(sb.table("livros").select("*").eq("isbn", book_id))
    if not rows:
        return jsonify({"error": "Livro não encontrado"}), 404
    b   = rows[0]
    gen = b.pop("generos", None) or {}
    b["genero_nome"] = gen.get("nome", "")
    b["genero_cor"]  = gen.get("cor", "")
    b["genero_icone"]= gen.get("icone", "")
    return jsonify(b)


@books_bp.route("/", methods=["POST"])
def create_book():
    body = request.get_json(force=True) or {}
    if not body.get("titulo") or not body.get("autor"):
        return jsonify({"error": "titulo e autor são obrigatórios"}), 400

    sb      = get_client()
    book_id = new_id()
    try:
        copies = max(1, int(body.get("exemplares", 1)))
    except (ValueError, TypeError):
        copies = 1

    payload = {
        "id":         book_id,
        "isbn":       body.get("isbn", "") or "",
        "titulo":     body["titulo"].strip(),
        "autor":      body["autor"].strip(),
        "area":       body.get("area", "Geral") or "Geral",
        "exemplares": copies,
    }

    genero_id = body.get("genero_id") or None
    if genero_id:
        try:
            exists = sb_exec(sb.table("generos").select("id").eq("id", genero_id))
            if exists:
                payload["genero_id"] = genero_id
        except Exception:
            if _local_genre_exists(genero_id):
                payload["genero_id"] = genero_id
            else:
                payload.pop("genero_id", None)

    try:
        rows = sb_exec(sb.table("livros").insert(payload))
    except Exception as e:
        msg = str(e).lower()
        if "could not find the 'genero_id' column" in msg:
            payload.pop("genero_id", None)
            rows = sb_exec(sb.table("livros").insert(payload))
        else:
            raise
    if not rows:
        return jsonify({"error": "Não foi possível cadastrar o livro."}), 500
    result = rows[0]

    # Gera QR Code e retorna junto
    try:
        import qrcode as qr_lib
        import base64
        from io import BytesIO
        qr = qr_lib.QRCode(version=1, box_size=6, border=2)
        qr.add_data(book_id)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1a4f8a", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        result["qr_code"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        result["qr_code"] = None

    return jsonify(result), 201


@books_bp.route("/<book_id>", methods=["PUT"])
def update_book(book_id):
    body = request.get_json(force=True) or {}
    body.pop("id", None); body.pop("criado_em", None)
    body.pop("generos", None); body.pop("genero_nome", None)
    body.pop("genero_cor", None); body.pop("genero_icone", None)

    sb = get_client()
    genero_id = body.get("genero_id") or None
    if genero_id:
        try:
            exists = sb_exec(sb.table("generos").select("id").eq("id", genero_id))
            if not exists:
                body.pop("genero_id", None)
        except Exception:
            if not _local_genre_exists(genero_id):
                body.pop("genero_id", None)

    try:
        rows = sb_exec(sb.table("livros").update(body).eq("id", book_id))
    except Exception as e:
        msg = str(e).lower()
        if "could not find the 'genero_id' column" in msg:
            body.pop("genero_id", None)
            rows = sb_exec(sb.table("livros").update(body).eq("id", book_id))
        else:
            raise
    if not rows:
        return jsonify({"error": "Livro não encontrado"}), 404
    return jsonify(rows[0])


@books_bp.route("/<book_id>", methods=["DELETE"])
def delete_book(book_id):
    sb     = get_client()
    ativos = sb_exec(
        sb.table("emprestimos").select("id")
          .eq("livro_id", book_id)
          .is_("devolvido_em", "null")
    )
    if ativos:
        return jsonify({"error": "Livro possui empréstimos ativos."}), 409
    if _has_deleted_at(sb, "livros"):
        sb_exec(sb.table("livros").update({"deleted_at": today_str()}).eq("id", book_id))
    else:
        sb_exec(sb.table("livros").delete().eq("id", book_id))
    return jsonify({"success": True})


@books_bp.route("/<book_id>/recover", methods=["POST"])
def recover_book(book_id):
    sb = get_client()
    if not _has_deleted_at(sb, "livros"):
        return jsonify({"error": "Recuperação não disponível"}), 400
    rows = sb_exec(sb.table("livros").update({"deleted_at": None}).eq("id", book_id))
    if not rows:
        return jsonify({"error": "Livro não encontrado"}), 404
    return jsonify(rows[0])
