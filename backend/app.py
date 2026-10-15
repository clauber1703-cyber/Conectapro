from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "conectapro.db"
DB.parent.mkdir(parents=True, exist_ok=True)

def conectar():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

with conectar() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS profissionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            regiao TEXT NOT NULL,
            servico TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            fotos TEXT DEFAULT '[]',
            criado_em TEXT NOT NULL
        )
    """)

class API(BaseHTTPRequestHandler):
    def responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self):
        self.responder(200, {"ok": True})

    def do_GET(self):
        if self.path == "/api/health":
            return self.responder(200, {
                "ok": True, "servico": "ConectaPro API"
            })

        if self.path == "/api/profissionais":
            with conectar() as db:
                linhas = db.execute(
                    "SELECT * FROM profissionais ORDER BY id DESC"
                ).fetchall()
            lista = []
            for linha in linhas:
                item = dict(linha)
                item["fotos"] = json.loads(item["fotos"] or "[]")
                lista.append(item)
            return self.responder(200, {
                "ok": True, "total": len(lista), "profissionais": lista
            })

        self.responder(404, {"ok": False, "erro": "Rota não encontrada"})

    def do_POST(self):
        if self.path != "/api/profissionais":
            return self.responder(404, {"ok": False, "erro": "Rota não encontrada"})

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if tamanho <= 0 or tamanho > 12 * 1024 * 1024:
                return self.responder(413, {"ok": False, "erro": "Envie dados de até 12 MB."})

            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            nome = str(dados.get("nome", "")).strip()
            whatsapp = "".join(c for c in str(dados.get("whatsapp", "")) if c.isdigit())
            regiao = str(dados.get("regiao", "")).strip()
            servico = str(dados.get("servico", "")).strip()
            descricao = str(dados.get("descricao", "")).strip()
            fotos = dados.get("fotos", [])

            if not nome or not whatsapp or not regiao or not servico:
                return self.responder(400, {
                    "ok": False, "erro": "Preencha nome, WhatsApp, região e serviço."
                })
            if not isinstance(fotos, list) or len(fotos) > 4:
                return self.responder(400, {"ok": False, "erro": "Envie no máximo 4 fotos."})

            if any(not isinstance(f, str) or len(f) > 2_000_000 for f in fotos):
                return self.responder(400, {"ok": False, "erro": "Uma das fotos é muito grande."})

            with conectar() as db:
                cur = db.execute("""
                    INSERT INTO profissionais
                    (nome, whatsapp, regiao, servico, descricao, fotos, criado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome, whatsapp, regiao, servico, descricao,
                    json.dumps(fotos), datetime.now(timezone.utc).isoformat()
                ))
                novo_id = cur.lastrowid

            return self.responder(201, {
                "ok": True, "mensagem": "Profissional cadastrado no banco de dados.",
                "id": novo_id
            })
        except (ValueError, json.JSONDecodeError):
            return self.responder(400, {"ok": False, "erro": "Dados inválidos."})
        except Exception:
            return self.responder(500, {"ok": False, "erro": "Erro interno ao salvar."})

    def log_message(self, formato, *args):
        print("%s - %s" % (self.log_date_time_string(), formato % args))

print("ConectaPro API iniciada na porta 5000.")
print("Banco:", DB)
HTTPServer(("127.0.0.1", 5000), API).serve_forever()
