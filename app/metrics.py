from datetime import timedelta

from .models import Payment


def calculate_late_loss_payment(payment: Payment, cost_of_cash: float) -> float:
    """
    Tek bir ödeme satırı icin finansal kayip (TRY).

    Formül (senin tarifin):
      Gecikme Gunu = payment_date - (invoice_date + vade)
      ADAT = Gecikme Gunu * applied_amount
      Finansal Kayıp = ADAT * (cost_of_cash_annual / 100 / 365)

    Notlar:
      - Gecikme gunu <= 0 ise kayip 0 kabul edilir.
      - invoice_date veya vade yoksa bu satir icin kayip 0 kabul edilir.
      - Sadece applied_amount kullanilir, payment_amount_try kullanilmaz.
    """
    if payment is None:
        return 0.0

    if payment.payment_date is None or payment.invoice_date is None or payment.vade is None:
        return 0.0

    # Sadece Uygulanan Tutar kullanilir
    amount = payment.applied_amount
    if amount is None or amount == 0.0:
        return 0.0

    # Beklenen ödeme tarihi = Fatura Tarihi + vade (gun)
    try:
        expected_date = payment.invoice_date + timedelta(days=payment.vade)
    except Exception:
        return 0.0

    delay_days = (payment.payment_date - expected_date).days
    if delay_days <= 0:
        return 0.0

    # ADAT: gun * tutar
    adat = delay_days * amount

    # Yillik orani gunluk orana cevir
    daily_rate = (cost_of_cash / 100.0) / 365.0

    # Finansal kayip: ADAT * gunluk oran
    loss = adat * daily_rate
    return loss



