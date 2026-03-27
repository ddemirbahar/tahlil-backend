import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# --- GÜVENLİK VE YAPAY ZEKA KÜTÜPHANELERİ ---
from dotenv import load_dotenv
from groq import Groq

# Proje klasöründeki .env dosyasını yükle
load_dotenv()

# Modeller ve yardımcı fonksiyonlar (utils.py ve models.py'den)
from models import db, User, TahlilRaporu, TestParametresi, Hastalik
from utils import parse_pdf_data, is_abnormal, metni_vektore_cevir, faiss_indeksine_ekle, faiss_ara

app = Flask(__name__)
CORS(app)

# --- GROQ API YAPILANDIRMASI ---
# Anahtar artık .env dosyasından güvenli bir şekilde çekiliyor
GROQ_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_KEY)

# --- LOGLAMA AYARLARI ---
logging.basicConfig(level=logging.INFO)
logger = app.logger

# Veritabanı Yolu Ayarları
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'tahliller.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# --- VERİTABANI VE SEED VERİLERİ ---
def veritabani_baslat():
    with app.app_context():
        db.create_all()
        if not Hastalik.query.first():
            temel_hastaliklar = [
                "Diyabet (Şeker)", "Hipertansiyon (Tansiyon)", "Kalp Yetmezliği",
                "KOAH / Astım", "Böbrek Yetmezliği", "Tiroid (Guatr/Haşimato)",
                "Yüksek Kolesterol", "Demir Eksikliği Anemisi", "B12 Eksikliği",
                "Karaciğer Yağlanması"
            ]
            for h_adi in temel_hastaliklar:
                db.session.add(Hastalik(ad=h_adi))
            db.session.commit()
            print(">>> Veritabanı ve hastalık listesi hazır.")

# --- KULLANICI İŞLEMLERİ (AUTH) ---

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"hata": "Kullanıcı adı zaten alınmış"}), 400
    
    new_user = User(
        username=data['username'], 
        password_hash=generate_password_hash(data['password']),
        email=data.get('email'),
        dogum_yili=data.get('dogum_yili'),
        cinsiyet=data.get('cinsiyet'),
        hastaliklar=data.get('hastaliklar')
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"mesaj": "Kayıt başarılı"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        return jsonify({"mesaj": "Giriş başarılı", "username": user.username}), 200
    return jsonify({"hata": "Hatalı kullanıcı adı veya şifre"}), 401

@app.route('/user_info', methods=['GET'])
def get_user_info():
    username = request.args.get('username')
    user = User.query.filter_by(username=username).first()
    if not user: return jsonify({"hata": "Kullanıcı bulunamadı"}), 404
    return jsonify({
        "username": user.username, "email": user.email,
        "dogum_yili": user.dogum_yili, "cinsiyet": user.cinsiyet,
        "hastaliklar": user.hastaliklar
    }), 200

# --- TAHLİL YÜKLEME VE HİBRİT KAYIT (SQLite + FAISS) ---

@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.form.get('username')
    user = User.query.filter_by(username=username).first()
    if not user: return jsonify({"hata": "Kullanıcı girişi gerekli"}), 401

    file = request.files['file']
    try:
        hasta_adi, sonuclar = parse_pdf_data(file.stream)
        if not sonuclar: return jsonify({"hata": "PDF içeriği okunamadı"}), 400
        
        yeni_rapor = TahlilRaporu(hasta_adi=hasta_adi, user_id=user.id)
        db.session.add(yeni_rapor)
        db.session.commit()
        
        for sonuc in sonuclar:
            # 1. SQLite Kaydı
            p = TestParametresi(
                tahlil_adi=sonuc["Tahlil Adı"], deger=sonuc["Değer"], 
                birim=sonuc["Birim"], referans_araligi=sonuc["Referans Aralığı"], 
                tahlil_tarihi=sonuc["Tarih"], rapor_id=yeni_rapor.id
            )
            db.session.add(p)
            db.session.commit()

            # 2. FAISS Vektör Kaydı (RAG Hazırlığı)
            tahlil_metni = f"Tahlil: {p.tahlil_adi}, Değer: {p.deger} {p.birim}, Referans: {p.referans_araligi}"
            vektor = metni_vektore_cevir(tahlil_metni)
            faiss_indeksine_ekle(vektor, p.id)
        
        return jsonify({"mesaj": "Tahliller başarıyla işlendi ve hafızaya alındı"}), 201
    except Exception as e: 
        logger.error(f"Upload hatası: {str(e)}")
        return jsonify({"hata": str(e)}), 500

# --- YAPAY ZEKA CHAT (RAG & INTENT DETECTION) ---

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    username = data.get('username')
    soru = data.get('soru')

    user = User.query.filter_by(username=username).first()
    if not user: return jsonify({"hata": "Kullanıcı bulunamadı"}), 404

    # Niyet Algılama: Soruda tahlil sorgusu var mı?
    niyet_analiz = any(k in soru.lower() for k in ["sonuc", "deger", "tahlil", "nasil", "seker", "kan", "idrar", "referans"])

    # Kullanıcı Bağlamı Oluşturma
    yas = datetime.now().year - user.dogum_yili if user.dogum_yili else "Bilinmiyor"
    profil_ozeti = f"Profil: {yas} yaşında, {user.cinsiyet}. Geçmiş Hastalıklar: {user.hastaliklar}"
    
    tahlil_bilgisi = ""
    if niyet_analiz:
        # FAISS'ten en alakalı 3 tahlil kaydını getir
        ilgili_id_listesi = faiss_ara(soru, k=3)
        bulunanlar = []
        for p_id in ilgili_id_listesi:
            p = TestParametresi.query.get(p_id)
            if p: bulunanlar.append(f"{p.tahlil_adi}: {p.deger} {p.birim} (Ref: {p.referans_araligi}, Tarih: {p.tahlil_tarihi})")
        
        if bulunanlar:
            tahlil_bilgisi = "\nKullanıcının İlgili Tahlil Kayıtları:\n" + "\n".join(bulunanlar)

    # Qwen-2.5 için Sistem Talimatı
    system_prompt = f"""Sen uzman bir tıbbi veri analisti ve yapay zeka asistanısın. 
    Aşağıdaki kullanıcı profiline ve tahlil verilerine dayanarak soruları yanıtla:
    
    {profil_ozeti}
    {tahlil_bilgisi}
    
    ÖNEMLİ KURALLAR:
    1. Yanıtlarını tahlil sonuçlarına ve kullanıcı profiline göre kişiselleştir.
    2. Tıbbi terimleri sadeleştirerek açıkla.
    3. Asla kesin tanı koyma. Her zaman 'Bu bir ön incelemedir, doktorunuza danışın' uyarısını yap.
    4. Eğer tahlil verisi bulamazsan, genel tıbbi bilgiler vererek yardımcı ol.
    """

    try:
        completion = client.chat.completions.create(
            model="qwen-2.5-32b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": soru}
            ],
            temperature=0.3
        )
        return jsonify({"yanit": completion.choices[0].message.content}), 200
    except Exception as e:
        logger.error(f"Groq Chat Hatası: {e}")
        return jsonify({"hata": "Yapay zeka motoruna ulaşılamadı."}), 500

