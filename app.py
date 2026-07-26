from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort, jsonify
from functools import wraps
import os
from pathlib import Path
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
import re

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / '.env'
# override=True so values in .env win over empty/stale shell env vars
load_dotenv(ENV_PATH, override=True)

def require_env(name):
    value = os.environ.get(name)
    if value is None or str(value).strip() == '':
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Set it in {ENV_PATH} (see .env.template)."
        )
    return value.strip()

app = Flask(__name__)
app.secret_key = require_env('SECRET_KEY')

# MongoDB connection
mongo_uri = require_env('MONGO_URI')
client = MongoClient(mongo_uri, tlsAllowInvalidCertificates=True)
db = client['koshur']
lessons_collection = db['lessons']
users_collection = db['users']
quizzes_collection = db['quizzes']

# AWS S3 configuration
s3_client = boto3.client(
    's3',
    aws_access_key_id=require_env('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=require_env('AWS_SECRET_ACCESS_KEY'),
    region_name=os.environ.get('AWS_REGION', 'us-east-1').strip() or 'us-east-1'
)
S3_BUCKET = require_env('S3_BUCKET')
S3_BASE_URL = f"https://{S3_BUCKET}.s3.amazonaws.com"

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'm4a', 'ogg', 'webm'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_audio_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS

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

def sanitize_slide_content(content):
    if not content:
        return None
    # Remove HTML tags and whitespace
    text = re.sub(r'<[^>]*>', '', content)
    text = text.replace('&nbsp;', '').strip()
    if not text:
        return None
    return content

def _form_list_value(values, idx, default=''):
    if idx < len(values):
        return values[idx]
    return default

def _slide_url_at(urls, index_str):
    try:
        idx = int(str(index_str).strip())
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx >= len(urls):
        return None
    url = urls[idx]
    return url if url else None

def parse_lesson_quiz_questions(form, slide_image_urls, slide_audio_urls):
    """Parse quiz questions from a lesson create/edit form."""
    questions = form.getlist('quiz_questions[]')
    answers = form.getlist('quiz_answers[]')
    types = form.getlist('quiz_question_types[]')
    audio_slides = form.getlist('quiz_audio_slide[]')
    image_slide_lists = [
        form.getlist('quiz_image_slide_1[]'),
        form.getlist('quiz_image_slide_2[]'),
        form.getlist('quiz_image_slide_3[]'),
        form.getlist('quiz_image_slide_4[]'),
    ]

    quiz_questions = []
    question_images = form.getlist('quiz_question_image_url[]')
    for idx, q in enumerate(questions):
        q_type = _form_list_value(types, idx, 'short_answer') or 'short_answer'
        image_url = (_form_list_value(question_images, idx) or '').strip() or None
        q_obj = {
            'question': q,
            'type': q_type,
            'answer': (_form_list_value(answers, idx) or '').strip(),
            'image_url': image_url,
        }
        if q_type == 'multiple_choice':
            options = []
            opt_idx = 1
            while True:
                opt_vals = form.getlist(f'quiz_option_{opt_idx}[]')
                if not opt_vals:
                    break
                if len(opt_vals) > idx and opt_vals[idx]:
                    options.append(opt_vals[idx])
                opt_idx += 1
            q_obj['options'] = options
        elif q_type == 'audio_image':
            audio_slide = _form_list_value(audio_slides, idx, '')
            audio_url = _slide_url_at(slide_audio_urls, audio_slide)
            image_options = []
            image_slide_indexes = []
            for image_list in image_slide_lists:
                slide_idx = _form_list_value(image_list, idx, '')
                image_slide_indexes.append(slide_idx)
                image_options.append(_slide_url_at(slide_image_urls, slide_idx))
            q_obj['audio_url'] = audio_url
            q_obj['audio_slide_index'] = audio_slide
            q_obj['image_options'] = image_options
            q_obj['image_slide_indexes'] = image_slide_indexes
        quiz_questions.append(q_obj)
    return quiz_questions

def get_quiz_user_answer(form, idx):
    value = form.get(f'answer_{idx}')
    if value is not None:
        return value.strip()
    answers = form.getlist('answers[]')
    return answers[idx].strip() if idx < len(answers) else ''

def parse_independent_quiz_questions(form):
    """Parse questions from independent quiz create/edit forms."""
    questions = form.getlist('quiz_questions[]')
    answers = form.getlist('quiz_answers[]')
    types = form.getlist('quiz_question_types[]')
    question_images = form.getlist('quiz_question_image_url[]')

    quiz_questions = []
    for idx, q in enumerate(questions):
        q_type = types[idx] if idx < len(types) else 'short_answer'
        image_url = (question_images[idx] if idx < len(question_images) else '').strip() or None
        q_obj = {
            'question': q,
            'type': q_type,
            'answer': answers[idx] if idx < len(answers) else '',
            'image_url': image_url,
        }
        if q_type == 'multiple_choice':
            options = []
            opt_idx = 1
            while True:
                opt_vals = form.getlist(f'quiz_option_{opt_idx}[]')
                if not opt_vals:
                    break
                if len(opt_vals) > idx and opt_vals[idx]:
                    options.append(opt_vals[idx])
                opt_idx += 1
            q_obj['options'] = options
        quiz_questions.append(q_obj)
    return quiz_questions

def lesson_has_quiz(lesson):
    quiz = lesson.get('quiz')
    return bool(quiz and quiz.get('questions'))

def is_lesson_completed(lesson, user_id):
    completions = lesson.get('completions', {})
    if user_id in completions:
        return True
    if lesson_has_quiz(lesson):
        return user_id in lesson['quiz'].get('completed_by', [])
    return False

def mark_lesson_completed(lesson_id, user_id):
    lessons_collection.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$set': {f'completions.{user_id}': {'completed_at': datetime.datetime.utcnow()}}}
    )

