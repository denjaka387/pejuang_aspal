import firebase_admin
print('OK:', firebase_admin.__version__)
from firebase_admin import credentials, firestore, messaging
print('All firebase_admin submodules OK')
