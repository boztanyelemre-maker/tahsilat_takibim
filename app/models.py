from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String

from .db import Base


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)


class Customer(Base):
    __tablename__ = "customers"

    customer_no = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    region_id = Column(Integer, ForeignKey("regions.id"))


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_no = Column(String, primary_key=True, index=True)
    customer_no = Column(String, ForeignKey("customers.customer_no"))
    # Aging dosyasindaki Customer Name bilgisini faturaya da yaziyoruz
    customer_name = Column(String)
    invoice_date = Column(Date)
    due_date = Column(Date)
    # Vade gun sayisi: due_date - invoice_date
    vade = Column(Integer)
    currency = Column(String)
    total_amount = Column(Float)
    open_balance = Column(Float)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    customer_no = Column(String)
    # Payments (data) dosyasindaki Müsteri Adi bilgisi
    customer_name = Column(String)
    # Excel'den gelen fatura tarihi ve odeme tarihi
    invoice_date = Column(Date)
    payment_date = Column(Date)
    ar_invoice_no = Column(String, index=True)
    value_date = Column(Date)
    delay_days = Column(Integer)
    # Ilgili faturadan gelen vade (gun) bilgisini de payments uzerinde tutalim
    vade = Column(Integer)
    applied_amount = Column(Float)
    payment_amount_try = Column(Float)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Float)



