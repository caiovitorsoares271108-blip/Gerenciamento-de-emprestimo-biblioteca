"""
api/loans.py
Empréstimos e devoluções — supabase-py v2.
"""

from flask import Blueprint, request, jsonify
from utils import get_client, sb_exec, new_id, today_str, add_days, loan_status

loans_bp = Blueprint("loans", __name__)


def _available_copies(sb, book_id: str, total: int) -> list[str]:
    """Retorna lista de códigos de exemplar disponíveis."""
    usados = {
        r["exemplar"] for r in sb_exec(
            sb.table("emprestimos")
              .select("exemplar")
              .eq("livro_id", book_id)
              .is_("devolvido_em", "null")
        )
    }
    todos = [str(i + 1).zfill(3) for i in range(total)]
    return [c for c in todos if c not in usados]


@loans_bp.route("/", methods=["GET"])
def list_loans():
    sb     = get_client()
    status = request.args.get("status", "")

    loans = sb_exec(
        sb.table("emprestimos")
          .select("*")
          .order("data_emprestimo", desc=True)
    )

    if status == "active":
        loans = [l for l in loans if loan_status(l) == "active"]
    elif status == "overdue":
        loans = [l for l in loans if loan_status(l) == "overdue"]
    elif status == "returned":
        loans = [l for l in loans if loan_status(l) == "returned"]

    return jsonify(loans)


@loans_bp.route("/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    sb   = get_client()
    rows = sb_exec(sb.table("emprestimos").select("*").eq("id", loan_id))
    if not rows:
        return jsonify({"error": "Empréstimo não encontrado"}), 404
    return jsonify(rows[0])


@loans_bp.route("/", methods=["POST"])
def create_loan():
    body       = request.get_json(force=True) or {}
    book_id    = body.get("livro_id")
    student_id = body.get("aluno_id")
    days       = int(body.get("dias", 7))

    if not book_id or not student_id:
        return jsonify({"error": "livro_id e aluno_id são obrigatórios"}), 400

    sb = get_client()

    # Busca o livro
    books = sb_exec(sb.table("livros").select("*").eq("id", book_id))
    if not books:
        return jsonify({"error": "Livro não encontrado"}), 404
    book = books[0]

    # Verifica exemplares disponíveis
    avail = _available_copies(sb, book_id, book["exemplares"])
    if not avail:
        return jsonify({"error": "Nenhum exemplar disponível no momento"}), 409

    # Verifica se aluno existe
    aluno = sb_exec(sb.table("alunos").select("id").eq("id", student_id))
    if not aluno:
        return jsonify({"error": "Aluno não encontrado"}), 404

    loan_date = body.get("data_emprestimo") or today_str()
    due_date  = add_days(loan_date, days)
    loan_id   = new_id()

    payload = {
        "id":                      loan_id,
        "livro_id":                book_id,
        "aluno_id":                student_id,
        "exemplar":                avail[0],
        "data_emprestimo":         loan_date,
        "data_devolucao_prevista": due_date,
        "devolvido_em":            None,
        "observacao":              body.get("observacao", "") or "",
        "criado_por":              body.get("criado_por", "system"),
    }

    try:
        rows = sb_exec(sb.table("emprestimos").insert(payload))
    except Exception as e:
        msg = str(e).lower()
        if "could not find the 'criado_por' column" in msg or "could not find the 'observacao' column" in msg:
            payload.pop("criado_por", None)
            payload.pop("observacao", None)
            rows = sb_exec(sb.table("emprestimos").insert(payload))
        else:
            raise
    return jsonify(rows[0] if rows else payload), 201


@loans_bp.route("/<loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    body = request.get_json(force=True) or {}
    sb   = get_client()

    # Verifica se empréstimo existe e ainda está ativo
    loans = sb_exec(sb.table("emprestimos").select("*").eq("id", loan_id))
    if not loans:
        return jsonify({"error": "Empréstimo não encontrado"}), 404
    if loans[0].get("devolvido_em"):
        return jsonify({"error": "Este empréstimo já foi devolvido"}), 409

    upd = {
        "devolvido_em": body.get("devolvido_em") or today_str(),
        "observacao":   body.get("observacao", "") or "",
    }
    try:
        rows = sb_exec(sb.table("emprestimos").update(upd).eq("id", loan_id))
    except Exception as e:
        msg = str(e).lower()
        if "could not find the 'observacao' column" in msg:
            upd.pop("observacao", None)
            rows = sb_exec(sb.table("emprestimos").update(upd).eq("id", loan_id))
        else:
            raise
    return jsonify(rows[0] if rows else upd)


@loans_bp.route("/available-copies/<book_id>", methods=["GET"])
def available_copies(book_id):
    sb    = get_client()
    books = sb_exec(sb.table("livros").select("exemplares").eq("id", book_id))
    if not books:
        return jsonify({"error": "Livro não encontrado"}), 404
    avail = _available_copies(sb, book_id, books[0]["exemplares"])
    return jsonify({"available": avail, "count": len(avail)})
