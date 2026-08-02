# TODO_SECURITY.md

## Phase A — Integrasi 7 modul agar sinkron & berjalan (sesuai repo saat ini)

### A1. Real-Time Communication (WebSockets /radar)
- [ ] Tambahkan auth payload (JWT/session token) saat connect namespace /radar.
- [ ] Terapkan rate limit konsisten pada event `update_location`.
- [ ] Tambahkan replay protection (client_time + sequence_no / window).
- [ ] Sinkronkan event payload antara Flutter dan backend.

### A2. Penyimpanan (kompresi foto Flutter sebelum upload)
- [ ] Tambahkan dependensi kompresi foto.
- [ ] Buat service kompresi + checksum sebelum upload.
- [ ] Tambahkan endpoint backend untuk verifikasi ukuran/checksum.

### A3. Peta & Navigasi (offline caching + polyline routing)
- [ ] Tambahkan tile caching untuk flutter_map.
- [ ] Tambahkan PolylineLayer dan update pergerakan kendaraan (debounced).
- [ ] Tambahkan endpoint backend untuk route polyline (validasi banned + signature).

### A4. Enkripsi End-to-End
- [ ] Buat crypto service Flutter (hybrid ECDH + AES-256-GCM) untuk chat/lelang.
- [ ] Buat backend key exchange endpoints (public keys / wrapped session keys).
- [ ] Ubah socket events untuk payload encrypted (opaque blob).

### A5. Deteksi Fake GPS / Mock Location
- [ ] Naikkan heuristik mock location menjadi risk scoring.
- [ ] Samakan skema response `fraud_detected` (risk_score + reasons + tindakan).
- [ ] Pastikan antifraud client menerima dan melakukan force logout/block.

### A6. Anti-Tamper & Root Detection
- [ ] Tambahkan plugin root/jailbreak detection di Flutter.
- [ ] Saat startup: panggil /register-device dengan integrity_signals.
- [ ] Enable R8/ProGuard hardening untuk Android.

### A7. API Rate Limiting (Anti-DDoS / anti-spam)
- [ ] Gunakan flask-limiter untuk REST endpoints sensitif (lelang, kyc, finance).
- [ ] Tambahkan global per-user throttling.
- [ ] Tambahkan security logging alert untuk investigasi.

## Phase B — Dokumen & Mekanisme “Sistem Keamanan Tingkat Tinggi”
- [ ] Menyusun dokumen arsitektur Anti-Fraud + Anti-Tamper + Self-Destruct yang terintegrasi dengan modul baru.
- [ ] Menetapkan skenario self-destruct (local wipe, disable access, token revoke, device blacklist, remote ban).
- [ ] Final check OWASP Mobile Top 10 mapping.

