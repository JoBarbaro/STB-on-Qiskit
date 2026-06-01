from qiskit import (
    QuantumCircuit,
    QuantumRegister,
    ClassicalRegister,
    transpile
)

from qiskit_aer import AerSimulator

from copy import deepcopy

import time
import psutil
import os

from typing import Dict, Optional

# ПАРАМЕТРЫ

SBOX3 = [0xB & 0x7, 0x1 & 0x7, 0x9 & 0x7, 0x4 & 0x7,
    0xB & 0x7, 0xA & 0x7, 0xC & 0x7, 0x8 & 0x7,
]

MASK3 = 0x7

NUM_ROUNDS = 8

R = [1, 1, 1]


# КЭШ СХЕМ

ROUNDS_CACHE: Dict[str, Optional[QuantumCircuit]] = {
    "encrypt": None,
    "decrypt": None
}


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

    # 1
    add_mod3(qc, A, K)
    G3(qc, A, t1, r1)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r1)
    sub_mod3(qc, A, K)

    # 2
    add_mod3(qc, D, K)
    G3(qc, D, t1, r3)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r3)
    sub_mod3(qc, D, K)

    # 3
    add_mod3(qc, B, K)
    G3(qc, B, t1, r2)
    sub_mod3(qc, A, t1)
    G3_uncompute(qc, B, t1, r2)
    sub_mod3(qc, B, K)

    # 4
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

    # 5
    add_mod3(qc, B, t1)

    # 6
    sub_mod3(qc, C, t1)
    G3_uncompute(qc, t2, t1, r3)
    sub_mod3(qc, K, t2)
    sub_mod3(qc, C, t2)
    sub_mod3(qc, B, t2)

    # 7
    add_mod3(qc, C, K)
    G3(qc, C, t1, r2)
    add_mod3(qc, D, t1)
    G3_uncompute(qc, C, t1, r2)
    sub_mod3(qc, C, K)

    # 8
    add_mod3(qc, A, K)
    G3(qc, A, t1, r3)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r3)
    sub_mod3(qc, A, K)

    # 9
    add_mod3(qc, D, K)
    G3(qc, D, t1, r1)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r1)
    sub_mod3(qc, D, K)
    
    # swaps
    for i in range(3):

        qc.swap(A[i], B[i])
        qc.swap(C[i], D[i])
        qc.swap(B[i], C[i])


# ПОСТРОЕНИЕ 

def build_rounds(mode="encrypt"):

    A = QuantumRegister(3, "A")
    B = QuantumRegister(3, "B")
    C = QuantumRegister(3, "C")
    D = QuantumRegister(3, "D")

    t1 = QuantumRegister(3, "t1")
    t2 = QuantumRegister(3, "t2")

    K = QuantumRegister(3, "K")

    qc = QuantumCircuit(A,B,C,D,t1,t2,K
    )

    for i in range(NUM_ROUNDS):
        round_func_3(qc,A,B,C,D,t1,t2,K,i + 1
        )

    if mode == "decrypt":
        qc = qc.inverse()

    return qc


# КЭШ


def get_cached_rounds(mode) -> QuantumCircuit:
    global ROUNDS_CACHE
    if ROUNDS_CACHE[mode] is None:
        ROUNDS_CACHE[mode] = build_rounds(mode)

    return ROUNDS_CACHE[mode]  # type: ignore


# ПОДГОТОВКА ПОЛНОЙ СХЕМЫ=

def prepare_circuit(block, key3, mode):

    rounds = get_cached_rounds(mode)

    A = QuantumRegister(3, "A")
    B = QuantumRegister(3, "B")
    C = QuantumRegister(3, "C")
    D = QuantumRegister(3, "D")

    t1 = QuantumRegister(3, "t1")
    t2 = QuantumRegister(3, "t2")

    K = QuantumRegister(3, "K")

    out = ClassicalRegister(12, "out")

    qc = QuantumCircuit(A, B, C,D,t1,t2,K,out
    )

    # Загрузка данных
    load3(qc, A, (block >> 0) & MASK3)
    load3(qc, B, (block >> 3) & MASK3)
    load3(qc, C, (block >> 6) & MASK3)
    load3(qc, D, (block >> 9) & MASK3)

    load3(qc, K, key3 & MASK3)

    # Подключаем готовую round-схему
    qc.compose(rounds, inplace=True)

    # Измерение
    qubits = list(A) + list(B) + list(C) + list(D)

    qc.measure(qubits, list(out))

    return qc

# ЗАПУСК

SIM = AerSimulator()


def run_circuit(block, key3, mode="encrypt", shots=1):

    qc = prepare_circuit(block, key3, mode)
    tqc = transpile(qc, SIM)
    result = SIM.run(
        tqc,
        shots=shots
    ).result()

    counts = result.get_counts()
    best = max(counts, key=counts.get)

    return int(best, 2)


# API


def encrypt_block(block, key3):

    return run_circuit(
        block,
        key3,
        mode="encrypt"
    )


