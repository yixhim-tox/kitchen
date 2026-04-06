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

# Cloudinary config (optional - for external image hosting)
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === UNIFIED MongoDB setup (uses same connection for everything) ===
USE_MONGO = False
mongo_client = None
mongo_db = None
mongo_meals = None
mongo_gallery = None
leaderboard_collection = None

# Use LEADERBOARD_MONGODB_URI as primary, fallback to MONGODB_URL
mongodb_uri = os.getenv('LEADERBOARD_MONGODB_URI') or os.getenv('MONGODB_URL')

try:
    if mongodb_uri:
        mongo_client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        mongo_db = mongo_client['tgs_kitchen']  # Single database for everything
        mongo_meals = mongo_db['meals']
        mongo_gallery = mongo_db['gallery']
        leaderboard_collection = mongo_db['leaderboard']  # Same DB, different collection
        USE_MONGO = True
        print("✅ MongoDB connected successfully to tgs_kitchen database")
        print(f"   - Meals collection: {mongo_meals.name}")
        print(f"   - Gallery collection: {mongo_gallery.name}")
        print(f"   - Leaderboard collection: {leaderboard_collection.name}")
    else:
        print("ℹ️ No MongoDB URI found (LEADERBOARD_MONGODB_URI or MONGODB_URL), using SQLite")
except Exception as e:
    print("❌ MongoDB connection failed:", e)
    USE_MONGO = False

