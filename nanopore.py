import math

MEMBRANE_THICKNESS_DEFAULT = 20.0

CONDUCTIVITY_TABLE = {
    "KCl": [
        (0.001, 0.0147),
        (0.005, 0.0718),
        (0.01, 0.1413),
        (0.02, 0.2766),
        (0.05, 0.6685),
        (0.1, 1.2886),
        (0.2, 2.489),
        (0.5, 5.880),
        (1.0, 11.18),
        (1.5, 16.36),
        (2.0, 20.88),
        (2.5, 24.90),
        (3.0, 28.60),
        (3.5, 31.90),
        (4.0, 34.80),
        (4.5, 37.30),
        (5.0, 39.40),
    ],
    "NaCl": [
        (0.001, 0.0124),
        (0.005, 0.0606),
        (0.01, 0.1205),
        (0.02, 0.2377),
        (0.05, 0.5678),
        (0.1, 1.0674),
        (0.2, 1.997),
        (0.5, 4.670),
        (1.0, 8.56),
        (1.5, 12.05),
        (2.0, 15.31),
        (2.5, 18.24),
        (3.0, 20.88),
        (3.5, 23.20),
        (4.0, 25.20),
        (4.5, 26.90),
        (5.0, 28.30),
    ],
    "LiCl": [
        (0.001, 0.0113),
        (0.005, 0.0552),
        (0.01, 0.1094),
        (0.02, 0.2157),
        (0.05, 0.5178),
        (0.1, 0.9638),
        (0.2, 1.790),
        (0.5, 4.100),
        (1.0, 7.64),
        (1.5, 10.67),
        (2.0, 13.70),
        (2.5, 16.20),
        (3.0, 18.30),
        (3.5, 20.10),
        (4.0, 21.60),
        (4.5, 22.80),
        (5.0, 23.70),
    ],
}


def get_conductivity(salt_type, concentration):
    salt_type = salt_type.strip()
    if salt_type not in CONDUCTIVITY_TABLE:
        raise ValueError(f"Unknown salt type: {salt_type}")
    table = CONDUCTIVITY_TABLE[salt_type]
    if concentration <= table[0][0]:
        return table[0][1]
    if concentration >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        c0, s0 = table[i]
        c1, s1 = table[i + 1]
        if c0 <= concentration <= c1:
            frac = (concentration - c0) / (c1 - c0)
            return s0 + frac * (s1 - s0)
    return table[-1][1]


def calculate_pore_diameter(current, voltage, sigma=11.18, thickness=20e-9):
    if abs(voltage) < 1e-12 or abs(current) < 1e-15:
        return 0.0
    try:
        G = current / voltage
        d = (current / (2 * sigma * voltage)) * (
            1 + math.sqrt(1 + (16 * sigma * thickness) / (math.pi * G))
        )
        return d * 1e9
    except (ValueError, ZeroDivisionError):
        return 0.0
