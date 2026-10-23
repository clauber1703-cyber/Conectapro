from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import os
import json
import sqlite3
import hmac

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "index.html"
ADMIN_PAGE = ROOT / "frontend" / "admin.html"
DB = Path(os.environ.get("DATABASE_PATH", str(ROOT / "data" / "conectapro.db")))
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
    db.execute("""
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_centavos INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmado',
            confirmado_em TEXT NOT NULL
        )
    """)


class API(BaseHTTPRequestHandler):
    def responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def pagina(self, arquivo):
        if not arquivo.exists():
            return self.responder(500, {
                "ok": False, "erro": "Arquivo da página não encontrado."
            })
        corpo = arquivo.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def admin_autorizado(self):
        segredo = os.environ.get("ADMIN_TOKEN", "").strip()
        recebido = self.headers.get("Authorization", "")
        esperado = "Bearer " + segredo
        if not segredo:
            self.responder(503, {
                "ok": False,
                "erro": "ADMIN_TOKEN não configurado no servidor."
            })
            return False
        if not hmac.compare_digest(recebido, esperado):
            self.responder(401, {
                "ok": False, "erro": "Acesso administrativo não autorizado."
            })
            return False
        return True

    def do_OPTIONS(self):
        self.responder(200, {"ok": True})

    def do_GET(self):
        caminho = self.path.split("?", 1)[0]

        if caminho in ("/", "/index.html"):
            return self.pagina(FRONTEND)

        if caminho in ("/admin", "/admin.html"):
            return self.pagina(ADMIN_PAGE)

        if caminho == "/api/health":
            return self.responder(200, {
                "ok": True, "servico": "ConectaPro API"
            })

        if caminho == "/api/profissionais":
            with conectar() as db:
                linhas = db.execute(
                    "SELECT * FROM profissionais ORDER BY id DESC"
                ).fetchall()
            lista = []
            for linha in linhas:
                item = dict(linha)
                try:
                    item["fotos"] = json.loads(item["fotos"] or "[]")
                except (ValueError, TypeError):
                    item["fotos"] = []
                lista.append(item)
            return self.responder(200, {
                "ok": True, "total": len(lista), "profissionais": lista
            })

        if caminho == "/api/admin/dashboard":
            if not self.admin_autorizado():
                return
            limite = (datetime.now(timezone.utc) -
                      timedelta(hours=24)).isoformat()
            with conectar() as db:
                total = db.execute(
                    "SELECT COUNT(*) FROM profissionais"
                ).fetchone()[0]
                categorias = db.execute("""
                    SELECT servico, COUNT(*) AS total
                    FROM profissionais
                    GROUP BY servico ORDER BY total DESC, servico
                """).fetchall()
                pagamentos = db.execute("""
                    SELECT COUNT(*) AS quantidade,
                           COALESCE(SUM(valor_centavos), 0) AS total
                    FROM pagamentos
                    WHERE status = 'confirmado' AND confirmado_em >= ?
                """, (limite,)).fetchone()
            return self.responder(200, {
                "ok": True,
                "profissionais": total,
                "por_categoria": [
                    {"categoria": r["servico"], "total": r["total"]}
                    for r in categorias
                ],
                "clientes": None,
                "pedidos": None,
                "clientes_pedidos_aviso":
                    "Cadastro de clientes e envio de pedidos ainda não implementados.",
                "pagamentos_confirmados_24h": pagamentos["quantidade"],
                "faturamento_centavos_24h": pagamentos["total"]
            })

        self.responder(404, {"ok": False, "erro": "Rota não encontrada"})

    def do_POST(self):
        caminho = self.path.split("?", 1)[0]

        if caminho not in ("/api/profissionais", "/api/admin/pagamentos"):
            return self.responder(404, {
                "ok": False, "erro": "Rota não encontrada"
            })

        if caminho == "/api/admin/pagamentos":
            if not self.admin_autorizado():
                return

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if tamanho <= 0 or tamanho > 12 * 1024 * 1024:
                return self.responder(413, {
                    "ok": False, "erro": "Tamanho dos dados inválido."
                })
            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("Objeto inválido")

            if caminho == "/api/admin/pagamentos":
                descricao = str(dados.get("descricao", "")).strip()
                try:
                    valor = Decimal(str(dados.get("valor", "")))
                except InvalidOperation:
                    return self.responder(400, {
                        "ok": False, "erro": "Informe um valor válido."
                    })
                if not descricao or len(descricao) > 200:
                    return self.responder(400, {
                        "ok": False, "erro": "Informe a descrição do pagamento."
                    })
                if not valor.is_finite() or valor <= 0 or valor > Decimal("99999999"):
                    return self.responder(400, {
                        "ok": False, "erro": "O valor precisa ser maior que zero."
                    })
                centavos = int((valor * 100).quantize(Decimal("1")))
                agora = datetime.now(timezone.utc).isoformat()
                with conectar() as db:
                    cur = db.execute("""
                        INSERT INTO pagamentos
                        (descricao, valor_centavos, status, confirmado_em)
                        VALUES (?, ?, 'confirmado', ?)
                    """, (descricao, centavos, agora))
                return self.responder(201, {
                    "ok": True, "id": cur.lastrowid,
                    "mensagem": "Registro manual salvo como confirmado."
                })

            nome = str(dados.get("nome", "")).strip()
            whatsapp = "".join(
                c for c in str(dados.get("whatsapp", "")) if c.isdigit()
            )
            regiao = str(dados.get("regiao", "")).strip()
            servico = str(dados.get("servico", "")).strip()
            descricao = str(dados.get("descricao", "")).strip()
            fotos = dados.get("fotos", [])

            if not nome or not whatsapp or not regiao or not servico:
                return self.responder(400, {
                    "ok": False,
                    "erro": "Preencha nome, WhatsApp, região e serviço."
                })
            if not isinstance(fotos, list) or len(fotos) > 4:
                return self.responder(400, {
                    "ok": False, "erro": "Envie no máximo 4 fotos."
                })
            if any(not isinstance(f, str) or len(f) > 2_000_000 for f in fotos):
                return self.responder(400, {
                    "ok": False, "erro": "Uma das fotos é muito grande."
                })

            with conectar() as db:
                existente = db.execute(
                    "SELECT id FROM profissionais WHERE whatsapp = ? "
                    "ORDER BY id DESC LIMIT 1", (whatsapp,)
                ).fetchone()
                if existente:
                    perfil_id = existente["id"]
                    db.execute("""
                        UPDATE profissionais
                        SET nome=?, regiao=?, servico=?, descricao=?, fotos=?
                        WHERE id=?
                    """, (nome, regiao, servico, descricao,
                          json.dumps(fotos), perfil_id))
                    status, mensagem = 200, "Cadastro existente atualizado."
                else:
                    cur = db.execute("""
                        INSERT INTO profissionais
                        (nome, whatsapp, regiao, servico, descricao, fotos, criado_em)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (nome, whatsapp, regiao, servico, descricao,
                          json.dumps(fotos),
                          datetime.now(timezone.utc).isoformat()))
                    perfil_id = cur.lastrowid
                    status, mensagem = 201, "Profissional cadastrado no banco de dados."

            return self.responder(status, {
                "ok": True, "mensagem": mensagem, "id": perfil_id
            })

        except (ValueError, json.JSONDecodeError):
            return self.responder(400, {
                "ok": False, "erro": "Dados inválidos."
            })
        except Exception:
            return self.responder(500, {
                "ok": False, "erro": "Erro interno ao salvar."
            })

    def log_message(self, formato, *args):
        print("%s - %s" % (
            self.log_date_time_string(), formato % args
        ))


porta = int(os.environ.get("PORT", "5000"))
print("ConectaPro API iniciada na porta", porta)
print("Banco:", DB)
ThreadingHTTPServer(("0.0.0.0", porta), API).serve_forever()
