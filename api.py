import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import pdfplumber
from groq import Groq
from dotenv import load_dotenv

# .env dosyasını yükle (Yerel çalışma için)
load_dotenv()

app = Flask(__name__)
CORS(app)

# Veritabanı Ayarları (SQLite)
app.config['SQLALCHEMY_DATABASE_DATABASE_URI'] = 'sqlite:///tahlil_verileri.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Groq İstemcisi (Render'daki Environment Variable'dan alır)
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- VERİTABANI MODELLERİ ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    cinsiyet = db.Column(db.String(10))
    dogum_yili = db.Column(db.Integer)
    hastaliklar = db.Column(db.Text)  # Virgülle ayrılmış liste

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

with app.app_context():
    db.create_all()
    # Varsayılan hastalıkları ekle (eğer boşsa)
    if not Hastalik.query.first():
        liste = ["Diyabet", "Hipertansiyon", "Anemi", "Tiroid", "Kolesterol"]
        for h in liste:
            db.session.add(Hastalik(isim=h))
        db.session.commit()

# --- API ROTLARI ---

@app.route('/hastaliklari_getir', methods=['GET'])
def hastaliklari_getir():
    hastaliklar = Hastalik.query.all()
    return jsonify([h.isim for h in hastaliklar])

@app.route('/kayit', methods=['POST'])
def kayit():
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

@app.route('/giris', methods=['POST'])
def giris():
    data = request.json
    user = User.query.filter_by(username=data['username'], password=data['password']).first()
    if user:
        return jsonify({"mesaj": "Giriş başarılı", "user_id": user.id})
    return jsonify({"mesaj": "Hatalı bilgiler"}), 401

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
            # Tarih bulma (Basit mantık)
            if "Tarih" in text and tarih == "Bilinmiyor":
                lines = text.split('\n')
                for line in lines:
                    if "Tarih" in line:
                        tarih = line.split(':')[-1].strip()

        # PDF'den veri çekme (Tablo yapısına göre özelleştirilebilir)
        lines = text.split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    # Örnek: "Glikoz 95 mg/dL 70-100"
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
                # Risk kontrolü (Basit)
                riskli = False
                if "-" in v.referans:
                    parts = v.referans.split("-")
                    try:
                        alt = float(parts[0].strip())
                        ust = float(parts[1].strip())
                        if v.deger < alt or v.deger > ust: riskli = True
                    except: pass
                hucreler.append({"deger": str(v.deger), "riskli": riskli})
            else:
                hucreler.append({"deger": "-", "riskli": False})
        satirlar.append({"isim": p, "referans": referans, "hucreler": hucreler})
        
    return jsonify({"sutunlar": tarihler, "satirlar": satirlar})

@app.route('/parametre_gecmisi/<parametre>', methods=['GET'])
def parametre_gecmisi(parametre):
    user_id = request.args.get("user_id")
    veriler = TahlilVerisi.query.filter_by(kullanici_id=user_id, parametre=parametre).all()
    sonuc = [{"tarih": v.tarih, "deger": v.deger, "birim": v.birim, "referans": v.referans} for v in veriler]
    return jsonify(sonuc)

@app.route('/profil', methods=['GET'])
def profil():
    user_id = request.args.get("user_id")
    user = User.query.get(user_id)
    if user:
        return jsonify({
            "username": user.username,
            "cinsiyet": user.cinsiyet,
            "dogum_yili": user.dogum_yili,
            "hastaliklar": user.hastaliklar
        })
    return jsonify({"hata": "Kullanıcı bulunamadı"}), 404

@app.route('/sil_tarih', methods=['DELETE'])
def sil_tarih():
    user_id = request.args.get("user_id")
    tarih = request.args.get("tarih")
    TahlilVerisi.query.filter_by(kullanici_id=user_id, tarih=tarih).delete()
    db.session.commit()
    return jsonify({"mesaj": f"{tarih} tarihli veriler silindi"})

# --- YENİ: YAPAY ZEKA SOHBET ROTU (PLAN B) ---

@app.route('/sohbet', methods=['POST'])
def sohbet():
    data = request.json
    user_id = data.get("user_id")
    soru = data.get("soru")
    
    user = User.query.get(user_id)
    tahliller = TahlilVerisi.query.filter_by(kullanici_id=user_id).all()
    
    # RAG: Veritabanındaki tahlilleri metin haline getir (Context)
    tahlil_metni = ""
    for v in tahliller:
        tahlil_metni += f"- {v.tarih} | {v.parametre}: {v.deger} {v.birim} (Ref: {v.referans})\n"
    
    kullanici_profili = f"Yaş: {2026 - user.dogum_yili}, Cinsiyet: {user.cinsiyet}, Mevcut Hastalıklar: {user.hastaliklar}"

    try:
        completion = client.chat.completions.create(
            model="qwen-2.5-32b",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Sen profesyonel bir tahlil yorumlama asistanısın. Kullanıcının aşağıda verilen "
                        "profil bilgilerini ve tahlil geçmişini analiz ederek sorularını yanıtla. "
                        "Tıbbi tavsiye vermediğini, sadece sonuçları açıkladığını hatırlat. "
                        "Anlaşılır, nazik ve destekleyici bir dil kullan.\n\n"
                        f"KULLANICI PROFİLİ: {kullanici_profili}\n"
                        f"TAHLİL VERİLERİ:\n{tahlil_metni}"
                    )
                },
                {"role": "user", "content": soru}
            ]
        )
        cevap = completion.choices[0].message.content
        return jsonify({"cevap": cevap})
    except Exception as e:
        return jsonify({"cevap": f"Üzgünüm, şu an yanıt veremiyorum. (Hata: {str(e)})"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)