import os
import json
import re 
from groq import Groq
from dotenv import load_dotenv

# .env dosyasındaki API anahtarını yükle
load_dotenv()

# Groq İstemcisini Başlat
client = Groq()

def belirle_niyet(soru):
    """
    1. AŞAMA: NİYET ANALİZİ (INTENT DETECTION)
    """
    system_prompt = """
    Sen bir niyet analiz (intent detection) asistanısın. Görevin, kullanıcının sorduğu sorunun kategorisini belirlemektir.
    
    Kurallar:
    - Eğer kullanıcı "benim değerim", "tahlilim", "şekerim kaç", "neden yüksek çıkmış", "sonucum" gibi KENDİ sağlık verilerini soruyorsa sadece "TAHLIL" yaz.
    - Eğer kullanıcı "glikoz nedir", "diyabet nasıl beslenmeli", "b12 eksikliği belirtileri" gibi GENEL tıbbi bilgiler soruyorsa sadece "BILGI" yaz.
    
    Çıktı sadece TAHLIL veya BILGI kelimesinden biri olmalıdır. Başka hiçbir açıklama yapma.
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": soru}
            ],
            temperature=0.0,
            max_tokens=10
        )
        niyet = completion.choices[0].message.content.strip().upper()
        
        if "BILGI" in niyet:
            return "BILGI"
        return "TAHLIL"
        
    except Exception as e:
        print(f"[AI HATA - Niyet Analizi]: {e}")
        return "TAHLIL"

def ai_asistan_yanitla(soru, niyet, profil_ozeti=None, tahlil_verileri=None, gecmis_mesajlar=None):
    """
    2. AŞAMA: DİNAMİK BAĞLAM VE YANIT ÜRETİMİ (HAFIZA DESTEĞİ EKLENDİ)
    """
    
    system_prompt = """Sen profesyonel, empatik ve güvenilir bir tıbbi asistansın.
    Amacın kullanıcının sağlık verilerini anlamasına yardımcı olmak veya genel tıbbi sorularını yanıtlamaktır.
    
    KESİN KURALLAR:
    1. ÇOK KISA VE ÖZ OL: Yanıtlarını olabildiğince kısa, net ve akıcı bir Türkçe ile ver. Uzun paragraflardan ve gereksiz tıbbi terimlerden kaçın. En fazla 3-4 cümle veya kısa maddeler kullan.
    2. DİL: Yanıtını KESİNLİKLE VE SADECE TÜRKÇE ver. Asla İngilizce kelime kullanma.
    3. SINIRLAR: Asla kesin bir tıbbi teşhis koyma ve ilaç önerme.
    5. TARİH DUYARLILIĞI: Sana sunulan tahlil verileri [GG.AA.YYYY] formatında tarihler içerir. Eğer kullanıcı spesifik bir tarih belirtirse (örneğin: 'son tahlilim' veya 'Mart ayındaki sonucum'), sadece o tarihe ait verilere odaklanarak yanıt ver. Eğer tarih belirtmezse genel bir değerlendirme yap.
    """

    # --- MESAJ LİSTESİNİ OLUŞTURUYORUZ ---
    messages = [{"role": "system", "content": system_prompt}]

    # 1. HAFIZA: Eğer Flutter'dan gelen bir geçmiş varsa, son 6 mesajı ekliyor (Kotayı aşmamak için)
    if gecmis_mesajlar:
        messages.extend(gecmis_mesajlar[-6:])

    # 2. BAĞLAM (Context): Yeni soruyu ve verileri hazırlıyor
    user_context = ""
    if niyet == "TAHLIL":
        if profil_ozeti:
            user_context += f"[KULLANICI PROFİLİ]: {profil_ozeti}\n"
        if tahlil_verileri:
            user_context += f"[TAHLİL GEÇMİŞİ]:\n{tahlil_verileri}\n\n"
    
    user_context += f"Kullanıcının Yeni Sorusu: {soru}"

    # 3. GÜNCEL SORUYU EKLE
    messages.append({"role": "user", "content": user_context})

    try:
        completion = client.chat.completions.create(
            model="qwen/qwen3-32b", 
            messages=messages, # Artık sadece soru değil, tüm geçmiş gidiyor
            temperature=0.4,
            max_tokens=1024
        )
        
        ham_cevap = completion.choices[0].message.content
        
        # --- GÜÇLENDİRİLMİŞ TEMİZLEME FİLTRESİ ---
        temiz_cevap = re.sub(r'<(think|thought)>[\s\S]*?(?:<\/\1>|$)', '', ham_cevap, flags=re.IGNORECASE).strip()
        
        if not temiz_cevap:
            temiz_cevap = ham_cevap.replace("<think>", "").replace("</think>", "").strip()

        return temiz_cevap
        
    except Exception as e:
        print(f"[AI HATA - Yanıt Üretimi]: {e}")
        return "Üzgünüm, şu anda yapay zeka servisine ulaşılamıyor. Lütfen daha sonra tekrar deneyiniz."