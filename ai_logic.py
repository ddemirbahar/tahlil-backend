import os
import json
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq()


def temizle_markdown(metin):
    if not metin:
        return metin

    metin = metin.replace("**", "")
    metin = metin.replace("__", "")
    metin = metin.replace("*", "")
    metin = re.sub(r"^\s*#+\s*", "", metin, flags=re.MULTILINE)
    metin = re.sub(r"^\s*-\s+", "", metin, flags=re.MULTILINE)
    metin = re.sub(r"\n{3,}", "\n\n", metin)

    return metin.strip()


def belirle_niyet(soru):
    system_prompt = """
Sen bir niyet analiz (intent detection) asistanısın.
Görevin, kullanıcının sorduğu sorunun kategorisini belirlemektir.

Kurallar:

- Kullanıcı kendi sağlık verileri, kendi tahlil sonuçları,
  kendi değerleri, kendi geçmiş sonuçları veya kendi sonuçlarındaki
  değişimler hakkında soru soruyorsa "TAHLIL" yaz.

- Örneğin:
  "Benim B12 değerim kaç?"
  "Benim şekerim yüksek mi?"
  "Tahlillerimi değerlendir"
  "Son tahlilimde ne anormal?"
  "Geçen tahlilimle karşılaştır"
  "Bu değerim neden yüksek çıkmış?"
  "Tahlillerimde gastritle ilgili bir şey görüyor musun?"
  gibi sorular TAHLIL kategorisidir.

- Kullanıcı genel tıbbi bilgi soruyorsa "BILGI" yaz.

- Örneğin:
  "D vitamini nedir?"
  "Gastrit nedir?"
  "B12 eksikliği belirtileri nelerdir?"
  "Glikoz nedir?"
  "Diyabet nedir?"
  gibi sorular BILGI kategorisidir.

Çıktı sadece TAHLIL veya BILGI kelimelerinden biri olmalıdır.
Başka hiçbir açıklama yapma.
"""

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": soru}
            ],
            temperature=0.0,
            max_completion_tokens=100,
            reasoning_effort="low",
            include_reasoning=False
        )

        print(f"[AI INTENT RESPONSE]: {completion}")
        print(f"[AI INTENT MESSAGE]: {completion.choices[0].message}")

        ham_niyet = completion.choices[0].message.content or ""
        ham_niyet = ham_niyet.strip().upper()

        print(f"[AI INTENT RAW]: {repr(ham_niyet)}")

        if "BILGI" in ham_niyet:
            return "BILGI"

        if "TAHLIL" in ham_niyet:
            return "TAHLIL"

        return "BILGI"

    except Exception as e:
        print(f"[AI HATA - Niyet Analizi]: {e}")
        return "BILGI"


