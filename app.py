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
        # Get lesson title
        title = request.form.get('lesson_title')
        
        # Get slides with new structure
        slide_contents = request.form.getlist('slide_content')
        slide_image_urls = request.form.getlist('slide_image_url')
        
        # Create slides array with image and content
        slides = []
        for i in range(len(slide_contents)):
            slide = {
                'content': slide_contents[i] if slide_contents[i] else None,
                'image_url': slide_image_urls[i] if slide_image_urls[i] else None
            }
            slides.append(slide)
        
        # Create lesson document
        lesson = {
            'title': title,
            'slides': slides,
            'date_created': datetime.datetime.utcnow(),
            'is_slide_format': True
        }
        
        # Add quiz if present
        if request.form.get('has_quiz'):
            questions = request.form.getlist('quiz_questions[]')
            answers = request.form.getlist('quiz_answers[]')
            types = request.form.getlist('quiz_question_types[]')
            quiz_questions = []
            for idx, q in enumerate(questions):
                q_type = types[idx] if idx < len(types) else 'short_answer'
                q_obj = {
                    'question': q,
                    'type': q_type,
                    'answer': answers[idx] if idx < len(answers) else ''
                }
                if q_type == 'multiple_choice':
                    # Collect all options for this question
                    options = []
                    opt_idx = 1
                    while True:
                        opt_key = f'quiz_option_{opt_idx}[]'
                        opt_vals = request.form.getlist(opt_key)
                        if not opt_vals:
                            break
                        # Each opt_vals is a list, one value per question block
                        if len(opt_vals) > idx:
                            options.append(opt_vals[idx])
                        opt_idx += 1
                    q_obj['options'] = options
                quiz_questions.append(q_obj)
            quiz_data = {
                'questions': quiz_questions,
                'completed_by': []
            }
            lesson['quiz'] = quiz_data
        
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

@app.route('/delete_lesson/<lesson_id>')
@login_required
def delete_lesson(lesson_id):
    if not session.get('is_admin', False):
        flash('Access denied', 'error')
        return redirect(url_for('lessons'))
    password = request.args.get('password', '')
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    if not user or user.get('password') != hashlib.sha256(password.encode('utf-8')).hexdigest():
        flash('Incorrect admin password.', 'error')
        return redirect(url_for('lessons'))
    try:
        lessons_collection.delete_one({'_id': ObjectId(lesson_id)})
        flash('Lesson deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting lesson: {e}', 'error')
    return redirect(url_for('lessons'))

@app.route('/take_lesson_quiz/<lesson_id>', methods=['POST'])
@login_required
def take_lesson_quiz(lesson_id):
    lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    if not lesson or 'quiz' not in lesson:
        flash('Quiz not found for this lesson.', 'error')
        return redirect(url_for('lesson_detail', lesson_id=lesson_id))

    user_id = str(session['user_id'])
    quiz = lesson['quiz']
    questions = quiz['questions']
    user_answers = request.form.getlist('answers[]')
    score = 0
    total = len(questions)
    results = []

    for idx, q in enumerate(questions):
        q_type = q.get('type', 'short_answer')
        correct = False
        user_answer = user_answers[idx].strip() if idx < len(user_answers) else ''
        correct_answer = q.get('answer', '').strip()
        if q_type == 'short_answer':
            correct = user_answer.lower().strip() == correct_answer.lower().strip()
        elif q_type == 'multiple_choice':
            # For MC, user_answer is the selected option index (1-based as string), correct_answer is also 1-based as string
            correct = user_answer == correct_answer
            # For review, show the option text
            user_answer_text = q['options'][int(user_answer)-1] if user_answer.isdigit() and 1 <= int(user_answer) <= len(q['options']) else user_answer
            correct_answer_text = q['options'][int(correct_answer)-1] if correct_answer.isdigit() and 1 <= int(correct_answer) <= len(q['options']) else correct_answer
        elif q_type == 'true_false':
            correct = user_answer.lower() == correct_answer.lower()
            user_answer_text = user_answer.capitalize()
            correct_answer_text = correct_answer.capitalize()
        else:
            user_answer_text = user_answer
            correct_answer_text = correct_answer
        if q_type == 'multiple_choice' or q_type == 'true_false':
            results.append({'question': q['question'], 'your_answer': user_answer_text, 'correct_answer': correct_answer_text, 'is_correct': correct})
        else:
            results.append({'question': q['question'], 'your_answer': user_answer, 'correct_answer': correct_answer, 'is_correct': correct})
        if correct:
            score += 1

    # Store result in lesson document (per user)
    if 'results' not in quiz:
        quiz['results'] = {}
    quiz['results'][user_id] = {
        'score': score,
        'total_questions': total,
        'percentage': (score / total) * 100 if total else 0,
        'details': results
    }
    if 'completed_by' not in quiz:
        quiz['completed_by'] = []
    if user_id not in quiz['completed_by']:
        quiz['completed_by'].append(user_id)
    lessons_collection.update_one({'_id': ObjectId(lesson_id)}, {'$set': {'quiz': quiz}})
    flash(f'Quiz submitted! Your score: {score}/{total}', 'success')
    return redirect(url_for('lesson_detail', lesson_id=lesson_id))

@app.route('/reset_lesson_quiz/<lesson_id>', methods=['POST'])
@login_required
def reset_lesson_quiz(lesson_id):
    lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    if not lesson or 'quiz' not in lesson:
        flash('Quiz not found for this lesson.', 'error')
        return redirect(url_for('lesson_detail', lesson_id=lesson_id))

    user_id = str(session['user_id'])
    quiz = lesson['quiz']
    # Remove user from completed_by and results
    if 'completed_by' in quiz and user_id in quiz['completed_by']:
        quiz['completed_by'].remove(user_id)
    if 'results' in quiz and user_id in quiz['results']:
        del quiz['results'][user_id]
    lessons_collection.update_one({'_id': ObjectId(lesson_id)}, {'$set': {'quiz': quiz}})
    flash('Quiz reset. You can take it again.', 'success')
    return redirect(url_for('lesson_detail', lesson_id=lesson_id))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
