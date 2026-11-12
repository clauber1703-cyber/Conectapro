from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import os
import json
import sqlite3
import hmac
import hashlib
import secrets

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "index.html"
ADMIN_PAGE = ROOT / "frontend" / "admin.html"

POSTGRES = bool(os.environ.get("DATABASE_URL", "").strip())

if POSTGRES:
    import psycopg
    from psycopg.rows import dict_row
    DB = "Neon PostgreSQL"

    class ConexaoPostgres:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            return self.conn.execute(sql.replace("?", "%s"), params)

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, tipo, valor, traceback):
            return self.conn.__exit__(tipo, valor, traceback)

    def conectar():
        conn = psycopg.connect(
            os.environ["DATABASE_URL"],
            row_factory=dict_row
        )
        return ConexaoPostgres(conn)
else:
    DB = Path(os.environ.get(
        "DATABASE_PATH", str(ROOT / "data" / "conectapro.db")
    ))
    DB.parent.mkdir(parents=True, exist_ok=True)

    def conectar():
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        return conn

if POSTGRES:
    tabela_profissionais = """
        CREATE TABLE IF NOT EXISTS profissionais (
            id BIGSERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            whatsapp TEXT NOT NULL,
            regiao TEXT NOT NULL,
            servico TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            fotos TEXT DEFAULT '[]',
            criado_em TEXT NOT NULL
        )
    """
    tabela_pagamentos = """
        CREATE TABLE IF NOT EXISTS pagamentos (
            id BIGSERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            valor_centavos INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmado',
            confirmado_em TEXT NOT NULL
        )
    """
else:
    tabela_profissionais = """
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
    """
    tabela_pagamentos = """
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            valor_centavos INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmado',
            confirmado_em TEXT NOT NULL
        )
    """

with conectar() as db:
    db.execute(tabela_profissionais)
    db.execute(tabela_pagamentos)

with conectar() as db:
    if POSTGRES:
        db.execute("""
            ALTER TABLE profissionais
            ADD COLUMN IF NOT EXISTS status_pagamento
            TEXT NOT NULL DEFAULT 'pendente'
        """)
        db.execute("""
            ALTER TABLE profissionais
            ADD COLUMN IF NOT EXISTS pagamento_confirmado_em TEXT
        """)
    else:
        colunas = {
            linha["name"]
            for linha in db.execute("PRAGMA table_info(profissionais)")
        }
        if "status_pagamento" not in colunas:
            db.execute("""
                ALTER TABLE profissionais
                ADD COLUMN status_pagamento TEXT NOT NULL DEFAULT 'pendente'
            """)
        if "pagamento_confirmado_em" not in colunas:
            db.execute("""
                ALTER TABLE profissionais
                ADD COLUMN pagamento_confirmado_em TEXT
            """)


# TABELAS DE CONTAS E PEDIDOS CONECTAPRO
if POSTGRES:
    tabelas_novas = [
        """CREATE TABLE IF NOT EXISTS prestador_contas (
            id BIGSERIAL PRIMARY KEY,
            profissional_id BIGINT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS prestador_sessoes (
            token_hash TEXT PRIMARY KEY,
            profissional_id BIGINT NOT NULL,
            expira_em TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS pedidos (
            id BIGSERIAL PRIMARY KEY,
            cliente_nome TEXT NOT NULL,
            cliente_whatsapp TEXT NOT NULL,
            regiao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            fotos TEXT DEFAULT '[]',
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS pedidos_prestadores (
            id BIGSERIAL PRIMARY KEY,
            pedido_id BIGINT NOT NULL,
            profissional_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            atualizado_em TEXT NOT NULL,
            UNIQUE(pedido_id, profissional_id)
        )"""
    ]
else:
    tabelas_novas = [
        """CREATE TABLE IF NOT EXISTS prestador_contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profissional_id INTEGER NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS prestador_sessoes (
            token_hash TEXT PRIMARY KEY,
            profissional_id INTEGER NOT NULL,
            expira_em TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_nome TEXT NOT NULL,
            cliente_whatsapp TEXT NOT NULL,
            regiao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            fotos TEXT DEFAULT '[]',
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS pedidos_prestadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            profissional_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            atualizado_em TEXT NOT NULL,
            UNIQUE(pedido_id, profissional_id)
        )"""
    ]

