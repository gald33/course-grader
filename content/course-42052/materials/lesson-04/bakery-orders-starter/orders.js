// The calculations. Each function takes data and returns a result; none of
// them touches the page, so check.js can test them.

// How many of each product were ordered, for example { rolls: 10, cookies: 5 }.
function totalItems(orders) {
  var totals = {};
  orders.forEach(function (order) {
    order.items.forEach(function (item) {
      totals[item.product] = (totals[item.product] || 0) + item.quantity;
    });
  });
  return totals;
}

// The orders that still need an answer from the customer: no pickup time yet.
// The time is never guessed.
function missingPickupTime(orders) {
  return orders
    .filter(function (order) {
      return order.pickup_time === null;
    })
    .map(function (order) {
      return order.id;
    });
}

// Marks one order as ready for pickup. Returns true if it worked, false if
// there is no order with that id.
function markReady(orders, readyIds, orderId) {
  var exists = orders.some(function (order) {
    return order.id === orderId;
  });
  if (!exists) return false;
  readyIds[orderId] = true;
  return true;
}

if (typeof module !== "undefined") {
  module.exports = { totalItems: totalItems, missingPickupTime: missingPickupTime, markReady: markReady };
}
