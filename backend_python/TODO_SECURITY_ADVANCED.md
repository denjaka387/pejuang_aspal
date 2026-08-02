# Phase B — Dokumen Sistem Keamanan Tingkat Tinggi (Backend + Flutter)

> Target: meningkatkan keamanan terhadap penyadapan, manipulasi klien, penyamaran lokasi (Fake GPS/Mock Location), dan serangan volumetrik (DDoS/abuse) untuk REST + Socket.IO.

Dokumen ini adalah rancangan arsitektur implementasi (blueprint) yang dapat langsung diturunkan menjadi task engineering Phase B.

---

## 1) Ringkasan Arsitektur Keamanan

Komponen utama:

1. **E2E Encryption (Chat + Lelang/Order payload sensitif)**
   - Chat: *hybrid cryptosystem* (ECDH untuk key agreement + AES-256-GCM untuk payload terenkripsi).
   - Lelang/Order: enkripsi *per message/event* untuk data sensitif (mis. passenger_contact, detail rute, atau token lock).
   - Backend: bertindak sebagai relay/otorisator event, **tanpa membaca plaintext** payload yang terenkripsi.

2. **Anti-Tamper & Root Detection (Frontend Flutter + Build Hardening)**
   - Integrity signals dari aplikasi (root/jailbreak, emulator, tampering heuristics, attestation).
   - Obfuscation & hardening untuk Release build.
   - Proses registrasi device + binding fingerprint ke akun setelah KYC.

3. **Rate Limiting Lanjutan**
   - REST: flask-limiter per IP, per user_id, dan per endpoint (sensitive actions).
   - Socket.IO: rate limiting per `sid` + per event name + per user_id (jika tersedia), termasuk *burst control*.

4. **Self-Destruct / Auto-Banned**
   - Deteksi berulang Fake GPS/Root/tampering → *risk escalation*.
   - Backend otomatis:
     - ban akun (banned_until)
     - revoke token/session
     - blacklist fingerprint/device
     - audit-log & *progressive punishment*.

5. **Observability & Forensics**
   - Security event schema terstruktur.
   - Alerting berbasis anomali (rate limited, fraud, ban triggers).

---

## 2) Enkripsi End-to-End (E2E)

### 2.1 Prinsip Desain

- **Tidak ada plaintext sensitif** yang dikirim ke backend untuk channel yang dimaksud (chat dan data sensitif lelang).
- Backend hanya memverifikasi:
  - Identitas/otorisasi event (mis. user_id, room, token).
  - Validitas skema event (struktur blob, sequence, anti-replay).
- Semua crypto operation dilakukan di client (Flutter). Backend memegang **metadata minimal**:
  - key exchange public data (opsional)
  - `session_id`/`conversation_id`
  - `key_id` / `epoch`
  - `ciphertext` + `nonce` + `tag`

### 2.2 Skema Crypto yang Disarankan

#### A) Chat E2E: Hybrid ECDH + AES-256-GCM

- **ECDH**: gunakan kurva modern (contoh: X25519 atau P-256) untuk *key agreement*.
- **AES-256-GCM**: untuk enkripsi payload chat.

Workflow:

1. Client A dan Client B menghasilkan key pair:
   - `IK_A` (identity/static key pair)
   - `EK_A` (ephemeral key pair untuk sesi/conversation epoch)
2. Lakukan pertukaran *public keys* via backend endpoints / socket events.
3. Hitung shared secret `S = ECDH(EK_A_private, IK_B_public)` (atau varian dua sisi).
4. Derive *symmetric key* dengan KDF:
   - `K = HKDF(S, salt=conversation_epoch, info="chat-e2e-v1")`
5. Enkripsi payload:
   - plaintext = JSON chat message payload (mis. message_text, metadata minimal)
   - `AESGCM(K).encrypt(nonce, plaintext, aad)`
   - `aad` = binding metadata (conversation_id, sequence_no, sender_id) untuk mencegah mix-and-match.

Payload yang dikirim ke backend (opaque):

