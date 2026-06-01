from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister, transpile
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit import transpile
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime import SamplerV2 as Sampler

#НАСТРОЙКА
USE_IBM = True   # True → запуск на реальном квантовом компьютере

# HBOX 
SBOX3 = [
    0xB & 0x7, 0x1 & 0x7, 0x9 & 0x7, 0x4 & 0x7,
    0xB & 0x7, 0xA & 0x7, 0xC & 0x7, 0x8 & 0x7,
]

MASK3 = 0x7
NUM_ROUNDS = 2
R = [1, 1, 1]

# УТИЛИТЫ
def load3(qc, reg, val):
    for i in range(3):
        if (val >> i) & 1:
            qc.x(reg[i])

def rotl3(qc, reg, r):
    r %= 3
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

    add_mod3(qc, A, K)
    G3(qc, A, t1, r1)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r1)
    sub_mod3(qc, A, K)

    add_mod3(qc, D, K)
    G3(qc, D, t1, r3)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r3)
    sub_mod3(qc, D, K)

    add_mod3(qc, B, K)
    G3(qc, B, t1, r2)
    sub_mod3(qc, A, t1)
    G3_uncompute(qc, B, t1, r2)
    sub_mod3(qc, B, K)

    add_mod3(qc, B, t2)
    add_mod3(qc, C, t2)
    add_mod3(qc, K, t2)

    G3(qc, t2, t1, r3)
    if round_num & 1: qc.x(t1[0])
    if round_num & 2: qc.x(t1[1])
    if round_num & 4: qc.x(t1[2])

    add_mod3(qc, B, t1)
    sub_mod3(qc, C, t1)

    G3_uncompute(qc, t2, t1, r3)
    sub_mod3(qc, K, t2)
    sub_mod3(qc, C, t2)
    sub_mod3(qc, B, t2)

    add_mod3(qc, C, K)
    G3(qc, C, t1, r2)
    add_mod3(qc, D, t1)
    G3_uncompute(qc, C, t1, r2)
    sub_mod3(qc, C, K)

    add_mod3(qc, A, K)
    G3(qc, A, t1, r3)
    for i in range(3):
        qc.cx(t1[i], B[i])
    G3_uncompute(qc, A, t1, r3)
    sub_mod3(qc, A, K)

    add_mod3(qc, D, K)
    G3(qc, D, t1, r1)
    for i in range(3):
        qc.cx(t1[i], C[i])
    G3_uncompute(qc, D, t1, r1)
    sub_mod3(qc, D, K)

    for i in range(3):
        qc.swap(A[i], B[i])
        qc.swap(C[i], D[i])
        qc.swap(B[i], C[i])

# ПОСТРОЕНИЕ
def build_encrypt_circuit_3(block, key3):
    A = QuantumRegister(3)
    B = QuantumRegister(3)
    C = QuantumRegister(3)
    D = QuantumRegister(3)
    t1 = QuantumRegister(3)
    t2 = QuantumRegister(3)
    K  = QuantumRegister(3)

    qc = QuantumCircuit(A, B, C, D, t1, t2, K)

    load3(qc, A, (block >> 0) & MASK3)
    load3(qc, B, (block >> 3) & MASK3)
    load3(qc, C, (block >> 6) & MASK3)
    load3(qc, D, (block >> 9) & MASK3)
    load3(qc, K, key3 & MASK3)

    for i in range(NUM_ROUNDS):
        round_func_3(qc, A, B, C, D, t1, t2, K, i+1)

    return qc, (A, B, C, D)

# ЗАПУСК
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
from qiskit import transpile

from collections import Counter

def print_backend_metrics(backend):
    print("\n=== МЕТРИКИ КВАНТОВОГО КОМПЬЮТЕРА ===")

    # Попытка получить свойства backend
    try:
        props = backend.properties()
    except Exception as e:
        print("Свойства backend недоступны через Runtime V2.")
        print("Причина:", e)
        print("=\n")
        return

    #Ошибки CX
    cx_errors = []
    for gate in props.gates:
        if gate.gate == "cx":
            for p in gate.parameters:
                if p.name == "gate_error":
                    cx_errors.append(p.value)

    if cx_errors:
        print(f"Средняя ошибка CX: {sum(cx_errors)/len(cx_errors):.5f}")
    else:
        print("Ошибка CX: данные недоступны")

    #Ошибки одиночных гейтов
    u_errors = []
    for gate in props.gates:
        if gate.gate in ("u3", "u"):
            for p in gate.parameters:
                if p.name == "gate_error":
                    u_errors.append(p.value)

    if u_errors:
        print(f"Средняя ошибка одиночных гейтов: {sum(u_errors)/len(u_errors):.5f}")
    else:
        print("Ошибка одиночных гейтов: данные недоступны")

    # --- T1/T2 ---
    T1 = []
    T2 = []

    for qubit in props.qubits:
        # qubit — это список параметров, ищем t1/t2 вручную
        t1 = next((p.value for p in qubit if p.name == "T1"), None)
        t2 = next((p.value for p in qubit if p.name == "T2"), None)

        if t1 is not None:
            T1.append(t1)
        if t2 is not None:
            T2.append(t2)

    if T1:
        print(f"Среднее T1: {sum(T1)/len(T1):.1f} мкс")
    else:
        print("T1 недоступно")

    if T2:
        print(f"Среднее T2: {sum(T2)/len(T2):.1f} мкс")
    else:
        print("T2 недоступно")

    print("=\n")

    

def run_on_ibm(qc):
    service = QiskitRuntimeService()

    print("=== Проверка подключения к IBM Runtime ===")
    print("Инстансы:", service.instances())

    backend = service.least_busy(simulator=False, operational=True)
    print("Backend:", backend.name)
    print_backend_metrics(backend)


    tqc = transpile(qc, backend)

    sampler = Sampler(backend)
    job = sampler.run([tqc], shots=20000)


    print("Job ID:", job.job_id())
    print("Статус job:", job.status())

    result = job.result()
    pub = result[0]

    print("pub.data keys:", list(pub.data.keys()))

    c_keys = [k for k in pub.data.keys() if k.startswith("c")]
    c = pub.data[c_keys[0]]
    counts = c.get_counts()

    best_bitstring = max(counts, key=counts.get)
    return int(best_bitstring, 2)


        
def run_circuit(qc, A, B, C, D):

    out = ClassicalRegister(12)
    qc.add_register(out)
    qc.measure(A[:] + B[:] + C[:] + D[:], out)

    if USE_IBM:
        return run_on_ibm(qc)
    else:
        sim = AerSimulator()
        res = sim.run(qc, shots=1).result()
        return int(list(res.get_counts().keys())[0], 2)

#API
def encrypt_block(block, key3):
    qc, (A, B, C, D) = build_encrypt_circuit_3(block, key3)
    return run_circuit(qc, A, B, C, D)

def decrypt_block(block, key3):
    qc, regs = build_encrypt_circuit_3(block, key3)
    qc = qc.inverse()
    return run_circuit(qc, *regs)

#ТЕСТ
def main():
    plaintext = 0x6D3   # ⚠️ только 12 бит!
    key3 = 0x6

    print("Plain:", hex(plaintext))

    cipher = encrypt_block(plaintext, key3)
    print("Cipher:", hex(cipher))

    decrypted = decrypt_block(cipher, key3)
    print("Decrypted:", hex(decrypted))

    print("\nOK:", decrypted == plaintext)

if __name__ == "__main__":
    main()