def decrypt_block(block, key3):

    return run_circuit(
        block,
        key3,
        mode="decrypt"
    )


# РАБОТА С 12-БИТНЫМИ БЛОКАМИ 
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


def xor_block_12(a, b):
    return (a ^ b) & 0xFFF


def split_bits(data, block_size, total_bits):

    bits = total_bits
    blocks = []
    while bits > 0:
        take = min(block_size, bits)
        block = (data >> (bits - take)) & ((1 << take) - 1)
        blocks.append((block, take))
        bits -= take
    return blocks

def join_bits(blocks):
    
    out = 0
    for val, ln in blocks:
        out = (out << ln) | val
    return out


# ECB 
def encrypt_ecb(data, key3):
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
def decrypt_ecb(cipher, key3, tail):
    blocks = split_blocks_12(cipher)

    if tail == 0:
        dec = [decrypt_block(b, key3) for b in blocks]
        return join_blocks_12(dec)

    if len(blocks) == 1:
        Xn_concat = decrypt_block(blocks[0], key3)
        Xn = Xn_concat >> (12 - tail)
        return Xn

    Yn = blocks[-1]
    Yn_minus_1 = blocks[-2]

    Xn_concat_r = decrypt_block(Yn_minus_1, key3)
    Xn = Xn_concat_r >> (12 - tail)
    r_new = Xn_concat_r & ((1 << (12 - tail)) - 1)

    Yn_concat_r = (Yn << (12 - tail)) | r_new
    Xn_1 = decrypt_block(Yn_concat_r, key3)

    if len(blocks) > 2:
        dec_full = [decrypt_block(b, key3) for b in blocks[:-2]]
    else:
        dec_full = []

    dec_full.append(Xn_1)
    data_full = join_blocks_12(dec_full)

    data = (data_full << tail) | Xn
    return data


# CBC 
def encrypt_cbc(plaintext, key3, iv):
    
    blocks, Xn, tail = split_last_block(plaintext)
    
    prev = iv & 0xFFF
    encrypted_blocks = []
    
    # Случай 1: все блоки полные
    if tail == 0:
        for b in blocks:
            x = b ^ prev
            c = encrypt_block(x, key3)
            encrypted_blocks.append(c)
            prev = c
        return join_blocks_12(encrypted_blocks), 0
    
    # Случай 2: только один неполный блок
    if len(blocks) == 0:
        Xn_concat = Xn << (12 - tail)
        x = Xn_concat ^ prev
        c = encrypt_block(x, key3)
        return c, tail
    
    # Случай 3: CTS (2+ блоков)
    # Шифруем все полные блоки, кроме последнего
    for b in blocks[:-1]:
        x = b ^ prev
        c = encrypt_block(x, key3)
        encrypted_blocks.append(c)
        prev = c
    
    Xn_1 = blocks[-1]  # последний полный блок
    
    # Шифруем Xn_1
    tmp = encrypt_block(Xn_1 ^ prev, key3)
    
    Yn = tmp >> (12 - tail)
    r = tmp & ((1 << (12 - tail)) - 1)
    
    # Шифруем (Xn || r) XOR prev
    combined = (Xn << (12 - tail)) | r
    Yn_1 = encrypt_block(combined ^ prev, key3)
    
    encrypted_blocks.append(Yn_1)
    encrypted_blocks.append(Yn)
    
    return join_blocks_12(encrypted_blocks), tail


def decrypt_cbc(ciphertext, key3, iv, tail):
 
    blocks = split_blocks_12(ciphertext)

    if tail == 0:
        prev = iv & 0xFFF
        dec = []
        for c in blocks:
            x = decrypt_block(c, key3)
            p = x ^ prev
            dec.append(p)
            prev = c
        return join_blocks_12(dec)

    if len(blocks) == 1:
        x = decrypt_block(blocks[0], key3)
        p = x ^ (iv & 0xFFF)
        Xn = p >> (12 - tail)
        return Xn

    Yn = blocks[-1]
    Yn_1 = blocks[-2]

    prev_last = iv & 0xFFF
    for b in blocks[:-2]:
        prev_last = b


    tmp = decrypt_block(Yn_1, key3)
    tmp ^= prev_last
    Xn = tmp >> (12 - tail)
    r = tmp & ((1 << (12 - tail)) - 1)


    combined = (Yn << (12 - tail)) | r
    Xn_1 = decrypt_block(combined, key3)
    Xn_1 ^= prev_last


    dec_full = []
    prev = iv & 0xFFF
    for c in blocks[:-2]:
        x = decrypt_block(c, key3)
        p = x ^ prev
        dec_full.append(p)
        prev = c

    # добавляем восстановленный полный блок
    dec_full.append(Xn_1)
    data_full = join_blocks_12(dec_full)
    plaintext = (data_full << tail) | Xn
    return plaintext

