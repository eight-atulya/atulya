# Nginx Reverse Proxy with Custom Base Path

Deploy Atulya API under `/atulya` (or any custom path) using Nginx reverse proxy.

## Quick Start (Published Image - API Only)

```bash
docker-compose up
```

- **API:** http://localhost:8080/atulya/docs
- **Control Plane:** http://localhost:9999 (direct access, not proxied)

## Full Stack with Custom Base Path (Requires Build)

**Important:** You cannot rebuild from the published image with build args. You must build from source.

### Build from Source with Custom Base Path

1. **Clone the repository** (if you haven't):
```bash
git clone https://github.com/eight-atulya/atulya.git
cd atulya
```

2. **Build with base path**:
```bash
docker build \
  --build-arg NEXT_PUBLIC_BASE_PATH=/atulya \
  -f docker/standalone/Dockerfile \
  -t atulya:custom \
  .
```

3. **Update docker-compose.yml** to use your built image:
```yaml
services:
  atulya:
    image: atulya:custom  # ← Change this
    environment:
      ATULYA_API_BASE_PATH: /atulya
      NEXT_PUBLIC_BASE_PATH: /atulya
```

4. **Update nginx.conf** to handle Control Plane routes (see below)

5. **Run**:
```bash
docker-compose up
```

### Required nginx.conf for Full Stack

Replace the current `nginx.conf` with this to proxy both API and Control Plane:

```nginx
events { worker_connections 1024; }

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    upstream atulya_api { server atulya:8888; }
    upstream atulya_cp { server atulya:9999; }

    server {
        listen 80;

        # API
        location ~ ^/atulya/(docs|openapi\.json|health|metrics|v1|mcp) {
            proxy_pass http://atulya_api;
            proxy_set_header Host $http_host;
        }

        # Control Plane static files
        location ~ ^/atulya/_next/ {
            proxy_pass http://atulya_cp;
            proxy_set_header Host $http_host;
        }

        # Control Plane UI
        location /atulya {
            proxy_pass http://atulya_cp;
            proxy_set_header Host $http_host;
        }

        location = / { return 301 /atulya; }
    }
}
```

### Why Build is Required

Next.js requires `basePath` at **build time**. The published image was built without a custom base path, so you must rebuild from source with the `NEXT_PUBLIC_BASE_PATH` build arg to deploy the Control Plane under a subpath.

The API works without rebuild because `ATULYA_API_BASE_PATH` is a runtime environment variable.
