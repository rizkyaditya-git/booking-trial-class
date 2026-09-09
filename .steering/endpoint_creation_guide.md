# Endpoint creation guide

Use these rules when designing or reviewing public FastAPI endpoints in this repo. Define the contract before writing the handler: method, path, parameters, request model, success response, expected errors, authorization, and write-safety rules.

## Routes and methods

- Keep routes under `/v1`.
- Use lowercase path segments and hyphenated resource names, for example:
  - `/v1/health`
  - `/v1/trial-classes`
  - `/v1/trial-classes/{trialClassId}/bookings`
  - `/v1/bookings/{bookingId}`
- Do not add trailing-slash variants. Configure the app with `redirect_slashes=False` and test that a trailing slash returns `404`.
- Prefer nouns in paths. Add a verb only when the domain action cannot be represented as a resource or a state update.
- Do not add a new endpoint when an existing resource operation already expresses the same behavior.
- Do not send a request body with `GET` or `HEAD`.

| Method | Use it for | Required behavior |
| --- | --- | --- |
| `GET` | Read a resource or collection | Must not change application state. |
| `POST` | Create a server-named resource or start a non-idempotent operation | Return `201` for a completed creation, `200` for a completed action with a result, or `202` only for unfinished work. |
| `PUT` | Replace a resource at a known URI | Repeating the same request must have the same intended effect. Return `201` only when the contract allows creation. |
| `PATCH` | Apply a partial update | Distinguish omitted fields from fields explicitly set to `null`. Document whether retries are safe. |
| `DELETE` | Remove or deactivate a resource | Repeating the request must have the same intended effect. |

## Path and query parameters

- Path parameters use `camelCase` aliases in the public contract, for example `trialClassId`.
- Query parameters use `camelCase`, for example `pageSize`, `pageToken`, `status`, and `teacherId`.
- Do not expose public `snake_case` aliases for path or query parameters.
- Use a path parameter for resource identity and query parameters for filtering, sorting, pagination, or optional representation choices.
- Do not switch business actions with flags such as `?action=confirm` or body fields such as `operation: "cancel"`. Model a resource update or a clear domain action instead.
- Document every supported filter. Do not accept undocumented filters and silently ignore them.
- If a list endpoint pages, use `pageSize`, `pageToken`, and `nextPageToken`. Set a maximum page size, keep the token opaque, and use a stable ordering with a unique tie-breaker.

## Request and JSON contracts

- Keep internal Python fields `snake_case`.
- Public JSON keys must be `camelCase` for requests and responses.
- Define request bodies with Pydantic models. Do not accept an untyped `dict` at a public boundary.
- Reject unknown request fields unless the contract deliberately provides an extension object.
- Express required fields, nullability, length, range, and enum constraints in the model. Repeat checks in the database when they protect stored-data integrity.
- Treat omitted and `null` values as different states when processing `PATCH` requests.
- Accept timestamps with an explicit offset and store normalized UTC values. Return RFC 3339 timestamps.
- Do not accept client-supplied owners, roles, totals, or state derived from authenticated or server-owned data.
- Public enum, state, and status fields use documented semantic strings, not database IDs.
- Do not expose lookup-table primary keys as workflow intent unless the endpoint is a lookup endpoint.
- Backend services own the mapping from public state values to database foreign keys.
- Mutating endpoints validate the transitions allowed by that operation, even when the database contains more statuses.

## Success responses and status codes

Choose the status code that accurately describes the outcome. `async def` does not make an endpoint asynchronous from the client's perspective and is not a reason to return `202`.

| Status | Use it when | Contract requirement |
| --- | --- | --- |
| `200 OK` | The request finished and the client needs a result or current representation. | Return the standard success envelope. |
| `201 Created` | The request finished and created a resource. | Return the created representation and a `Location` header containing its canonical URI. |
| `202 Accepted` | The request was accepted but processing is still unfinished. | Return an operation resource with its current state and a `Location` header containing the URL the client can poll. The work must survive the request lifecycle. |
| `204 No Content` | The request finished and there is nothing useful to return. | Return no body. Do not return the success envelope. |
| `304 Not Modified` | A conditional read can reuse the client's cached representation. | Return no body. Do not return the success envelope. |

Choose between common write responses as follows:

- `POST` that creates a booking now: `201`.
- `POST` that queues work and returns before the outcome is known: `202`.
- `POST` that completes a domain action and returns its result: `200`.
- `PUT` or `PATCH` that returns the updated representation: `200`.
- `PUT`, `PATCH`, or `DELETE` that completes without a useful representation: `204`.

Successful responses with a body use:

```json
{
  "data": [],
  "meta": {}
}
```

- `data` is always an array.
- `meta` is always an object.
- A singleton response still contains one item in `data`.
- `204`, `304`, and `HEAD` responses have no body and are exceptions to the envelope rule.
- Do not return `200` with an error object in the body.

## Error responses

- Use `application/problem+json` for non-success responses.
- Do not wrap a Problem Details response in the success envelope.
- Keep exception translation centralized. Route handlers must not invent one-off error shapes.
- Include `type`, `title`, and `status`. Add `detail` and `instance` when they help identify or resolve the occurrence.
- Give each public problem a stable machine-readable type or error code. Keep extension field names stable and in `camelCase`. Clients must not need to parse `detail`.
- For validation failures, use a stable `errors` extension whose items identify the rejected field and explain the constraint.
- Keep `detail` useful to the caller, but never expose stack traces, SQL, credentials, tokens, or internal hostnames.

