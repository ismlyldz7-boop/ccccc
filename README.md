# SkinLand Charm Scanner

Windows uygulaması: Skin.Land'deki CS2 item fiyatlarını tarar ve charm içeren itemleri listeler.
Program satın alma/satış işlemi yapmaz; sadece analiz ve Skin.Land bağlantısı gösterir.

## Kurulum / EXE oluşturma

1. GitHub'da yeni bir repository oluşturun.
2. Bu klasördeki dosyaları repository'ye yükleyin.
3. GitHub > Actions > Build Windows EXE > Run workflow.
4. İşlem bittiğinde Artifacts bölümünden `SkinLandCharmScanner-Windows` ZIP'ini indirin.
5. ZIP'i açıp `SkinLandCharmScanner.exe` dosyasını çalıştırın.

## API

Uygulama SteamWebAPI'nin Skin.Land endpointini kullanır:
`/market/skinland/prices`

API anahtarınızı uygulama içinden girin. Anahtar kaynak koda gömülmez.

Not: SteamWebAPI verisi yaklaşık 5 dakikalık yenileme aralığıyla sunuluyor. Bu nedenle uygulama çok sık tarama yapsa bile kaynağın yenilenme hızından daha güncel veri garanti edilmez.

## Charm tespiti

İlk sürüm charm adlarını yapılandırılabilir `charms.json` listesinden tespit eder.
Yeni charm çıktığında listeye eklenebilir. Otomatik overpay öğrenme sistemi sonraki sürümde eklenebilir.
