from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit_aer import AerSimulator

# 3-битный S-BOX 
SBOX3 = [
    0xB & 0x7, 0x1 & 0x7, 0x9 & 0x7, 0x4 & 0x7,
    0xB & 0x7, 0xA & 0x7, 0xC & 0x7, 0x8 & 0x7,
]

MASK3 = 0x7
NUM_ROUNDS = 8
R = [1, 1, 1]


# УТИЛИТЫ 
def load3(qc, reg, val):
    for i in range(3):
        if (val >> i) & 1:
            qc.x(reg[i])


def rotl3(qc, reg, r):
    r %= 3
    if r == 0:
        return
    for _ in range(r):
        qc.swap(reg[0], reg[1])
        qc.swap(reg[1], reg[2])


def sbox3(qc, x, y):
    for v in range(8):
        bits = [(v >> i) & 1 for i in range(3)]
        for i in range(3):
            if bits[i] == 0:
                qc.x(x[i])
        out = SBOX3[v]
        for j in range(3):
            if (out >> j) & 1:
                qc.mcx(x[:], y[j])
        for i in range(3):
            if bits[i] == 0:
                qc.x(x[i])


def G3(qc, x, tmp, r):
    sbox3(qc, x, tmp)
    rotl3(qc, tmp, r)


def G3_uncompute(qc, x, tmp, r):
    rotl3(qc, tmp, (3 - r) % 3)
    sbox3(qc, x, tmp)


def add_mod3(qc, a, b):
    for i in range(3):
        qc.cx(b[i], a[i])


def sub_mod3(qc, a, b):
    for i in range(3):
        qc.cx(b[i], a[i])


# РАУНД
def round_func_3(qc, A, B, C, D, t1, t2, K, round_num):

    r1, r2, r3 = R
    
    # 1) b ← b ⊕ G(a ⊞ k)
    add_mod3(qc, A, K)
    G3(qc, A, t1, r1)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r1)
    sub_mod3(qc, A, K)

    # 2) c ^= G(d ⊞ k)
    add_mod3(qc, D, K)
    G3(qc, D, t1, r3)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r3)
    sub_mod3(qc, D, K)

    # 3) a -= G(b ⊞ k)
    add_mod3(qc, B, K)
    G3(qc, B, t1, r2)
    sub_mod3(qc, A, t1)
    G3_uncompute(qc, B, t1, r2)
    sub_mod3(qc, B, K)

    # 4) e = G(b ⊞ c ⊞ k) ⊕ i
    add_mod3(qc, B, t2)
    add_mod3(qc, C, t2)
    add_mod3(qc, K, t2)

    G3(qc, t2, t1, r3)
    if round_num & 1:
        qc.x(t1[0])
    if round_num & 2:
        qc.x(t1[1])
    if round_num & 4:
        qc.x(t1[2])

    # 5) b += e
    add_mod3(qc, B, t1)

    # 6) c -= e
    sub_mod3(qc, C, t1)

    # uncompute e
    G3_uncompute(qc, t2, t1, r3)
    sub_mod3(qc, K, t2)
    sub_mod3(qc, C, t2)
    sub_mod3(qc, B, t2)

    # 7) d += G(c ⊞ k)
    add_mod3(qc, C, K)
    G3(qc, C, t1, r2)
    add_mod3(qc, D, t1)
    G3_uncompute(qc, C, t1, r2)
    sub_mod3(qc, C, K)

    # 8) b ^= G(a ⊞ k)
    add_mod3(qc, A, K)
    G3(qc, A, t1, r3)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r3)
    sub_mod3(qc, A, K)

    # 9) c ^= G(d ⊞ k)
    add_mod3(qc, D, K)
    G3(qc, D, t1, r1)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r1)
    sub_mod3(qc, D, K)

    # 10–12 swaps
    for i in range(3):
        qc.swap(A[i], B[i])
        qc.swap(C[i], D[i])
        qc.swap(B[i], C[i])


#ПОСТРОЕНИЕ СХЕМЫ ШИФРОВАНИЯ
def build_encrypt_circuit_3(block, key3):
    A = QuantumRegister(3, "A")
    B = QuantumRegister(3, "B")
    C = QuantumRegister(3, "C")
    D = QuantumRegister(3, "D")
    t1 = QuantumRegister(3, "t1")
    t2 = QuantumRegister(3, "t2")
    K  = QuantumRegister(3, "K")

    qc = QuantumCircuit(A, B, C, D, t1, t2, K)

    load3(qc, A, (block >> 0) & MASK3)
    load3(qc, B, (block >> 3) & MASK3)
    load3(qc, C, (block >> 6) & MASK3)
    load3(qc, D, (block >> 9) & MASK3)
    load3(qc, K, key3 & MASK3)

    for i in range(NUM_ROUNDS):
        round_func_3(qc, A, B, C, D, t1, t2, K, i+1)

    return qc, (A, B, C, D)


#СИМУЛЯЦИЯ ШИФРОВАНИЯ
def simulate_encrypt(qc, A, B, C, D):
    out = ClassicalRegister(12, "out")
    qc.add_register(out)
    qc.measure(A[:] + B[:] + C[:] + D[:], out)

    sim = AerSimulator()
    res = sim.run(qc, shots=1).result()
    return int(list(res.get_counts().keys())[0], 2)


# ШИФРОВАНИЕ БЛОКА
def encrypt_block(block, key3):
    qc, (A, B, C, D) = build_encrypt_circuit_3(block, key3)
    return simulate_encrypt(qc, A, B, C, D)


