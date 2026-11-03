// Draws the page: the orders, the totals and what is still missing.
var readyIds = {};

function render() {
  var data = BAKERY_DATA;
  var list = document.getElementById("orders");
  list.innerHTML = "";
  data.orders.forEach(function (order) {
    var row = document.createElement("li");
    row.className = readyIds[order.id] ? "order ready" : "order";

    var text = document.createElement("p");
    text.textContent = order.message;
    row.appendChild(text);

    var items = order.items
      .map(function (item) {
        return item.quantity + " " + data.products[item.product];
      })
      .join(", ");
    var details = document.createElement("p");
    details.className = "details";
    details.textContent =
      "איסוף: " + order.pickup_day + (order.pickup_time ? " בשעה " + order.pickup_time : "") + " · " + items;
    row.appendChild(details);

    if (order.pickup_time === null) {
      var warning = document.createElement("p");
      warning.className = "warning";
      warning.textContent = "⚠ חסרה שעת איסוף – צריך לברר עם " + order.customer + ".";
      row.appendChild(warning);
    }

    var button = document.createElement("button");
    button.type = "button";
    button.textContent = readyIds[order.id] ? "✓ מוכנה" : "סימון כמוכנה";
    button.disabled = !!readyIds[order.id];
    button.addEventListener("click", function () {
      if (markReady(data.orders, readyIds, order.id)) {
        render();
      }
    });
    row.appendChild(button);
    list.appendChild(row);
  });

  var totals = totalItems(data.orders);
  document.getElementById("totals").textContent = Object.keys(totals)
    .map(function (product) {
      return data.products[product] + ": " + totals[product];
    })
    .join(" · ");

  var missing = missingPickupTime(data.orders);
  document.getElementById("missing").textContent = missing.length
    ? "הזמנות בלי שעת איסוף: " + missing.length
    : "לכל ההזמנות יש שעת איסוף.";
}

render();
