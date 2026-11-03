// The checks, shared by check.js (in a terminal) and check.html (in a
// browser). Each one runs a calculation from orders.js and compares the
// result with the answer worked out by hand.
function runChecks(data, lib) {
  var lines = [];
  var passed = 0;
  var checks = [
    ["total rolls = 10", function () {
      return lib.totalItems(data.orders).rolls === 10;
    }],
    ["total cookies = 5", function () {
      return lib.totalItems(data.orders).cookies === 5;
    }],
    ["missing pickup time: m3 only", function () {
      return lib.missingPickupTime(data.orders).join(",") === "m3";
    }],
    ["order m1 can be marked ready", function () {
      var ready = {};
      return lib.markReady(data.orders, ready, "m1") === true && ready.m1 === true;
    }],
    ["an order that does not exist is not marked", function () {
      var ready = {};
      return lib.markReady(data.orders, ready, "m9") === false && !ready.m9;
    }]
  ];
  checks.forEach(function (check) {
    var ok = false;
    try {
      ok = check[1]() === true;
    } catch (err) {
      ok = false;
    }
    if (ok) passed += 1;
    lines.push((ok ? "PASS " : "FAIL ") + check[0]);
  });
  lines.push(passed + " of " + checks.length + " checks passed");
  return { lines: lines, passed: passed, total: checks.length };
}

if (typeof module !== "undefined") module.exports = runChecks;
