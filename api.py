import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


from models import db, User, TahlilRaporu, TestParametresi, Hastalik
from utils import parse_pdf_data, is_abnormal

app = Flask(__name__)
CORS(app)

# --- Loglama Ayarları ---
logging.basicConfig(level=logging.INFO)
logger = app.logger

basedir = os.path.abspath(os.path.dirname(__file__))
# Veritabanı dosyası adı
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'tahliller.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# --- VERİTABANI BAŞLATMA VE HASTALIKLARI EKLEME (SEED) ---
def veritabani_baslat():
    with app.app_context():
        db.create_all()
        
        # Eğer hastalık tablosu boşsa standart listeyi ekle
        if not Hastalik.query.first():
            temel_hastaliklar = [
                "Diyabet (Şeker)",
                "Hipertansiyon (Tansiyon)",
                "Kalp Yetmezliği",
                "KOAH / Astım",
                "Böbrek Yetmezliği",
                "Tiroid (Guatr/Haşimato)",
                "Yüksek Kolesterol",
                "Demir Eksikliği Anemisi",
                "B12 Eksikliği",
                "Karaciğer Yağlanması"
            ]
            for h_adi in temel_hastaliklar:
                db.session.add(Hastalik(ad=h_adi))
            db.session.commit()
            print(">>> Standart hastalık listesi veritabanına eklendi.")

# ---  Hastalık Listesini Getir ---
@app.route('/diseases', methods=['GET'])
def get_diseases():
    try:
        hastaliklar = Hastalik.query.all()
        # Sadece isimleri liste olarak döndür
        liste = [h.ad for h in hastaliklar]
        return jsonify(liste), 200
    except Exception as e:
        logger.error(f"Hastalık listesi hatası: {e}")
        return jsonify([]), 500

# --- AUTH (Kayıt Ol) ---
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if User.query.filter_by(username=data['username']).first():
        logger.warning(f"Kayıt başarısız: {data['username']} zaten var.")
        return jsonify({"hata": "Kullanıcı adı kullanımda"}), 400
    
    # Yeni alanları (email, yaş, cinsiyet, hastalıklar) kaydediyoruz
    new_user = User(
        username=data['username'], 
        password_hash=generate_password_hash(data['password']),
        email=data.get('email'),
        dogum_yili=data.get('dogum_yili'),
        cinsiyet=data.get('cinsiyet'),
        hastaliklar=data.get('hastaliklar') # Frontend'den string olarak gelecek
    )
    
    db.session.add(new_user)
    db.session.commit()
    logger.info(f"Yeni kullanıcı kayıt oldu: {data['username']}")
    return jsonify({"mesaj": "Kayıt başarılı"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        logger.info(f"Giriş başarılı: {user.username}")
        return jsonify({"mesaj": "Giriş başarılı", "username": user.username}), 200
    
    logger.warning(f"Hatalı giriş denemesi: {data.get('username')}")
    return jsonify({"hata": "Hatalı giriş"}), 401

# --- YENİ EKLENEN: KULLANICI DETAYLARINI GETİR ---
@app.route('/user_info', methods=['GET'])
def get_user_info():
    username = request.args.get('username')
    if not username:
        return jsonify({"hata": "Kullanıcı adı gerekli"}), 400

    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"hata": "Kullanıcı bulunamadı"}), 404

    return jsonify({
        "username": user.username,
        "email": user.email,
        "dogum_yili": user.dogum_yili,
        "cinsiyet": user.cinsiyet,
        "hastaliklar": user.hastaliklar # "Diyabet,Tansiyon" şeklinde string döner
    }), 200
# -------------------------------------------------

