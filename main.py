from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Tahsilat Takibi API")

# CORS (istersen buraya frontend domainlerini ekleyebilirsin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "tahsilat_takibi Python backend calisiyor"}


# Örnek statik veri (istersen sonradan veritabanı ile değiştirebiliriz)
collections = [
    {
        "id": 1,
        "musteri": "ABC A.S.",
        "tutar": 150_000,
        "para_birimi": "TRY",
        "vade": "2026-03-15",
        "durum": "beklemede",
    },
    {
        "id": 2,
        "musteri": "XYZ LTD.",
        "tutar": 80_000,
        "para_birimi": "EUR",
        "vade": "2026-03-01",
        "durum": "odendi",
    },
    {
        "id": 3,
        "musteri": "TST HAVACILIK",
        "tutar": 120_000,
        "para_birimi": "USD",
        "vade": "2026-02-28",
        "durum": "gecikti",
    },
]


@app.get("/api/dashboard/summary")
def dashboard_summary():
    toplam_tutar = sum(c["tutar"] for c in collections)
    odendi_tutar = sum(c["tutar"] for c in collections if c["durum"] == "odendi")
    bekleyen_tutar = sum(c["tutar"] for c in collections if c["durum"] == "beklemede")
    geciken_tutar = sum(c["tutar"] for c in collections if c["durum"] == "gecikti")

    return {
        "toplamTutar": toplam_tutar,
        "odendiTutar": odendi_tutar,
        "bekleyenTutar": bekleyen_tutar,
        "gecikenTutar": geciken_tutar,
        "birim": "karisik",  # farkli para birimleri oldugu icin
    }


@app.get("/api/dashboard/collections")
def list_collections():
    return collections


@app.get("/api/dashboard/collections/{item_id}")
def get_collection(item_id: int):
    for item in collections:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Kayit bulunamadi")


# Uvicorn ile calistirmak icin:
# uvicorn main:app --reload --host 0.0.0.0 --port 4000







