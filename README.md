# PDF Editor App

Bu proje, yuklenen bir PDF dosyasindaki gercek metin katmanini sayfa bazli analiz eder ve desteklenen alanlarda content stream uzerinden dogrudan metin degisikligi yapar.

## Neler Yapabilir

- PDF yukleme ve sayfa bazli analiz
- Makine ismi, makine turu, tarih ve fiyat alanlarini odakli duzenleme
- Duz fiyatli ve parolu fiyatli sayfa tiplerini ayri ele alma
- PDF uzerine overlay cizmeden gercek text-layer degisikligi
- Eksik karakterlerde fallback font kullanimi

## Teknoloji

- Node.js + Express
- Python PDF engine (`pikepdf`, `PyMuPDF`, `fonttools`)
- Frontend: vanilla HTML / CSS / JS

## Kurulum

```bash
pnpm install
```

Python bagimliliklari:

```bash
.\\tools\\python311\\python.exe -m pip install pymupdf pikepdf fonttools pytest
```

## Calistirma

```bash
node server.js
```

Uygulama varsayilan olarak [http://localhost:4678](http://localhost:4678) adresinde acilir.

## Proje Yapisi

- `server.js`: HTTP API ve dosya akisi
- `tools/pdf_engine.py`: analiz ve gercek PDF metin guncelleme motoru
- `public/`: arayuz
- `assets/fonts/`: fallback fontlar

## Notlar

- PDF uzerine beyaz kutu cizilip ustune yazilmaz; desteklenen alanlarda mevcut text operatorleri dogrudan degistirilir.
- Font subset'i icinde bulunmayan karakterler varsa uygun fallback font denenir; yine desteklenmiyorsa alan hata verir.
- V1 kapsaminda tek satirli kodlar, fiyatlar, tarih alanlari ve kisa basliklar hedeflenmistir.
