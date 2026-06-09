"""
api/reports.py
Relatórios, gráficos em tempo real e exportações CSV — supabase-py v2.
Inclui suporte à tabela relatorios_mensais do schema.
"""

from flask import Blueprint, jsonify, request, Response
from utils import get_client, sb_exec, loan_status, days_until, today_str
import csv
import io
from datetime import date

reports_bp = Blueprint("reports", __name__)


# ── Busca todos os dados de uma vez ──────────────────────────────
def _fetch_all(sb):
    books    = sb_exec(sb.table("livros").select("*"))
    students = sb_exec(sb.table("alunos").select("*"))
    loans    = sb_exec(sb.table("emprestimos").select("*"))
    return books, students, loans


# ── Gráfico resumo (polling em tempo real) ────────────────────────
@reports_bp.route("/chart-summary", methods=["GET"])
def chart_summary():
    sb = get_client()
    _, _, loans = _fetch_all(sb)

    active   = sum(1 for l in loans if loan_status(l) == "active")
    overdue  = sum(1 for l in loans if loan_status(l) == "overdue")
    returned = sum(1 for l in loans if loan_status(l) == "returned")

    return jsonify({
        "labels": ["Emprestados", "Atrasados", "Devolvidos"],
        "values": [active, overdue, returned],
        "colors": ["#f59e0b", "#ef4444", "#22c55e"],
    })


# ── Top livros mais emprestados ───────────────────────────────────
@reports_bp.route("/top-books", methods=["GET"])
def top_books():
    limit = int(request.args.get("limit", 8))
    sb    = get_client()
    books, _, loans = _fetch_all(sb)

    counts: dict[str, int] = {}
    for loan in loans:
        bid = loan["livro_id"]
        counts[bid] = counts.get(bid, 0) + 1

    ranked   = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    book_map = {b["id"]: b for b in books}

    result = []
    for bid, count in ranked:
        b = book_map.get(bid)
        if b:
            result.append({
                "titulo": b["titulo"],
                "autor":  b["autor"],
                "area":   b.get("area", ""),
                "total":  count,
            })

    return jsonify(result)


# ── Empréstimos por turma ─────────────────────────────────────────
@reports_bp.route("/by-class", methods=["GET"])
def by_class():
    sb = get_client()
    _, students, loans = _fetch_all(sb)

    student_map   = {s["id"]: s.get("turma", "?") for s in students}
    class_count: dict[str, dict] = {}

    for loan in loans:
        cls = student_map.get(loan["aluno_id"], "Desconhecido")
        if cls not in class_count:
            class_count[cls] = {"active": 0, "overdue": 0, "returned": 0}
        class_count[cls][loan_status(loan)] += 1

    labels = sorted(class_count.keys())
    return jsonify({
        "labels":   labels,
        "active":   [class_count[c]["active"]   for c in labels],
        "overdue":  [class_count[c]["overdue"]  for c in labels],
        "returned": [class_count[c]["returned"] for c in labels],
    })


# ── Relatórios mensais ─────────────────────────────────────────────
@reports_bp.route("/monthly", methods=["GET"])
def get_monthly_reports():
    """Lista todos os relatórios mensais salvos."""
    sb   = get_client()
    rows = sb_exec(sb.table("relatorios_mensais").select("*").order("mes_ano", desc=True))
    return jsonify(rows)


