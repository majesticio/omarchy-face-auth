// Pure transition rules, also exercised without a live PAM service.
function transition(state, event) {
  if (event === "cancel" || event === "failure") return "idle";
  if (state === "idle" && event === "start") return "scanning";
  if (state === "scanning" && event === "success") return "authenticated";
  return state;
}

function mayUnlock(state, success, allowed) {
  return state === "scanning" && success && allowed;
}
