from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

DB_NAME = 'meals.db'

cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USE_MONGO = os.getenv('MONGODB_URL') is not None
if USE_MONGO:
    mongo_client = MongoClient(os.getenv('MONGODB_URL'))
    mongo_db = mongo_client['tgs_kitchen']
    mongo_meals = mongo_db['meals']
    mongo_leaderboard = mongo_db['leaderboard']  # leaderboard collection

def init_db():
    if not USE_MONGO:
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
            conn.commit()

init_db()

def get_all_meals():
    if USE_MONGO:
        return list(mongo_meals.find().sort("_id", -1))
    else:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        meals = conn.execute('SELECT * FROM meals ORDER BY id DESC').fetchall()
        conn.close()
        return meals

@app.route('/')
def home():
    meals = get_all_meals()
    return render_template('index.html', meals=meals)

@app.route('/menu')
def menu():
    meals = get_all_meals()
    return render_template('menu.html', meals=meals)

# === Admin page (meals + leaderboard together) ===
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and 'name' in request.form:
        # Meal submission
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        category = request.form['category']
        image_url = request.form['image']
        file = request.files['file']

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            image_path = '/' + filepath.replace('\\', '/')
        elif image_url:
            image_path = image_url
        else:
            image_path = ''

        if USE_MONGO:
            mongo_meals.insert_one({
                'name': name,
                'description': description,
                'price': price,
                'image': image_path,
                'category': category
            })
        else:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute(
                "INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
                (name, description, price, image_path, category)
            )
            conn.commit()
            conn.close()
        return redirect(url_for('admin'))

    # Get meals and leaderboard data
    meals = get_all_meals()
    leaderboard = list(mongo_leaderboard.find().sort('plates', -1)) if USE_MONGO else []
    return render_template('admin.html', meals=meals, leaderboard=leaderboard)

