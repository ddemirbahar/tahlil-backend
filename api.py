import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import pdfplumber
from groq import Groq
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)
CORS(app)

# --- VERİTABANI AYARLARI ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tahlil_verileri.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Groq İstemcisi
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- VERİTABANI MODELLERİ ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    cinsiyet = db.Column(db.String(10))
    dogum_yili = db.Column(db.Integer)
    hastaliklar = db.Column(db.Text)

class Hastalik(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    isim = db.Column(db.String(100), unique=True)

class TahlilVerisi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kullanici_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    tarih = db.Column(db.String(20))
    parametre = db.Column(db.String(100))
    deger = db.Column(db.Float)
    birim = db.Column(db.String(20))
    referans = db.Column(db.String(50))

# Veritabanını oluştur ve Genişletilmiş Hastalık Listesini Ekle
with app.app_context():
    db.create_all()
    # En sık görülen kronik hastalıklar listesi
    kronik_hastaliklar = [
        "Diyabet (Tip 1/2)", "Hipertansiyon", "Anemi (Kansızlık)",
        "Hipotiroidi / Hipertiroidi", "Hiperlipidemi (Yüksek Kolesterol)",
        "Astım", "KOAH", "Kronik Kalp Yetmezliği", "Koroner Arter Hastalığı",
        "Romatoid Artrit", "Migren", "Kronik Böbrek Yetmezliği",
        "Karaciğer Yağlanması", "Çölyak", "Gastrit / Ülser",
        "Egzama / Sedef", "Anksiyete Bozukluğu", "Depresyon",
        "Obezite", "Uyku Apnesi", "Huzursuz Bacak Sendromu",
        "İnsülin Direnci", "B12 Eksikliği", "D Vitamini Eksikliği"
    ]
    
    for h_isim in kronik_hastaliklar:
        mevcut = Hastalik.query.filter_by(isim=h_isim).first()
        if not mevcut:
            db.session.add(Hastalik(isim=h_isim))
    db.session.commit()

# --- AUTH ROTLARI ---

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"mesaj": "Bu kullanıcı adı zaten alınmış"}), 400
    
    yeni_user = User(
        username=data['username'],
        password=data['password'],
        cinsiyet=data.get('cinsiyet'),
        dogum_yili=data.get('dogum_yili'),
        hastaliklar=",".join(data.get('hastaliklar', []))
    )
    db.session.add(yeni_user)
    db.session.commit()
    return jsonify({"mesaj": "Kayıt başarılı", "user_id": yeni_user.id})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username'], password=data['password']).first()
    if user:
        return jsonify({"mesaj": "Giriş başarılı", "user_id": user.id})
    return jsonify({"mesaj": "Hatalı bilgiler"}), 401

# --- DİĞER ROTLAR ---

@app.route('/hastaliklari_getir', methods=['GET'])
def hastaliklari_getir():
    hastaliklar = Hastalik.query.order_by(Hastalik.isim).all()
    return jsonify([h.isim for h in hastaliklar])

@app.route('/pdf_yukle', methods=['POST'])
def pdf_yukle():
    kullanici_id = request.form.get("user_id")
    if 'file' not in request.files: return jsonify({"hata": "Dosya yok"}), 400
    
    file = request.files['file']
    tarih = "Bilinmiyor"
    
    with pdfplumber.open(file) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() or ""

        lines = text.split('\n')
        for line in lines:
            if "Tarih" in line and tarih == "Bilinmiyor":
                tarih = line.split(':')[-1].strip()
            
            parts = line.split()
            if len(parts) >= 4:
                try:
                    param = parts[0]
                    deger = float(parts[1].replace(',', '.'))
                    birim = parts[2]
                    ref = parts[3]
                    
                    yeni_veri = TahlilVerisi(
                        kullanici_id=kullanici_id,
                        tarih=tarih,
                        parametre=param,
                        deger=deger,
                        birim=birim,
                        referans=ref
                    )
                    db.session.add(yeni_veri)
                except: continue
        db.session.commit()
    return jsonify({"mesaj": f"{tarih} tarihli tahlil işlendi."})

@app.route('/matris_getir', methods=['GET'])
def matris_getir():
    user_id = request.args.get("user_id")
    veriler = TahlilVerisi.query.filter_by(kullanici_id=user_id).all()
    
    tarihler = sorted(list(set([v.tarih for v in veriler])))
    parametreler = sorted(list(set([v.parametre for v in veriler])))
    
    satirlar = []
    for p in parametreler:
        hucreler = []
        referans = ""
        for t in tarihler:
            v = TahlilVerisi.query.filter_by(kullanici_id=user_id, parametre=p, tarih=t).first()
            if v:
                referans = v.referans
                riskli = False
                if "-" in v.referans:
                    try:
                        pts = v.referans.split("-")
                        alt = float(pts[0].strip())
                        ust = float(pts[1].strip())
                        if v.deger < alt or v.deger > ust: riskli = True
                    except: pass
                hucreler.append({"deger": str(v.deger), "riskli": riskli})
            else:
                hucreler.append({"deger": "-", "riskli": False})
        satirlar.append({"isim": p, "referans": referans, "hucreler": hucreler})
        
    return jsonify({"sutunlar": tarihler, "satirlar": satirlar})

@app.route('/profil', methods=['GET'])
def profil():
    user_id = request.args.get("user_id")
    u = User.query.get(user_id)
    if u:
        return jsonify({
            "username": u.username,
            "cinsiyet": u.cinsiyet,
            "dogum_yili": u.dogum_yili,
            "hastaliklar": u.hastaliklar
        })
    return jsonify({"hata": "Profil bulunamadı"}), 404

@app.route('/sohbet', methods=['POST'])
def sohbet():
    data = request.json
    u_id = data.get("user_id")
    soru = data.get("soru")
    
    user = User.query.get(u_id)
    tahliller = TahlilVerisi.query.filter_by(kullanici_id=u_id).all()
    
    tahlil_metni = ""
    for v in tahliller:
        tahlil_metni += f"- {v.tarih}: {v.parametre} {v.deger} {v.birim} (Ref: {v.referans})\n"
    
    profil = f"Yaş: {2026 - user.dogum_yili}, Cinsiyet: {user.cinsiyet}, Hastalıklar: {user.hastaliklar}"

    try:
        completion = client.chat.completions.create(
            model="qwen-2.5-32b",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Sen uzman bir tahlil analiz asistanısın. Kullanıcının profilini "
                        "ve geçmiş tahlillerini analiz ederek soruları yanıtla. "
                        "Anlaşılır bir dil kullan ve riskli durumlarda doktora yönlendir.\n\n"
                        f"HASTA PROFİLİ: {profil}\nSONUÇLAR:\n{tahlil_metni}"
                    )
                },
                {"role": "user", "content": soru}
            ]
        )
        return jsonify({"cevap": completion.choices[0].message.content})
    except Exception as e:
        return jsonify({"cevap": f"Bir hata oluştu: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)