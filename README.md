# Biblioteca IFES — Backend

## Estrutura

```
backend/
├── app.py                  # Entrada Flask
├── requirements.txt        # Dependências Python
├── .env                    # Credenciais (Supabase + Flask)
│
├── api/
│   ├── books.py            # CRUD /api/books
│   ├── students.py         # CRUD /api/students + CSV
│   ├── loans.py            # /api/loans + devoluções
│   └── reports.py          # /api/reports (gráficos + CSV + mensal)
│
├── scanner/
│   └── routes.py           # /api/qr — leitor QR (OpenCV + pyzbar)
│
└── utils/
    ├── supabase_client.py  # Cliente Supabase singleton (v2)
    └── helpers.py          # Datas, IDs, status de empréstimo
```

## Instalação

```bash
# 1. Ambiente virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Dependências
pip install -r requirements.txt

# 3. Configurar credenciais
cp .env.example .env
# Edite .env com a URL e a chave do seu projeto Supabase

# 4. Rodar
python app.py
# → http://localhost:5000
```

## Banco de Dados (Supabase)

O backend conecta diretamente ao Supabase. Configure `SUPABASE_URL` e `SUPABASE_KEY` no arquivo `backend/.env` ou nas variáveis de ambiente para usar seu projeto.

Se preferir, copie o exemplo:

```bash
cp backend/.env.example backend/.env
```

Depois edite `backend/.env` com a URL e a chave do seu projeto Supabase.

Use `database.sql` no Supabase para criar as tabelas antes de rodar o app.

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/health` | Status + conexão Supabase |
| GET/POST | `/api/books/` | Listar/criar livros |
| PUT/DELETE | `/api/books/<id>` | Editar/excluir livro |
| GET/POST | `/api/students/` | Listar/criar alunos |
| POST | `/api/students/import/csv` | Importar CSV |
| GET/POST | `/api/loans/` | Listar/criar empréstimos |
| POST | `/api/loans/<id>/return` | Devolver |
| GET | `/api/reports/chart-summary` | Dados gráfico principal |
| GET | `/api/reports/top-books` | Top livros |
| GET | `/api/reports/by-class` | Por turma |
| GET | `/api/reports/monthly` | Relatórios mensais |
| POST | `/api/reports/monthly/generate` | Gerar relatório mensal |
| POST | `/api/qr/decode` | Decodificar imagem QR |
| POST | `/api/qr/generate` | Gerar QR Code PNG |