def get_user_completed_lessons(user_id):
    completed = []
    for lesson in lessons_collection.find():
        if not is_lesson_completed(lesson, user_id):
            continue
        completion = lesson.get('completions', {}).get(user_id, {})
        completed_at = completion.get('completed_at')
        if not completed_at and lesson_has_quiz(lesson):
            quiz_results = lesson['quiz'].get('results', {})
            if user_id in quiz_results:
                completed_at = datetime.datetime.utcnow()
        if not completed_at:
            completed_at = lesson.get('date_created', datetime.datetime.utcnow())
        completed.append({
            '_id': lesson['_id'],
            'title': lesson['title'],
            'completed_at': completed_at,
        })
    completed.sort(key=lambda x: x['completed_at'], reverse=True)
    return completed

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
    def format_date(date_obj):
        if date_obj:
            return date_obj.strftime('%B %d, %Y')
        return ''
    
    return {'t': g.t, 'format_date': format_date}

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
    user_id = str(session['user_id'])
    completed_lessons = get_user_completed_lessons(user_id)
    
    # Get quiz results
    quizzes = list(quizzes_collection.find())
    quiz_results = []
    
    for quiz in quizzes:
        if 'results' in quiz and user_id in quiz['results']:
            result = quiz['results'][user_id]
            quiz_results.append({
                'quiz_title': quiz['title'],
                'score': f"{result['score']}/{result['total_questions']}",
                'percentage': result['percentage'],
                'date_taken': quiz['date_created']
            })
    
    # Sort by date taken (most recent first)
    quiz_results.sort(key=lambda x: x['date_taken'], reverse=True)
    
    return render_template('dashboard.html', completed_lessons=completed_lessons, quiz_results=quiz_results)

@app.route('/lessons')
@login_required
def lessons():
    user_id = str(session['user_id'])
    lessons = list(lessons_collection.find())
    completed_lesson_ids = [
        str(lesson['_id']) for lesson in lessons if is_lesson_completed(lesson, user_id)
    ]
    return render_template('lessons.html', lessons=lessons, completed_lesson_ids=completed_lesson_ids)

