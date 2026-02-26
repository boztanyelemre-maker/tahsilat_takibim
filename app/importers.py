from __future__ import annotations

from typing import Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from .models import Customer, Invoice, Payment, Region


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        return float(text.replace(".", "").replace(",", ".")) if "," in text and text.count(",") == 1 else float(text)
    except Exception:
        return None


def _to_int(value: object) -> Optional[int]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def _normalize_customer_no(value: object) -> Optional[str]:
    """
    Müşteri numarasını stringe çevirir, bos veya 'nan' ise None döner.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "nan":
        return None
    return text


def import_invoices_df(db: Session, df: pd.DataFrame) -> int:
    """
    Aging (open balance) Excel/CSV datasini invoices + customers tablolarina yazar.

    Beklenen kolonlar (senin raporundan):
      - Transaction Number
      - Customer Number
      - Customer Name
      - Date
      - Due Date
      - Invoice Currency Code
      - Total Amount
      - Open Balance
    """
    col_invoice_no = "Transaction Number"
    col_customer_no = "Customer Number"
    col_customer_name = "Customer Name"
    col_invoice_date = "Date"
    col_due_date = "Due Date"
    col_currency = "Invoice Currency Code"
    col_total_amount = "Total Amount"
    col_open_balance = "Open Balance"

    # Tarih kolonlarini date tipine cevir
    for col in (col_invoice_date, col_due_date):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    imported = 0

    # Aynı import içinde tekrar tekrar Customer yaratmamak icin cache
    customers_cache: Dict[str, Customer] = {}

    for _, row in df.iterrows():
        invoice_no = str(row.get(col_invoice_no) or "").strip()
        customer_no = _normalize_customer_no(row.get(col_customer_no))

        if not invoice_no or not customer_no:
            continue

        customer_name = str(row.get(col_customer_name) or "").strip() or None

        # Musteri cache / DB
        customer = customers_cache.get(customer_no)
        if not customer:
            customer = db.query(Customer).filter(Customer.customer_no == customer_no).first()
            if not customer:
                customer = Customer(customer_no=customer_no, name=customer_name or customer_no, region_id=None)
                db.add(customer)
            customers_cache[customer_no] = customer
        else:
            # Isim degismis ise guncelle
            if customer_name and customer.name != customer_name:
                customer.name = customer_name

        invoice = db.query(Invoice).filter(Invoice.invoice_no == invoice_no).first()

        invoice_date = row.get(col_invoice_date)
        due_date = row.get(col_due_date)
        vade_days: Optional[int] = None
        if invoice_date and due_date:
            try:
                vade_days = (due_date - invoice_date).days
            except Exception:
                vade_days = None
        currency = str(row.get(col_currency) or "").strip() or None
        total_amount = _to_float(row.get(col_total_amount))
        open_balance = _to_float(row.get(col_open_balance))

        if invoice:
            invoice.customer_no = customer_no
            invoice.customer_name = customer_name or customer.name
            invoice.invoice_date = invoice_date
            invoice.due_date = due_date
            invoice.vade = vade_days
            invoice.currency = currency
            invoice.total_amount = total_amount
            invoice.open_balance = open_balance
        else:
            invoice = Invoice(
                invoice_no=invoice_no,
                customer_no=customer_no,
                customer_name=customer_name or customer.name,
                invoice_date=invoice_date,
                due_date=due_date,
                vade=vade_days,
                currency=currency,
                total_amount=total_amount,
                open_balance=open_balance,
            )
            db.add(invoice)
            imported += 1

    db.commit()
    return imported


def import_payments_df(db: Session, df: pd.DataFrame) -> int:
    """
    Geç ödenen faturalar dosyasini payments + customers tablolarina yazar.

    Beklenen kolonlar:
      - Müşteri No
      - Müşteri Adı
      - AR Fatura No
      - Ödeme Valör Tarihi (yoksa Ödeme Tarihi)
      - Gecikme Tarihi (gün sayisi)
      - Uygulanan Tutar
      - Ödeme Tutar TRY
    """
    # Basliklardaki bosluk vb. farklarini tolere etmek icin trim'le
    df.columns = [str(c).strip() for c in df.columns]

    col_customer_no = "Müşteri No"
    col_customer_name = "Müşteri Adı"
    col_ar_invoice_no = "AR Fatura No"
    col_value_date = "Ödeme Valör Tarihi"
    col_payment_date = "Ödeme Tarihi"
    col_invoice_date_pay = "Fatura Tarihi"
    col_applied_amount = "Uygulanan Tutar"
    col_payment_try = "Ödeme Tutar TRY"
    
    # Kolon kontrolü: "Uygulanan Tutar" kolonu yoksa uyari ver
    if col_applied_amount not in df.columns:
        # Alternatif kolon adlarini dene
        possible_names = ["Uygulanan Tutar", "UygulananTutar", "Uygulanan_Tutar", "Applied Amount", "applied_amount"]
        found = False
        for alt_name in possible_names:
            if alt_name in df.columns:
                col_applied_amount = alt_name
                found = True
                break
        if not found:
            print(f"UYARI: 'Uygulanan Tutar' kolonu bulunamadi. Mevcut kolonlar: {list(df.columns)}")

    # Tarih kolonlarini cevir
    for col in (col_value_date, col_payment_date, col_invoice_date_pay):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    # Her import'ta payments tablosunu temizle (yeni dosya tam fotoğraf kabul ediliyor)
    db.query(Payment).delete()

    imported = 0

    customers_cache: Dict[str, Customer] = {}
    invoices_cache: Dict[str, Invoice] = {}
    customer_vade_cache: Dict[str, Optional[int]] = {}

    for _, row in df.iterrows():
        customer_no = _normalize_customer_no(row.get(col_customer_no))
        if not customer_no:
            continue

        customer_name = str(row.get(col_customer_name) or "").strip() or None

        # Musteri yoksa olustur (region_id su an icin None)
        customer = customers_cache.get(customer_no)
        if not customer:
            customer = db.query(Customer).filter(Customer.customer_no == customer_no).first()
            if not customer:
                customer = Customer(customer_no=customer_no, name=customer_name or customer_no, region_id=None)
                db.add(customer)
            customers_cache[customer_no] = customer
        else:
            if customer_name and customer.name != customer_name:
                customer.name = customer_name

        ar_invoice_no = str(row.get(col_ar_invoice_no) or "").strip() or None

        value_date = row.get(col_value_date)
        payment_date = row.get(col_payment_date)
        invoice_date_pay = row.get(col_invoice_date_pay)
        if pd.isna(value_date):
            value_date = payment_date
        if pd.isna(value_date):
            value_date = None

        # Gecikme gunu: her zaman fatura vadesine gore, AR Fatura No uzerinden
        delay_days = 0
        if value_date and ar_invoice_no:
            inv = invoices_cache.get(ar_invoice_no)
            if inv is None:
                inv = db.query(Invoice).filter(Invoice.invoice_no == ar_invoice_no).first()
                invoices_cache[ar_invoice_no] = inv
            if inv and inv.due_date:
                diff = (value_date - inv.due_date).days
                if diff > 0:
                    delay_days = diff

        # Vade (gun) artik customer_name bazli: invoices tablosundaki ayni customer_name'den cekilir
        vade_days_for_payment: Optional[int] = None
        if customer_name:
            if customer_name in customer_vade_cache:
                vade_days_for_payment = customer_vade_cache[customer_name]
            else:
                inv_for_cust = (
                    db.query(Invoice)
                    .filter(Invoice.customer_name == customer_name)
                    .order_by(Invoice.invoice_date.desc())
                    .first()
                )
                if inv_for_cust and inv_for_cust.vade is not None:
                    vade_days_for_payment = inv_for_cust.vade
                customer_vade_cache[customer_name] = vade_days_for_payment
        applied_amount = _to_float(row.get(col_applied_amount))
        payment_amount_try = _to_float(row.get(col_payment_try))

        payment = Payment(
            customer_no=customer_no,
            customer_name=customer_name or (customer.name if customer else None),
            invoice_date=invoice_date_pay,
            payment_date=payment_date,
            ar_invoice_no=ar_invoice_no,
            value_date=value_date,
            delay_days=delay_days,
            vade=vade_days_for_payment,
            applied_amount=applied_amount,
            payment_amount_try=payment_amount_try,
        )
        db.add(payment)
        imported += 1

    db.commit()
    return imported


def import_customer_regions_df(db: Session, df: pd.DataFrame) -> int:
    """
    Musteri-bolge eslemesini import eder.

    Beklenen kolonlar:
      - Customer Number  (veya alternatif olarak Customer Name)
      - Region Name

    Not: Region Name daha once yoksa regions tablosunda olusturulur,
    ilgili musterinin region_id alanina baglanir.
    """
    # Basliklari normalize et
    df.columns = [str(c).strip() for c in df.columns]

    col_customer_no = "Customer Number"
    col_customer_name = "Customer Name"
    col_region_name = "Region Name"

    # En azindan Region Name ve (Customer Number veya Customer Name) kolonlarindan
    # biri olmali, yoksa hicbir sey yapma.
    if col_region_name not in df.columns or (
        col_customer_no not in df.columns and col_customer_name not in df.columns
    ):
        return 0

    # Region cache
    regions_cache: Dict[str, Region] = {}

    updated = 0

    for _, row in df.iterrows():
        # Hem Customer Number hem Customer Name'i destekle
        customer_no = (
            _normalize_customer_no(row.get(col_customer_no))
            if col_customer_no in df.columns
            else None
        )
        customer_name = (
            str(row.get(col_customer_name) or "").strip()
            if col_customer_name in df.columns
            else ""
        )
        if not customer_no and not customer_name:
            # Musteri referansi yoksa satiri atla
            continue

        region_name = str(row.get(col_region_name) or "").strip()
        if not region_name:
            continue

        # Musteriyi bul
        if customer_no:
            customer = (
                db.query(Customer)
                .filter(Customer.customer_no == customer_no)
                .first()
            )
        else:
            customer = (
                db.query(Customer)
                .filter(Customer.name == customer_name)
                .first()
            )
        if not customer:
            # Bu customer aging'de yoksa atla
            continue

        # Region'i cache/DB'den bul/olustur
        region = regions_cache.get(region_name)
        if not region:
            region = db.query(Region).filter(Region.name == region_name).first()
            if not region:
                region = Region(name=region_name)
                db.add(region)
                db.flush()  # id almak icin
            regions_cache[region_name] = region

        # Musterinin bolgesini guncelle
        if customer.region_id != region.id:
            customer.region_id = region.id
            updated += 1

    db.commit()
    return updated