#КВАНТОВОЕ РАСШИФРОВАНИЕ БЛОКА
def quantum_block_decrypt_3(block, key3):
    A = QuantumRegister(3, "A")
    B = QuantumRegister(3, "B")
    C = QuantumRegister(3, "C")
    D = QuantumRegister(3, "D")
    t1 = QuantumRegister(3, "t1")
    t2 = QuantumRegister(3, "t2")
    K  = QuantumRegister(3, "K")

    qc = QuantumCircuit(A, B, C, D, t1, t2, K)

    # загружаем шифртекст в регистры
    load3(qc, A, (block >> 0) & MASK3)
    load3(qc, B, (block >> 3) & MASK3)
    load3(qc, C, (block >> 6) & MASK3)
    load3(qc, D, (block >> 9) & MASK3)
    load3(qc, K, key3 & MASK3)

    # строим прямой раундовый оператор
    round_qc = QuantumCircuit(A, B, C, D, t1, t2, K)
    for i in range(NUM_ROUNDS):
        round_func_3(round_qc, A, B, C, D, t1, t2, K, i+1)

    # применяем обратный оператор
    qc.compose(round_qc.inverse(), inplace=True)

    out = ClassicalRegister(12, "out")
    qc.add_register(out)
    qc.measure(A[:] + B[:] + C[:] + D[:], out)

    sim = AerSimulator()
    res = sim.run(qc, shots=1).result()
    return int(list(res.get_counts().keys())[0], 2)


# АНАЛИЗ РЕСУРСОВ ОДНОГО БЛОКА
def analyze_circuit(qc):

    num_qubits = qc.num_qubits
    depth = qc.depth()
    size = qc.size()
    ops = qc.count_ops()
    
    return {
        "qubits": num_qubits,
        "depth": depth,
        "size": size,
        "ops": ops,
    }


def analyze_single_block(block, key3):
    qc, _ = build_encrypt_circuit_3(block, key3)
    qc2 = qc.copy()
    return analyze_circuit(qc2)


# РАБОТА С БЛОКАМИ 12 БИТ
def split_blocks_12(data):
    blocks = []
    while data:
        blocks.append(data & 0xFFF)
        data >>= 12
    blocks.reverse()
    return blocks


def join_blocks_12(blocks):
    result = 0
    for b in blocks:
        result = (result << 12) | (b & 0xFFF)
    return result


def split_last_block(data):
    bitlen = data.bit_length()
    tail = bitlen % 12
    if tail == 0:
        blocks = split_blocks_12(data)
        return blocks, 0, 0
    Xn = data & ((1 << tail) - 1)
    rest = data >> tail
    blocks = split_blocks_12(rest)
    return blocks, Xn, tail


# ШИФРОВАНИЕ СООБЩЕНИЯ
def encrypt_message(data, key3):
    blocks, Xn, tail = split_last_block(data)

    encrypted_blocks = []

    if tail == 0:
        for b in blocks:
            encrypted_blocks.append(encrypt_block(b, key3))
        return join_blocks_12(encrypted_blocks), 0

    if len(blocks) == 0:
        Xn_concat = Xn << (12 - tail)
        return encrypt_block(Xn_concat, key3), tail

    if len(blocks) > 1:
        for b in blocks[:-1]:
            encrypted_blocks.append(encrypt_block(b, key3))

    Xn_1 = blocks[-1]

    Yn_concat_r = encrypt_block(Xn_1, key3)

    Yn = Yn_concat_r >> (12 - tail)
    r_new = Yn_concat_r & ((1 << (12 - tail)) - 1)

    Xn_concat_r = (Xn << (12 - tail)) | r_new
    Yn_minus_1 = encrypt_block(Xn_concat_r, key3)

    encrypted_blocks.append(Yn_minus_1)
    encrypted_blocks.append(Yn)

    return join_blocks_12(encrypted_blocks), tail


#РАСШИФРОВАНИЕ СООБЩЕНИЯ
def decrypt_message(cipher, key3, tail):
    blocks = split_blocks_12(cipher)

    if tail == 0:
        dec = [quantum_block_decrypt_3(b, key3) for b in blocks]
        return join_blocks_12(dec)

    if len(blocks) == 1:
        Xn_concat = quantum_block_decrypt_3(blocks[0], key3)
        Xn = Xn_concat >> (12 - tail)
        return Xn

    Yn = blocks[-1]
    Yn_minus_1 = blocks[-2]

    Xn_concat_r = quantum_block_decrypt_3(Yn_minus_1, key3)
    Xn = Xn_concat_r >> (12 - tail)
    r_new = Xn_concat_r & ((1 << (12 - tail)) - 1)

    Yn_concat_r = (Yn << (12 - tail)) | r_new
    Xn_1 = quantum_block_decrypt_3(Yn_concat_r, key3)

    if len(blocks) > 2:
        dec_full = [quantum_block_decrypt_3(b, key3) for b in blocks[:-2]]
    else:
        dec_full = []

    dec_full.append(Xn_1)
    data_full = join_blocks_12(dec_full)

    data = (data_full << tail) | Xn
    return data


#ТЕСТ
def analyze():
    plaintext = 0xA54746483884FF
    key3 = 0x6

    print("Исходный:", hex(plaintext))

    cipher, tail = encrypt_message(plaintext, key3)
    print("Шифр:", hex(cipher))

    decrypted = decrypt_message(cipher, key3, tail)
    print("Расшифровка:", hex(decrypted))

    print("\n=== АНАЛИЗ ОДНОГО БЛОКА ===")
    first_block = split_blocks_12(plaintext)[0]
    res = analyze_single_block(first_block, key3)
    for k, v in res.items():
        print(f"{k}: {v}")

    if decrypted == plaintext:
        print("\nОбратимость подтверждена!")
    else:
        print("\nНЕСОВПАДЕНИЕ!")


if __name__ == "__main__":
    analyze()