@app.route('/lesson/<lesson_id>')
@login_required
def lesson_detail(lesson_id):
    try:
        lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    except Exception:
        lesson = None
    if not lesson:
        abort(404)
    # Fetch all lessons ordered by creation date (or title if you prefer)
    lessons = list(lessons_collection.find().sort('date_created', 1))
    lesson_ids = [str(l['_id']) for l in lessons]
    current_idx = lesson_ids.index(str(lesson_id)) if str(lesson_id) in lesson_ids else -1
    previous_lesson = lessons[current_idx - 1] if current_idx > 0 else None
    next_lesson = lessons[current_idx + 1] if current_idx < len(lessons) - 1 else None
    user_id = str(session['user_id'])
    lesson_completed = is_lesson_completed(lesson, user_id)
    return render_template(
        'lesson_detail.html',
        lesson=lesson,
        previous_lesson=previous_lesson,
        next_lesson=next_lesson,
        lesson_completed=lesson_completed,
        lesson_has_quiz=lesson_has_quiz(lesson),
    )

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
        slide_audio_urls = request.form.getlist('slide_audio_url')
        
        # Create slides array with image, content, and audio
        slides = []
        for i in range(len(slide_contents)):
            clean_content = sanitize_slide_content(slide_contents[i])
            slide = {
                'content': clean_content,
                'image_url': slide_image_urls[i] if slide_image_urls[i] else None,
                'audio_url': slide_audio_urls[i] if i < len(slide_audio_urls) and slide_audio_urls[i] else None
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
            quiz_questions = parse_lesson_quiz_questions(
                request.form,
                [u for u in slide_image_urls],
                [u for u in slide_audio_urls],
            )
            lesson['quiz'] = {
                'questions': quiz_questions,
                'completed_by': []
            }
        
        lessons_collection.insert_one(lesson)
        flash('Lesson created successfully!', 'success')
        return redirect(url_for('lessons'))
    return render_template('create_lesson.html')

@app.route('/quizzes')
@login_required
def quizzes():
    # Get all quizzes
    quizzes = list(quizzes_collection.find().sort('date_created', -1))
    
    # Get user's completed quizzes
    user_id = str(session['user_id'])
    completed_quizzes = []
    
    for quiz in quizzes:
        if 'completed_by' in quiz and user_id in quiz['completed_by']:
            completed_quizzes.append(str(quiz['_id']))
    
    return render_template('quizzes.html', quizzes=quizzes, completed_quizzes=completed_quizzes)

@app.route('/create_quiz', methods=['GET', 'POST'])
@login_required
def create_quiz():
    if not session.get('is_admin', False):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = (request.form.get('quiz_title') or '').strip()
        if not title:
            flash('Quiz title cannot be empty.', 'error')
            return render_template('create_quiz.html')

        quiz_questions = parse_independent_quiz_questions(request.form)
        quiz = {
            'title': title,
            'questions': quiz_questions,
            'date_created': datetime.datetime.utcnow(),
            'completed_by': []
        }
        
        quizzes_collection.insert_one(quiz)
        flash('Independent quiz created successfully!', 'success')
        return redirect(url_for('quizzes'))
    
    return render_template('create_quiz.html')

@app.route('/edit_quiz/<quiz_id>', methods=['GET', 'POST'])
@login_required
def edit_quiz(quiz_id):
    if not session.get('is_admin', False):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))

    try:
        quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    except Exception:
        quiz = None

    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('quizzes'))

    if request.method == 'POST':
        title = (request.form.get('quiz_title') or '').strip()
        if not title:
            flash('Quiz title cannot be empty.', 'error')
            return render_template('edit_quiz.html', quiz=quiz)

        quiz_questions = parse_independent_quiz_questions(request.form)
        quizzes_collection.update_one(
            {'_id': ObjectId(quiz_id)},
            {'$set': {
                'title': title,
                'questions': quiz_questions,
                # Keep completion history; learners can retake if needed
                'completed_by': quiz.get('completed_by', []),
                'results': quiz.get('results', {}),
            }}
        )
        flash('Independent quiz updated successfully!', 'success')
        return redirect(url_for('quizzes'))

    return render_template('edit_quiz.html', quiz=quiz)

