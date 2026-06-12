import re
import pdfplumber
from datetime import datetime

def is_abnormal(deger, referans_str):
    try:
        if not referans_str or referans_str.strip() == "": return False
        range_match = re.search(r"(\d+\.?\d*)\s*-\s*(\d+\.?\d*)", referans_str)
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            return not (low <= deger <= high)
        return False
    except: return False

def parse_pdf_data(pdf_stream):
    sonuclar_listesi = []
    hasta_adi = "Bilinmiyor"
    genel_tarih = None
    try:
        with pdfplumber.open(pdf_stream) as pdf:
            full_text = ""
            for page in pdf.pages: full_text += page.extract_text() + "\n"
            
            isim_kalibi = re.search(r"Adı/Soyadı:\s*(.+?)\s+(Cinsiyet|Tarih)", full_text)
            if not isim_kalibi: isim_kalibi = re.search(r"Adı Soyadı:\s*(.+)", full_text)
            if isim_kalibi: hasta_adi = isim_kalibi.group(1).strip()

            tarih_kalibi = re.search(r"Tarih:\s*(\d{1,2}\.\d{1,2}\.\d{4})", full_text)
            if tarih_kalibi: genel_tarih = tarih_kalibi.group(1).strip()
            if not genel_tarih: genel_tarih = datetime.now().strftime("%d.%m.%Y")

            lines = full_text.split('\n')
            # Satır yakalama kalıbı
            row_pattern = re.compile(r"^(?:(\d{1,2}\.\d{1,2}\.\d{4})\s+)?(.+?)\s+(\d+\.?\d*)\s+(\S+)\s+(.*)$")

            for line in lines:
                match = row_pattern.search(line.strip())
                if match:
                    isim = match.group(2).strip()
                    
                    # --- KRİTİK FİLTRELEME GÜNCELLEMESİ ---
                    
                    # 1. HARF KONTROLÜ: İsimde en az bir harf (a-z, A-Z) olmalı. 
                    # Bu sayede "0", "0.38 -", ">=" gibi sadece rakam/sembol içeren çöpler elenir.
                    if not any(c.isalpha() for c in isim): continue
                    
                    # 2. UZUNLUK VE ÖZEL KELİME KONTROLÜ
                    if len(isim) > 45 or len(isim) < 2: continue
                    
                    yasakli = ["yaş altı", "trimestr", "trimester", "formülüne", "hesaplanmıştır", "dikkat", "0 850"]
                    if any(k in isim.lower() for k in yasakli): continue
                    
                    # 3. SAYFA VE SAAT KONTROLLERİ
                    if "Sayfa" in line or "Saat" in isim: continue
                    
                    sonuclar_listesi.append({
                        "Tarih": match.group(1) if match.group(1) else genel_tarih,
                        "Tahlil Adı": isim, 
                        "Değer": float(match.group(3)),
                        "Birim": match.group(4).strip(), 
                        "Referans Aralığı": match.group(5).strip()
                    })
        return hasta_adi, sonuclar_listesi
    except Exception as e:
        print(f"PDF Hatası: {e}")
        return None, []