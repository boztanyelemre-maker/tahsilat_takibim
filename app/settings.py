# Sistem parametreleri icin basit yardimci fonksiyonlar.

from sqlalchemy.orm import Session

from .models import Setting


def get_cost_of_cash_annual(db: Session, default: float = 45.0) -> float:
    row = db.query(Setting).filter(Setting.key == "cost_of_cash_annual").first()
    return row.value if row else default


def set_cost_of_cash_annual(db: Session, value: float) -> None:
    row = db.query(Setting).filter(Setting.key == "cost_of_cash_annual").first()
    if row:
        row.value = value
    else:
        row = Setting(key="cost_of_cash_annual", value=value)
        db.add(row)
    db.commit()