# --- DOSYA YÜKLEME ---
@app.route('/upload', methods=['POST'])
def upload_file():
    username = request.form.get('username')
    if not username: return jsonify({"hata": "Kullanıcı girişi gerekli"}), 401
    
    user = User.query.filter_by(username=username).first()
    if not user: return jsonify({"hata": "Kullanıcı bulunamadı"}), 404

    file = request.files['file']
    try:
        hasta_adi, sonuclar = parse_pdf_data(file.stream)
        if not sonuclar: 
            logger.warning("PDF yüklendi ama veri bulunamadı.")
            return jsonify({"hata": "Veri yok"}), 400
        
        yeni_rapor = TahlilRaporu(hasta_adi=hasta_adi, user_id=user.id)
        db.session.add(yeni_rapor)
        db.session.commit()
        
        for sonuc in sonuclar:
            exists = TestParametresi.query.filter_by(rapor_id=yeni_rapor.id, tahlil_adi=sonuc["Tahlil Adı"]).first()
            if not exists:
                p = TestParametresi(tahlil_adi=sonuc["Tahlil Adı"], deger=sonuc["Değer"], birim=sonuc["Birim"], referans_araligi=sonuc["Referans Aralığı"], tahlil_tarihi=sonuc["Tarih"], rapor_id=yeni_rapor.id)
                db.session.add(p)
        db.session.commit()
        
        logger.info(f"Dosya başarıyla işlendi: {file.filename} (Kullanıcı: {username})")
        return jsonify({"mesaj": "Başarılı"}), 201
    except Exception as e: 
        logger.error(f"Dosya yükleme hatası: {str(e)}")
        return jsonify({"hata": str(e)}), 500

# --- TARİH SİLME FONKSİYONU ---
@app.route('/delete_date', methods=['DELETE'])
def delete_date_data():
    username = request.args.get('username')
    date = request.args.get('date')

    if not username or not date:
        return jsonify({"hata": "Eksik parametre"}), 400

    try:
        silinecekler = db.session.query(TestParametresi).join(TahlilRaporu).join(User)\
            .filter(User.username == username, TestParametresi.tahlil_tarihi == date).all()

        if not silinecekler:
            return jsonify({"mesaj": "Veri bulunamadı"}), 404

        for kayit in silinecekler:
            db.session.delete(kayit)
        
        db.session.commit()
        logger.info(f"Silme başarılı: {date}")
        return jsonify({"mesaj": f"{date} tarihli veriler silindi"}), 200

    except Exception as e:
        logger.error(f"Silme hatası: {str(e)}")
        db.session.rollback()
        return jsonify({"hata": str(e)}), 500

# --- DİĞER VERİ FONKSİYONLARI ---
@app.route('/all_parameters', methods=['GET'])
def get_all_parameters():
    username = request.args.get('username')
    res = db.session.query(TestParametresi.tahlil_adi).join(TahlilRaporu).join(User)\
            .filter(User.username == username).distinct().all()
    return jsonify([r[0] for r in res]), 200

@app.route('/results/<parameter_name>', methods=['GET'])
def get_results(parameter_name):
    username = request.args.get('username')
    res = db.session.query(TestParametresi).join(TahlilRaporu).join(User)\
            .filter(User.username == username, TestParametresi.tahlil_adi == parameter_name).all()
            
    res.sort(key=lambda x: datetime.strptime(x.tahlil_tarihi, "%d.%m.%Y"))
    return jsonify([{"tarih": r.tahlil_tarihi, "deger": r.deger, "birim": r.birim, "referans": r.referans_araligi} for r in res]), 200

@app.route('/comparison_matrix', methods=['GET'])
def get_comparison_matrix():
    username = request.args.get('username')
    if not username: return jsonify({"hata": "Giriş gerekli"}), 401

    try:
        dates_q = db.session.query(TestParametresi.tahlil_tarihi).join(TahlilRaporu).join(User)\
                    .filter(User.username == username).distinct().all()
        dates = []
        for d in dates_q:
            try: dates.append(datetime.strptime(d[0], "%d.%m.%Y"))
            except: pass
        dates.sort(reverse=True)
        str_dates = [d.strftime("%d.%m.%Y") for d in dates]

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
    except Exception as e: 
        logger.error(f"Matris oluşturma hatası: {str(e)}")
        return jsonify({"hata": str(e)}), 500

if __name__ == '__main__':
    veritabani_baslat()
    app.run(debug=True, host='0.0.0.0', port=5000)