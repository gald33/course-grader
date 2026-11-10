// החוזה: המבנה שהמודל מתבקש להחזיר (structured output), כ-JSON Schema.
const MENU = ["לחמניות", "עוגיות"];

const ORDER_SCHEMA = {
  type: "object",
  properties: {
    customer: { type: "string", description: "שם הלקוח/ה כפי שמופיע בהודעה" },
    items: {
      type: "array",
      minItems: 1,
      items: {
        type: "object",
        properties: {
          product: { type: "string", enum: MENU },
          quantity: { type: "integer" },
        },
        required: ["product", "quantity"],
        additionalProperties: false,
      },
    },
    pickup_time: {
      type: ["string", "null"],
      description: "שעת האיסוף בדיוק כפי שכתובה בהודעה (למשל 09:00), או null אם לא כתובה",
    },
    needs_clarification: { type: "boolean", description: "true אם חסר פרט שצריך לברר עם הלקוח/ה" },
  },
  required: ["customer", "items", "pickup_time", "needs_clarification"],
  additionalProperties: false,
};

module.exports = { MENU, ORDER_SCHEMA };
