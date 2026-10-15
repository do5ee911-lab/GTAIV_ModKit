import hashlib
from Crypto.Cipher import AES

KEY_HEX = "1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d"
KEY_SHA1 = "DEA375EF1E6EF2223A1221C2C575C47BF17EFA5E"

KEY = bytes.fromhex(KEY_HEX)


def verify_key(key=KEY):
    return hashlib.sha1(key).hexdigest().upper() == KEY_SHA1


def crypt16(data, encrypt):
    if len(data) % 16 != 0:
        raise ValueError("data length must be a multiple of 16, got %d" % len(data))
    cipher = AES.new(KEY, AES.MODE_ECB)
    out = data
    for _ in range(16):
        out = cipher.encrypt(out) if encrypt else cipher.decrypt(out)
    return out


def decrypt(data):
    return crypt16(data, False)


def encrypt(data):
    return crypt16(data, True)
