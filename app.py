from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
import urllib.parse
import base64
import io
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

DB_NAME = 'meals.db'

# Cloudinary config
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === MongoDB setup ===
USE_MONGO = bool(os.getenv('MONGODB_URL'))
mongo_client = None
mongo_db = None
mongo_meals = None
mongo_gallery = None
mongo_leaderboard = None
leaderboard_client = None
leaderboard_collection = None

if os.getenv('LEADERBOARD_MONGODB_URI'):
    try:
        leaderboard_client = MongoClient(os.getenv('LEADERBOARD_MONGODB_URI'))
        leaderboard_client.server_info()
        leaderboard_db = leaderboard_client['leaderboard_db']
        leaderboard_collection = leaderboard_db['leaderboard']
        print("✅ Leaderboard MongoDB connected successfully")
    except Exception as e:
        print("❌ Leaderboard MongoDB connection failed:", e)

if USE_MONGO:
    try:
        mongo_client = MongoClient(os.getenv('MONGODB_URL'))
        mongo_client.server_info()
        mongo_db = mongo_client['tgs_kitchen']
        mongo_meals = mongo_db['meals']
        mongo_gallery = mongo_db['gallery']
        mongo_leaderboard = mongo_db['leaderboard']
        print("✅ MongoDB connected successfully")
    except Exception as e:
        USE_MONGO = False
        print("❌ MongoDB connection failed:", e)

# === SQLite setup ===
def init_db():
    if not USE_MONGO:
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            # Meals table
            c.execute('''
                CREATE TABLE IF NOT EXISTS meals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    price REAL NOT NULL,
                    image TEXT,
                    category TEXT
                )
            ''')
            # Gallery table
            c.execute('''
                CREATE TABLE IF NOT EXISTS gallery (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    image_url TEXT NOT NULL,
                    category TEXT DEFAULT 'Featured',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

init_db()

# === Helper functions ===
def get_all_meals():
    if USE_MONGO:
        meals = list(mongo_meals.find().sort("_id", -1))
        for meal in meals:
            meal['id'] = str(meal['_id'])
        return meals
    else:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        meals = conn.execute('SELECT * FROM meals ORDER BY id DESC').fetchall()
        conn.close()
        return [dict(meal) for meal in meals]

def get_all_gallery():
    if USE_MONGO:
        images = list(mongo_gallery.find().sort("created_at", -1))
        for img in images:
            img['id'] = str(img['_id'])
        return images
    else:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        images = conn.execute('SELECT * FROM gallery ORDER BY created_at DESC').fetchall()
        conn.close()
        return [dict(img) for img in images]

# === Page Routes ===
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/menu')
def menu():
    return render_template('menu.html')

@app.route('/gallery')
def gallery():
    return render_template('gallery.html')

@app.route('/cart')
def cart():
    return render_template('cart.html')

@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

@app.route('/leaderboard')
def leaderboard():
    return render_template('leaderboard.html')

@app.route('/leaderboardad')
def leaderboard_admin():
    return render_template('leaderboardad.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

# === API Routes - Meals ===
@app.route('/api/meals')
def api_meals():
    meals = get_all_meals()
    return jsonify(meals)

@app.route('/api/add_meal', methods=['POST'])
def api_add_meal():
    data = request.get_json()
    name = data.get('name')
    description = data.get('description', '')
    price = float(data.get('price', 0))
    image = data.get('image', '')
    category = data.get('category', 'Pasta')
    
    if USE_MONGO:
        result = mongo_meals.insert_one({
            'name': name,
            'description': description,
            'price': price,
            'image': image,
            'category': category
        })
        return jsonify({'message': 'Meal added', 'id': str(result.inserted_id)})
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
                  (name, description, price, image, category))
        conn.commit()
        meal_id = c.lastrowid
        conn.close()
        return jsonify({'message': 'Meal added', 'id': meal_id})

@app.route('/api/update_meal/<meal_id>', methods=['POST'])
def api_update_meal(meal_id):
    data = request.get_json()
    
    if USE_MONGO:
        mongo_meals.update_one(
            {'_id': ObjectId(meal_id)},
            {'$set': {
                'name': data.get('name'),
                'description': data.get('description'),
                'price': float(data.get('price')),
                'image': data.get('image'),
                'category': data.get('category')
            }}
        )
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''UPDATE meals SET name=?, description=?, price=?, image=?, category=? WHERE id=?''',
                  (data.get('name'), data.get('description'), float(data.get('price')), 
                   data.get('image'), data.get('category'), meal_id))
        conn.commit()
        conn.close()
    
    return jsonify({'message': 'Meal updated'})

