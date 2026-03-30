from datetime import date, timedelta
from typing import Dict, List

import pandas as pd
from io import BytesIO
import unicodedata
import re

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine
from .importers import (
    import_customer_regions_df,
    import_invoices_df,
    import_payments_df,
)
from .metrics import calculate_late_loss_payment


def _get_payment_loss(payment: Payment, cost_of_cash: float) -> float:
    """Excel'deki Finansal Kayip sütunu varsa onu kullan, yoksa hesapla."""
    if payment.financial_loss is not None:
        return payment.financial_loss
    return calculate_late_loss_payment(payment, cost_of_cash)
from .models import Action, Customer, Invoice, Payment, Region, Setting
from .risk_score import calculate_risk_score
from .schemas import ActionCreate, ActionOut, SettingsUpdate
from .settings import (
    get_cost_of_cash_annual,
    get_late_fee_rate_annual,
    set_cost_of_cash_annual,
    set_late_fee_rate_annual,
)


# Tabloları oluştur
Base.metadata.create_all(bind=engine)

# Basit migration: invoices tablosuna vade ve customer_name kolonlari,
# payments tablosuna da vade, customer_name, invoice_date, payment_date kolonlari ekle
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE invoices ADD COLUMN vade INTEGER"))
    except Exception:
        # Kolon zaten varsa veya tablo yoksa hata yoksayilir
        pass
    try:
        conn.execute(text("ALTER TABLE payments ADD COLUMN vade INTEGER"))
    except Exception:
        pass
    try:
        conn.execute(text("ALTER TABLE invoices ADD COLUMN customer_name VARCHAR"))
    except Exception:
        pass
    try:
        conn.execute(text("ALTER TABLE payments ADD COLUMN customer_name VARCHAR"))
    except Exception:
        pass
    try:
        conn.execute(text("ALTER TABLE payments ADD COLUMN invoice_date DATE"))
    except Exception:
        pass
    try:
        conn.execute(text("ALTER TABLE payments ADD COLUMN payment_date DATE"))
    except Exception:
        pass
    try:
        conn.execute(text("ALTER TABLE payments ADD COLUMN financial_loss FLOAT"))
    except Exception:
        pass

app = FastAPI(title="ALACAK360 – Bölge Bazlı Alacak Takip API")

# CORS middleware - Netlify frontend'den istekler için
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da sadece Netlify domain'ini ekle: ["https://tahsilattakip.netlify.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sanitize_filename(name: str) -> str:
    """
    Dosya adindaki Turkce karakterleri ASCII'ye cevirir.
    """
    # Turkce karakter donusum tablosu
    turkish_map = {
        'ç': 'c', 'Ç': 'C',
        'ğ': 'g', 'Ğ': 'G',
        'ı': 'i', 'İ': 'I',
        'ö': 'o', 'Ö': 'O',
        'ş': 's', 'Ş': 'S',
        'ü': 'u', 'Ü': 'U',
    }
    
    result = ""
    for char in name:
        result += turkish_map.get(char, char)
    
    # ASCII olmayan karakterleri temizle
    result = unicodedata.normalize('NFKD', result).encode('ascii', 'ignore').decode('ascii')
    
    # Ozel karakterleri alt cizgi ile degistir
    result = re.sub(r'[^\w\s-]', '_', result)
    result = re.sub(r'[-\s]+', '_', result)
    
    return result.strip('_')


# Statik frontend (Meeting Mode) icin
# Proje kokune gore mutlak yol: uvicorn baska cwd ile baslasa bile /static 404 olmasin
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# index.html cache'siz servis edilir (her yenilemede guncel sayfa)
NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


@app.get("/static/index.html")
async def serve_index_html():
    """index.html her zaman cache'siz - guncel veri icin."""
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers=NO_CACHE_HEADERS)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    """Ana sayfaya yonlendir."""
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "ALACAK360 backend calisiyor"}


@app.get("/debug/db-stats")
def debug_db_stats(db: Session = Depends(get_db)):
    """Veritabanindaki ham veriyi gosterir - guncel veri kontrolu icin."""
    from .db import DATABASE_URL
    invoices = db.query(Invoice).all()
    payments = db.query(Payment).all()
    total_open_all = sum(i.open_balance or 0 for i in invoices)
    total_open_try = sum(i.open_balance or 0 for i in invoices if (i.currency or "").upper() in ("TRY", "TL", "TRL"))
    _proj = Path(__file__).resolve().parent.parent
    _sqlite_default = _proj / "tahsilat.db"
    url = DATABASE_URL or ""
    uses_sqlite = "sqlite" in url.lower()
    uses_pg = "postgresql" in url
    return {
        "database": "postgresql" if uses_pg else "sqlite",
        "active_sqlite_path": str(_sqlite_default) if uses_sqlite else None,
        "tahsilat_db_note": (
            "Bu calisma PostgreSQL kullaniyor; proje klasorundeki tahsilat.db dosyasi yazilmaz. "
            "SQLite istiyorsaniz .env / .env.txt icinden DATABASE_URL satirini kaldirin veya yorum yapin."
            if uses_pg
            else None
        ),
        "invoice_count": len(invoices),
        "payment_count": len(payments),
        "total_open_all": total_open_all,
        "total_open_try": total_open_try,
        "currencies": list(set((i.currency or "N/A") for i in invoices)),
    }