@app.route('/take_quiz/<quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    try:
        quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    except Exception:
        quiz = None
    
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('quizzes'))
    
    user_id = str(session['user_id'])
    
    # Check if user has already completed this quiz
    if 'completed_by' in quiz and user_id in quiz['completed_by']:
        # Show results if already completed
        if 'results' in quiz and user_id in quiz['results']:
            result = quiz['results'][user_id]
            return render_template('take_quiz.html', quiz=quiz, result=result, completed=True)
    
    if request.method == 'POST':
        questions = quiz['questions']
        score = 0
        total = len(questions)
        results = []

        for idx, q in enumerate(questions):
            q_type = q.get('type', 'short_answer')
            correct = False
            user_answer = get_quiz_user_answer(request.form, idx)
            correct_answer = q.get('answer', '').strip()
            user_answer_text = user_answer
            correct_answer_text = correct_answer
            
            if q_type == 'short_answer':
                correct = user_answer.lower().strip() == correct_answer.lower().strip()
            elif q_type == 'multiple_choice':
                correct = user_answer == correct_answer
                user_answer_text = q['options'][int(user_answer)-1] if user_answer.isdigit() and 1 <= int(user_answer) <= len(q.get('options', [])) else user_answer
                correct_answer_text = q['options'][int(correct_answer)-1] if correct_answer.isdigit() and 1 <= int(correct_answer) <= len(q.get('options', [])) else correct_answer
            elif q_type == 'true_false':
                correct = user_answer.lower() == correct_answer.lower()
                user_answer_text = user_answer.capitalize()
                correct_answer_text = correct_answer.capitalize()
            
            results.append({
                'question': q.get('question', ''),
                'your_answer': user_answer_text,
                'correct_answer': correct_answer_text,
                'is_correct': correct,
                'image_url': q.get('image_url'),
            })
            
            if correct:
                score += 1

        # Store result in quiz document (per user)
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
        
        quizzes_collection.update_one({'_id': ObjectId(quiz_id)}, {'$set': quiz})
        flash(f'Quiz submitted! Your score: {score}/{total}', 'success')
        return redirect(url_for('take_quiz', quiz_id=quiz_id))
    
    return render_template('take_quiz.html', quiz=quiz, completed=False)

@app.route('/reset_quiz/<quiz_id>', methods=['POST'])
@login_required
def reset_quiz(quiz_id):
    try:
        quiz = quizzes_collection.find_one({'_id': ObjectId(quiz_id)})
    except Exception:
        quiz = None
    
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('quizzes'))

    user_id = str(session['user_id'])
    
    # Remove user from completed_by and results
    if 'completed_by' in quiz and user_id in quiz['completed_by']:
        quiz['completed_by'].remove(user_id)
    if 'results' in quiz and user_id in quiz['results']:
        del quiz['results'][user_id]
    
    quizzes_collection.update_one({'_id': ObjectId(quiz_id)}, {'$set': quiz})
    flash('Quiz reset. You can take it again.', 'success')
    return redirect(url_for('take_quiz', quiz_id=quiz_id))

@app.route('/lesson_history')
@login_required
def lesson_history():
    user_id = str(session['user_id'])
    completed_lessons = get_user_completed_lessons(user_id)
    return render_template('lesson_history.html', completed_lessons=completed_lessons)

@app.route('/complete_lesson/<lesson_id>', methods=['POST'])
@login_required
def complete_lesson(lesson_id):
    try:
        lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    except Exception:
        lesson = None
    if not lesson:
        flash('Lesson not found.', 'error')
        return redirect(url_for('lessons'))

    user_id = str(session['user_id'])
    if lesson_has_quiz(lesson) and user_id not in lesson.get('quiz', {}).get('completed_by', []):
        flash(g.t.get('complete_quiz_first', 'Complete the lesson quiz first.'), 'error')
        return redirect(url_for('lesson_detail', lesson_id=lesson_id))

    if not is_lesson_completed(lesson, user_id):
        mark_lesson_completed(lesson_id, user_id)
        flash(g.t.get('lesson_complete_success', 'Lesson marked as completed!'), 'success')
    return redirect(url_for('lesson_detail', lesson_id=lesson_id))

