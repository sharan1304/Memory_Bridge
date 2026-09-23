# Extra CA certificates

Drop PEM-encoded `*.crt` files here to have the backend image trust them.

Needed on networks with TLS inspection (e.g. corporate proxies such as Cisco
Secure Access / Zscaler), which re-sign HTTPS traffic from containers with
their own CA. Without it, pip, the Hugging Face model download and Qdrant
Cloud all fail with `CERTIFICATE_VERIFY_FAILED`.

`*.crt` files are gitignored - they are specific to your network. Rebuild the
image after adding one: `docker compose build backend`.
