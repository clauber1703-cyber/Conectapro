from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os

class API(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "app": "ConectaPro"}')

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 10000))
    print("ConectaPro API iniciada na porta", porta)
    print("Banco: Ativo")
    ThreadingHTTPServer(("0.0.0.0", porta), API).serve_forever()
