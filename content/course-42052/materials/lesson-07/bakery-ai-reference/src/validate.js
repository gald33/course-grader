// בודק את מה שחזר מהמודל: גם המבנה (סכימה) וגם כללי העסק.
// JSON תקין עדיין יכול להיות שגוי בתוכן – לכן הבדיקה כאן, בקוד שלנו.
const { MENU } = require("./schema");

const KEYS = ["customer", "items", "pickup_time", "needs_clarification"];

function validateOrder(order, inputText) {
  const errors = [];
  if (typeof order !== "object" || order === null || Array.isArray(order)) {
    return ["התשובה אינה אובייקט JSON"];
  }
  for (const key of Object.keys(order)) {
    if (!KEYS.includes(key)) errors.push(`שדה לא צפוי: ${key}`);
  }
  for (const key of KEYS) {
    if (!(key in order)) errors.push(`שדה חסר: ${key}`);
  }
  if (errors.length) return errors;

  if (typeof order.customer !== "string" || !order.customer.trim()) {
    errors.push("שם לקוח חסר");
  } else if (!inputText.includes(order.customer)) {
    errors.push(`השם "${order.customer}" לא מופיע בהודעה`);
  }
  if (!Array.isArray(order.items) || order.items.length === 0) {
    errors.push("אין פריטים בהזמנה");
  } else {
    for (const item of order.items) {
      if (!item || !MENU.includes(item.product)) {
        errors.push(`פריט שלא בתפריט: ${item && item.product}`);
      }
      if (!item || !Number.isInteger(item.quantity) || item.quantity <= 0) {
        errors.push(`כמות לא תקינה: ${item && item.quantity} (צריכה להיות מספר שלם גדול מ-0)`);
      }
    }
  }
  if (order.pickup_time === null) {
    if (order.needs_clarification !== true) errors.push("שעה חסרה, אבל needs_clarification אינו true");
  } else if (typeof order.pickup_time !== "string") {
    errors.push("pickup_time צריך להיות טקסט או null");
  } else if (!inputText.includes(order.pickup_time)) {
    errors.push(`השעה ${order.pickup_time} לא כתובה בהודעה – אסור להמציא שעה`);
  }
  if (typeof order.needs_clarification !== "boolean") errors.push("needs_clarification צריך להיות true או false");
  return errors;
}

module.exports = { validateOrder };