```json
{
  "conversation_id": "...",
  "sender_id": 123,
  "epoch": 7,
  "key_id": "...",
  "seq": 104,
  "aad": "(optional, atau dihitung oleh client)",
  "ciphertext": "base64(...)",
  "nonce": "base64(...)",
  "tag": "base64(...)"
}
```

Backend tidak perlu memahami isi ciphertext.

#### B) Lelang/Order E2E untuk data sensitif

Data yang berpotensi sensitif pada modul lelang:
- `passenger_contact`
- detail rute (apabila dianggap sensitif)
- token lock/transaction metadata

Rancangan:
- Enkripsi per event **menggunakan symmetric session key** yang dibentuk pada awal percakapan/entitas lelang.
- Alternatif: gunakan public key milik penerima (hybrid RSA-OAEP atau ECDH) untuk mengenkripsi *session key*.

Rekomendasi implementasi:
- Gunakan skema konsisten dengan chat (ECDH + AES-GCM) agar library crypto tidak terlalu kompleks.

### 2.3 Key Exchange dan Rotasi

- **Key exchange endpoints** (contoh):
  - `POST /e2e/keys/exchange` (REST)
  - atau `socket event: "e2e_key_announce"`
- Simpan key hanya sebagai public key & metadata (tanpa private key).
- **Rotasi keys**:
  - per `conversation_id`
  - per `epoch` (mis. tiap 24 jam atau N message)

### 2.4 Anti-Replay & Sequencing

- Setiap pihak menjaga `seq` monotonic per `conversation_id`.
- Backend memverifikasi:
  - `seq` numeric
  - `seq` dalam window toleransi (mis. window 50) per user/event.
- Client menolak replay berdasarkan cache `seen(seq)`.

### 2.5 Dampak pada Backend Saat Ini (Repo Saat Ini)

Saat ini backend sudah memiliki modul anti-fraud, rate limiter token bucket, dan socket namespaces (/radar, /chat, /sos, /walkie, /test).

Untuk Phase B:
- Tambahkan middleware/validator untuk:
  - skema payload terenkripsi (`ciphertext`, `nonce`, `key_id`, `seq`)
  - anti-replay tracking di backend (in-memory dulu, Redis untuk produksi)
- Untuk `/chat`:
  - menggantikan `message_text` plaintext → `message_blob`.
  - moderation: apabila moderation berbasis teks, perlu strategi:
    - opsi 1 (lebih aman): moderation di client sebelum enkripsi (tapi trust pada client)
    - opsi 2: *client-side redaction* untuk konten sensitif lalu server moderation atas field teredaksi
    - opsi 3: *homomorphic/secure enclave* (umumnya tidak realistis untuk MVP)

---

## 3) Anti-Tamper & Root Detection

### 3.1 Tujuan

- Menangkal aplikasi hasil reverse engineering / perangkat rooted.
- Mendeteksi tampering runtime (hooking, bypass jailbreak, mock location).
- Menghambat akses akun saat integrity fail terulang.

### 3.2 Arsitektur Integrity Signals

Saat ini backend sudah memiliki endpoint:
- `POST /anti-fraud/register-device`

Payload MVP saat ini (dari rancangan repo):
- `user_id`
- `fingerprint`
- `integrity_signals`: `is_rooted`, `app_tampered`, `mock_location_detected`

Rancangan Phase B:
- Tambah granularitas:
  - `is_emulator`
  - `is_debug_build`
  - `zygisk_magisk_detected`
  - `suspected_hooking_framework`
  - `play_integrity_status` (jika pakai Play Integrity API)

Contoh payload:

```json
{
  "user_id": 123,
  "fingerprint": "device-hash",
  "integrity_signals": {
    "is_rooted": false,
    "app_tampered": true,
    "mock_location_detected": false,
    "is_emulator": false,
    "is_debug_build": false,
    "hooking_detected": false,
    "attestation": {
      "provider": "play_integrity",
      "verdict": "MEETS_BASIC",
      "nonce": "..."
    }
  },
  "mock_location_signals": {
    "provider_mock_location": true,
    "developer_options_enabled": false
  }
}
```

