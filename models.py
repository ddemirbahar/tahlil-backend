from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# --- KULLANICI TABLOSU ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    
    # Yeni Eklenen Alanlar
    email = db.Column(db.String(120), nullable=True)      # Opsiyonel
    dogum_yili = db.Column(db.Integer, nullable=True)     # Yaş hesabı için
    cinsiyet = db.Column(db.String(10), nullable=True)    # Erkek/Kadın
    hastaliklar = db.Column(db.String(500), nullable=True) # Virgülle ayrılmış metin (Örn: "Diyabet,Tansiyon")

    raporlar = db.relationship('TahlilRaporu', backref='user', lazy=True)

# --- DİNAMİK HASTALIK LİSTESİ TABLOSU ---
class Hastalik(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False, unique=True)

# --- TAHLİL RAPORLARI ---
class TahlilRaporu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hasta_adi = db.Column(db.String(100), nullable=False)
    yukleme_tarihi = db.Column(db.DateTime, default=db.func.current_timestamp())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sonuclar = db.relationship('TestParametresi', backref='rapor', lazy=True, cascade="all, delete-orphan")

# --- TEST PARAMETRELERİ ---
class TestParametresi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tahlil_adi = db.Column(db.String(100), nullable=False)
    deger = db.Column(db.Float, nullable=False)
    birim = db.Column(db.String(20))
    referans_araligi = db.Column(db.String(50))
    tahlil_tarihi = db.Column(db.String(20))
    rapor_id = db.Column(db.Integer, db.ForeignKey('tahlil_raporu.id'), nullable=False)