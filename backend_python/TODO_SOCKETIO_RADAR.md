y# TODO_SOCKETIO_RADAR.md

## Sesi: perbaikan Flask-Socket.IO namespace /radar

- [ ] Investigasi error TypeError: handle_connect() takes 0 positional arguments but 1 was given
- [ ] Sesuaikan handler `@socketio.on('connect', namespace='/radar')` agar menerima argumen SID (atau parameter yang benar)
- [ ] Pastikan import `emit`, dan inisialisasi `socketio`/`app` sudah benar
- [ ] Pertahankan logic anti-fraud: validasi speed_kmh dan accuracy_m
- [ ] Pastikan inisialisasi server stabil dengan `async_mode='eventlet'`
- [ ] Update file `backend_python/main.py` dengan kode lengkap siap pakai
- [ ] (opsional) Jalankan sanity check sederhana/tes koneksi

