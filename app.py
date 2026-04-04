from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response
import sqlite3
import os
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import json

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Manual CORS handling - NO flask_cors needed
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

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
USE_MONGO = False
mongo_client = None
mongo_db = None
mongo_meals = None
mongo_gallery = None
leaderboard_client = None
leaderboard_collection = None

# Try to connect to MongoDB
try:
    if os.getenv('MONGODB_URL'):
        mongo_client = MongoClient(os.getenv('MONGODB_URL'), serverSelectionTimeoutMS=3000)
        mongo_client.server_info()
        mongo_db = mongo_client['tgs_kitchen']
        mongo_meals = mongo_db['meals']
        mongo_gallery = mongo_db['gallery']
        USE_MONGO = True
        print("✅ MongoDB connected successfully")
    else:
        print("ℹ️ No MONGODB_URL found, using SQLite")
except Exception as e:
    print("❌ MongoDB connection failed:", e)
    USE_MONGO = False

# Leaderboard MongoDB (separate connection)
try:
    if os.getenv('LEADERBOARD_MONGODB_URI'):
        leaderboard_client = MongoClient(os.getenv('LEADERBOARD_MONGODB_URI'), serverSelectionTimeoutMS=3000)
        leaderboard_client.server_info()
        leaderboard_db = leaderboard_client['leaderboard_db']
        leaderboard_collection = leaderboard_db['leaderboard']
        print("✅ Leaderboard MongoDB connected successfully")
    else:
        print("ℹ️ No LEADERBOARD_MONGODB_URI found")
except Exception as e:
    print("❌ Leaderboard MongoDB connection failed:", e)
    leaderboard_collection = None

# === SQLite setup (always works as fallback) ===
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
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
        c.execute('''
            CREATE TABLE IF NOT EXISTS leaderboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER,
                player TEXT,
                plates INTEGER,
                img TEXT
            )
        ''')
        conn.commit()
        print("✅ SQLite database initialized")

init_db()

# === CRITICAL FIX: Helper to convert MongoDB documents to JSON-serializable dicts ===
def mongo_to_dict(doc):
    """Convert MongoDB document to JSON-serializable dictionary"""
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == '_id':
            # Convert ObjectId to string and rename to 'id'
            result['id'] = str(value)
        elif isinstance(value, ObjectId):
            # Convert any other ObjectId fields
            result[key] = str(value)
        elif isinstance(value, datetime):
            # Convert datetime to ISO string
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result

# === Helper functions ===
def get_all_meals():
    if USE_MONGO and mongo_meals is not None:
        try:
            meals = list(mongo_meals.find().sort("_id", -1))
            # Convert each document to JSON-serializable dict
            meals = [mongo_to_dict(meal) for meal in meals]
            print(f"📊 MongoDB: Found {len(meals)} meals")
            return meals
        except Exception as e:
            print("MongoDB query failed, falling back to SQLite:", e)
    
    # Fallback to SQLite
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        meals = conn.execute('SELECT * FROM meals ORDER BY id DESC').fetchall()
        conn.close()
        result = [dict(meal) for meal in meals]
        print(f"📊 SQLite: Found {len(result)} meals")
        return result
    except Exception as e:
        print("SQLite error:", e)
        return []

def get_all_gallery():
    if USE_MONGO and mongo_gallery is not None:
        try:
            images = list(mongo_gallery.find().sort("created_at", -1))
            images = [mongo_to_dict(img) for img in images]
            return images
        except Exception as e:
            print("MongoDB gallery query failed:", e)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        images = conn.execute('SELECT * FROM gallery ORDER BY created_at DESC').fetchall()
        conn.close()
        return [dict(img) for img in images]
    except Exception as e:
        print("SQLite gallery error:", e)
        return []

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
@app.route('/api/meals', methods=['GET'])
def api_meals():
    try:
        meals = get_all_meals()
        return jsonify(meals)
    except Exception as e:
        print("Error in api_meals:", e)
        return jsonify([]), 200