def ai_asistan_yanitla(
    soru,
    niyet,
    profil_ozeti=None,
    tahlil_verileri=None,
    gecmis_mesajlar=None
):
    system_prompt = """
Sen profesyonel, empatik ve güvenilir bir tıbbi asistansın.

Amacın kullanıcının sağlık verilerini anlamasına yardımcı olmak
veya genel tıbbi sorularını sade bir dille yanıtlamaktır.

Yanıtlarını kullanıcı arayüzünde doğrudan gösterilecek şekilde
sade düz metin olarak üret.

Markdown kullanma.
Kalın yazı için ** işareti,
başlık için # işareti,
maddeleme için * veya - işareti kullanma.

Gerekirse bilgileri kısa satırlar halinde ver.
Özel biçimlendirme işareti kullanma.

KESİN KURALLAR:

1. KISA VE ÖZ OL:
Yanıtlarını kısa, net ve akıcı Türkçe ile ver.
Gereksiz uzun açıklamalardan kaçın.

2. DİL:
Yanıtını kesinlikle Türkçe ver.
İngilizce terim gerekiyorsa yalnızca gerekli teknik terimleri kullan.

3. SINIRLAR:
Kesin tıbbi teşhis koyma.
İlaç adı, ilaç dozu veya kişiye özel tedavi planı önerme.

4. VERİYE BAĞLI KAL:
Sana verilen tahlil verilerinde bulunmayan parametre,
değer, tarih veya referans aralığı hakkında kesin yorum yapma.

Değer uydurma, değiştirme veya yuvarlama.

5. BİLGİ DOĞRULUĞU:
Bilmediğin veya emin olmadığın tıbbi bilgiyi uydurma.
Belirsizlik varsa bunu açıkça belirt.

6. NORMAL YORUMU:
Kullanıcının genel sağlık durumunun normal olduğunu söyleme.
Yalnızca verilen tahlil değerlerinin referans aralıklarına göre
ön değerlendirme yap.

7. NİYET AYRIMI:
Soru genel sağlık bilgisiyle ilgiliyse genel açıklama yap.

Soru kişisel tahlil sonucuyla ilgiliyse verilen tahlil verilerini,
kullanıcı profilini ve konuşma bağlamını dikkate al.

8. TARİH DUYARLILIĞI:
Tahlil verilerindeki tarihleri dikkate al.

Kullanıcı belirli bir tarih soruyorsa ilgili tarihe odaklan.

"Son tahlilim", "önceki tahlilim" veya
"geçen tahlilim" gibi ifadelerde mevcut tahlil geçmişindeki
uygun tarih ve sonuçları kullan.

Tarih veya veri bulunmuyorsa tahminde bulunma.

9. DEĞİŞİM ANALİZİ:
Kullanıcı iki veya daha fazla tahlili karşılaştırıyorsa
verilen sonuçları tarih sırasına göre değerlendir.

Değerin arttığını veya azaldığını yalnızca verilen veriler
bunu gösteriyorsa söyle.

10. BAĞLAM:
Önceki mesajlarda konuşulan konu mevcut soruyla ilgiliyse
önceki konuşma bağlamını dikkate al.

Ancak önceki konuşmada bulunmayan bir bilgiyi varmış gibi kabul etme.

11. GÜVENLİK:
Acil olabilecek göğüs ağrısı, nefes darlığı, bayılma,
bilinç bulanıklığı, şiddetli kanama veya çok kötü hissetme
gibi durumlarda kullanıcıyı vakit kaybetmeden sağlık kuruluşuna
başvurmaya yönlendir.
"""

    messages = [{"role": "system", "content": system_prompt}]

    if gecmis_mesajlar:
        messages.extend(gecmis_mesajlar[-6:])

    user_context = ""

    if niyet == "TAHLIL":
        if profil_ozeti:
            user_context += (
                f"[KULLANICI PROFİLİ]:\n"
                f"{profil_ozeti}\n\n"
            )

        if tahlil_verileri:
            user_context += (
                f"[TAHLİL GEÇMİŞİ]:\n"
                f"{tahlil_verileri}\n\n"
            )
    else:
        user_context += "[SORU TÜRÜ]: GENEL BİLGİ\n\n"

    user_context += (
        f"[KULLANICININ YENİ SORUSU]:\n"
        f"{soru}"
    )

    messages.append({
        "role": "user",
        "content": user_context
    })

    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.4,
            max_tokens=1024,
            reasoning_effort="medium",
            include_reasoning=False
        )

        ham_cevap = completion.choices[0].message.content

        temiz_cevap = re.sub(
            r'<(think|thought)>[\s\S]*?(?:</\1>|$)',
            '',
            ham_cevap,
            flags=re.IGNORECASE
        ).strip()

        if not temiz_cevap:
            temiz_cevap = (
                ham_cevap
                .replace("<think>", "")
                .replace("</think>", "")
                .strip()
            )

        temiz_cevap = temizle_markdown(temiz_cevap)

        return temiz_cevap

    except Exception as e:
        print(f"[AI HATA - Yanıt Üretimi]: {e}")

        return (
            "Üzgünüm, şu anda yapay zeka servisine ulaşılamıyor. "
            "Lütfen daha sonra tekrar deneyiniz."
        )