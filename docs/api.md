# API Documentation

## Base URL

```
http://localhost:8000
```

FastAPI also auto-generates interactive docs at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## Endpoints

### Health Check

```
GET /health
```

**Response** `200 OK`
```json
{
  "status": "healthy",
  "database": "healthy",
  "cache": "healthy"
}
```

---

### Shorten URL

```
POST /api/shorten
```

**Request Body**
```json
{
  "url": "https://www.google.com",
  "custom_code": "goog"          // optional, 3-20 alphanumeric chars
}
```

**Response** `201 Created`
```json
{
  "id": 1,
  "short_code": "aB3xK9m",
  "original_url": "https://www.google.com",
  "short_url": "http://localhost:8000/aB3xK9m",
  "clicks": 0,
  "created_at": "2026-02-14T09:00:00Z",
  "updated_at": "2026-02-14T09:00:00Z"
}
```

**Errors**
| Status | Reason |
|---|---|
| `422` | Invalid URL or invalid custom code |
| `409` | Custom code already taken |

---

### Redirect

```
GET /:short_code
```

**Response** `307 Temporary Redirect`
- `Location` header set to the original URL.
- Click count is incremented.

**Errors**
| Status | Reason |
|---|---|
| `404` | Short code not found |

---

### Get URL Stats

```
GET /api/stats/:short_code
```

**Response** `200 OK`
```json
{
  "id": 1,
  "short_code": "aB3xK9m",
  "original_url": "https://www.google.com",
  "short_url": "http://localhost:8000/aB3xK9m",
  "clicks": 42,
  "created_at": "2026-02-14T09:00:00Z",
  "updated_at": "2026-02-14T10:30:00Z"
}
```

**Errors**
| Status | Reason |
|---|---|
| `404` | Short code not found |
