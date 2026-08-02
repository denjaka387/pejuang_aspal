import firebase_admin
from firebase_admin import credentials, firestore

# Memuat kredensial dari file JSON yang telah diunduh
# Pastikan file JSON-mu sudah dipindah ke dalam folder backend_python
# dan bernama 'firebase_key.json' (sesuaikan jika namanya berbeda)
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)

# Menginisialisasi koneksi ke Firestore
db = firestore.client()

print("Koneksi ke Firebase berhasil, Jo!")

# Uji coba menambah data dummy ke Firestore
def test_add_data():
    doc_ref = db.collection("users_test").document("driver_001")
    doc_ref.set({
        "full_name": "Pejuang Aspal Dummy",
        "whatsapp_number": "08153024711`",
        "vehicle_type": "motor"
    })
    print("Data tes berhasil ditambahkan ke Firestore!")

if __name__ == "__main__":
    test_add_data()