@reports_bp.route("/monthly/generate", methods=["POST"])
def generate_monthly_report():
    """
    Gera (ou atualiza) o relatório do mês atual com base nos dados reais.
    """
    sb   = get_client()
    body = request.get_json(force=True) or {}
    mes_ano = body.get("mes_ano") or date.today().strftime("%Y-%m")

    books, students, loans = _fetch_all(sb)

    # Filtra empréstimos do mês
    mes_loans = [
        l for l in loans
        if (l.get("data_emprestimo") or "")[:7] == mes_ano
    ]
    mes_devs = [
        l for l in loans
        if (l.get("devolvido_em") or "")[:7] == mes_ano
    ]
    mes_atrasos = [l for l in mes_loans if loan_status(l) == "overdue"]

    # Top livros do mês
    counts: dict[str, int] = {}
    for loan in mes_loans:
        bid = loan["livro_id"]
        counts[bid] = counts.get(bid, 0) + 1
    book_map  = {b["id"]: b for b in books}
    top_livros = [
        {"titulo": book_map[bid]["titulo"], "total": cnt}
        for bid, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
        if bid in book_map
    ]

    # Turmas mais ativas no mês
    student_map = {s["id"]: s.get("turma", "?") for s in students}
    turma_cnt: dict[str, int] = {}
    for loan in mes_loans:
        t = student_map.get(loan["aluno_id"], "?")
        turma_cnt[t] = turma_cnt.get(t, 0) + 1
    top_turmas = [
        {"turma": t, "total": c}
        for t, c in sorted(turma_cnt.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    payload = {
        "mes_ano":             mes_ano,
        "total_emprestimos":   len(mes_loans),
        "total_devolucoes":    len(mes_devs),
        "total_atrasos":       len(mes_atrasos),
        "livros_mais_lidos":   top_livros,
        "turmas_mais_ativas":  top_turmas,
        "gerado_em":           today_str(),
        "gerado_por":          body.get("gerado_por", "system"),
    }

    # Upsert (atualiza se já existe, cria se não existe)
    rows = sb_exec(
        sb.table("relatorios_mensais")
          .upsert(payload, on_conflict="mes_ano")
    )
    return jsonify(rows[0] if rows else payload), 201


# ── CSV Exports ────────────────────────────────────────────────────
def _csv_response(rows: list[list], filename: str) -> Response:
    output = io.StringIO()
    csv.writer(output, quoting=csv.QUOTE_ALL).writerows(rows)
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@reports_bp.route("/export/overdue", methods=["GET"])
def export_overdue():
    sb = get_client()
    books, students, loans = _fetch_all(sb)
    bmap = {b["id"]: b for b in books}
    smap = {s["id"]: s for s in students}

    rows = [["Aluno", "Turma", "Livro", "Exemplar", "Emprestado em", "Vencimento", "Dias Atraso"]]
    for l in loans:
        if loan_status(l) != "overdue":
            continue
        b = bmap.get(l["livro_id"], {})
        s = smap.get(l["aluno_id"], {})
        rows.append([
            s.get("nome", ""), s.get("turma", ""),
            b.get("titulo", ""), l.get("exemplar", ""),
            l.get("data_emprestimo", ""),
            l.get("data_devolucao_prevista", ""),
            abs(days_until(l["data_devolucao_prevista"])),
        ])
    return _csv_response(rows, "emprestimos-atrasados.csv")


@reports_bp.route("/export/all", methods=["GET"])
def export_all():
    sb = get_client()
    books, students, loans = _fetch_all(sb)
    bmap = {b["id"]: b for b in books}
    smap = {s["id"]: s for s in students}

    rows = [["Aluno", "Turma", "Livro", "Exemplar",
             "Emprestado em", "Devolução prevista", "Devolvido em", "Status"]]
    for l in loans:
        b = bmap.get(l["livro_id"], {})
        s = smap.get(l["aluno_id"], {})
        rows.append([
            s.get("nome", ""), s.get("turma", ""),
            b.get("titulo", ""), l.get("exemplar", ""),
            l.get("data_emprestimo", ""),
            l.get("data_devolucao_prevista", ""),
            l.get("devolvido_em", "") or "",
            loan_status(l),
        ])
    return _csv_response(rows, "historico-completo.csv")


@reports_bp.route("/export/books", methods=["GET"])
def export_books():
    sb = get_client()
    books, _, loans = _fetch_all(sb)

    rows = [["Título", "Autor", "Área", "ISBN", "Total Empréstimos", "Ativos Agora"]]
    for b in books:
        total  = sum(1 for l in loans if l["livro_id"] == b["id"])
        active = sum(1 for l in loans if l["livro_id"] == b["id"] and not l.get("devolvido_em"))
        rows.append([b.get("titulo", ""), b.get("autor", ""), b.get("area", ""),
                     b.get("isbn", ""), total, active])
    rows[1:] = sorted(rows[1:], key=lambda r: r[4], reverse=True)
    return _csv_response(rows, "livros-mais-emprestados.csv")


@reports_bp.route("/export/by-class", methods=["GET"])
def export_by_class():
    sb = get_client()
    _, students, loans = _fetch_all(sb)
    smap = {s["id"]: s for s in students}

    class_data: dict[str, dict] = {}
    for l in loans:
        s   = smap.get(l["aluno_id"], {})
        cls = s.get("turma", "?")
        if cls not in class_data:
            class_data[cls] = {"alunos": set(), "ativos": 0, "atrasados": 0, "total": 0}
        class_data[cls]["alunos"].add(l["aluno_id"])
        class_data[cls]["total"] += 1
        st = loan_status(l)
        if st == "active":
            class_data[cls]["ativos"] += 1
        elif st == "overdue":
            class_data[cls]["atrasados"] += 1

    rows = [["Turma", "Alunos Únicos", "Empréstimos Ativos", "Atrasados", "Total Histórico"]]
    for cls, d in sorted(class_data.items()):
        rows.append([cls, len(d["alunos"]), d["ativos"], d["atrasados"], d["total"]])
    return _csv_response(rows, "relatorio-por-turma.csv")
