import pdfplumber
import os
import re  # Regular Expressions modülü
import json 

# Test edilecek PDF dosyasının adı
pdf_dosyasi_adi = "ornek.pdf"

print(f"'{pdf_dosyasi_adi}' dosyası işleniyor...")

if not os.path.exists(pdf_dosyasi_adi):
    print(f"HATA: '{pdf_dosyasi_adi}' adında bir dosya bulunamadı.")
else:
    try:
        with pdfplumber.open(pdf_dosyasi_adi) as pdf:
            ilk_sayfa = pdf.pages[0]
            ham_metin = ilk_sayfa.extract_text()

            print("Ham metin başarıyla çekildi. Şimdi veriler ayrıştırılıyor...")

            # 1. Hasta Adını Bulma
            hasta_adi = "Bilinmiyor"
            isim_kalibi = re.search(r"Adı Soyadı:\s*(.+)", ham_metin)
            if isim_kalibi:
                hasta_adi = isim_kalibi.group(1).strip()

            print(f"Hasta Adı: {hasta_adi}")

            # 2. Tahlil Sonuçlarını Bulma
            
            tahlil_kalibi = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{4})\s+(.+?)\s+(\d+\.?\d*)\s+(\S+)\s+(.+)$", re.MULTILINE)
            
            sonuclar_listesi = []

            bulunanlar = tahlil_kalibi.findall(ham_metin)

            for eslesme in bulunanlar:
                
                sonuc_detayi = {
                    "Tarih": eslesme[0].strip(),
                    "Tahlil Adı": eslesme[1].strip(),
                    "Değer": float(eslesme[2].strip()), # Sayıya çevir
                    "Birim": eslesme[3].strip(),
                    "Referans Aralığı": eslesme[4].strip()
                }
                sonuclar_listesi.append(sonuc_detayi)

            # Çekilen veriyi terminale güzel bir formatta yazdır
            if sonuclar_listesi:
                print(f"\n--- {len(sonuclar_listesi)} ADET TAHLİL SONUCU BAŞARIYLA AYRIŞTIRILDI ---")
                
                print(json.dumps(sonuclar_listesi, indent=2, ensure_ascii=False))
                
                print("\nİşlem başarıyla tamamlandı.")
            else:
                print("\nPDF içinde tahlil kalıbına uyan hiçbir sonuç bulunamadı. (Kalıp 3. deneme)")
                print("--- HAM METİN (Hata Ayıklama İçin) ---")
                print(ham_metin)
                print("--- HAM METİN SONU ---")

    except Exception as e:
        print(f"PDF dosyası işlenirken beklenmedik bir hata oluştu: {e}")