### 3.3 Implementasi Frontend Flutter

Komponen yang disarankan:

1. **Root/Jailbreak Detection Plugin**
   - Integrasi plugin deteksi root/jailbreak yang sesuai Android.
   - Tambahkan `emulator detection`.

2. **App Tamper Detection**
   - Guard runtime:
     - deteksi debugger/hooking (heuristic)
     - deteksi modifikasi konfigurasi signature (lebih sulit di Flutter murni; butuh sisi native)

3. **Release Build Hardening**
   - Aktifkan:
     - **R8/ProGuard** untuk Android (minify + shrink + obfuscation)
     - konfigurasi `-dontwarn` secukupnya
   - Terapkan strategi *string obfuscation* untuk indikator fraud.

4. **Secure Storage & Token Handling**
   - Simpan token session di storage terenkripsi.
   - Pastikan token tidak disimpan plaintext.

5. **Startup Integrity Gate**
   - Saat startup:
     - kumpulkan `integrity_signals`
     - kirim ke `/anti-fraud/register-device`.
   - Jika response backend menyatakan `blocked=true` → app:
     - menutup akses layar sensitif
     - force logout / disable network actions.

### 3.4 Backend Binding dan Enforcement

Dari repo saat ini, backend sudah memiliki:
- `DeviceFingerprint` (model)
- `integrity_is_blocked()` dan set `user.banned_until` untuk 30 hari ketika blocked.

Phase B:
- Bungkus jadi policy engine yang mendukung escalation:
  - threshold berdasarkan kombinasi root + mock_location + tamper
  - progressive ban: 1 hari → 7 hari → 30 hari → permanent.

---

## 4) Proteksi API Rate Limiting Lanjutan (REST + Socket.IO)

### 4.1 Masalah yang Ada (Repo Saat Ini)

- REST saat ini: `flask-limiter` baseline ada (default 60/minute per IP) dengan storage `memory://`.
- Socket.IO saat ini: token bucket in-memory per `sid` (dan pada beberapa tempat memakai `RateLimiter.allow(f"radar:{request.sid}")`).

Kekurangan untuk Phase B:
- belum ada per-user/per-namespace yang ketat
- belum ada burst control & endpoint-specific policies
- in-memory limiter tidak tahan terhadap multi-instance

### 4.2 Strategi REST Rate Limiting

Gunakan flask-limiter dengan konfigurasi:

1. **Per endpoint**
   - Contoh:
     - `POST /anti-fraud/register-device`: 10/min per user_id dan 30/min per IP
     - `POST /kyc-success`: 10/min per user_id
     - `POST /orders`: 20/min per user_id + 100/min per IP
     - `GET /admin/*`: 1/min global + akses admin only

2. **Per user_id**
   - kunci berdasarkan `Authorization` token (sub/user_id) atau payload user_id.

3. **Burst + sustained**
   - sustained: mis. 60/minute
   - burst: mis. max 120 dalam 10 menit

4. **Fail-close pada sensitive endpoints**
   - bila limiter tidak bisa dijalankan (Redis down), tetapkan kebijakan:
     - dev: fail open
     - prod: fail closed (lebih aman)

### 4.3 Strategi Socket.IO Rate Limiting

Tambahkan rate limiter pada event handler:
- kunci: `namespace:event:user_id` atau `namespace:event:sid`

Event critical di repo:
- `/radar`: `update_location`
- `/chat`: `send_message`
- `/test`: bidding/take order stage update

Aturan yang direkomendasikan:

- **/radar:update_location**
  - per sid: 10 events/10s (contoh)
  - per user_id: 30 events/1 menit
  - deteksi pola spam (mis. repetisi timestamp atau lonjakan seq)

- **/chat:send_message**
  - per user_id: 5 message/10s
  - panjang message limit + schema validation

