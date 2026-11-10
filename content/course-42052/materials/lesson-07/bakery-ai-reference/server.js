// שרת קטן: מגיש את הממשק ומקבל הודעה ב-POST /api/order.
// רק כאן, בצד השרת, יש גישה למפתח (מתוך .env).
const http = require("http");
const fs = require("fs");
const path = require("path");
const { loadEnv } = require("./src/env");

loadEnv();
const { extractOrder, settings } = require("./src/extract");

const PORT = Number(process.env.PORT) || 3000;
const FILES = { "/": "index.html", "/app.js": "app.js" };
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8" };

function send(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && FILES[req.url]) {
    const file = path.join(__dirname, "public", FILES[req.url]);
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] });
    fs.createReadStream(file).pipe(res);
    return;
  }
  if (req.method === "POST" && req.url === "/api/order") {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 10000) req.destroy();
    });
    req.on("end", async () => {
      let message = "";
      try {
        message = String(JSON.parse(body).message || "").trim();
      } catch {
        return send(res, 400, { ok: false, error: { kind: "bad_request", message: "בקשה לא תקינה" } });
      }
      if (!message || message.length > 2000) {
        return send(res, 400, { ok: false, error: { kind: "bad_request", message: "כתבו הודעה (עד 2000 תווים)" } });
      }
      send(res, 200, await extractOrder(message));
    });
    return;
  }
  send(res, 404, { ok: false, error: { kind: "not_found", message: "לא נמצא" } });
});

server.listen(PORT, () => {
  const s = settings();
  const mode = s.mode === "mock" ? "mock (הדגמה ללא מודל חי)" : `live (${s.model})`;
  console.log(`http://localhost:${PORT}  mode: ${mode}${s.forceError ? `  AI_FORCE_ERROR=${s.forceError}` : ""}`);
});
