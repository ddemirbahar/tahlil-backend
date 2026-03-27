import re
import pdfplumber
from datetime import datetime
import os
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

# Model ve Dosya Yolu
model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
FAISS_INDEX_PATH = "tahlil_hafizasi.index"

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

def metni_vektore_cevir(metin):
    return model.encode([metin])[0]

def faiss_indeksine_ekle(vektor, sqlite_id):
    boyut = vektor.shape[0]
    if os.path.exists(FAISS_INDEX_PATH):
        index = faiss.read_index(FAISS_INDEX_PATH)
    else:
        index = faiss.IndexIDMap(faiss.IndexFlatL2(boyut))

    vektor_hazir = np.array([vektor]).astype('float32')
    id_hazir = np.array([sqlite_id]).astype('int64')

    index.add_with_ids(vektor_hazir, id_hazir)
    faiss.write_index(index, FAISS_INDEX_PATH)

# --- YENİ: FAISS İÇİNDE ARAMA YAPMA FONKSİYONU ---
def faiss_ara(soru_metni, k=3):
    """
    Kullanıcının sorusuna en yakın k adet tahlil kaydının SQLite ID'sini döner.
    """
    if not os.path.exists(FAISS_INDEX_PATH):
        return []

    index = faiss.read_index(FAISS_INDEX_PATH)
    soru_vektoru = np.array([metni_vektore_cevir(soru_metni)]).astype('float32')
    
    # L2 mesafesine göre en yakın k sonucu bul (distances: uzaklık, indices: SQLite ID'leri)
    distances, indices = index.search(soru_vektoru, k)
    
    # -1 olan (boş) sonuçları temizleyip ID listesini döndür
    return [int(idx) for idx in indices[0] if idx != -1]
# ------------------------------------------------

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
            row_pattern = re.compile(r"^(?:(\d{1,2}\.\d{1,2}\.\d{4})\s+)?(.+?)\s+(\d+\.?\d*)\s+(\S+)\s+(.*)$")

            for line in lines:
                match = row_pattern.search(line.strip())
                if match:
                    isim = match.group(2).strip()
                    if "Sayfa" in line or "Saat" in isim: continue
                    sonuclar_listesi.append({
                        "Tarih": match.group(1) if match.group(1) else genel_tarih,
                        "Tahlil Adı": isim, "Değer": float(match.group(3)),
                        "Birim": match.group(4).strip(), "Referans Aralığı": match.group(5).strip()
                    })
        return hasta_adi, sonuclar_listesi
    except Exception as e:
        print(f"PDF Hatası: {e}")
        return None, []