- **/test:order actions**
  - `driver_take_order`: 3 take/30s per user_id
  - `driver_stage_update`: 10 stage updates/2 menit
  - batasi stage update hanya untuk winner driver (sudah ada) + rate limit

### 4.4 Namespace-level Protection & DDoS

- Implementasi *connection throttling*:
  - Batasi jumlah connect simultan per IP/subnet.
- Tambahkan *max payload size* untuk event payload.
- Terapkan *circuit breaker* untuk namespace jika error rate meningkat.

---

## 5) Mekanisme Self-Destruct / Auto-Banned

### 5.1 Tujuan

Ketika terdeteksi pelanggaran Fake GPS/Root berulang:
- **Backend** melakukan blok permanen/berjenjang.
- Sesi token driver dihapus/revoke.
- Device fingerprint diblacklist.
- Mengurangi dampak biaya komputasi (rate limiter makin ketat untuk pelaku).

### 5.2 Model Risiko (Risk Scoring)

Saat ini sudah ada:
- `RadarNamespace` mendeteksi:
  - `accuracy_m > 80`
  - `mock_location_detected == true`
  - `speed_kmh > 200`
  - fraud speed check (implisit)
- jika terdeteksi: `user.mock_location_detected = True` dan `user.banned_until = now + 24h`.

Phase B:
- Ubah menjadi scoring berbasis event.

Contoh skema:
- root/tamper detected: +60
- mock_location_detected: +40
- accuracy too bad: +30
- implied speed too high: +50

Threshold:
- >= 50 → ban 24h
- >= 100 → ban 7d
- >= 140 → ban 30d
- >= 200 atau kombinasi 3+ insiden dalam 7 hari → permanent

### 5.3 Self-Destruct: Rencana Backend

Istilah “self-destruct” dalam konteks aplikasi driver biasanya berarti *remote wipe* dari akses/otorisasi.

Langkah backend yang disarankan:

1. **Revoke sessions/tokens**
   - Tambah tabel/collection `Session` atau `TokenRevocation`.
   - Set `revoked_at` dan `reason`.

2. **Permanent device blacklist**
   - `DeviceFingerprint.is_blocked = True`
   - Tambah `blocked_reason`, `blocked_at`.

3. **Progressive ban**
   - `User.banned_until` dan `User.banned_reason` diisi.
   - Simpan juga `risk_score_total` per periode.

4. **Remote enforcement pada socket**
   - Saat event `update_location` / `send_message` dicegah karena banned:
     - kirim event `ban_enforced`
     - server menutup koneksi jika memungkinkan.

5. **Auto-delete/disable sensitive resources**
   - Jika pelanggaran parah:
     - disable ability to create orders
     - hapus cache data sensitif di storage sementara (redis)

### 5.4 Desain Endpoint Administrasi & Otomasi

Backend otomatis seharusnya bekerja tanpa admin.
Namun untuk kontrol manual tetap disediakan.

Contoh endpoints admin yang ada:
- `POST /unban-driver/<int:user_id>` sudah ada.

Phase B: tambah endpoints internal:
- `POST /security/violations/{type}` untuk internal event ingestion.
- `POST /security/actions/ban` untuk menjalankan policy engine.

### 5.5 Integrasi dengan Fake GPS/Root yang Sudah Ada

Hook point yang sudah ada di repo:
- `/radar` saat `fraud_detected` → persist ban 24h
- `/anti-fraud/register-device` saat integrity fail → ban 30 hari dan set `is_active=False`

Phase B:
- Unifikasi menjadi satu `SecurityPolicyEngine`:
  - input: `user_id`, `violation_type`, `details`, `risk_delta`
  - output: ban duration, reason code, actions (revoke, blacklist)

---

## 6) Skema Logging Keamanan (Wajib)

Gunakan struktur event log agar bisa diaudit.

Contoh schema:

