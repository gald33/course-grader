// The orders this app summarizes: three synthetic messages (not real
// customers) and how each one was read. Copied from the course's
// bakery-orders.json example.
var BAKERY_DATA = {
  products: {
    rolls: "לחמניות",
    cookies: "עוגיות"
  },
  orders: [
    {
      id: "m1",
      customer: "דנה",
      message: "דנה: למחר בשעה 09:00, ארבע לחמניות ושתי עוגיות.",
      pickup_day: "מחר",
      pickup_time: "09:00",
      items: [
        { product: "rolls", quantity: 4 },
        { product: "cookies", quantity: 2 }
      ]
    },
    {
      id: "m2",
      customer: "יואב",
      message: "יואב: למחר בשעה 10:00, שש לחמניות.",
      pickup_day: "מחר",
      pickup_time: "10:00",
      items: [{ product: "rolls", quantity: 6 }]
    },
    {
      id: "m3",
      customer: "מיכל",
      message: "מיכל: שלוש עוגיות למחר; שעת האיסוף עדיין לא סוכמה.",
      pickup_day: "מחר",
      pickup_time: null,
      items: [{ product: "cookies", quantity: 3 }]
    }
  ]
};

if (typeof module !== "undefined") module.exports = BAKERY_DATA;
