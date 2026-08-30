/* Display formatting runtime.
   Preserve Tableau precision: split counts may be fractional, rates use two
   decimals and currency calculations retain cents. */
fmt = function(v, type, symbol="$" ){
  const n = Number(v || 0);
  if(type === "currency"){
    return symbol + n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }
  if(type === "percent") return n.toFixed(2) + "%";
  if(type === "number"){
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
  }
  return esc(v);
};
