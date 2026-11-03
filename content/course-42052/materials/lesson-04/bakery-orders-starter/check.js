// Run the checks in a terminal:  node check.js
var data = require("./data.js");
var lib = require("./orders.js");
var runChecks = require("./checks.js");

console.log("Checking the bakery order summary...");
var result = runChecks(data, lib);
result.lines.forEach(function (line) {
  console.log(line);
});
process.exitCode = result.passed === result.total ? 0 : 1;