# CFB 
def encrypt_cfb(plaintext, key3, iv):
    # 1. Split(X, 12)
    total_bits = plaintext.bit_length() or 1
    blocks = split_bits(plaintext, 12, total_bits)

    # 2. Y0 = S
    prev = iv & 0xFFF

    out_blocks = []

    # 3. Для каждого Xi
    for Xi, ln in blocks:
        # gamma = Lo(E(prev), ln)
        s = encrypt_block(prev, key3)
        gamma = s & ((1 << ln) - 1)

        # Yi = Xi XOR gamma
        Yi = Xi ^ gamma
        out_blocks.append((Yi, ln))

        # prev = Yi
        prev = Yi

    # 4. Y = concat(Yi)
    return join_bits(out_blocks), total_bits


def decrypt_cfb(cipher, key3, iv, total_bits):
    # 1. Split(Y, 12)
    blocks = split_bits(cipher, 12, total_bits)

    # 2. Y0 = S
    prev = iv & 0xFFF

    out_blocks = []

    # 3. Для каждого Yi
    for Yi, ln in blocks:
        # gamma = Lo(E(prev), ln)
        s = encrypt_block(prev, key3)
        gamma = s & ((1 << ln) - 1)

        # Xi = Yi XOR gamma
        Xi = Yi ^ gamma
        out_blocks.append((Xi, ln))

        # prev = Yi
        prev = Yi

    # 4. X = concat(Xi)
    return join_bits(out_blocks)


# CTR 
def encrypt_ctr(plaintext, key3, iv):
    # 1. Split(X, 12)
    total_bits = plaintext.bit_length() or 1
    blocks = split_bits(plaintext, 12, total_bits)

    # 2. s = E(S)
    s = encrypt_block(iv & 0xFFF, key3)

    out_blocks = []

    # 3. Для каждого Xi
    for Xi, ln in blocks:
        # s = s + 1 mod 2^12
        s = (s + 1) & 0xFFF

        # gamma = E(s)
        gamma = encrypt_block(s, key3)

        # Lo(gamma, ln) = младшие ln бит
        lo = gamma & ((1 << ln) - 1)

        # Yi = Xi XOR Lo(...)
        Yi = Xi ^ lo

        out_blocks.append((Yi, ln))

    cipher = join_bits(out_blocks)
    return cipher, total_bits
        

def decrypt_ctr(cipher, key3, iv, total_bits):
    blocks = split_bits(cipher, 12, total_bits)

    s = encrypt_block(iv & 0xFFF, key3)

    out_blocks = []

    for Ci, ln in blocks:
        s = (s + 1) & 0xFFF
        gamma = encrypt_block(s, key3)
        lo = gamma & ((1 << ln) - 1)
        Xi = Ci ^ lo
        out_blocks.append((Xi, ln))

    return join_bits(out_blocks)

def test_quantum_mode(name, enc_func, dec_func, data, key3, iv=None):
    print(f"\n=== {name} (квантовый) ===")
    
    process = psutil.Process(os.getpid())
    
    # ШИФРОВАНИЕ
    t0 = time.perf_counter()
    
    if iv is None:
        enc_res, tail = enc_func(data, key3)
    else:
        enc_res, tail= enc_func(data, key3, iv)
    
    t1 = time.perf_counter()
    enc_rss_abs = process.memory_info().rss / 1024
    
    # РАСШИФРОВАНИЕ
    t2 = time.perf_counter()
    
    if iv is None:
        dec_res = dec_func(enc_res, key3, tail)
    else:
        dec_res = dec_func(enc_res, key3, iv, tail)
    
    t3 = time.perf_counter()
    dec_rss_abs = process.memory_info().rss / 1024
    
    #ВЫВОД 
    print(f"Блок: {data} (0x{data:X})")
    print(f"Шифр: {hex(enc_res)}")
    print(f"Расшифровка: {hex(dec_res)}")
    print(f"Время шифрования: {t1 - t0:.6f} сек")
    print(f"RSS (реальная память): {enc_rss_abs:.2f} КБ")
    print(f"Время расшифрования: {t3 - t2:.6f} сек")
    print(f"RSS (реальная память): {dec_rss_abs:.2f} КБ")
    print("Корректность:", "OK" if dec_res == data else "ERROR")

def main():

    plaintext = 0xABC4342F4B7D1E6A5C8F3B9D28E3C9A2F4B7D1E6A5C8F3B9D28E3C9A2F4B7D1E6A5C8F3B9D28E3C9A2F4B7D1E6A5C8F3B9D28E3C9A2F4B7D1E6A5C8F3B9D2654
    bit_length = plaintext.bit_length()
    print(f"Длина открытого текста: {bit_length} бит")


    key3 = 0x6
    iv = 0x123

    test_quantum_mode(
        "ECB", encrypt_ecb, decrypt_ecb, plaintext, key3
    )
    
    test_quantum_mode(
        "CBC", encrypt_cbc, decrypt_cbc, plaintext, key3, iv
    )
      
    test_quantum_mode(
        "CFB", encrypt_cfb, decrypt_cfb, plaintext, key3, iv
    )
       
    test_quantum_mode(
        "CTR", encrypt_ctr, decrypt_ctr, plaintext, key3, iv
    )


if __name__ == "__main__":

    main()
