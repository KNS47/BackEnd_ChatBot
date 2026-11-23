const localHosts = ["localhost", "127.0.0.1", "[::1]"];
window.API_BASE = localHosts.includes(window.location.hostname) && window.location.port === "5173"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin;
