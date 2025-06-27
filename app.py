from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort, jsonify
from functools import wraps
import os
from translations import translations
from bson.objectid import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv
import hashlib
from werkzeug.utils import secure_filename
import time
import boto3
from botocore.exceptions import ClientError
import datetime
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '!hUcAZCNrL-HM&-')

# MongoDB connection
mongo_uri = os.environ.get('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['koshur']
lessons_collection = db['lessons']
users_collection = db['users']

# AWS S3 configuration
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_REGION', 'us-east-1')
)
S3_BUCKET = os.environ.get('S3_BUCKET')
S3_BASE_URL = f"https://{S3_BUCKET}.s3.amazonaws.com"

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_audio_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}

def upload_to_s3(file, filename):
    try:
        s3_client.upload_fileobj(
            file,
            S3_BUCKET,
            f"uploads/{filename}",
            ExtraArgs={
                'ContentType': file.content_type
            }
        )
        return f"{S3_BASE_URL}/uploads/{filename}"
    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        return None

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
                session['is_admin'] = bool(user.get('is_admin', False))
                flash('Successfully logged in!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password', 'error')
        else:
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

@app.route('/create_lesson', methods=['GET', 'POST'])
@login_required
def create_lesson():
    if not session.get('is_admin', False):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        # Basic lesson creation logic (expand as needed)
        title = request.form.get('lesson_title')
        slides = [s for s in request.form.getlist('slide_content') if s and s.strip()]
        lesson = {
            'title': title,
            'slides': slides,
            'date_created': datetime.datetime.utcnow(),
            'is_slide_format': True
        }
        lessons_collection.insert_one(lesson)
        flash('Lesson created successfully!', 'success')
        return redirect(url_for('lessons'))
    return render_template('create_lesson.html')

@app.route('/quizzes')
@login_required
def quizzes():
    return render_template('quizzes.html')

@app.route('/create_quiz')
@login_required
def create_quiz():
    if not session.get('is_admin', False):
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

@app.route('/upload_inline_image', methods=['POST'])
@login_required
def upload_inline_image():
    print(request.form,request.files)
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No image file provided'})
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to filename to prevent overwriting
        filename = f"{int(time.time())}_{filename}"
        
        # Upload to S3
        s3_url = upload_to_s3(file, filename)
        print(file,filename)
        if s3_url:
            return jsonify({'success': True, 'filename': filename, 'url': s3_url})
        else:
            return jsonify({'success': False, 'error': 'Failed to upload image to S3'})
    
    print(file,filename)
    
    return jsonify({'success': False, 'error': 'Invalid file type'})

@app.route('/upload_audio', methods=['POST'])
@login_required
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'No audio file provided'})
    
    file = request.files['audio']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})
    
    if file and allowed_audio_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to filename to prevent overwriting
        filename = f"{int(time.time())}_{filename}"
        
        # Upload to S3
        s3_url = upload_to_s3(file, filename)
        if s3_url:
            return jsonify({'success': True, 'filename': filename, 'url': s3_url})
        else:
            return jsonify({'success': False, 'error': 'Failed to upload audio to S3'})
    
    return jsonify({'success': False, 'error': 'Invalid file type'})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