@app.route('/reset_lesson/<lesson_id>', methods=['POST'])
@login_required
def reset_lesson(lesson_id):
    try:
        lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    except Exception:
        lesson = None
    if not lesson:
        flash('Lesson not found.', 'error')
        return redirect(url_for('lessons'))

    user_id = str(session['user_id'])
    lessons_collection.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$unset': {f'completions.{user_id}': ''}}
    )
    flash(translations[session.get('locale', 'en')].get('lesson_reset_success', 'Lesson has been reset.'), 'success')
    return redirect(url_for('lesson_detail', lesson_id=lesson_id))

@app.route('/quiz_history')
@login_required
def quiz_history():
    user_id = str(session['user_id'])
    
    # Get all quizzes and filter for user's results
    quizzes = list(quizzes_collection.find())
    quiz_results = []
    
    for quiz in quizzes:
        if 'results' in quiz and user_id in quiz['results']:
            result = quiz['results'][user_id]
            quiz_results.append({
                'quiz_title': quiz['title'],
                'score': f"{result['score']}/{result['total_questions']}",
                'percentage': result['percentage'],
                'date_taken': quiz['date_created']  # Using quiz creation date as approximation
            })
    
    # Sort by date taken (most recent first)
    quiz_results.sort(key=lambda x: x['date_taken'], reverse=True)
    
    return render_template('quiz_history.html', quiz_results=quiz_results)

@app.route('/change_language/<language>')
def change_language(language):
    if language in translations:
        session['locale'] = language
    return redirect(request.referrer or url_for('homepage'))

@app.route('/upload_inline_image', methods=['POST'])
@login_required
def upload_inline_image():
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
        if s3_url:
            return jsonify({'success': True, 'filename': filename, 'url': s3_url})
        else:
            return jsonify({'success': False, 'error': 'Failed to upload image to S3'})
    
    return jsonify({'success': False, 'error': f'Unsupported image format. Please use: {", ".join(ALLOWED_EXTENSIONS)}'})

@app.route('/upload_inline_audio', methods=['POST'])
@login_required
def upload_inline_audio():
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'No audio file provided'})
    file = request.files['audio']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})
    if file and allowed_audio_file(file.filename):
        filename = secure_filename(file.filename)
        filename = f"{int(time.time())}_{filename}"
        s3_url = upload_to_s3(file, filename)
        if s3_url:
            return jsonify({'success': True, 'filename': filename, 'url': s3_url})
        else:
            return jsonify({'success': False, 'error': 'Failed to upload audio to S3'})
    return jsonify({'success': False, 'error': f'Unsupported audio format. Please use: {", ".join(ALLOWED_AUDIO_EXTENSIONS)}'})