```json
{
  "ts": "2026-06-25T10:11:12Z",
  "event_type": "GEO_FRAUD",
  "namespace": "/radar",
  "user_id": 123,
  "device_fingerprint_id": 77,
  "risk_delta": 50,
  "risk_score_total": 120,
  "action": "ban",
  "banned_until": "2026-07-25T...Z",
  "reason_code": "implied_speed_too_high",
  "client_evidence": {"accuracy_m": 120, "speed_kmh": 230}
}
```

---

## 7) Mapping ke OWASP Mobile Top 10 (Ringkas)

Pemetaan fitur Phase B:

- **M1 / Improper Platform Usage**: Android Flutter hardening + integritas attestation.
- **M2 / Insecure Communication**: E2E encryption untuk chat/lelang.
- **M3 / Insecure Authentication**: session token revoke + device binding.
- **M5 / Insufficient Cryptography**: AES-GCM + ECDH hybrid.
- **M7 / Client Code Quality**: obfuscation + anti-tamper checks.
- **M8 / Code Tampering**: integrity_signals + release hardening.
- **M10 / Extraneous Functionality**: disable akses terhadap endpoints sensitif saat banned.

---

## 8) Checklist Implementasi (Tugas Teknik)

### A) E2E Encryption
- [ ] Definisikan format payload encrypted (ciphertext/nonce/tag/seq/epoch/key_id).
- [ ] Implement crypto service Flutter (ECDH + HKDF + AES-256-GCM).
- [ ] Implement key exchange handshake (REST atau socket).
- [ ] Update backend event validation agar menerima blob (tidak decode plaintext).
- [ ] Update clients chat/lelang untuk encrypt/decrypt.
- [ ] Anti-replay (seq/epoch) di backend + cache seen.

### B) Anti-Tamper & Root Detection
- [ ] Integrasikan plugin root/jailbreak/emulator detection.
- [ ] Tambahkan attestation (Play Integrity / SafetyNet fallback).
- [ ] Update register-device payload schema.
- [ ] Aktifkan R8/ProGuard hardening + obfuscation.
- [ ] Pastikan app menutup akses saat `blocked=true`.

### C) Rate Limiting Lanjutan
- [ ] Pindahkan storage limiter ke Redis (production).
- [ ] Buat kebijakan per endpoint & per user.
- [ ] Rate limit event socket berdasarkan event name + user_id/sid.
- [ ] Tambah connection throttling.

### D) Self-Destruct / Auto-Banned
- [ ] Implement SecurityPolicyEngine risk scoring.
- [ ] Implement token/session revoke mekanisme.
- [ ] Implement device blacklist persist.
- [ ] Terapkan progressive ban logic.
- [ ] Tambah event ban_enforced ke client.

---

## 9) Status Integrasi dengan Kode Saat Ini (Referensi Repo)

- `/radar` sudah memiliki fraud detection dan ban 24 jam:
  - `fake_gps_banned_24h` emit
- `/anti-fraud/register-device` sudah mendukung integrity_signals (root/tamper/mock flag) dan ban 30 hari.
- Rate limiter untuk Socket.IO event sudah menggunakan token bucket in-memory per `sid` (MVP).
- REST limiter baseline ada melalui flask-limiter dengan default limit 60/minute/IP (MVP).

Phase B akan:
- menyatukan policy engine,
- memperketat limiter,
- memperluas enforcement (revoke/blacklist),
- dan menambahkan E2E encryption.

---

## 10) Catatan Keamanan Penting (Trade-off)

- **Moderation vs E2E**: jika server perlu memoderasi konten teks, E2E akan menghambat server melihat plaintext. Pilih pendekatan (client moderation/redaction) atau moderation tanpa akses plaintext (lebih kompleks).
- **Device integrity signals** tidak 100% reliable: gunakan sebagai sinyal probabilistik + risk scoring, bukan satu-satunya penentu.
- **Replay/seq** harus dikelola hati-hati agar tidak memutus koneksi pengguna normal.

---

> Dokumen ini sengaja bersifat blueprint. Implementasi nyata harus mengikuti kebutuhan produk, performa, dan kepatuhan (privacy/security policy).