@app.route('/api/add_meal', methods=['POST', 'OPTIONS'])
def api_add_meal():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        print("📝 Adding new meal...")
        
        data = request.get_json(force=True, silent=True)
        if not data:
            print("❌ No JSON data received")
            return jsonify({'error': 'No data received'}), 400
        
        print("Received data:", data)
        
        name = data.get('name')
        description = data.get('description', '')
        price = data.get('price')
        image = data.get('image', '')
        category = data.get('category', 'Pasta')
        
        # Validation
        if not name:
            return jsonify({'error': 'Name is required'}), 400
        if not price:
            return jsonify({'error': 'Price is required'}), 400
        
        try:
            price = float(price)
        except:
            return jsonify({'error': 'Price must be a number'}), 400
        
        print(f"Validated: name={name}, price={price}, category={category}")
        
        # Try MongoDB first
        if USE_MONGO and mongo_meals is not None:
            try:
                result = mongo_meals.insert_one({
                    'name': name,
                    'description': description,
                    'price': price,
                    'image': image,
                    'category': category
                })
                print(f"✅ Meal added to MongoDB with ID: {result.inserted_id}")
                return jsonify({'message': 'Meal added', 'id': str(result.inserted_id)})
            except Exception as mongo_err:
                print("MongoDB insert failed, trying SQLite:", mongo_err)
        
        # Fallback to SQLite
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
                  (name, description, price, image, category))
        conn.commit()
        meal_id = c.lastrowid
        conn.close()
        print(f"✅ Meal added to SQLite with ID: {meal_id}")
        return jsonify({'message': 'Meal added', 'id': meal_id})
        
    except Exception as e:
        print("❌ Error adding meal:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_meal/<meal_id>', methods=['POST', 'OPTIONS'])
def api_update_meal(meal_id):
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        if USE_MONGO and mongo_meals is not None:
            try:
                mongo_meals.update_one(
                    {'_id': ObjectId(meal_id)},
                    {'$set': {
                        'name': data.get('name'),
                        'description': data.get('description'),
                        'price': float(data.get('price', 0)),
                        'image': data.get('image'),
                        'category': data.get('category')
                    }}
                )
                return jsonify({'message': 'Meal updated'})
            except Exception as mongo_err:
                print("MongoDB update failed:", mongo_err)
        
        # SQLite fallback
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''UPDATE meals SET name=?, description=?, price=?, image=?, category=? WHERE id=?''',
                  (data.get('name'), data.get('description'), float(data.get('price', 0)), 
                   data.get('image'), data.get('category'), meal_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Meal updated'})
    except Exception as e:
        print("Error updating meal:", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete_meal/<meal_id>', methods=['DELETE', 'OPTIONS'])
def api_delete_meal(meal_id):
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        if USE_MONGO and mongo_meals is not None:
            try:
                mongo_meals.delete_one({'_id': ObjectId(meal_id)})
                return jsonify({'message': 'Meal deleted'})
            except Exception as mongo_err:
                print("MongoDB delete failed:", mongo_err)
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM meals WHERE id=?', (meal_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Meal deleted'})
    except Exception as e:
        print("Error deleting meal:", e)
        return jsonify({'error': str(e)}), 500

# === API Routes - Gallery ===
@app.route('/api/gallery', methods=['GET'])
def api_gallery():
    try:
        images = get_all_gallery()
        return jsonify(images)
    except Exception as e:
        print("Error in api_gallery:", e)
        return jsonify([]), 200

@app.route('/api/gallery', methods=['POST', 'OPTIONS'])
def api_add_gallery():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'error': 'No data received'}), 400
            
        title = data.get('title')
        description = data.get('description', '')
        image_url = data.get('image_url')
        category = data.get('category', 'Featured')
        
        if not title or not image_url:
            return jsonify({'error': 'Title and image URL are required'}), 400
        
        if USE_MONGO and mongo_gallery is not None:
            try:
                result = mongo_gallery.insert_one({
                    'title': title,
                    'description': description,
                    'image_url': image_url,
                    'category': category,
                    'created_at': datetime.now()
                })
                return jsonify({'message': 'Image added', 'id': str(result.inserted_id)})
            except Exception as mongo_err:
                print("MongoDB gallery insert failed:", mongo_err)
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''INSERT INTO gallery (title, description, image_url, category) VALUES (?, ?, ?, ?)''',
                  (title, description, image_url, category))
        conn.commit()
        img_id = c.lastrowid
        conn.close()
        return jsonify({'message': 'Image added', 'id': img_id})
    except Exception as e:
        print("Error adding gallery:", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/gallery/<img_id>', methods=['DELETE', 'OPTIONS'])
def api_delete_gallery(img_id):
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        if USE_MONGO and mongo_gallery is not None:
            try:
                mongo_gallery.delete_one({'_id': ObjectId(img_id)})
                return jsonify({'message': 'Image deleted'})
            except Exception as mongo_err:
                print("MongoDB gallery delete failed:", mongo_err)
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM gallery WHERE id=?', (img_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Image deleted'})
    except Exception as e:
        print("Error deleting gallery:", e)
        return jsonify({'error': str(e)}), 500

# === API Routes - Image Upload ===
@app.route('/api/upload_image', methods=['POST', 'OPTIONS'])
def upload_image():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
            
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Check if Cloudinary is configured
        if not os.getenv('CLOUDINARY_CLOUD_NAME'):
            print("⚠️ Cloudinary not configured, returning placeholder")
            return jsonify({
                'url': 'https://via.placeholder.com/800x600?text=Upload+Disabled',
                'public_id': 'placeholder'
            })
        
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
        if leaderboard_collection is not None:
            data = list(leaderboard_collection.find())
            data = [mongo_to_dict(d) for d in data]
            for d in data:
                d['plates'] = d.get('plates', d.get('score', 0))
                d['score'] = d.get('score', d.get('plates', 0))
            return jsonify(data)
        
        # Fallback to SQLite
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM leaderboard ORDER BY rank').fetchall()
        conn.close()
        result = []
        for row in rows:
            d = dict(row)
            d['plates'] = d.get('plates', d.get('score', 0))
            d['score'] = d.get('score', d.get('plates', 0))
            result.append(d)
        return jsonify(result)
    except Exception as e:
        print("Error fetching leaderboard:", e)
        return jsonify([]), 200

@app.route('/api/leaderboard', methods=['POST', 'OPTIONS'])
def save_leaderboard():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        data = request.get_json(force=True, silent=True)
        
        if not data or not isinstance(data, list):
            return jsonify({'error': 'No data or invalid format'}), 400
        
        if leaderboard_collection is not None:
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
        else:
            # Fallback to SQLite
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('DELETE FROM leaderboard')
            for entry in data:
                c.execute('INSERT INTO leaderboard (rank, player, plates, img) VALUES (?, ?, ?, ?)',
                          (int(entry.get('rank', 0)), entry.get('player') or '',
                           int(entry.get('plates', entry.get('score', 0))), entry.get('img') or ''))
            conn.commit()
            conn.close()
            return jsonify({'message': 'Leaderboard saved to SQLite'})
    except Exception as e:
        print("Leaderboard save error:", e)
        return jsonify({'error': str(e)}), 500

# === Legacy Routes ===
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
