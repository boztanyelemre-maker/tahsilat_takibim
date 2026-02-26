# Render Deployment Rehberi

## Adım 1: PostgreSQL Database Oluştur

1. Render Dashboard'a giriş yap: https://dashboard.render.com
2. **New +** butonuna tıkla
3. **PostgreSQL** seçeneğini seç
4. Formu doldur:
   - **Name**: `alacak360-db` (veya istediğin isim)
   - **Database**: `tahsilat` (veya istediğin isim)
   - **User**: (otomatik oluşturulur)
   - **Region**: En yakın region'ı seç (örn: Frankfurt, EU)
   - **PostgreSQL Version**: 15 (veya en son)
   - **Plan**: Free tier (başlangıç için yeterli)
5. **Create Database** butonuna tıkla
6. Database oluşturulduktan sonra:
   - **Connections** sekmesine git
   - **Internal Database URL**'yi kopyala
   - Örnek format: `postgresql://user:password@host:5432/dbname`
   - ⚠️ Bu URL'yi sakla, Web Service'te kullanacaksın!

## Adım 2: Web Service Oluştur

1. Render Dashboard'da **New +** butonuna tıkla
2. **Web Service** seçeneğini seç
3. Repository'ni bağla:
   - GitHub/GitLab/Bitbucket hesabını bağla (ilk seferde)
   - Repository'ni seç: `tahsilat_takibi` (veya repo adın)
4. Formu doldur:
   - **Name**: `alacak360-backend`
   - **Environment**: `Python 3`
   - **Region**: Database ile aynı region'ı seç
   - **Branch**: `main` (veya `master`)
   - **Root Directory**: (boş bırak)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free tier (başlangıç için)

## Adım 3: Environment Variables Ekle

Web Service oluşturulduktan sonra:

1. Web Service sayfasında **Environment** sekmesine git
2. **Add Environment Variable** butonuna tıkla
3. Şu değişkeni ekle:
   - **Key**: `DATABASE_URL`
   - **Value**: Adım 1'de kopyaladığın **Internal Database URL**
   - Örnek: `postgresql://user:password@dpg-xxxxx-a.frankfurt-postgres.render.com/tahsilat`
4. **Save Changes** butonuna tıkla

## Adım 4: Deploy

1. Render otomatik olarak deploy başlatacak
2. **Events** sekmesinden deploy durumunu takip et
3. İlk deploy 5-10 dakika sürebilir
4. Deploy tamamlandığında **URL**'yi kopyala
   - Örnek: `https://alacak360-backend.onrender.com`

## Adım 5: Frontend'i Güncelle

1. `static/index.html` dosyasını aç
2. 234. satırı bul:
   ```javascript
   const API_BASE = "https://your-app-name.onrender.com";
   ```
3. Render URL'sini yaz:
   ```javascript
   const API_BASE = "https://alacak360-backend.onrender.com"; // Gerçek URL'yi buraya yaz
   ```
4. Değişikliği commit et ve push et
5. Netlify otomatik deploy edecek

## Adım 6: Test Et

1. **Backend Test**:
   - `https://alacak360-backend.onrender.com/health`
   - Cevap: `{"status": "ok", "message": "ALACAK360 backend calisiyor"}`

2. **Frontend Test**:
   - `https://tahsilattakip.netlify.app`
   - Dashboard verileri görünmeli

## Sorun Giderme

### Database bağlantı hatası
- `DATABASE_URL` environment variable'ının doğru olduğundan emin ol
- Internal Database URL kullan (External değil!)

### CORS hatası
- `app/main.py` dosyasında CORS middleware zaten ekli
- Production'da `allow_origins` listesini Netlify domain'i ile sınırla

### Deploy hatası
- `requirements.txt` dosyasının doğru olduğundan emin ol
- Build loglarını kontrol et: Web Service → **Logs** sekmesi

## Önemli Notlar

- ⚠️ Free tier'da uygulama 15 dakika kullanılmazsa "sleep" moduna geçer
- İlk istek 30-60 saniye sürebilir (cold start)
- Production için paid plan önerilir
- Database backup'ları otomatik alınır (free tier'da 7 gün)



