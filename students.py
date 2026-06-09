"""
api/students.py
CRUD de alunos com sala_id + geração de QR automático no cadastro.
"""

from flask import Blueprint, request, jsonify
from utils import get_client, sb_exec, new_id, today_str
import csv, io, json
from pathlib import Path

students_bp = Blueprint("students", __name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ROOMS_FILE = DATA_DIR / "salas.json"
ALUNOS_FILE = DATA_DIR / "alunos.json"
LOANS_FILE = DATA_DIR / "emprestimos.json"


def _ensure_json(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def _load_local_rooms():
    if not ROOMS_FILE.exists():
        return []
    try:
        return json.loads(ROOMS_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _load_local_students():
    _ensure_json(ALUNOS_FILE)
    try:
        return json.loads(ALUNOS_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _write_local_students(items):
    _ensure_json(ALUNOS_FILE)
    ALUNOS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_local_loans():
    if not LOANS_FILE.exists():
        return []
    try:
        return json.loads(LOANS_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def _local_room_exists(room_id):
    if not room_id:
        return False
    rooms = _load_local_rooms()
    return any(r.get("id") == room_id for r in rooms)


def _table_available(sb, table_name: str):
    try:
        sb_exec(sb.table(table_name).select("id").limit(1))
        return True
    except Exception as exc:
        return "could not find the table" not in str(exc).lower()


def _has_deleted_at(sb, table_name: str) -> bool:
    try:
        sb_exec(sb.table(table_name).select("deleted_at").limit(1))
        return True
    except Exception as exc:
        msg = str(exc).lower()
        return not ("could not find the 'deleted_at' column" in msg or "column deleted_at does not exist" in msg)


@students_bp.route("/", methods=["GET"])
def list_students():
    sb           = get_client()
    q            = request.args.get("q", "").strip().lower()
    cls          = request.args.get("class", "").strip()
    sala         = request.args.get("sala_id", "").strip()
    show_deleted = request.args.get("show_deleted", "").strip().lower() in ("1", "true", "yes", "on")

    if _table_available(sb, "alunos"):
        query = sb.table("alunos").select("*, salas(nome, codigo)").order("nome")
        if not show_deleted and _has_deleted_at(sb, "alunos"):
            query = query.is_("deleted_at", "null")
        try:
            students = sb_exec(query)
        except Exception:
            query = sb.table("alunos").select("*").order("nome")
            if not show_deleted and _has_deleted_at(sb, "alunos"):
                query = query.is_("deleted_at", "null")
            students = sb_exec(query)
    else:
        students = _load_local_students()
        if not show_deleted:
            students = [s for s in students if not s.get("deleted_at")]

    if q:
        students = [s for s in students
            if q in (s.get("nome") or "").lower()
            or q in (s.get("turma") or "").lower()
            or q in (s.get("carteirinha") or "").lower()
            or q in (s.get("id") or "").lower()
        ]
    if cls:
        students = [s for s in students if s.get("turma") == cls]
    if sala:
        students = [s for s in students if s.get("sala_id") == sala]

    # Flatten sala
    if _table_available(sb, "alunos"):
        for s in students:
            sala_data = s.pop("salas", None) or {}
            s["sala_nome"]   = sala_data.get("nome", "")
            s["sala_codigo"] = sala_data.get("codigo", "")
    else:
        rooms = {r.get("id"): r for r in _load_local_rooms()}
        for s in students:
            room = rooms.get(s.get("sala_id")) or {}
            s["sala_nome"]   = room.get("nome", "")
            s["sala_codigo"] = room.get("codigo", "")

    return jsonify(students)


@students_bp.route("/<student_id>", methods=["GET"])
def get_student(student_id):
    sb = get_client()
    if _table_available(sb, "alunos"):
        try:
            rows = sb_exec(sb.table("alunos").select("*, salas(nome, codigo)").eq("id", student_id))
            if not rows:
                rows = sb_exec(sb.table("alunos").select("*, salas(nome, codigo)").eq("carteirinha", student_id))
        except Exception:
            rows = sb_exec(sb.table("alunos").select("*").eq("id", student_id))
            if not rows:
                rows = sb_exec(sb.table("alunos").select("*").eq("carteirinha", student_id))
        if not rows:
            try:
                all_s = sb_exec(sb.table("alunos").select("*, salas(nome, codigo)"))
                rows  = [s for s in all_s if student_id.lower() in (s.get("nome") or "").lower()]
            except Exception:
                all_s = sb_exec(sb.table("alunos").select("*") )
                rows  = [s for s in all_s if student_id.lower() in (s.get("nome") or "").lower()]
        if not rows:
            return jsonify({"error": "Aluno não encontrado"}), 404

        s         = rows[0]
        sala_data = s.pop("salas", None) or {}
        s["sala_nome"]   = sala_data.get("nome", "")
        s["sala_codigo"] = sala_data.get("codigo", "")
        return jsonify(s)

    students = _load_local_students()
    rows = [s for s in students if s.get("id") == student_id or s.get("carteirinha") == student_id]
    if not rows:
        rows = [s for s in students if student_id.lower() in (s.get("nome") or "").lower()]
    if not rows:
        return jsonify({"error": "Aluno não encontrado"}), 404

    s = rows[0]
    room = next((r for r in _load_local_rooms() if r.get("id") == s.get("sala_id")), {})
    s["sala_nome"] = room.get("nome", "")
    s["sala_codigo"] = room.get("codigo", "")
    return jsonify(s)


@students_bp.route("/", methods=["POST"])
def create_student():
    body = request.get_json(force=True) or {}
    if not body.get("nome") or not body.get("turma"):
        return jsonify({"error": "nome e turma são obrigatórios"}), 400

    sb         = get_client()
    student_id = new_id()
    sala_id    = body.get("sala_id") or None
    if sala_id:
        try:
            salas = sb_exec(sb.table("salas").select("id").eq("id", sala_id))
            if not salas:
                sala_id = None
        except Exception:
            if not _local_room_exists(sala_id):
                sala_id = None

    carteirinha = body.get("carteirinha")
    if isinstance(carteirinha, str):
        carteirinha = carteirinha.strip()
    if not carteirinha:
        carteirinha = student_id[:8]

    payload    = {
        "id":          student_id,
        "nome":        body["nome"].strip(),
        "turma":       body["turma"].strip().upper(),
        "carteirinha": carteirinha,
    }
    if sala_id is not None:
        payload["sala_id"] = sala_id

    if _table_available(sb, "alunos"):
        try:
            rows = sb_exec(sb.table("alunos").insert(payload))
        except Exception as e:
            msg = str(e).lower()
            if "sala_id" in payload and "could not find the 'sala_id' column" in msg:
                payload.pop("sala_id", None)
                rows = sb_exec(sb.table("alunos").insert(payload))
            elif "duplicate key value" in msg or "unique constraint" in msg:
                return jsonify({"error": "Carteirinha já cadastrada."}), 409
            else:
                raise
        if not rows:
            return jsonify({"error": "Não foi possível cadastrar o aluno."}), 500
        result = rows[0]
    else:
        students = _load_local_students()
        if payload["carteirinha"] and any(s.get("carteirinha") == payload["carteirinha"] for s in students):
            return jsonify({"error": "Carteirinha já cadastrada."}), 409
        students.append(payload)
        _write_local_students(students)
        result = payload

    # Gera QR Code automaticamente
    try:
        import qrcode as qr_lib, base64
        from io import BytesIO
        qr = qr_lib.QRCode(version=1, box_size=6, border=2)
        qr.add_data(student_id)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#166534", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        result["qr_code"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        result["qr_code"] = None

    return jsonify(result), 201


@students_bp.route("/<student_id>", methods=["PUT"])
def update_student(student_id):
    body = request.get_json(force=True) or {}
    body.pop("id", None); body.pop("criado_em", None)
    body.pop("salas", None); body.pop("sala_nome", None); body.pop("sala_codigo", None)
    if body.get("turma"):
        body["turma"] = body["turma"].upper()

    sala_id = body.get("sala_id") or None
    if sala_id:
        try:
            sb = get_client()
            salas = sb_exec(sb.table("salas").select("id").eq("id", sala_id))
            if not salas:
                body["sala_id"] = None
        except Exception:
            if not _local_room_exists(sala_id):
                body["sala_id"] = None

    sb   = get_client()
    if _table_available(sb, "alunos"):
        try:
            rows = sb_exec(sb.table("alunos").update(body).eq("id", student_id))
        except Exception as e:
            msg = str(e).lower()
            if "sala_id" in body and "could not find the 'sala_id' column" in msg:
                body.pop("sala_id", None)
                rows = sb_exec(sb.table("alunos").update(body).eq("id", student_id))
            elif "duplicate key value" in msg or "unique constraint" in msg:
                return jsonify({"error": "Carteirinha já cadastrada."}), 409
            else:
                raise
        if not rows:
            return jsonify({"error": "Aluno não encontrado"}), 404
        return jsonify(rows[0])

    students = _load_local_students()
    updated = False
    for s in students:
        if s.get("id") == student_id:
            s.update(body)
            updated = True
            result = s
            break
    if not updated:
        return jsonify({"error": "Aluno não encontrado"}), 404
    _write_local_students(students)
    return jsonify(result)


@students_bp.route("/<student_id>", methods=["DELETE"])
def delete_student(student_id):
    sb = get_client()
    try:
        ativos = []
        if _table_available(sb, "emprestimos"):
            ativos = sb_exec(sb.table("emprestimos").select("id").eq("aluno_id", student_id).is_("devolvido_em", "null"))
        else:
            ativos = [l for l in _read_local_loans() if l.get("aluno_id") == student_id and not l.get("devolvido_em")]
        if ativos:
            return jsonify({"error": "Aluno possui empréstimos ativos"}), 409
    except Exception:
        pass

    if _table_available(sb, "alunos"):
        if _has_deleted_at(sb, "alunos"):
            sb_exec(sb.table("alunos").update({"deleted_at": today_str()}).eq("id", student_id))
        else:
            sb_exec(sb.table("alunos").delete().eq("id", student_id))
        return jsonify({"success": True})

    students = _load_local_students()
    found = False
    for s in students:
        if s.get("id") == student_id:
            s["deleted_at"] = today_str()
            found = True
            break
    if not found:
        return jsonify({"error": "Aluno não encontrado"}), 404
    _write_local_students(students)
    return jsonify({"success": True})


@students_bp.route("/<student_id>/recover", methods=["POST"])
def recover_student(student_id):
    sb = get_client()
    if _table_available(sb, "alunos"):
        if not _has_deleted_at(sb, "alunos"):
            return jsonify({"error": "Recuperação não disponível"}), 400
        rows = sb_exec(sb.table("alunos").update({"deleted_at": None}).eq("id", student_id))
        if not rows:
            return jsonify({"error": "Aluno não encontrado"}), 404
        return jsonify(rows[0])

    students = _load_local_students()
    recovered = False
    for s in students:
        if s.get("id") == student_id and s.get("deleted_at"):
            s.pop("deleted_at", None)
            recovered = True
            break
    if not recovered:
        return jsonify({"error": "Aluno não encontrado ou não está excluído"}), 404
    _write_local_students(students)
    return jsonify({"success": True})


@students_bp.route("/import/csv", methods=["POST"])
def import_csv():
    sb = get_client()
    if "file" in request.files:
        raw = request.files["file"].read().decode("utf-8", errors="replace")
    else:
        raw = request.get_data(as_text=True)
    if not raw.strip():
        return jsonify({"error": "Arquivo vazio"}), 400

    sep    = ";" if ";" in raw.split("\n")[0] else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=sep)

    try:
        rooms = sb_exec(sb.table("salas").select("id,codigo,nome"))
    except Exception:
        rooms = []
    room_index = {r["id"]: r for r in rooms}
    room_index.update({r["codigo"]: r for r in rooms if r.get("codigo")})
    room_index.update({r["nome"]: r for r in rooms if r.get("nome")})

    existing = {s.get("carteirinha", "") for s in sb_exec(sb.table("alunos").select("carteirinha")) if s.get("carteirinha")}
    added, skipped = 0, 0
    batch = []

    for row in reader:
        nome  = (row.get("nome") or row.get("Nome") or "").strip()
        turma = (row.get("turma") or row.get("Turma") or "").strip().upper()
        card  = (row.get("carteirinha") or row.get("matricula") or row.get("matrícula") or "").strip()
        sala  = (row.get("sala_id") or "").strip() or None
        if sala and sala in room_index:
            sala = room_index[sala]["id"]
        else:
            sala = None

        if not nome or not turma: skipped += 1; continue
        if card and card in existing: skipped += 1; continue

        batch.append({"id": new_id(), "nome": nome, "turma": turma, "carteirinha": card, "sala_id": sala})
        if card: existing.add(card)
        added += 1

    if batch:
        if _table_available(sb, "alunos"):
            try:
                sb_exec(sb.table("alunos").insert(batch))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        else:
            students = _load_local_students()
            students.extend(batch)
            _write_local_students(students)

    return jsonify({"added": added, "skipped": skipped})