# --- VERİ GÖRSELLEŞTİRME VE LİSTELEME ---

@app.route('/comparison_matrix', methods=['GET'])
def get_comparison_matrix():
    username = request.args.get('username')
    try:
        dates_q = db.session.query(TestParametresi.tahlil_tarihi).join(TahlilRaporu).join(User)\
                        .filter(User.username == username).distinct().all()
        str_dates = sorted([d[0] for d in dates_q], key=lambda x: datetime.strptime(x, "%d.%m.%Y"), reverse=True)

        params_q = db.session.query(TestParametresi.tahlil_adi).join(TahlilRaporu).join(User)\
                        .filter(User.username == username).distinct().all()
        param_names = sorted([p[0] for p in params_q])

        matrix_data = []
        for p_name in param_names:
            ref_kayit = db.session.query(TestParametresi).join(TahlilRaporu).join(User)\
                            .filter(User.username == username, TestParametresi.tahlil_adi == p_name).first()
            row_data = {"isim": p_name, "referans": ref_kayit.referans_araligi if ref_kayit else "", "hucreler": []}
            for date in str_dates:
                rec = db.session.query(TestParametresi).join(TahlilRaporu).join(User)\
                            .filter(User.username == username, TestParametresi.tahlil_adi == p_name, TestParametresi.tahlil_tarihi == date).first()
                if rec: row_data["hucreler"].append({"deger": str(rec.deger), "riskli": is_abnormal(rec.deger, rec.referans_araligi)})
                else: row_data["hucreler"].append({"deger": "-", "riskli": False})
            matrix_data.append(row_data)

        return jsonify({"sutunlar": str_dates, "satirlar": matrix_data}), 200
    except Exception as e: return jsonify({"hata": str(e)}), 500

if __name__ == '__main__':
    veritabani_baslat()
    app.run(debug=True, host='0.0.0.0', port=5000)