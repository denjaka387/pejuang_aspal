# TODO_PHASE_A (Phase A - Security)

## Step 1: Rate Limiting + socket stability
- [ ] Implement flask-limiter initialization helper (if not already).
- [ ] Wire flask-limiter into app factory and apply to REST endpoints via decorators (lelang, kyc, admin, anti-fraud).
- [ ] Add socket-level throttle to update_location (already exists) and align message schema.
- [ ] Migrate runtime from eventlet/threading to a stable production setup:
  - [ ] Update entrypoint main.py to use eventlet/gevent correctly with monkey-patching OR
  - [ ] Ensure SocketIO uses async_mode that matches server (gunicorn+gevent).

## Step 2: Fake GPS / Coordinate validation
- [ ] Add/adjust function in backend_python/main.py:
  - [ ] validate koordinat + timestamp + delta-speed logic.
  - [ ] If speed not logical -> emit `fraud_detected` event to client.
- [ ] Ensure logic is actually used by radar socket update_location path.

## Step 3: Frontend handling for `fraud_detected`
- [ ] In frontend_flutter radar screen/service:
  - [ ] Listen to `fraud_detected`.
  - [ ] Show popup warning.
  - [ ] Lock access to main features until user is unblocked.

## Step 4: Testing
- [ ] Smoke test backend websocket update_location + fraud detection.
- [ ] Flutter: verify popup + locked UI when fraud_detected emitted.

