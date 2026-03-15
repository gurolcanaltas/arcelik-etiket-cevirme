# Calisma Kurali

Bu proje tasinacaksa veya baska bir klasorde acilacaksa `node_modules` klasoru tasinmaz.

Standart akis:

1. Proje klasorunu tasiriz.
2. `package.json` ve `pnpm-lock.yaml` dosyalari korunur.
3. Eski `node_modules` kullanilmaz.
4. Yeni klasorde `pnpm install` calistirilir.
5. Sonra `node server.js` veya `pnpm start` ile proje acilir.

Neden boyle:

- Windows bazen `node_modules` icindeki dosyalari kilitler.
- `pnpm` `.pnpm` altinda bagli klasorler ve native paketler kullanir.
- Bu yapilar tasima ve silme sirasinda `Access denied` veya `EPERM` hatasi verebilir.

Kacinilacak seyler:

- `node_modules` klasorunu manuel tasimak
- yari tasinmis `node_modules` ile projeyi calistirmak
- acik PDF veya preview pencereleri varken `output` klasorunu tasimak

Sorun olursa:

1. Acik terminalleri, preview pencerelerini ve editor dev serverlarini kapat.
2. Gerekirse eski `node_modules` sil.
3. Yeni klasorde tekrar `pnpm install` calistir.

Bu proje icin aktif calisma klasoru:

- `C:\\Kişisel Projeler\\Arçelik Etiket`