@app.route('/edit_lesson/<lesson_id>', methods=['GET', 'POST'])
@login_required
def edit_lesson(lesson_id):
    if not session.get('is_admin', False):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        lesson = lessons_collection.find_one({'_id': ObjectId(lesson_id)})
    except Exception:
        lesson = None
    
    if not lesson:
        flash('Lesson not found.', 'error')
        return redirect(url_for('lessons'))
    
    if request.method == 'POST':
        new_title = (request.form.get('lesson_title') or '').strip()
        if not new_title:
            flash('Lesson title cannot be empty.', 'error')
            return render_template('edit_lesson.html', lesson=lesson)

        # Get all slides data (existing and new)
        slide_contents = request.form.getlist('slide_content')
        slide_image_urls = request.form.getlist('slide_image_url')
        slide_audio_urls = request.form.getlist('slide_audio_url')

        # Create new slides array
        updated_slides = []
        for i in range(len(slide_contents)):
            clean_content = sanitize_slide_content(slide_contents[i])
            slide = {
                'content': clean_content,
                'image_url': slide_image_urls[i] if i < len(slide_image_urls) and slide_image_urls[i] else None,
                'audio_url': slide_audio_urls[i] if i < len(slide_audio_urls) and slide_audio_urls[i] else None
            }
            updated_slides.append(slide)

        # Update title and slides together
        update_fields = {'title': new_title, 'slides': updated_slides}

        if request.form.get('has_quiz'):
            quiz_questions = parse_lesson_quiz_questions(
                request.form,
                slide_image_urls,
                slide_audio_urls,
            )
            existing_quiz = lesson.get('quiz') or {}
            update_fields['quiz'] = {
                'questions': quiz_questions,
                'completed_by': existing_quiz.get('completed_by', []),
                'results': existing_quiz.get('results', {}),
            }
        elif lesson.get('quiz'):
            # Quiz checkbox unchecked — remove quiz
            lessons_collection.update_one(
                {'_id': ObjectId(lesson_id)},
                {'$set': update_fields, '$unset': {'quiz': ''}}
            )
            flash('Successfully updated the lesson!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))

        lessons_collection.update_one(
            {'_id': ObjectId(lesson_id)},
            {'$set': update_fields}
        )

        flash('Successfully updated the lesson!', 'success')
        return redirect(url_for('lesson_detail', lesson_id=lesson_id))
    
    return render_template('edit_lesson.html', lesson=lesson)

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
    score = 0
    total = len(questions)
    results = []

    for idx, q in enumerate(questions):
        q_type = q.get('type', 'short_answer')
        correct = False
        user_answer = get_quiz_user_answer(request.form, idx)
        correct_answer = q.get('answer', '').strip()
        user_answer_text = user_answer
        correct_answer_text = correct_answer

        if q_type == 'short_answer':
            correct = user_answer.lower().strip() == correct_answer.lower().strip()
        elif q_type == 'multiple_choice':
            correct = user_answer == correct_answer
            user_answer_text = q['options'][int(user_answer)-1] if user_answer.isdigit() and 1 <= int(user_answer) <= len(q.get('options', [])) else user_answer
            correct_answer_text = q['options'][int(correct_answer)-1] if correct_answer.isdigit() and 1 <= int(correct_answer) <= len(q.get('options', [])) else correct_answer
        elif q_type == 'true_false':
            correct = user_answer.lower() == correct_answer.lower()
            user_answer_text = user_answer.capitalize()
            correct_answer_text = correct_answer.capitalize()
        elif q_type == 'audio_image':
            correct = user_answer == correct_answer
            image_options = q.get('image_options') or []
            def _option_label(choice):
                if choice.isdigit() and 1 <= int(choice) <= len(image_options):
                    return f"Image {choice}"
                return choice or '—'
            user_answer_text = _option_label(user_answer)
            correct_answer_text = _option_label(correct_answer)

        results.append({
            'question': q.get('question') or 'Listen and choose the correct image',
            'your_answer': user_answer_text,
            'correct_answer': correct_answer_text,
            'is_correct': correct,
            'type': q_type,
            'image_url': q.get('image_url'),
            'audio_url': q.get('audio_url'),
            'image_options': q.get('image_options') if q_type == 'audio_image' else None,
            'your_answer_index': user_answer if q_type == 'audio_image' else None,
            'correct_answer_index': correct_answer if q_type == 'audio_image' else None,
        })
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
    mark_lesson_completed(lesson_id, user_id)
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
    lessons_collection.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$set': {'quiz': quiz}, '$unset': {f'completions.{user_id}': ''}}
    )
    flash('Quiz reset. You can take it again.', 'success')
    return redirect(url_for('lesson_detail', lesson_id=lesson_id))

@app.route('/api/user/autoplay_sound', methods=['GET'])
@login_required
def get_autoplay_sound():
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    autoplay = user.get('autoplay_sound', False)
    return jsonify({'autoplay_sound': bool(autoplay)})

@app.route('/api/user/autoplay_sound', methods=['POST'])
@login_required
def set_autoplay_sound():
    data = request.get_json()
    autoplay = bool(data.get('autoplay_sound', False))
    users_collection.update_one({'_id': ObjectId(session['user_id'])}, {'$set': {'autoplay_sound': autoplay}})
    return jsonify({'success': True, 'autoplay_sound': autoplay})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
