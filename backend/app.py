from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FRONTEND = RAIZ / "frontend" / "index.html"
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(RAIZ / "data" / "conectapro.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Inicializar tabela de profissionais
with conectar() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS profissionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            regiao TEXT NOT NULL,
            servico TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            fotos TEXT,
            criado_em TEXT NOT NULL
        )
    """)

class API(BaseHTTPRequestHandler):
    def responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self):
        self.responder(200, {"ok": True})

    def do_GET(self):
        # Servir a página visual (frontend)
        if self.path == "/" or self.path == "/index.html":
            if not FRONTEND.exists():
                return self.responder(404, {"ok": False, "erro": "Ficheiro frontend/index.html não encontrado."})
            corpo = FRONTEND.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return

        # Rota de verificação de saúde
        if self.path == "/api/health":
            return self.responder(200, {"ok": True, "service": "ConectaPro API"})

        # Rota para listar os profissionais cadastrados
        if self.path == "/api/profissionais":
            with conectar() as db:
                linhas = db.execute("SELECT * FROM profissionais ORDER BY id DESC").fetchall()
                lista = []
                for linha in linhas:
                    item = dict(linha)
                    try:
                        item["fotos"] = json.loads(item["fotos"] or "[]")
                    except:
                        item["fotos"] = []
                    lista.append(item)
            return self.responder(200, {"ok": True, "total": len(lista), "profissionais": lista})

        return self.responder(404, {"ok": False, "erro": "Rota não encontrada"})

    def do_POST(self):
        # Rota para receber o cadastro de novos prestadores
        if self.path == "/api/profissionais":
            try:
                tamanho = int(self.headers.get("Content-Length", 0))
                dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
                
                nome = dados.get("nome", "").strip()
                whatsapp = dados.get("whatsapp", "").strip()
                regiao = dados.get("regiao", "").strip()
                servico = dados.get("servico", "").strip()
                descricao = dados.get("descricao", "").strip()
                fotos = dados.get("fotos", [])

                if not nome or not whatsapp or not regiao or not servico:
                    return self.responder(400, {"ok": False, "erro": "Preencha todos os campos obrigatórios."})

                with conectar() as db:
                    cur = db.execute(
                        "INSERT INTO profissionais (nome, whatsapp, regiao, servico, descricao, fotos, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (nome, whatsapp, regiao, servico, descricao, json.dumps(fotos), datetime.now(timezone.utc).isoformat())
                    )
                    perfil_id = cur.lastrowid
                
                return self.responder(201, {"ok": True, "mensagem": "Profissional cadastrado com sucesso!", "id": perfil_id})
            except Exception:
                return self.responder(500, {"ok": False, "erro": "Erro interno ao salvar o cadastro."})

        return self.responder(404, {"ok": False, "erro": "Rota não encontrada"})

    def log_message(self, formato, *args):
        return

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    print("ConectaPro API iniciada na porta", porta)
    ThreadingHTTPServer(("0.0.0.0", porta), API).serve_forever()
