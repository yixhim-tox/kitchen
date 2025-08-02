from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader  # ✅ Cloudinary added

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DB_NAME = 'meals.db'

# ✅ Cloudinary Configuration
cloudinary.config(
    cloud_name='denmxg0a5',      # 🔁 Replace with actual cloud name
    api_key='272213367143922',            # 🔁 Replace with your Cloudinary API key
    api_secret='w-ABxei5675kKaZdysi9ncxvHi8'       # 🔁 Replace with your Cloudinary API secret
)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize DB
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
        conn.commit()

init_db()

@app.route('/')
def home():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute('SELECT * FROM meals').fetchall()
    conn.close()
    return render_template('index.html', meals=meals)

@app.route('/menu')
def menu():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute('SELECT * FROM meals').fetchall()
    conn.close()
    return render_template('menu.html', meals=meals)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = request.form['price']
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

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT INTO meals (name, description, price, image, category) VALUES (?, ?, ?, ?, ?)",
                  (name, description, price, image_path, category))
        conn.commit()
        conn.close()
        return redirect(url_for('admin'))

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute('SELECT * FROM meals').fetchall()
    conn.close()
    return render_template('admin.html', meals=meals)

@app.route('/edit/<int:meal_id>', methods=['POST'])
def edit_meal(meal_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    name = request.form['name']
    description = request.form['description']
    price = request.form['price']
    image = request.form['image']
    category = request.form['category']

    c.execute('''
        UPDATE meals SET name = ?, description = ?, price = ?, image = ?, category = ? WHERE id = ?
    ''', (name, description, price, image, category, meal_id))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

# ✅ FIXED: DELETE should use POST
@app.route('/delete/<int:meal_id>', methods=['POST'])
def delete_meal(meal_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM meals WHERE id = ?', (meal_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/add_to_cart/<int:meal_id>')
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

    placeholders = ','.join('?' * len(meal_ids))
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute(f'SELECT * FROM meals WHERE id IN ({placeholders})', meal_ids).fetchall()
    conn.close()

    total = sum(meal['price'] * cart[str(meal['id'])] for meal in meals)
    return render_template('cart.html', meals=meals, cart=cart, total=total)

@app.route('/remove_from_cart/<int:meal_id>')
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

    placeholders = ','.join('?' * len(meal_ids))
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute(f'SELECT * FROM meals WHERE id IN ({placeholders})', meal_ids).fetchall()
    conn.close()

    total = sum(meal['price'] * cart[str(meal['id'])] for meal in meals)
    return render_template('checkout.html', meals=meals, cart=cart, total=total)

@app.route('/api/meals')
def api_meals():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    meals = conn.execute('SELECT * FROM meals').fetchall()
    conn.close()

    result = []
    for meal in meals:
        result.append({
            'id': meal['id'],
            'name': meal['name'],
            'description': meal['description'],
            'price': meal['price'],
            'image': meal['image'],
            'category': meal['category'] or 'Meals'
        })
    return jsonify(result)

# ✅ CLOUDINARY UPLOAD ROUTE
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

if __name__ == '__main__':
    app.run(debug=True)
