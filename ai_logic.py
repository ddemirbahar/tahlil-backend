import os
import json
import re 
from groq import Groq
from dotenv import load_dotenv

# .env dosyasındaki API anahtarını yükle
load_dotenv()

# Groq İstemcisini Başlat
client = Groq()

def temizle_markdown(metin):
    if not metin:
        return metin

    # Kalın/italik markdown işaretlerini temizle
    metin = metin.replace("**", "")
    metin = metin.replace("__", "")
    metin = metin.replace("*", "")

    # Başlık işaretlerini temizle
    metin = re.sub(r"^\s*#+\s*", "", metin, flags=re.MULTILINE)

    # Satır başındaki madde işaretlerini temizle
    metin = re.sub(r"^\s*-\s+", "", metin, flags=re.MULTILINE)

    # Fazla boş satırları azalt
    metin = re.sub(r"\n{3,}", "\n\n", metin)

    return metin.strip()

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
Amacın kullanıcının sağlık verilerini anlamasına yardımcı olmak veya genel tıbbi sorularını sade bir dille yanıtlamaktır.

Yanıtlarını kullanıcı arayüzünde doğrudan gösterilecek şekilde sade düz metin olarak üret.
Markdown kullanma. Kalın yazı için ** işareti, başlık için # işareti, maddeleme için * veya - işareti kullanma.
Gerekirse bilgileri kısa satırlar halinde ver, ancak özel biçimlendirme işareti kullanma.

KESİN KURALLAR:
1. ÇOK KISA VE ÖZ OL: Yanıtlarını kısa, net ve akıcı Türkçe ile ver. Uzun paragraflardan ve gereksiz tıbbi terimlerden kaçın.
2. DİL: Yanıtını kesinlikle Türkçe ver. İngilizce terim gerekiyorsa yalnızca çok bilinen teknik adları kullan.
3. SINIRLAR: Kesin tıbbi teşhis koyma, ilaç adı, ilaç dozu veya tedavi planı önerme.
4. VERİYE BAĞLI KAL: Sana verilen tahlil verilerinde bulunmayan parametre, değer, tarih veya referans aralığı hakkında kesin yorum yapma. Değer uydurma, değiştirme veya yuvarlama.
5. BİLGİ DOĞRULUĞU: Bilmediğin veya emin olmadığın tıbbi bilgiyi uydurma. Emin değilsen kullanıcıyı sağlık uzmanına yönlendir. Vitamin, mineral veya tahlil parametresi açıklarken yanlış eş anlamlı ad verme.
6. NORMAL YORUMU: Genel sağlık durumunun normal olduğunu söyleme. Yalnızca verilen tahlil değerlerinin referans aralığına göre ön değerlendirme yap.
7. NİYET AYRIMI: Soru genel sağlık bilgisiyle ilgiliyse genel açıklama yap. Soru kişisel tahlil sonucuyla ilgiliyse yalnızca verilen tahlil verilerini ve kullanıcı profilini dikkate al.
8. TARİH DUYARLILIĞI: Sana sunulan tahlil verileri [GG.AA.YYYY] formatında tarihler içerir. Kullanıcı belirli bir tarih veya “son tahlilim” gibi ifade kullanırsa ilgili tarihe odaklan. Tarih belirtmezse genel bir değerlendirme yap.
9. GÜVENLİK: Acil olabilecek göğüs ağrısı, nefes darlığı, bayılma, bilinç bulanıklığı, şiddetli kanama veya çok kötü hissetme gibi durumlarda kullanıcıyı vakit kaybetmeden sağlık kuruluşuna başvurmaya yönlendir.
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

        temiz_cevap = temizle_markdown(temiz_cevap)

        return temiz_cevap
        
    except Exception as e:
        print(f"[AI HATA - Yanıt Üretimi]: {e}")
        return "Üzgünüm, şu anda yapay zeka servisine ulaşılamıyor. Lütfen daha sonra tekrar deneyiniz."