@app.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = date.today()

    invoices = db.query(Invoice).all()
    payments = db.query(Payment).all()
    invoice_count = len(invoices)

    total_open = sum(i.open_balance or 0 for i in invoices)
    customer_count = len({i.customer_no for i in invoices if (i.open_balance or 0) > 0})
    overdue = sum(
        i.open_balance or 0
        for i in invoices
        if i.due_date is not None and i.due_date < today
    )

    over90 = sum(
        i.open_balance or 0
        for i in invoices
        if i.due_date is not None and (today - i.due_date).days > 90
    )

    # Para birimi bazinda ozet (Toplam Açık, Vadesi Geçmiş ve 90+ icin)
    # TL, TRY, ₺ ayni para birimi olarak birlestir
    def _norm_currency(c: str | None) -> str:
        if not c:
            return "N/A"
        c = str(c).strip().upper()
        if c in ("TL", "TRY", "TRL") or c == "₺":
            return "TRY"
        return c or "N/A"

    totals_by_currency: Dict[str, Dict[str, float]] = {}
    overdue_by_currency: Dict[str, Dict[str, float]] = {}
    over90_by_currency: Dict[str, Dict[str, float]] = {}
    for inv in invoices:
        cur = _norm_currency(inv.currency)
        bucket = totals_by_currency.setdefault(cur, {"total_open": 0.0})
        bucket["total_open"] += inv.open_balance or 0.0
        if inv.due_date is not None and inv.due_date < today:
            ob = inv.open_balance or 0.0
            ob_bucket = overdue_by_currency.setdefault(cur, {"overdue": 0.0})
            ob_bucket["overdue"] += ob
            # 90+ icin de ayni anda grupla
            days_overdue = (today - inv.due_date).days
            if days_overdue > 90:
                o90_bucket = over90_by_currency.setdefault(cur, {"over90": 0.0})
                o90_bucket["over90"] += ob

    # Ana toplam: tum para birimleri (bolgeler tablosu ile tutarli)
    total_open_all = sum(v["total_open"] for v in totals_by_currency.values())
    total_open_try = totals_by_currency.get("TRY", {}).get("total_open", 0.0)
    overdue_all = sum(v["overdue"] for v in overdue_by_currency.values())
    overdue_try = overdue_by_currency.get("TRY", {}).get("overdue", 0.0)
    over90_all = sum(v["over90"] for v in over90_by_currency.values())
    over90_try = over90_by_currency.get("TRY", {}).get("over90", 0.0)

    # Settings: cost_of_cash ve late_fee_rate (yillik %)
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)
    late_fee_rate = get_late_fee_rate_annual(db, default=53.13)

    # Finansal kayip: Excel'deki "Finansal Kayip" sütunu toplami; yoksa hesaplanan deger
    last_30 = today - timedelta(days=30)
    pay_rows_30 = [p for p in payments if p.value_date is not None and p.value_date >= last_30]
    loss_30 = sum(_get_payment_loss(p, cost_of_cash) for p in pay_rows_30)
    loss_30_rows = len(pay_rows_30)
    total_late_loss = sum(_get_payment_loss(p, cost_of_cash) for p in payments)
    total_late_loss_rows = len(payments)

    # Odenmemis faturalar icin GUNCEL vade farki (tahakkuk) hesaplama
    # Sadece TRY faturalar (oran TRY icin gecerli; EUR/USD farkli oran kullanir)
    # late_fee = open_balance * days_overdue * (late_fee_rate_annual / 100 / 365)
    def _is_try(c: str | None) -> bool:
        if not c:
            return False
        return str(c).strip().upper() in ("TRY", "TL", "TRL") or c == "₺"

    daily_late_fee_rate = (late_fee_rate / 100.0) / 365.0
    total_late_fee_unpaid = 0.0
    for inv in invoices:
        if inv.open_balance is None or inv.open_balance <= 0:
            continue
        if not _is_try(inv.currency):
            continue
        if inv.due_date is None or inv.due_date >= today:
            continue
        days_overdue = (today - inv.due_date).days
        if days_overdue <= 0:
            continue
        total_late_fee_unpaid += inv.open_balance * days_overdue * daily_late_fee_rate

    # Risk hesaplamasi tum para birimleri uzerinden (bolgeler tablosu ile tutarli)
    overdue_ratio = overdue_all / total_open_all if total_open_all else 0.0
    over90_ratio = over90_all / overdue_all if overdue_all else 0.0

    # MVP: weighted_days'i basit tutuyoruz, istersek sonraki adimda detaylandiririz
    weighted_days = 0.0
    loss_ratio = loss_30 / total_open_all if total_open_all else 0.0

    risk = calculate_risk_score(
        overdue_ratio=overdue_ratio,
        over90_ratio=over90_ratio,
        weighted_days=weighted_days,
        loss_ratio=loss_ratio,
    )

    content = {
        "total_open": total_open_all,
        "total_open_try": total_open_try,
        "invoice_count": invoice_count,
        "customer_count": customer_count,
        "overdue": overdue_all,
        "over90": over90_all,
        "loss_30d": loss_30,
        "loss_30d_rows": loss_30_rows,
        "total_late_loss": total_late_loss,
        "total_late_loss_rows": total_late_loss_rows,
        "risk_score": risk,
        "cost_of_cash_annual": cost_of_cash,
        "late_fee_rate_annual": late_fee_rate,
        "late_fee_unpaid_total": total_late_fee_unpaid,
        "totals_by_currency": [
            {"currency": cur, "total_open": vals["total_open"]}
            for cur, vals in totals_by_currency.items()
        ],
        "overdue_by_currency": [
            {"currency": cur, "overdue": vals["overdue"]}
            for cur, vals in overdue_by_currency.items()
        ],
        "over90_by_currency": [
            {"currency": cur, "over90": vals["over90"]}
            for cur, vals in over90_by_currency.items()
        ],
    }
    return JSONResponse(
        content=content,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.post("/import/invoices")
async def import_invoices(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Aging (open balance) Excel/CSV dosyasini import eder.
    Beklenen kolonlar: Transaction Number, Customer Number, Customer Name, Date, Due Date, Invoice Currency Code, Total Amount, Open Balance
    """
    filename = file.filename or ""
    suffix = filename.lower()

    try:
        if suffix.endswith((".xlsx", ".xls", ".xlsm")):
            # Ozellikle "ham_data" sayfasindan oku
            try:
                df = pd.read_excel(file.file, sheet_name="ham_data")
            except ValueError as exc:
                # ham_data yoksa kullaniciya net bilgi ver
                raise HTTPException(
                    status_code=400,
                    detail='Excel icinde "ham_data" isimli sayfa bulunamadi.',
                ) from exc
        elif suffix.endswith(".csv"):
            df = pd.read_csv(file.file)
        else:
            raise HTTPException(
                status_code=400,
                detail="Sadece Excel (.xlsx, .xls) veya CSV dosyasi yukleyin.",
            )
    except Exception as exc:  # pragma: no cover - sadece runtime icin
        raise HTTPException(status_code=400, detail=f"Dosya okunamadi: {exc}") from exc

    imported = import_invoices_df(db, df)
    db.commit()
    from .db import DATABASE_URL
    db_name = "tahsilat.db" if (DATABASE_URL or "").startswith("sqlite") else "veritabani"
    return {
        "rows": int(len(df)),
        "inserted_or_updated": imported,
        "database_updated": True,
        "message": f"{db_name} guncellendi",
    }


@app.post("/import/payments")
async def import_payments(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Geç odemeler (payments) Excel/CSV dosyasini import eder.
    Beklenen kolonlar: Müşteri No, Müşteri Adı, AR Fatura No, Ödeme Valör Tarihi, Ödeme Tarihi, Gecikme Tarihi, Uygulanan Tutar, Ödeme Tutar TRY
    """
    filename = file.filename or ""
    suffix = filename.lower()

    try:
        if suffix.endswith((".xlsx", ".xls", ".xlsm")):
            # "data" sayfasi yoksa "ham_data", "Sheet1" veya ilk sayfayi dene
            file.file.seek(0)
            xl = pd.ExcelFile(file.file)
            sheet_names = xl.sheet_names
            for name in ("data", "ham_data", "Sheet1", "Finansal Kayıp"):
                if name in sheet_names:
                    df = pd.read_excel(xl, sheet_name=name)
                    break
            else:
                df = pd.read_excel(xl, sheet_name=0)
        elif suffix.endswith(".csv"):
            df = pd.read_csv(file.file)
        else:
            raise HTTPException(
                status_code=400,
                detail="Sadece Excel (.xlsx, .xls) veya CSV dosyasi yukleyin.",
            )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Dosya okunamadi: {exc}") from exc

    imported = import_payments_df(db, df)
    db.commit()
    from .db import DATABASE_URL
    db_name = "tahsilat.db" if (DATABASE_URL or "").startswith("sqlite") else "veritabani"
    return {
        "rows": int(len(df)),
        "inserted": imported,
        "database_updated": True,
        "message": f"{db_name} guncellendi",
    }


def _customer_metrics(
    db: Session,
    customer_no: str,
    cost_of_cash: float,
    today: date,
) -> Dict:
    invoices: List[Invoice] = (
        db.query(Invoice).filter(Invoice.customer_no == customer_no).all()
    )

    # Payments tarafinda customer_no ile decimal/string farklari olabildigi icin
    # once Customer kaydindan isim al, sonrasinda customer_name uzerinden filtrele.
    cust_obj = db.query(Customer).filter(Customer.customer_no == customer_no).first()
    if cust_obj and cust_obj.name:
        payments: List[Payment] = (
            db.query(Payment).filter(Payment.customer_name == cust_obj.name).all()
        )
    else:
        payments: List[Payment] = (
            db.query(Payment).filter(Payment.customer_no == customer_no).all()
        )

    # Odenmemis fatura (open_balance > 0) adedi
    unpaid_invoices = [i for i in invoices if (i.open_balance or 0.0) > 0.0]
    unpaid_invoice_count = len(unpaid_invoices)

    total_open = sum(i.open_balance or 0 for i in invoices)
    overdue = sum(
        i.open_balance or 0
        for i in invoices
        if i.due_date is not None and i.due_date < today
    )

    over90 = sum(
        i.open_balance or 0
        for i in invoices
        if i.due_date is not None and (today - i.due_date).days > 90
    )

    # Ağırlıklı gecikme günü (sadece overdue aciklar uzerinden)
    overdue_invoices = [
        i for i in invoices if i.due_date is not None and i.due_date < today
    ]
    if overdue_invoices:
        weighted_days_num = 0.0
        overdue_sum = 0.0
        for inv in overdue_invoices:
            ob = inv.open_balance or 0.0
            days = (today - inv.due_date).days
            if days < 0:
                days = 0
            weighted_days_num += ob * days
            overdue_sum += ob
        weighted_days = weighted_days_num / overdue_sum if overdue_sum else 0.0
    else:
        weighted_days = 0.0

    # Son 30 gunde tum odemeler icin gec odeme kaybi
    last_30 = today - timedelta(days=30)
    loss_30 = sum(
        _get_payment_loss(p, cost_of_cash)
        for p in payments
        if p.value_date is not None and p.value_date >= last_30
    )

    # Musteri bazinda toplam finansal kayip (Excel sütunu veya hesaplanan)
    total_late_loss_customer = sum(_get_payment_loss(p, cost_of_cash) for p in payments)

    # Odenmemis faturalar icin musterinin GUNCEL vade farki (tahakkuk) tutari
    late_fee_rate = get_late_fee_rate_annual(db, default=53.13)
    daily_late_fee_rate = (late_fee_rate / 100.0) / 365.0
    late_fee_unpaid = 0.0
    for inv in unpaid_invoices:
        if inv.due_date is None or inv.due_date >= today:
            continue
        days_overdue = (today - inv.due_date).days
        if days_overdue <= 0:
            continue
        ob = inv.open_balance or 0.0
        late_fee_unpaid += ob * days_overdue * daily_late_fee_rate

    overdue_ratio = overdue / total_open if total_open else 0.0
    over90_ratio = over90 / overdue if overdue else 0.0
    loss_ratio = loss_30 / total_open if total_open else 0.0

    risk = calculate_risk_score(
        overdue_ratio=overdue_ratio,
        over90_ratio=over90_ratio,
        weighted_days=weighted_days,
        loss_ratio=loss_ratio,
    )

    return {
        "customer_no": customer_no,
        "total_open": total_open,
        "overdue": overdue,
        "over90": over90,
        "unpaid_invoice_count": unpaid_invoice_count,
        "late_fee_unpaid": late_fee_unpaid,
        "weighted_overdue_days": weighted_days,
        "loss_30d": loss_30,
        "total_late_loss": total_late_loss_customer,
        "risk_score": risk,
    }


@app.get("/customers/top-risky")
def top_risky_customers(
    limit: int = 10,
    region_id: int | None = None,
    sort_by: str = "risk",
    db: Session = Depends(get_db),
):
    """
    En riskli N musteri (risk skoru veya finansal kayip siralamasina gore).

    sort_by:
      - "risk" (varsayilan): risk_score'a gore azalan
      - "overdue": vadesi gecmis bakiye (overdue) gore azalan
      - "unpaid": odenmemis fatura sayisi (unpaid_invoice_count) gore azalan
      - "loss": toplam finansal kayip (total_late_loss) gore azalan
    """
    today = date.today()
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

    query = db.query(Customer)
    if region_id is not None:
        query = query.filter(Customer.region_id == region_id)

    customers = query.all()
    raw_results: List[Dict] = []
    for c in customers:
        m = _customer_metrics(db, c.customer_no, cost_of_cash, today)
        # Hic acik bakiyesi ve hic kaybi yoksa listeye alma
        if (
            m["total_open"] <= 0
            and m["loss_30d"] <= 0
            and m["total_late_loss"] <= 0
            and m["unpaid_invoice_count"] <= 0
        ):
            continue
        m["customer_name"] = c.name
        m["region_id"] = c.region_id
        raw_results.append(m)

    # Ayni musteriyi (isim bazli) tek satira indir - farkli customer_no formatlari
    # (1389 vs 1389.0) ayni firmayi gosterdigi icin birlestir
    grouped: Dict[str, Dict] = {}
    for m in raw_results:
        key = (m.get("customer_name") or m.get("customer_no") or "").strip()
        if not key:
            key = str(m.get("customer_no", ""))
        if key not in grouped:
            grouped[key] = dict(m)
        else:
            g = grouped[key]
            g["total_open"] += m["total_open"]
            g["overdue"] += m["overdue"]
            g["over90"] += m["over90"]
            # loss_30d ve total_late_loss: odemeler customer_name ile eslendigi icin
            # ayni isimdeki musteriler (1389 vs 1389.0) ayni odemeleri alir - toplama, max al
            g["loss_30d"] = max(g["loss_30d"], m["loss_30d"])
            g["total_late_loss"] = max(g["total_late_loss"], m["total_late_loss"])
            g["unpaid_invoice_count"] += m["unpaid_invoice_count"]
            g["late_fee_unpaid"] += m.get("late_fee_unpaid", 0.0)
            if m["risk_score"] > g["risk_score"]:
                g["risk_score"] = m["risk_score"]
    results = list(grouped.values())
    if sort_by == "overdue":
        results.sort(key=lambda x: x["overdue"], reverse=True)
    elif sort_by == "unpaid":
        results.sort(key=lambda x: x["unpaid_invoice_count"], reverse=True)
    elif sort_by == "loss":
        results.sort(key=lambda x: x["total_late_loss"], reverse=True)
    else:
        results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results[: max(1, limit)]


@app.get("/customers")
def list_customers(db: Session = Depends(get_db)):
    """
    Tum musterilerin basit listesi (dropdown icin).
    """
    customers = db.query(Customer).all()
    return [
        {
            "customer_no": c.customer_no,
            "customer_name": c.name,
            "region_id": c.region_id,
        }
        for c in customers
    ]


@app.get("/customers/top-unpaid")
def top_unpaid_customers(
    limit: int = 10,
    region_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Odenmemis fatura adedi en yuksek musteriler.
    """
    today = date.today()
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

    query = db.query(Customer)
    if region_id is not None:
        query = query.filter(Customer.region_id == region_id)

    customers = query.all()
    raw: List[Dict] = []
    for c in customers:
        m = _customer_metrics(db, c.customer_no, cost_of_cash, today)
        if m["unpaid_invoice_count"] <= 0:
            continue
        m["customer_name"] = c.name
        m["region_id"] = c.region_id
        raw.append(m)
    # Ayni musteri (isim bazli) tek satira indir
    grouped: Dict[str, Dict] = {}
    for m in raw:
        key = (m.get("customer_name") or m.get("customer_no") or "").strip() or str(m.get("customer_no", ""))
        if key not in grouped:
            grouped[key] = dict(m)
        else:
            g = grouped[key]
            g["total_open"] += m["total_open"]
            g["overdue"] += m["overdue"]
            g["over90"] += m["over90"]
            g["unpaid_invoice_count"] += m["unpaid_invoice_count"]
            g["total_late_loss"] = max(g["total_late_loss"], m["total_late_loss"])
            if m["risk_score"] > g["risk_score"]:
                g["risk_score"] = m["risk_score"]
    results = list(grouped.values())
    results.sort(key=lambda x: x["unpaid_invoice_count"], reverse=True)
    return results[: max(1, limit)]


@app.get("/customers/{customer_no}/summary")
def customer_summary(customer_no: str, db: Session = Depends(get_db)):
    """
    Tek bir musteri icin KPI + risk skoru.
    """
    customer = db.query(Customer).filter(Customer.customer_no == customer_no).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Musteri bulunamadi")

    today = date.today()
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)
    metrics = _customer_metrics(db, customer_no, cost_of_cash, today)
    metrics["customer_name"] = customer.name
    metrics["region_id"] = customer.region_id

    return metrics


@app.get("/regions/summary")
def regions_summary(db: Session = Depends(get_db)):
    """
    Bölge bazli ozet KPI ve risk skoru.
    region_id bos olan musteriler "Unknown" grubunda toplanir.
    """
    today = date.today()
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

    customers = db.query(Customer).all()
    invoices = db.query(Invoice).all()
    payments = db.query(Payment).all()

    # Haritalar
    customer_region: Dict[str, int] = {}
    for c in customers:
        # None olanlar icin -1 ile Unknown grubu yapalim
        rid = c.region_id if c.region_id is not None else -1
        customer_region[c.customer_no] = rid

    # Bölge bazli agregasyon
    region_totals: Dict[int, Dict] = {}

    def ensure_region(rid: int):
        if rid not in region_totals:
            region_totals[rid] = {
                "total_open": 0.0,
                "overdue": 0.0,
                "over90": 0.0,
                "weighted_num": 0.0,
                "weighted_den": 0.0,
                "loss_30d": 0.0,
                "customer_nos": set(),
            }
        return region_totals[rid]

    # Invoices
    for inv in invoices:
        rid = customer_region.get(inv.customer_no, -1)
        bucket = ensure_region(rid)
        ob = inv.open_balance or 0.0
        if ob > 0:
            bucket["customer_nos"].add(inv.customer_no)
        bucket["total_open"] += ob
        if inv.due_date is not None and inv.due_date < today:
            bucket["overdue"] += ob
            days = (today - inv.due_date).days
            if days < 0:
                days = 0
            bucket["weighted_num"] += ob * days
            bucket["weighted_den"] += ob
            if days > 90:
                bucket["over90"] += ob

    # Payments - loss_30d (son 30 gunde tum odemeler)
    last_30 = today - timedelta(days=30)
    for p in payments:
        rid = customer_region.get(p.customer_no, -1)
        if p.value_date is None or p.value_date < last_30:
            continue
        bucket = ensure_region(rid)
        bucket["loss_30d"] += _get_payment_loss(p, cost_of_cash)

    # Region isimleri
    regions = db.query(Region).all()
    region_names = {r.id: r.name for r in regions}
    region_names[-1] = "Unknown"

    result_list: List[Dict] = []
    for rid, agg in region_totals.items():
        total_open = agg["total_open"]
        overdue = agg["overdue"]
        over90 = agg["over90"]
        loss_30 = agg["loss_30d"]
        weighted_days = (
            agg["weighted_num"] / agg["weighted_den"] if agg["weighted_den"] else 0.0
        )

        overdue_ratio = overdue / total_open if total_open else 0.0
        over90_ratio = over90 / overdue if overdue else 0.0
        loss_ratio = loss_30 / total_open if total_open else 0.0

        risk = calculate_risk_score(
            overdue_ratio=overdue_ratio,
            over90_ratio=over90_ratio,
            weighted_days=weighted_days,
            loss_ratio=loss_ratio,
        )

        result_list.append(
            {
                "region_id": None if rid == -1 else rid,
                "region_name": region_names.get(rid, "Unknown"),
                "customer_count": len(agg.get("customer_nos", set())),
                "total_open": total_open,
                "overdue": overdue,
                "over90": over90,
                "weighted_overdue_days": weighted_days,
                "loss_30d": loss_30,
                "risk_score": risk,
            }
        )

    # Risk skoruna gore sirala (azalan)
    result_list.sort(key=lambda x: x["risk_score"], reverse=True)

    # Unknown uyari: sadece acik bakiyesi olan bolgesiz musteriler
    customers_with_open = {inv.customer_no for inv in invoices if (inv.open_balance or 0) > 0}
    unknown_customers = [
        {"customer_no": c.customer_no, "customer_name": c.name}
        for c in customers
        if c.region_id is None and c.customer_no in customers_with_open
    ]
    unknown_customer_count = len(unknown_customers)
    unknown_total_open = region_totals.get(-1, {}).get("total_open", 0.0)
    has_unknown_regions = unknown_customer_count > 0 and unknown_total_open > 0

    return {
        "regions": result_list,
        "has_unknown_regions": has_unknown_regions,
        "unknown_customer_count": unknown_customer_count,
        "unknown_customers": unknown_customers,
    }


@app.post("/import/customer-regions")
async def import_customer_regions(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Musteri-bolge eslesmesi icin Excel import (bolge_adlari.xlsx).

    Beklenen kolonlar:
      - Customer Name: musteriyi eslestir
      - Region Name: bolge atamasi
    """
    filename = file.filename or ""
    suffix = filename.lower()

    try:
        if suffix.endswith((".xlsx", ".xls", ".xlsm")):
            df = pd.read_excel(file.file)
        elif suffix.endswith(".csv"):
            df = pd.read_csv(file.file)
        else:
            raise HTTPException(
                status_code=400,
                detail="Sadece Excel (.xlsx, .xls) veya CSV dosyasi yukleyin.",
            )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"Dosya okunamadi: {exc}") from exc

    updated = import_customer_regions_df(db, df)
    return {"rows": int(len(df)), "updated_customers": updated}


@app.get("/regions/{region_id}/customers")
def region_customers(
    region_id: int,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """
    Belirli bir bolge icin en riskli musteriler (risk skoruna gore sirali).
    """
    # Region var mi kontrol edelim (Unknown icin -1 kullanmiyoruz burada)
    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        raise HTTPException(status_code=404, detail="Bolge bulunamadi")

    today = date.today()
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

    customers = db.query(Customer).filter(Customer.region_id == region_id).all()
    results: List[Dict] = []
    for c in customers:
        m = _customer_metrics(db, c.customer_no, cost_of_cash, today)
        if m["total_open"] <= 0 and m["loss_30d"] <= 0:
            continue
        m["customer_name"] = c.name
        m["region_id"] = c.region_id
        results.append(m)

    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return {
        "region_id": region.id,
        "region_name": region.name,
        "customers": results[: max(1, limit)],
    }


@app.get("/customers/{customer_no}/invoices")
def customer_invoices(customer_no: str, db: Session = Depends(get_db)):
    """
    Musterinin fatura listesi (open/overdue bilgileriyle).
    """
    today = date.today()
    invoices = db.query(Invoice).filter(Invoice.customer_no == customer_no).all()

    result = []
    for inv in invoices:
        overdue_days = 0
        is_overdue = False
        if inv.due_date is not None:
            diff = (today - inv.due_date).days
            if diff > 0:
                overdue_days = diff
                is_overdue = True

        result.append(
            {
                "invoice_no": inv.invoice_no,
                "invoice_date": inv.invoice_date,
                "due_date": inv.due_date,
                "currency": inv.currency,
                "total_amount": inv.total_amount,
                "open_balance": inv.open_balance,
                "overdue_days": overdue_days,
                "is_overdue": is_overdue,
            }
        )

    return result


@app.get("/customers/{customer_no}/late-payments")
def customer_late_payments(customer_no: str, db: Session = Depends(get_db)):
    """
    Musterinin gec odemeleri (delay_days > 0 olan payments satirlari).
    """
    cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

    # Customer_no ile kayitli musteri adini bul, varsa payments'i isim uzerinden filtrele
    customer = db.query(Customer).filter(Customer.customer_no == customer_no).first()
    if customer and customer.name:
        payments = db.query(Payment).filter(Payment.customer_name == customer.name).all()
    else:
        payments = db.query(Payment).filter(Payment.customer_no == customer_no).all()

    result = []
    for p in payments:
        loss = _get_payment_loss(p, cost_of_cash)
        result.append(
            {
                "payment_id": p.id,
                "ar_invoice_no": p.ar_invoice_no,
                "value_date": p.value_date,
                "delay_days": p.delay_days,
                "applied_amount": p.applied_amount,
                "payment_amount_try": p.payment_amount_try,
                "loss": loss,
            }
        )

    return result


@app.get("/customers/{customer_no}/financial-loss-export")
def customer_financial_loss_export(customer_no: str, db: Session = Depends(get_db)):
    """
    Musterinin finansal kayip hesaplamasini Excel'e aktar.
    Her payment satiri icin detayli hesaplama kolonlari ile.
    """
    try:
        customer = db.query(Customer).filter(Customer.customer_no == customer_no).first()
        if not customer:
            raise HTTPException(status_code=404, detail="Musteri bulunamadi")

        cost_of_cash = get_cost_of_cash_annual(db, default=49.0)

        # Payments satirlarini al (customer_name ile eslestir)
        if customer.name:
            payments = db.query(Payment).filter(Payment.customer_name == customer.name).all()
        else:
            payments = db.query(Payment).filter(Payment.customer_no == customer_no).all()

        # Excel icin detayli satirlar
        rows = []
        for p in payments:
            # Hesaplama detaylari
            invoice_date = p.invoice_date
            payment_date = p.payment_date
            vade = p.vade
            applied_amount = p.applied_amount or 0.0

            # Beklenen odeme tarihi
            expected_date = None
            if invoice_date and vade is not None:
                expected_date = invoice_date + timedelta(days=vade)

            # Gecikme gunu
            delay_days = 0
            if payment_date and expected_date:
                delay_days = max(0, (payment_date - expected_date).days)

            # Günlük oran
            daily_rate = (cost_of_cash / 100.0) / 365.0

            # ADAT (Average Daily Amount of Time)
            adat = delay_days * applied_amount if delay_days > 0 else 0.0

            # Finansal kayip: Excel sütunu varsa onu, yoksa hesaplanan
            loss = _get_payment_loss(p, cost_of_cash)

            rows.append(
                {
                    "Müşteri No": p.customer_no,
                    "Müşteri Adı": p.customer_name or customer.name,
                    "AR Fatura No": p.ar_invoice_no or "",
                    "Fatura Tarihi": invoice_date.strftime("%Y-%m-%d") if invoice_date else "",
                    "Ödeme Tarihi": payment_date.strftime("%Y-%m-%d") if payment_date else "",
                    "Vade (Gün)": vade if vade is not None else "",
                    "Beklenen Ödeme Tarihi": expected_date.strftime("%Y-%m-%d") if expected_date else "",
                    "Gecikme Günü": delay_days,
                    "Uygulanan Tutar (TRY)": applied_amount,
                    "Yıllık Oran (%)": cost_of_cash,
                    "Günlük Oran": daily_rate,
                    "ADAT (Gün × Tutar)": adat,
                    "Finansal Kayıp (TRY)": loss,
                }
            )

        # DataFrame olustur
        df = pd.DataFrame(rows)

        # Excel'e yaz
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Finansal Kayıp Detay", index=False)

        output.seek(0)

        # Dosya adi (Turkce karakterleri temizle)
        customer_name_raw = customer.name or customer_no
        customer_name_safe = _sanitize_filename(customer_name_raw)
        filename = f"Finansal_Kayip_{customer_name_safe}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        # Yukarida olusturulan HTTPException'lari aynen ilet
        raise
    except Exception as e:
        # Debug icin hatayi acik sekilde dondur
        raise HTTPException(status_code=500, detail=f"Excel export hatasi: {e!r}")


@app.get("/settings", tags=["Ayarlar"])
def get_settings(db: Session = Depends(get_db)):
    """
    Güncel sistem parametreleri: Cost of Cash ve **vade farkı (yıllık %)**.
    """
    cost_of_cash_value = get_cost_of_cash_annual(db, default=49.0)
    late_fee_value = get_late_fee_rate_annual(db, default=53.13)
    return {
        "cost_of_cash_annual": cost_of_cash_value,
        "late_fee_rate_annual": late_fee_value,
    }


@app.put("/settings", tags=["Ayarlar"])
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    """
    Parametreleri günceller. **Sadece vade farkı oranını** değiştirmek için gövdeye yalnızca
    `late_fee_rate_annual` yazmanız yeterli (ör. `{"late_fee_rate_annual": 53.13}`).
    """
    if payload.cost_of_cash_annual is None and payload.late_fee_rate_annual is None:
        raise HTTPException(
            status_code=400,
            detail="En az bir alan gönderin: cost_of_cash_annual ve/veya late_fee_rate_annual",
        )
    if payload.cost_of_cash_annual is not None:
        set_cost_of_cash_annual(db, payload.cost_of_cash_annual)
    if payload.late_fee_rate_annual is not None:
        set_late_fee_rate_annual(db, payload.late_fee_rate_annual)
    return {
        "cost_of_cash_annual": get_cost_of_cash_annual(db, default=49.0),
        "late_fee_rate_annual": get_late_fee_rate_annual(db, default=53.13),
    }


@app.post("/actions", response_model=ActionOut)
def create_action(payload: ActionCreate, db: Session = Depends(get_db)):
    """
    Toplantida alinan tek bir musteri aksiyonunu kaydeder.
    Simdilik basit tutuyoruz: owner_user / due_date vs. yok.
    """
    action = Action(
        customer_no=payload.customer_no,
        customer_name=payload.customer_name,
        action_type=payload.action_type,
        note=payload.note,
        status="open",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@app.get("/actions", response_model=List[ActionOut])
def list_actions(
    customer_no: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Kaydedilmis aksiyonlar listesi.
    - customer_no verilirse sadece o musterinin aksiyonlarini dondurur.
    - Simdilik created_at desc sirali, frontend musteribasinda en son kaydi kullanacak.
    """
    query = db.query(Action)
    if customer_no:
        query = query.filter(Action.customer_no == customer_no)
    actions = query.order_by(Action.created_at.desc()).all()
    return actions


# Uvicorn ile calistirmak icin:
# python -m uvicorn app.main:app --reload


