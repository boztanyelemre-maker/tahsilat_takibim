def clamp(value: float, min_val: float = 0, max_val: float = 100) -> float:
    return max(min_val, min(value, max_val))


def calculate_risk_score(
    overdue_ratio: float,
    over90_ratio: float,
    weighted_days: float,
    loss_ratio: float,
    score4_scale: float = 1000,
) -> float:
    """
    4 bileşenli risk skoru:
    B1: Overdue yoğunluğu (35%)
    B2: 90+ payı (30%)
    B3: ağırlıklı gecikme günü (20%)
    B4: geç ödeme kaybı oranı (15%)
    """
    score1 = clamp(overdue_ratio * 100)  # 0–100
    score2 = clamp(over90_ratio * 100)
    score3 = clamp((weighted_days / 120) * 100)  # 120+ günü 100 kabul ediyoruz
    score4 = clamp(loss_ratio * score4_scale)

    risk = 0.35 * score1 + 0.30 * score2 + 0.20 * score3 + 0.15 * score4
    return round(risk, 2)