@app.route('/api/delete_meal/<meal_id>', methods=['DELETE'])
def api_delete_meal(meal_id):
    if USE_MONGO:
        mongo_meals.delete_one({'_id': ObjectId(meal_id)})
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM meals WHERE id=?', (meal_id,))
        conn.commit()
        conn.close()
    return jsonify({'message': 'Meal deleted'})

# === API Routes - Gallery ===
@app.route('/api/gallery')
def api_gallery():
    images = get_all_gallery()
    return jsonify(images)

@app.route('/api/gallery', methods=['POST'])
def api_add_gallery():
    data = request.get_json()
    title = data.get('title')
    description = data.get('description', '')
    image_url = data.get('image_url')
    category = data.get('category', 'Featured')
    
    if USE_MONGO:
        result = mongo_gallery.insert_one({
            'title': title,
            'description': description,
            'image_url': image_url,
            'category': category,
            'created_at': datetime.now()
        })
        return jsonify({'message': 'Image added', 'id': str(result.inserted_id)})
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''INSERT INTO gallery (title, description, image_url, category) VALUES (?, ?, ?, ?)''',
                  (title, description, image_url, category))
        conn.commit()
        img_id = c.lastrowid
        conn.close()
        return jsonify({'message': 'Image added', 'id': img_id})

@app.route('/api/gallery/<img_id>', methods=['DELETE'])
def api_delete_gallery(img_id):
    if USE_MONGO:
        mongo_gallery.delete_one({'_id': ObjectId(img_id)})
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM gallery WHERE id=?', (img_id,))
        conn.commit()
        conn.close()
    return jsonify({'message': 'Image deleted'})

# === API Routes - Image Upload ===
@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    """Upload image to Cloudinary"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
            
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        upload_result = cloudinary.uploader.upload(
            file,
            folder="tgs_kitchen",
            transformation=[
                {'width': 800, 'height': 600, 'crop': 'limit'},
                {'quality': 'auto:good'}
            ]
        )
        
        return jsonify({
            'url': upload_result['secure_url'],
            'public_id': upload_result['public_id']
        })
        
    except Exception as e:
        print("Cloudinary upload error:", e)
        return jsonify({'error': str(e)}), 500

# === API Routes - Leaderboard ===
@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        if leaderboard_collection is None:
            return jsonify([])
        
        data = list(leaderboard_collection.find())
        for d in data:
            d['_id'] = str(d['_id'])
            d['plates'] = d.get('plates', d.get('score', 0))
            d['score'] = d.get('score', d.get('plates', 0))
        
        return jsonify(data)
    except Exception as e:
        print("Error fetching leaderboard:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/leaderboard', methods=['POST'])
def save_leaderboard():
    data = request.get_json(force=True)
    
    if not data or not isinstance(data, list):
        return jsonify({'error': 'No data or invalid format'}), 400
    
    if leaderboard_collection is None:
        return jsonify({'error': 'Leaderboard DB not available'}), 500
    
    try:
        leaderboard_collection.delete_many({})
        
        for entry in data:
            leaderboard_collection.insert_one({
                'rank': int(entry.get('rank', 0)),
                'player': entry.get('player') or '',
                'plates': int(entry.get('plates', entry.get('score', 0))),
                'score': int(entry.get('plates', entry.get('score', 0))),
                'img': entry.get('img') or ''
            })
        
        return jsonify({'message': 'Leaderboard saved'})
    except Exception as e:
        print("Leaderboard save error:", e)
        return jsonify({'error': str(e)}), 500

# === Legacy Routes (for backward compatibility) ===
@app.route('/add_to_cart/<meal_id>')
def add_to_cart(meal_id):
    cart = session.get('cart', {})
    cart[str(meal_id)] = cart.get(str(meal_id), 0) + 1
    session['cart'] = cart
    return redirect(url_for('home'))

@app.route('/remove_from_cart/<meal_id>')
def remove_from_cart(meal_id):
    cart = session.get('cart', {})
    cart.pop(str(meal_id), None)
    session['cart'] = cart
    return redirect(url_for('cart'))

# === Run app ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
