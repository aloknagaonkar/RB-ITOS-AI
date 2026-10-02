# Replay UI Untrusted Origin Same-Host Fix V1

The browser is loading the dashboard from an externally allowed VM host, while
the POST mutation guard only permits localhost origins. Browser POST requests
therefore get HTTP 403 with `Untrusted origin`.

This patch keeps the protection in place and permits browser POSTs only when the
Origin network location exactly matches the request Host header. Existing
localhost origins and originless CLI POSTs continue to work. Cross-host origins
remain rejected.