# === SQLite setup (fallback if MongoDB fails) ===
def init_db():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()

            # Meals table
            c.execute("""
                CREATE TABLE IF NOT EXISTS meals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    price REAL NOT NULL,
                    image TEXT,
                    category TEXT
                )
            """)

            # Gallery table - FIXED syntax
            c.execute("""
                CREATE TABLE IF NOT EXISTS gallery (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    image_url TEXT NOT NULL,
                    category TEXT DEFAULT 'Featured',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Leaderboard table
            c.execute("""
                CREATE TABLE IF NOT EXISTS leaderboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rank INTEGER,
                    player TEXT,
                    plates INTEGER,
                    img TEXT
                )
            """)

            conn.commit()
            print("✅ SQLite database initialized as fallback")
    except Exception as e:
        print("❌ Error initializing SQLite:", e)
        raise

init_db()

# === Helper to convert MongoDB documents to JSON-serializable dicts ===
def mongo_to_dict(doc):
    """Convert MongoDB document to JSON-serializable dictionary"""
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == '_id':
            result['id'] = str(value)
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result

# === Helper functions - FIXED to read from BOTH databases ===
def get_all_meals():
    all_meals = []
    seen_names = set()

    # Get from MongoDB first
    if USE_MONGO and mongo_meals is not None:
        try:
            mongo_meals_list = list(mongo_meals.find().sort("_id", -1))
            for meal in mongo_meals_list:
                meal_dict = mongo_to_dict(meal)
                all_meals.append(meal_dict)
                seen_names.add(meal_dict.get('name'))
            print(f"📊 MongoDB: Found {len(mongo_meals_list)} meals")
        except Exception as e:
            print("MongoDB query failed:", e)

    # Get from SQLite and add any missing meals
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        sqlite_meals = conn.execute('SELECT * FROM meals ORDER BY id DESC').fetchall()
        conn.close()

        sqlite_count = 0
        for meal in sqlite_meals:
            meal_dict = dict(meal)
            if meal_dict.get('name') not in seen_names:
                all_meals.append(meal_dict)
                seen_names.add(meal_dict.get('name'))
                sqlite_count += 1
        print(f"📊 SQLite: Found {len(sqlite_meals)} meals, added {sqlite_count} new ones")
    except Exception as e:
        print("SQLite error:", e)

    print(f"📊 Total combined meals: {len(all_meals)}")
    return all_meals

def get_all_gallery():
    all_images = []
    seen_titles = set()

    # Get from MongoDB first
    if USE_MONGO and mongo_gallery is not None:
        try:
            mongo_images = list(mongo_gallery.find().sort("created_at", -1))
            for img in mongo_images:
                img_dict = mongo_to_dict(img)
                all_images.append(img_dict)
                seen_titles.add(img_dict.get('title'))
            print(f"📊 MongoDB: Found {len(mongo_images)} gallery images")
        except Exception as e:
            print("MongoDB gallery query failed:", e)

    # Get from SQLite and add any missing images
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        sqlite_images = conn.execute('SELECT * FROM gallery ORDER BY created_at DESC').fetchall()
        conn.close()

        sqlite_count = 0
        for img in sqlite_images:
            img_dict = dict(img)
            if img_dict.get('title') not in seen_titles:
                all_images.append(img_dict)
                seen_titles.add(img_dict.get('title'))
                sqlite_count += 1
        print(f"📊 SQLite: Found {len(sqlite_images)} gallery images, added {sqlite_count} new ones")
    except Exception as e:
        print("SQLite gallery error:", e)

    print(f"📊 Total combined gallery images: {len(all_images)}")
    return all_images

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

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

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

        print("Received data:", {k: v[:50] + '...' if k == 'image' and len(str(v)) > 50 else v for k, v in data.items()})

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

        # Handle base64 image size check
        if image and image.startswith('data:image'):
            size_kb = len(image) / 1024
            print(f"📸 Base64 image size: {size_kb:.1f}KB")
            if size_kb > 500:  # 500KB limit for base64
                return jsonify({'error': 'Image too large. Max 500KB for base64 images.'}), 400

        print(f"Validated: name={name}, price={price}, category={category}")

        # Try MongoDB first (same DB as leaderboard)
        if USE_MONGO and mongo_meals is not None:
            try:
                result = mongo_meals.insert_one({
                    'name': name,
                    'description': description,
                    'price': price,
                    'image': image,  # Can be URL or base64
                    'category': category,
                    'created_at': datetime.now()
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

        # Handle base64 image size check
        image = data.get('image', '')
        if image and image.startswith('data:image'):
            size_kb = len(image) / 1024
            if size_kb > 500:
                return jsonify({'error': 'Image too large. Max 500KB for base64 images.'}), 400

        if USE_MONGO and mongo_meals is not None:
            try:
                mongo_meals.update_one(
                    {'_id': ObjectId(meal_id)},
                    {'$set': {
                        'name': data.get('name'),
                        'description': data.get('description'),
                        'price': float(data.get('price', 0)),
                        'image': image,
                        'category': data.get('category'),
                        'updated_at': datetime.now()
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
                   image, data.get('category'), meal_id))
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

        # Handle base64 image size check
        if image_url and image_url.startswith('data:image'):
            size_kb = len(image_url) / 1024
            if size_kb > 500:
                return jsonify({'error': 'Image too large. Max 500KB for base64 images.'}), 400

        if USE_MONGO and mongo_gallery is not None:
            try:
                result = mongo_gallery.insert_one({
                    'title': title,
                    'description': description,
                    'image_url': image_url,  # Can be URL or base64
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

# === API Routes - Image Upload (supports both Cloudinary and base64) ===
@app.route('/api/upload_image', methods=['POST', 'OPTIONS'])
def upload_image():
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200

    try:
        # Check if this is a base64 upload (from leaderboard-style crop)
        if request.is_json:
            data = request.get_json()
            if data and 'image' in data and isinstance(data['image'], str) and data['image'].startswith('data:image'):
                # Return base64 directly (like leaderboard)
                base64_img = data['image']
                if len(base64_img) > 500000:  # 500KB limit
                    return jsonify({'error': 'Base64 image too large'}), 400
                return jsonify({
                    'url': base64_img,
                    'public_id': 'base64',
                    'format': 'base64'
                })

        # File upload to Cloudinary (original behavior)
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
        print("Upload error:", e)
        return jsonify({'error': str(e)}), 500

# === API Routes - Leaderboard (FIXED to read from BOTH databases) ===
@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        all_entries = []
        seen_players = set()

        # Get from MongoDB first
        if leaderboard_collection is not None:
            try:
                mongo_data = list(leaderboard_collection.find())
                for entry in mongo_data:
                    entry_dict = mongo_to_dict(entry)
                    entry_dict['plates'] = entry_dict.get('plates', entry_dict.get('score', 0))
                    entry_dict['score'] = entry_dict.get('score', entry_dict.get('plates', 0))
                    all_entries.append(entry_dict)
                    seen_players.add(entry_dict.get('player'))
                print(f"📊 MongoDB: Found {len(mongo_data)} leaderboard entries")
            except Exception as e:
                print("MongoDB leaderboard query failed:", e)

        # Get from SQLite and add any missing entries
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM leaderboard ORDER BY rank').fetchall()
            conn.close()

            sqlite_count = 0
            for row in rows:
                entry_dict = dict(row)
                entry_dict['plates'] = entry_dict.get('plates', entry_dict.get('score', 0))
                entry_dict['score'] = entry_dict.get('score', entry_dict.get('plates', 0))
                if entry_dict.get('player') not in seen_players:
                    all_entries.append(entry_dict)
                    seen_players.add(entry_dict.get('player'))
                    sqlite_count += 1
            print(f"📊 SQLite: Found {len(rows)} leaderboard entries, added {sqlite_count} new ones")
        except Exception as e:
            print("SQLite leaderboard error:", e)

        # Sort by rank
        all_entries.sort(key=lambda x: x.get('rank', 999))
        print(f"📊 Total combined leaderboard entries: {len(all_entries)}")
        return jsonify(all_entries)
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

        # Check for oversized images and compress/convert to URLs if needed
        processed_data = []
        for entry in data:
            img = entry.get('img', '')
            # If base64 image is too large, use default URL
            if img and img.startswith('data:image') and len(img) > 500000:
                img = 'https://i.postimg.cc/RFQyqcrR/IMG-20260222-WA0018.jpg'

            processed_data.append({
                'rank': int(entry.get('rank', 0)),
                'player': entry.get('player') or '',
                'plates': int(entry.get('plates', entry.get('score', 0))),
                'score': int(entry.get('plates', entry.get('score', 0))),
                'img': img
            })

        if leaderboard_collection is not None:
            leaderboard_collection.delete_many({})

            for entry in processed_data:
                leaderboard_collection.insert_one(entry)

            return jsonify({'message': 'Leaderboard saved to MongoDB'})
        else:
            # Fallback to SQLite
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('DELETE FROM leaderboard')
            for entry in processed_data:
                c.execute('INSERT INTO leaderboard (rank, player, plates, img) VALUES (?, ?, ?, ?)',
                          (entry['rank'], entry['player'], entry['plates'], entry['img']))
            conn.commit()
            conn.close()
            return jsonify({'message': 'Leaderboard saved to SQLite'})
    except Exception as e:
        print("Leaderboard save error:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# === NEW API ENDPOINTS: Move between Gallery and Menu ===

@app.route('/api/gallery_to_meal/<img_id>', methods=['POST', 'OPTIONS'])
def convert_gallery_to_meal(img_id):
    """Convert a gallery image to a menu meal item"""
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200

    try:
        # Get additional data from request
        data = request.get_json(force=True, silent=True) or {}
        price = data.get('price', 0)
        category = data.get('category', 'Specials')

        # Find the gallery item
        gallery_item = None

        # Try MongoDB first
        if USE_MONGO and mongo_gallery is not None:
            try:
                gallery_item = mongo_gallery.find_one({'_id': ObjectId(img_id)})
                if gallery_item:
                    # Create meal from gallery item
                    meal_data = {
                        'name': gallery_item.get('title', 'Gallery Item'),
                        'description': gallery_item.get('description', ''),
                        'price': float(price),
                        'image': gallery_item.get('image_url', ''),
                        'category': category,
                        'created_at': datetime.now()
                    }
                    result = mongo_meals.insert_one(meal_data)

                    return jsonify({
                        'message': 'Gallery item converted to meal',
                        'meal_id': str(result.inserted_id),
                        'gallery_item': mongo_to_dict(gallery_item)
                    })
            except Exception as mongo_err:
                print("MongoDB gallery_to_meal failed:", mongo_err)

        # SQLite fallback
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get gallery item
        cursor.execute('SELECT * FROM gallery WHERE id = ?', (img_id,))
        gallery_item = cursor.fetchone()

        if not gallery_item:
            conn.close()
            return jsonify({'error': 'Gallery item not found'}), 404

        gallery_dict = dict(gallery_item)

        # Insert as meal
        cursor.execute(
            "INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
            (
                gallery_dict.get('title', 'Gallery Item'),
                gallery_dict.get('description', ''),
                float(price),
                gallery_dict.get('image_url', ''),
                category
            )
        )

        meal_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Gallery item converted to meal',
            'meal_id': meal_id,
            'gallery_item': gallery_dict
        })

    except Exception as e:
        print("Error converting gallery to meal:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/meal_to_gallery/<meal_id>', methods=['POST', 'OPTIONS'])
def convert_meal_to_gallery(meal_id):
    """Convert a menu meal item to a gallery image"""
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200

    try:
        # Get additional data from request
        data = request.get_json(force=True, silent=True) or {}
        category = data.get('category', 'Featured')

        # Find the meal
        meal_item = None

        # Try MongoDB first
        if USE_MONGO and mongo_meals is not None:
            try:
                meal_item = mongo_meals.find_one({'_id': ObjectId(meal_id)})
                if meal_item:
                    # Create gallery item from meal
                    gallery_data = {
                        'title': meal_item.get('name', 'Meal Item'),
                        'description': meal_item.get('description', ''),
                        'image_url': meal_item.get('image', ''),
                        'category': category,
                        'created_at': datetime.now()
                    }
                    result = mongo_gallery.insert_one(gallery_data)

                    return jsonify({
                        'message': 'Meal converted to gallery item',
                        'gallery_id': str(result.inserted_id),
                        'meal_item': mongo_to_dict(meal_item)
                    })
            except Exception as mongo_err:
                print("MongoDB meal_to_gallery failed:", mongo_err)

        # SQLite fallback
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get meal
        cursor.execute('SELECT * FROM meals WHERE id = ?', (meal_id,))
        meal_item = cursor.fetchone()

        if not meal_item:
            conn.close()
            return jsonify({'error': 'Meal not found'}), 404

        meal_dict = dict(meal_item)

        # Insert as gallery
        cursor.execute(
            "INSERT INTO gallery (title, description, image_url, category) VALUES (?, ?, ?, ?)",
            (
                meal_dict.get('name', 'Meal Item'),
                meal_dict.get('description', ''),
                meal_dict.get('image', ''),
                category
            )
        )

        gallery_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Meal converted to gallery item',
            'gallery_id': gallery_id,
            'meal_item': meal_dict
        })

    except Exception as e:
        print("Error converting meal to gallery:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
# === NEW API ENDPOINTS: Move between Gallery and Menu ===

@app.route('/api/gallery_to_meal/<img_id>', methods=['POST', 'OPTIONS'])
def convert_gallery_to_meal(img_id):
    """Convert a gallery image to a menu meal item"""
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        # Get additional data from request
        data = request.get_json(force=True, silent=True) or {}
        price = data.get('price', 0)
        category = data.get('category', 'Specials')
        
        # Find the gallery item
        gallery_item = None
        
        # Try MongoDB first
        if USE_MONGO and mongo_gallery is not None:
            try:
                gallery_item = mongo_gallery.find_one({'_id': ObjectId(img_id)})
                if gallery_item:
                    # Create meal from gallery item
                    meal_data = {
                        'name': gallery_item.get('title', 'Gallery Item'),
                        'description': gallery_item.get('description', ''),
                        'price': float(price),
                        'image': gallery_item.get('image_url', ''),
                        'category': category,
                        'created_at': datetime.now()
                    }
                    result = mongo_meals.insert_one(meal_data)
                    
                    return jsonify({
                        'message': 'Gallery item converted to meal',
                        'meal_id': str(result.inserted_id),
                        'gallery_item': mongo_to_dict(gallery_item)
                    })
            except Exception as mongo_err:
                print("MongoDB gallery_to_meal failed:", mongo_err)
        
        # SQLite fallback
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get gallery item
        cursor.execute('SELECT * FROM gallery WHERE id = ?', (img_id,))
        gallery_item = cursor.fetchone()
        
        if not gallery_item:
            conn.close()
            return jsonify({'error': 'Gallery item not found'}), 404
        
        gallery_dict = dict(gallery_item)
        
        # Insert as meal
        cursor.execute(
            "INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
            (
                gallery_dict.get('title', 'Gallery Item'),
                gallery_dict.get('description', ''),
                float(price),
                gallery_dict.get('image_url', ''),
                category
            )
        )
        
        meal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': 'Gallery item converted to meal',
            'meal_id': meal_id,
            'gallery_item': gallery_dict
        })
        
    except Exception as e:
        print("Error converting gallery to meal:", e)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/meal_to_gallery/<meal_id>', methods=['POST', 'OPTIONS'])
def convert_meal_to_gallery(meal_id):
    """Convert a menu meal item to a gallery image"""
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200
    
    try:
        # Get additional data from request
        data = request.get_json(force=True, silent=True) or {}
        category = data.get('category', 'Featured')
        
        # Find the meal
        meal_item = None
        
        # Try MongoDB first
        if USE_MONGO and mongo_meals is not None:
            try:
                meal_item = mongo_meals.find_one({'_id': ObjectId(meal_id)})
                if meal_item:
                    # Create gallery item from meal
                    gallery_data = {
                        'title': meal_item.get('name', 'Meal Item'),
                        'description': meal_item.get('description', ''),
                        'image_url': meal_item.get('image', ''),
                        'category': category,
                        'created_at': datetime.now()
                    }
                    result = mongo_gallery.insert_one(gallery_data)
                    
                    return jsonify({
                        'message': 'Meal converted to gallery item',
                        'gallery_id': str(result.inserted_id),
                        'meal_item': mongo_to_dict(meal_item)
                    })
            except Exception as mongo_err:
                print("MongoDB meal_to_gallery failed:", mongo_err)
        
        # SQLite fallback
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get meal
        cursor.execute('SELECT * FROM meals WHERE id = ?', (meal_id,))
        meal_item = cursor.fetchone()
        
        if not meal_item:
            conn.close()
            return jsonify({'error': 'Meal not found'}), 404
        
        meal_dict = dict(meal_item)
        
        # Insert as gallery
        cursor.execute(
            "INSERT INTO gallery (title, description, image_url, category) VALUES (?, ?, ?, ?)",
            (
                meal_dict.get('name', 'Meal Item'),
                meal_dict.get('description', ''),
                meal_dict.get('image', ''),
                category
            )
        )
        
        gallery_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': 'Meal converted to gallery item',
            'gallery_id': gallery_id,
            'meal_item': meal_dict
        })
        
    except Exception as e:
        print("Error converting meal to gallery:", e)
        import traceback
        traceback.print_exc()
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

# === MIGRATION ENDPOINT: Copy data from SQLite to MongoDB ===
@app.route('/api/migrate_to_mongodb', methods=['POST', 'OPTIONS'])
def migrate_to_mongodb():
    """
    Migrates all data from SQLite to MongoDB.
    Call this endpoint once to copy meals, gallery, and leaderboard data.
    """
    if request.method == 'OPTIONS':
        return jsonify({'message': 'OK'}), 200

    # Only allow migration if MongoDB is available
    if not USE_MONGO or mongo_db is None:
        return jsonify({
            'error': 'MongoDB not available. Migration not possible.',
            'mongodb_connected': USE_MONGO,
            'mongo_db': str(mongo_db)
        }), 400

    results = {
        'meals': {'sqlite_count': 0, 'mongo_count': 0, 'status': 'pending'},
        'gallery': {'sqlite_count': 0, 'mongo_count': 0, 'status': 'pending'},
        'leaderboard': {'sqlite_count': 0, 'mongo_count': 0, 'status': 'pending'}
    }

    try:
        # Connect to SQLite
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # === MIGRATE MEALS ===
        print("🔄 Migrating meals from SQLite to MongoDB...")
        try:
            # Get meals from SQLite
            rows = cursor.execute('SELECT * FROM meals ORDER BY id').fetchall()
            meals = [dict(row) for row in rows]
            results['meals']['sqlite_count'] = len(meals)

            if meals:
                # Clear existing MongoDB meals
                mongo_meals.delete_many({})

                # Convert and insert
                for meal in meals:
                    mongo_doc = {
                        'name': meal.get('name', ''),
                        'description': meal.get('description', ''),
                        'price': float(meal.get('price', 0)),
                        'image': meal.get('image', ''),
                        'category': meal.get('category', 'Pasta'),
                        'created_at': datetime.now(),
                        'sqlite_id': meal.get('id')  # Keep reference
                    }
                    mongo_meals.insert_one(mongo_doc)

                results['meals']['mongo_count'] = mongo_meals.count_documents({})
                results['meals']['status'] = 'success'
                print(f"✅ Migrated {results['meals']['mongo_count']} meals")
            else:
                results['meals']['status'] = 'no_data'
                print("ℹ️ No meals found in SQLite")

        except Exception as e:
            results['meals']['status'] = 'error'
            results['meals']['error'] = str(e)
            print(f"❌ Error migrating meals: {e}")

        # === MIGRATE GALLERY ===
        print("🔄 Migrating gallery from SQLite to MongoDB...")
        try:
            rows = cursor.execute('SELECT * FROM gallery ORDER BY id').fetchall()
            images = [dict(row) for row in rows]
            results['gallery']['sqlite_count'] = len(images)

            if images:
                mongo_gallery.delete_many({})

                for img in images:
                    mongo_doc = {
                        'title': img.get('title', ''),
                        'description': img.get('description', ''),
                        'image_url': img.get('image_url', ''),
                        'category': img.get('category', 'Featured'),
                        'created_at': datetime.now(),
                        'sqlite_id': img.get('id')
                    }
                    mongo_gallery.insert_one(mongo_doc)

                results['gallery']['mongo_count'] = mongo_gallery.count_documents({})
                results['gallery']['status'] = 'success'
                print(f"✅ Migrated {results['gallery']['mongo_count']} gallery images")
            else:
                results['gallery']['status'] = 'no_data'
                print("ℹ️ No gallery images found in SQLite")

        except Exception as e:
            results['gallery']['status'] = 'error'
            results['gallery']['error'] = str(e)
            print(f"❌ Error migrating gallery: {e}")

        # === MIGRATE LEADERBOARD ===
        print("🔄 Migrating leaderboard from SQLite to MongoDB...")
        try:
            rows = cursor.execute('SELECT * FROM leaderboard ORDER BY rank').fetchall()
            entries = [dict(row) for row in rows]
            results['leaderboard']['sqlite_count'] = len(entries)

            if entries:
                leaderboard_collection.delete_many({})

                for entry in entries:
                    mongo_doc = {
                        'rank': int(entry.get('rank', 0)),
                        'player': entry.get('player', ''),
                        'plates': int(entry.get('plates', entry.get('score', 0))),
                        'score': int(entry.get('plates', entry.get('score', 0))),
                        'img': entry.get('img', 'https://i.postimg.cc/RFQyqcrR/IMG-20260222-WA0018.jpg'),
                        'sqlite_id': entry.get('id')
                    }
                    leaderboard_collection.insert_one(mongo_doc)

                results['leaderboard']['mongo_count'] = leaderboard_collection.count_documents({})
                results['leaderboard']['status'] = 'success'
                print(f"✅ Migrated {results['leaderboard']['mongo_count']} leaderboard entries")
            else:
                results['leaderboard']['status'] = 'no_data'
                print("ℹ️ No leaderboard entries found in SQLite")

        except Exception as e:
            results['leaderboard']['status'] = 'error'
            results['leaderboard']['error'] = str(e)
            print(f"❌ Error migrating leaderboard: {e}")

        conn.close()

        # Summary
        total_migrated = (results['meals']['mongo_count'] + 
                         results['gallery']['mongo_count'] + 
                         results['leaderboard']['mongo_count'])

        print(f"🎉 Migration complete! Total items migrated: {total_migrated}")

        return jsonify({
            'message': f'Migration complete! {total_migrated} items migrated.',
            'details': results,
            'note': 'Your data is now in MongoDB. The app will use MongoDB going forward.'
        })

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Migration failed',
            'message': str(e),
            'details': results
        }), 500

# === DIAGNOSTIC ENDPOINT: Check database status ===
@app.route('/api/db_status', methods=['GET'])
def db_status():
    """Check the status of both SQLite and MongoDB databases"""
    status = {
        'mongodb': {
            'connected': USE_MONGO,
            'uri_configured': bool(os.getenv('LEADERBOARD_MONGODB_URI') or os.getenv('MONGODB_URL')),
            'client': str(mongo_client),
            'db': str(mongo_db),
            'meals_collection': str(mongo_meals),
            'gallery_collection': str(mongo_gallery),
            'leaderboard_collection': str(leaderboard_collection)
        },
        'sqlite': {
            'db_name': DB_NAME,
            'exists': os.path.exists(DB_NAME)
        },
        'data_counts': {}
    }

    # Count data in both databases
    try:
        if USE_MONGO and mongo_meals:
            status['data_counts']['mongodb_meals'] = mongo_meals.count_documents({})
            status['data_counts']['mongodb_gallery'] = mongo_gallery.count_documents({})
            status['data_counts']['mongodb_leaderboard'] = leaderboard_collection.count_documents({})
    except Exception as e:
        status['data_counts']['mongodb_error'] = str(e)

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        status['data_counts']['sqlite_meals'] = cursor.execute('SELECT COUNT(*) FROM meals').fetchone()[0]
        status['data_counts']['sqlite_gallery'] = cursor.execute('SELECT COUNT(*) FROM gallery').fetchone()[0]
        status['data_counts']['sqlite_leaderboard'] = cursor.execute('SELECT COUNT(*) FROM leaderboard').fetchone()[0]
        conn.close()
    except Exception as e:
        status['data_counts']['sqlite_error'] = str(e)

    return jsonify(status)

# === Run app ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