@app.route('/edit/<meal_id>', methods=['POST'])
def edit_meal(meal_id):
    name = request.form['name']
    description = request.form['description']
    price = float(request.form['price'])
    image = request.form['image']
    category = request.form['category']

    if USE_MONGO:
        mongo_meals.update_one({'_id': ObjectId(meal_id)}, {
            '$set': {
                'name': name,
                'description': description,
                'price': price,
                'image': image,
                'category': category
            }
        })
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''
            UPDATE meals SET name = ?, description = ?, price = ?, image = ?, category = ? WHERE id = ?
        ''', (name, description, price, image, category, meal_id))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/delete/<meal_id>', methods=['POST'])
def delete_meal(meal_id):
    if USE_MONGO:
        mongo_meals.delete_one({'_id': ObjectId(meal_id)})
    else:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM meals WHERE id = ?', (meal_id,))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/add_to_cart/<meal_id>')
def add_to_cart(meal_id):
    cart = session.get('cart', {})
    cart[str(meal_id)] = cart.get(str(meal_id), 0) + 1
    session['cart'] = cart
    return redirect(url_for('home'))

@app.route('/cart')
def cart():
    cart = session.get('cart', {})
    meal_ids = list(cart.keys())

    if not meal_ids:
        return render_template('cart.html', meals=[], total=0)

    if USE_MONGO:
        meals = list(mongo_meals.find({'_id': {'$in': [ObjectId(id) for id in meal_ids]}}))
        total = sum(meal['price'] * cart[str(meal['_id'])] for meal in meals)
    else:
        placeholders = ','.join('?' * len(meal_ids))
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        meals = conn.execute(f'SELECT * FROM meals WHERE id IN ({placeholders})', meal_ids).fetchall()
        conn.close()
        total = sum(meal['price'] * cart[str(meal['id'])] for meal in meals)

    return render_template('cart.html', meals=meals, cart=cart, total=total)

@app.route('/remove_from_cart/<meal_id>')
def remove_from_cart(meal_id):
    cart = session.get('cart', {})
    cart.pop(str(meal_id), None)
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/checkout')
def checkout():
    cart = session.get('cart', {})
    meal_ids = list(cart.keys())

    if not meal_ids:
        return render_template('checkout.html', meals=[], total=0)

    if USE_MONGO:
        meals = list(mongo_meals.find({'_id': {'$in': [ObjectId(id) for id in meal_ids]}}))
        total = sum(meal['price'] * cart[str(meal['_id'])] for meal in meals)
    else:
        placeholders = ','.join('?' * len(meal_ids))
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        meals = conn.execute(f'SELECT * FROM meals WHERE id IN ({placeholders})', meal_ids).fetchall()
        conn.close()
        total = sum(meal['price'] * cart[str(meal['id'])] for meal in meals)

    import urllib.parse
    order_details = "\n".join([
        f"{meal['name']} x{cart[str(meal['_id'])] if USE_MONGO else cart[str(meal['id'])]} = ₦{meal['price'] * (cart[str(meal['_id'])] if USE_MONGO else cart[str(meal['id'])]):,.2f}"
        for meal in meals
    ])
    message = f"New Order:\n{order_details}\n\nTotal: ₦{total:,.2f}"
    encoded_message = urllib.parse.quote(message)
    whatsapp_url = f"https://wa.me/2349061120754?text={encoded_message}"

    session.pop('cart', None)

    return redirect(whatsapp_url)

@app.route('/leaderboard')
def leaderboard():
    return render_template('leaderboard.html')

@app.route('/api/meals')
def api_meals():
    meals = get_all_meals()
    result = []
    for meal in meals:
        result.append({
            'id': str(meal['_id']) if USE_MONGO else meal['id'],
            'name': meal['name'],
            'description': meal['description'],
            'price': meal['price'],
            'image': meal['image'],
            'category': meal.get('category', 'Meals')
        })
    return jsonify(result)

@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    image = request.files['image']
    try:
        upload_result = cloudinary.uploader.upload(image)
        return jsonify({'url': upload_result['secure_url']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === Add Meal via JavaScript ===
@app.route('/api/add_meal', methods=['POST'])
def api_add_meal():
    data = request.get_json()
    name = data.get('name')
    description = data.get('description', '')
    price = float(data.get('price', 0))
    image = data.get('image', '')
    category = data.get('category', 'Meals')

    if USE_MONGO:
        mongo_meals.insert_one({
            'name': name,
            'description': description,
            'price': price,
            'image': image,
            'category': category
        })
        return jsonify({'message': 'Meal added successfully'})
    return jsonify({'error': 'MongoDB not available'}), 500

# === Update Meal via JavaScript ===
@app.route('/api/update_meal/<meal_id>', methods=['POST'])
def api_update_meal(meal_id):
    data = request.get_json()
    update_fields = {
        'name': data.get('name'),
        'description': data.get('description'),
        'price': float(data.get('price')),
        'image': data.get('image'),
        'category': data.get('category')
    }

    if USE_MONGO:
        mongo_meals.update_one({'_id': ObjectId(meal_id)}, {'$set': update_fields})
        return jsonify({'message': 'Meal updated successfully'})
    return jsonify({'error': 'MongoDB not available'}), 500

# === Delete Meal via JavaScript ===
@app.route('/api/delete_meal/<meal_id>', methods=['DELETE'])
def api_delete_meal(meal_id):
    if USE_MONGO:
        mongo_meals.delete_one({'_id': ObjectId(meal_id)})
        return jsonify({'message': 'Meal deleted successfully'})
    return jsonify({'error': 'MongoDB not available'}), 500

# === Leaderboard API ===
@app.route('/api/add_leaderboard', methods=['POST'])
def api_add_leaderboard():
    data = request.get_json()
    user_name = data.get('user_name')
    plates = int(data.get('plates', 0))
    profile = data.get('profile', '')

    mongo_leaderboard.insert_one({
        'user_name': user_name,
        'plates': plates,
        'profile': profile
    })
    return jsonify({'message': 'Leaderboard user added successfully'})


@app.route('/api/update_leaderboard/<user_id>', methods=['POST'])
def api_update_leaderboard(user_id):
    data = request.get_json()
    update_fields = {
        'user_name': data.get('user_name'),
        'plates': int(data.get('plates', 0)),
        'profile': data.get('profile', '')
    }
    mongo_leaderboard.update_one({'_id': ObjectId(user_id)}, {'$set': update_fields})
    return jsonify({'message': 'Leaderboard user updated successfully'})


@app.route('/api/delete_leaderboard/<user_id>', methods=['DELETE'])
def api_delete_leaderboard(user_id):
    mongo_leaderboard.delete_one({'_id': ObjectId(user_id)})
    return jsonify({'message': 'Leaderboard user deleted successfully'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)