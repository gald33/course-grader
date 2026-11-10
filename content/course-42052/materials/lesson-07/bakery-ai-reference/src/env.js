// טוען הגדרות מקובץ .env (אם יש) אל process.env, בצד השרת בלבד.
// משתנה שכבר הוגדר בסביבה לא נדרס.
const fs = require("fs");
const path = require("path");

function loadEnv(file = path.join(__dirname, "..", ".env")) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (match && process.env[match[1]] === undefined) process.env[match[1]] = match[2];
  }
}

module.exports = { loadEnv };
