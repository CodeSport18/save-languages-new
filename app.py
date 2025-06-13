from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from functools import wraps
import os
from translations import translations
from bson.objectid import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv
import hashlib
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '!hUcAZCNrL-HM&-')

# MongoDB connection

mongo_uri = os.environ.get('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['koshur']
lessons_collection = db['lessons']
users_collection = db['users']

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def before_request():
    # Set default locale to English if not set
    if 'locale' not in session:
        session['locale'] = 'en'
    
    # Get the current locale
    g.locale = session.get('locale', 'en')
    
    # Ensure the locale exists in translations
    if g.locale not in translations:
        g.locale = 'en'
    
    # Make translations available to all templates
    g.t = translations[g.locale]

@app.context_processor
def inject_translations():
    return {'t': g.t}

@app.route('/')
def homepage():
    return render_template('main.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        user = users_collection.find_one({'username': username})
        if user:
            password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
            if user.get('password') == password_hash:
                session['user_id'] = str(user['_id'])
                session['is_admin'] = user.get('is_admin', False)
                flash('Successfully logged in!', 'success')
                return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        if users_collection.find_one({'username': username}):
            flash('Username already exists', 'error')
        else:
            password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
            users_collection.insert_one({'username': username, 'password': password_hash, 'is_admin': False})
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out!', 'success')
    return redirect(url_for('homepage'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/lessons')
@login_required
def lessons():
    lessons = list(lessons_collection.find())
    return render_template('lessons.html', lessons=lessons)

@app.route('/lesson/<lesson_id>')
@login_required
def lesson_detail(lesson_id):
    try:
        lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    except Exception:
        lesson = None
    if not lesson:
        abort(404)
    return render_template('lesson_detail.html', lesson=lesson)

@app.route('/create_lesson')
@login_required
def create_lesson():
    if not session.get('is_admin'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return render_template('create_lesson.html')

@app.route('/quizzes')
@login_required
def quizzes():
    return render_template('quizzes.html')

@app.route('/create_quiz')
@login_required
def create_quiz():
    if not session.get('is_admin'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return render_template('create_quiz.html')

@app.route('/take_quiz/<int:quiz_id>')
@login_required
def take_quiz(quiz_id):
    return render_template('take_quiz.html')

@app.route('/lesson_history')
@login_required
def lesson_history():
    return render_template('lesson_history.html')

@app.route('/quiz_history')
@login_required
def quiz_history():
    return render_template('quiz_history.html')

@app.route('/change_language/<language>')
def change_language(language):
    if language in translations:
        session['locale'] = language
    return redirect(request.referrer or url_for('homepage'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
