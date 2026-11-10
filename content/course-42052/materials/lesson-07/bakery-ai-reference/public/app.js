// הדפדפן שולח רק את ההודעה לשרת שלנו. אין כאן מפתח ואין כאן קריאה ישירה ל-Gemini.
const form = document.getElementById("form");
const button = document.getElementById("send");
const status = document.getElementById("status");
const result = document.getElementById("result");
let busy = false;

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

function show(data) {
  result.replaceChildren();
  if (data.label) {
    const badge = document.createElement("p");
    badge.className = "badge";
    badge.textContent = data.label; // «הדגמה ללא מודל חי»
    result.append(badge);
  }
  if (data.ok) {
    const o = data.order;
    const table = document.createElement("table");
    for (const item of o.items) {
      const tr = document.createElement("tr");
      tr.append(cell(o.customer), cell(item.product), cell(String(item.quantity)), cell(o.pickup_time ?? "שעה חסרה – לבירור"));
      table.append(tr);
    }
    result.append(table);
    status.textContent = o.needs_clarification ? "ההזמנה סומנה לבירור." : "ההזמנה חולצה ונבדקה.";
    return;
  }
  const p = document.createElement("p");
  p.className = "error";
  p.textContent = data.errors ? `התשובה נדחתה: ${data.errors.join("; ")}` : data.error.message;
  result.append(p);
  status.textContent = data.attempts > 1 ? `נכשל אחרי ${data.attempts} ניסיונות.` : "נכשל.";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return; // אין שליחה כפולה
  busy = true;
  button.disabled = true;
  status.textContent = "מעבד… (זה יכול לקחת כמה שניות)";
  result.replaceChildren();
  try {
    const res = await fetch("/api/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: document.getElementById("message").value }),
    });
    show(await res.json());
  } catch {
    show({ ok: false, attempts: 1, error: { message: "אין חיבור לשרת. האם הוא רץ?" } });
  } finally {
    busy = false;
    button.disabled = false;
  }
});