with conectar() as db:
    for comando in tabelas_novas:
        db.execute(comando)
    db.execute("CREATE INDEX IF NOT EXISTS idx_pedidos_prestadores_profissional ON pedidos_prestadores(profissional_id)")


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


    def criar_hash_senha(self, senha):
        sal = secrets.token_bytes(16)
        chave = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), sal, 310000
        )
        return sal.hex() + "$" + chave.hex()

    def verificar_senha(self, senha, senha_hash):
        try:
            sal_hex, chave_hex = senha_hash.split("$", 1)
            sal = bytes.fromhex(sal_hex)
            chave = hashlib.pbkdf2_hmac(
                "sha256", senha.encode("utf-8"), sal, 310000
            )
            return hmac.compare_digest(chave.hex(), chave_hex)
        except (ValueError, TypeError):
            return False

    def prestador_autorizado(self):
        cabecalho = self.headers.get("Authorization", "")
        if not cabecalho.startswith("Bearer "):
            return None

        token = cabecalho[7:].strip()
        if not token:
            return None

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        agora = datetime.now(timezone.utc).isoformat()

        with conectar() as db:
            sessao = db.execute(
                "SELECT profissional_id, expira_em FROM prestador_sessoes WHERE token_hash = ?",
                (token_hash,)
            ).fetchone()

            if not sessao or sessao["expira_em"] <= agora:
                if sessao:
                    db.execute(
                        "DELETE FROM prestador_sessoes WHERE token_hash = ?",
                        (token_hash,)
                    )
                return None

            return sessao["profissional_id"]

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
                    "SELECT COUNT(*) AS total FROM profissionais"
                ).fetchone()["total"]
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
                profissionais_lista = db.execute("""
                    SELECT id, nome, whatsapp, servico, regiao,
                           status_pagamento, pagamento_confirmado_em
                    FROM profissionais ORDER BY id DESC
                """).fetchall()
            return self.responder(200, {
                "ok": True,
                "profissionais": total,
                "lista_profissionais": [dict(r) for r in profissionais_lista],
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

        if caminho not in ("/api/profissionais", "/api/admin/pagamentos", "/api/admin/profissionais/status", "/api/prestador/login"):
            return self.responder(404, {
                "ok": False, "erro": "Rota não encontrada"
            })

        if caminho in ("/api/admin/pagamentos", "/api/admin/profissionais/status"):
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

            if caminho == "/api/prestador/login":
                identificador = str(
                    dados.get("email") or dados.get("whatsapp") or ""
                ).strip()
                senha = str(dados.get("senha", ""))

                if not identificador or not senha:
                    return self.responder(400, {
                        "ok": False,
                        "erro": "Informe e-mail ou WhatsApp e senha."
                    })

                if "@" in identificador:
                    identificador = identificador.lower()
                    consulta = """
                        SELECT c.profissional_id, c.senha_hash, p.nome,
                               p.whatsapp, p.regiao, p.servico, p.status_pagamento
                        FROM prestador_contas c
                        JOIN profissionais p ON p.id = c.profissional_id
                        WHERE c.email = ?
                    """
                    parametro = identificador
                else:
                    telefone = "".join(
                        c for c in identificador if c.isdigit()
                    )
                    if len(telefone) in (10, 11):
                        telefone = "55" + telefone
                    elif len(telefone) not in (12, 13) or not telefone.startswith("55"):
                        return self.responder(400, {
                            "ok": False,
                            "erro": "Informe um WhatsApp válido com DDD."
                        })

                    consulta = """
                        SELECT c.profissional_id, c.senha_hash, p.nome,
                               p.whatsapp, p.regiao, p.servico, p.status_pagamento
                        FROM prestador_contas c
                        JOIN profissionais p ON p.id = c.profissional_id
                        WHERE p.whatsapp = ?
                    """
                    parametro = telefone

                with conectar() as db:
                    contas = db.execute(consulta, (parametro,)).fetchall()

                    conta = next(
                        (c for c in contas if self.verificar_senha(
                            senha, c["senha_hash"]
                        )),
                        None
                    )

                    if not conta:
                        return self.responder(401, {
                            "ok": False,
                            "erro": "E-mail/WhatsApp ou senha incorretos."
                        })

                    if str(conta["status_pagamento"] or "").lower() != "pago":
                        return self.responder(403, {
                            "ok": False,
                            "erro": "Pagamento pendente. Aguarde a confirmação do administrador."
                        })

                    token = secrets.token_urlsafe(32)
                    agora = datetime.now(timezone.utc)
                    db.execute("""
                        INSERT INTO prestador_sessoes
                        (token_hash, profissional_id, expira_em, criado_em)
                        VALUES (?, ?, ?, ?)
                    """, (
                        hashlib.sha256(token.encode("utf-8")).hexdigest(),
                        conta["profissional_id"],
                        (agora + timedelta(days=30)).isoformat(),
                        agora.isoformat()
                    ))

                return self.responder(200, {
                    "ok": True,
                    "token": token,
                    "prestador": {
                        "id": conta["profissional_id"],
                        "nome": conta["nome"],
                        "whatsapp": conta["whatsapp"],
                        "regiao": conta["regiao"],
                        "servico": conta["servico"],
                        "status_pagamento": conta["status_pagamento"]
                    }
                })

            if caminho == "/api/admin/profissionais/status":
                try:
                    pid = int(dados.get("id", 0))
                except (ValueError, TypeError):
                    return self.responder(400, {"ok": False, "erro": "ID inválido."})
                if dados.get("status") != "pago":
                    return self.responder(400, {"ok": False, "erro": "Status inválido."})
                agora = datetime.now(timezone.utc).isoformat()
                with conectar() as db:
                    prof = db.execute("SELECT nome, status_pagamento FROM profissionais WHERE id = ?", (pid,)).fetchone()
                    if not prof:
                        return self.responder(404, {"ok": False, "erro": "Profissional não encontrado."})
                    if prof["status_pagamento"] == "pago":
                        return self.responder(409, {"ok": False, "erro": "Pagamento já confirmado."})
                    db.execute("UPDATE profissionais SET status_pagamento='pago', pagamento_confirmado_em=? WHERE id=?", (agora, pid))
                    db.execute("INSERT INTO pagamentos (descricao, valor_centavos, status, confirmado_em) VALUES (?, 4990, 'confirmado', ?)", ("Mensalidade ConectaPro - " + prof["nome"], agora))
                return self.responder(200, {"ok": True, "mensagem": "Pix confirmado manualmente."})

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
                    if POSTGRES:
                        cur = db.execute("""
                            INSERT INTO pagamentos
                            (descricao, valor_centavos, status, confirmado_em)
                            VALUES (?, ?, 'confirmado', ?)
                            RETURNING id
                        """, (descricao, centavos, agora))
                        pagamento_id = cur.fetchone()["id"]
                    else:
                        cur = db.execute("""
                            INSERT INTO pagamentos
                            (descricao, valor_centavos, status, confirmado_em)
                            VALUES (?, ?, 'confirmado', ?)
                        """, (descricao, centavos, agora))
                        pagamento_id = cur.lastrowid

                return self.responder(201, {
                    "ok": True, "id": pagamento_id,
                    "mensagem": "Registro manual salvo como confirmado."
                })

            nome = str(dados.get("nome", "")).strip()
            whatsapp = "".join(
                c for c in str(dados.get("whatsapp", "")) if c.isdigit()
            )
            if len(whatsapp) in (10, 11):
                whatsapp = "55" + whatsapp
            elif len(whatsapp) not in (12, 13) or not whatsapp.startswith("55"):
                return self.responder(400, {
                    "ok": False,
                    "erro": "Informe o WhatsApp com DDD e código do Brasil (55)."
                })
            regiao = str(dados.get("regiao", "")).strip()
            servico = str(dados.get("servico", "")).strip()
            descricao = str(dados.get("descricao", "")).strip()
            fotos = dados.get("fotos", [])
            email = str(dados.get("email", "")).strip().lower()
            senha = str(dados.get("senha", ""))
            criar_conta = True

            if criar_conta and (
                "@" not in email or len(email) > 254 or
                len(senha) < 8 or len(senha) > 128
            ):
                return self.responder(400, {
                    "ok": False,
                    "erro": "Informe um e-mail válido e uma senha de 8 a 128 caracteres."
                })

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

                if criar_conta:
                    email_existente = db.execute(
                        "SELECT id FROM prestador_contas WHERE email = ?",
                        (email,)
                    ).fetchone()
                    if email_existente:
                        return self.responder(409, {
                            "ok": False, "erro": "Este e-mail já possui uma conta."
                        })

                if existente:
                    conta_existente = db.execute(
                        "SELECT id FROM prestador_contas WHERE profissional_id = ?",
                        (existente["id"],)
                    ).fetchone()
                    if conta_existente or criar_conta:
                        return self.responder(409, {
                            "ok": False,
                            "erro": "Este WhatsApp já está cadastrado. Entre em contato para recuperar o acesso."
                        })
                    perfil_id = existente["id"]
                    db.execute("""
                        UPDATE profissionais
                        SET nome=?, regiao=?, servico=?, descricao=?, fotos=?
                        WHERE id=?
                    """, (nome, regiao, servico, descricao,
                          json.dumps(fotos), perfil_id))
                    status, mensagem = 200, "Cadastro existente atualizado."
                else:
                    if POSTGRES:
                        cur = db.execute("""
                            INSERT INTO profissionais
                            (nome, whatsapp, regiao, servico, descricao, fotos, criado_em)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            RETURNING id
                        """, (nome, whatsapp, regiao, servico, descricao,
                              json.dumps(fotos),
                              datetime.now(timezone.utc).isoformat()))
                        perfil_id = cur.fetchone()["id"]
                    else:
                        cur = db.execute("""
                            INSERT INTO profissionais
                            (nome, whatsapp, regiao, servico, descricao, fotos, criado_em)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (nome, whatsapp, regiao, servico, descricao,
                              json.dumps(fotos),
                              datetime.now(timezone.utc).isoformat()))
                        perfil_id = cur.lastrowid

                    if criar_conta:
                        db.execute("""
                            INSERT INTO prestador_contas
                            (profissional_id, email, senha_hash, criado_em)
                            VALUES (?, ?, ?, ?)
                        """, (
                            perfil_id,
                            email,
                            self.criar_hash_senha(senha),
                            datetime.now(timezone.utc).isoformat()
                        ))

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