| Status | Use it when |
| --- | --- |
| `400 Bad Request` | The request violates an application or protocol rule that is not field validation. |
| `401 Unauthorized` | Authentication is missing or invalid. Include `WWW-Authenticate` when the authentication scheme requires it. |
| `403 Forbidden` | The caller is authenticated but cannot perform the operation. |
| `404 Not Found` | The resource does not exist, or policy requires hiding its existence from this caller. |
| `409 Conflict` | The request conflicts with current state, such as a duplicate booking, an invalid state transition, or losing the last-seat race. |
| `412 Precondition Failed` | An `If-Match` or other explicit HTTP precondition failed. |
| `415 Unsupported Media Type` | The request uses an unsupported content type. |
| `422 Unprocessable Content` | FastAPI or the domain understood the request format but field or business validation failed. |
| `429 Too Many Requests` | The caller exceeded an enforced limit. Include `Retry-After` when known. |
| `500 Internal Server Error` | An unexpected server defect occurred. Return only a sanitized problem response. |
| `503 Service Unavailable` | A required dependency or the service itself is temporarily unavailable. Include `Retry-After` when known. |

Do not use `404` for a known state conflict or `500` for an expected database constraint violation. Translate expected failures to the documented `4xx` response.

## Write safety, retries, and concurrency

- Keep the authoritative read, invariant check, and write in one database transaction.
- Enforce durable invariants with database constraints. API validation improves the error message but does not replace a unique, foreign-key, check, or capacity constraint.
- Prevent the last-seat race with a row lock, serializable transaction, or atomic conditional update. A count followed by an unrelated insert is not safe.
- Translate a duplicate booking or exhausted capacity to `409 Conflict`.
- Do not hold a database transaction open while calling a payment provider or another slow external service.
- Persist a payment attempt as a non-confirmed state. Move a booking to `confirmed` only after a verified success result. Confirmed rosters must read confirmed bookings only.
- Make retried `POST` operations safe when duplicates would charge money, consume capacity, or create multiple bookings. Require a persisted idempotency key scoped to the caller and operation.
- The same idempotency key and request must return the same logical result. Reject reuse of the key with a different request.
- Do not automatically retry a non-idempotent downstream call unless it has an idempotency guarantee.
- Use an `ETag` and require `If-Match` when concurrent edits could silently overwrite each other. Return `412` for a stale validator.

## FastAPI implementation

- Declare the primary `status_code` on every route decorator. Declare a `response_model` for every response that has a body; do not declare one for `204`.
- Declare every expected non-success response in `responses` so OpenAPI matches runtime behavior.
- Use response models for serialization, filtering, and validation. Return a raw `Response` only when the endpoint needs behavior the declared model cannot provide, such as `204`, streaming, or a file response.
- Use shared dependencies for authentication, authorization, database sessions, and repeated request validation.
- Use a `yield` dependency for request-scoped resources that require cleanup.
- Use FastAPI lifespan handling for shared resources such as connection pools. Do not create them during every request or as an import side effect.
- Use `async def` when the called libraries provide awaitable I/O. Use `def` for blocking I/O, or move that work to an explicit thread or process boundary. Never call blocking I/O directly inside an `async def` route.
- Keep route handlers focused on HTTP input and output. Put reusable business rules in plain functions or services, but do not add a layer that only forwards one call.
- Register routers through `app/main.py`.
- Use concise summaries and behavior-based route function names, such as `read_trial_classes` or `create_booking`.
- Add an explicit `operation_id` only when a generated client needs stable names.
- A `202` operation that must survive a process restart needs durable job state. In-process background work is not a durable queue.

## Security and caching

- When an endpoint is protected, authenticate and authorize on the server. Never rely on UI checks.
- Derive the current user and tenant from verified credentials, not request fields.
- Check authorization against the target resource, not only the route name or user role.
- Apply request-size limits and rate limits where abuse or accidental load would be costly.
- Do not put secrets or sensitive personal data in paths, query strings, logs, or error details.
- Set `Cache-Control` deliberately on `GET` responses. Use `no-store` for sensitive or user-specific data unless a reviewed cache policy says otherwise.
- Pass through or create a request ID and include it in structured logs and sanitized error diagnostics.

## Endpoint checks

Before treating an endpoint as complete, verify:

- the method, path, status codes, request model, and response models appear correctly in OpenAPI;
- public names use `camelCase` and the success body follows the envelope rule;
- `204`, `304`, and `HEAD` responses contain no body;
- validation, unauthenticated, forbidden, missing-resource, and expected-conflict paths return their documented Problem Details responses;
- a trailing slash returns `404`;
- transaction rollback leaves no partial write after a failure;
- duplicate and concurrent booking tests prove the database invariant, including two requests competing for one remaining seat;
- logs contain a request ID and do not contain secrets or raw payment data.

## Primary references

- [RFC 9110: HTTP Semantics](https://datatracker.ietf.org/doc/html/rfc9110)
- [RFC 9457: Problem Details for HTTP APIs](https://datatracker.ietf.org/doc/html/rfc9457)
- [FastAPI response status codes](https://fastapi.tiangolo.com/tutorial/response-status-code/)
- [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/)
- [FastAPI additional responses](https://fastapi.tiangolo.com/advanced/additional-responses/)
- [FastAPI concurrency and async](https://fastapi.tiangolo.com/async/)
- [FastAPI dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
