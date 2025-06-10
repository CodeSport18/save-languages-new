import pymongo
from flask import Flask, render_template, request, redirect, session, flash, g, jsonify, send_from_directory, url_for
from passlib.hash import sha256_crypt
import qrcode
from datetime import datetime,date
import random
from flask_socketio import SocketIO,emit
import string
from bson import ObjectId
import os
import logging
from werkzeug.utils import secure_filename
from translations import translations

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ip_current = '192.168.1.112:5001'

# Get environment variables
password = os.environ.get('MONGODB_URI')
secret_key = os.environ.get('SECRET_KEY')

if not password or not secret_key:
    logger.error("Missing required environment variables")
    raise ValueError("MONGODB_URI and SECRET_KEY environment variables must be set")

loggedIn = False
app = Flask(__name__)
socketio = SocketIO(app)
app.secret_key = secret_key

try:
    logger.info("Attempting to connect to MongoDB...")
    client = pymongo.MongoClient(
        password,
        tlsAllowInvalidCertificates=True,
        serverSelectionTimeoutMS=5000  # 5 second timeout
    )
    # Test the connection
    client.admin.command('ping')
    db = client.koshur
    logger.info("Successfully connected to MongoDB!")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {str(e)}")
    raise

# Add these configurations after app initialization
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename, allowed_extensions=None):
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# Add after other app configurations
def get_locale():
    # Get language from session or default to English
    return session.get('language', 'en')

@app.before_request
def before_request():
    g.locale = get_locale()
    g.translations = translations[g.locale]
    g.format_date = lambda date: format_date(date, g.locale)

@app.route('/change_language/<language>')
def change_language(language):
    if language in translations:
        session['language'] = language
    return redirect(request.referrer or '/')

@app.route('/', methods=['GET', 'POST'])
def homepage():
    if request.method == 'GET':
        return render_template('main.html', t=g.translations)
    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Fetch user data from MongoDB
        user = db.users.find_one({'username': username})
        
        if user and sha256_crypt.verify(password, user['password']):
            session['user_id'] = str(user['_id'])
            session['is_admin'] = user.get('is_admin', False)  # Get admin status
            flash('Login successful', 'success')
            return redirect('/dashboard')
        else:
            flash('Invalid login credentials', 'error')
            return redirect('/login')
    
    return render_template('login.html', t=g.translations)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = sha256_crypt.encrypt(request.form['password'])
        
        # Check if user already exists
        if db.users.find_one({'username': username}):
            flash('Username already taken', 'error')
            return redirect('/register')
        
        # Create new user in MongoDB with is_admin set to False
        db.users.insert_one({
            'username': username,
            'password': password,
            'date_created': datetime.now(),
            'is_admin': False  # New users are not admins by default
        })
        
        flash('Registration successful, please log in', 'success')
        return redirect('/login')
    
    return render_template('register.html', t=g.translations)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have logged out', 'success')
    return redirect('/')

@app.route('/upload_inline_image', methods=['POST'])
def upload_inline_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'error': 'No image provided'})
    
    file = request.files['image']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'success': True, 'filename': filename})
    
    return jsonify({'success': False, 'error': 'Invalid file type'})

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': 'No audio provided'})
    
    file = request.files['audio']
    if file and allowed_file(file.filename, {'mp3', 'wav', 'ogg'}):
        filename = secure_filename(file.filename)
        filename = f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'success': True, 'filename': filename})
    
    return jsonify({'success': False, 'error': 'Invalid file type'})

@app.route('/create_lesson', methods=['GET', 'POST'])
def create_lesson():
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access', 'error')
        return redirect('/dashboard')
        
    if request.method == 'POST':
        title = request.form['lesson_title']
        has_quiz = 'has_quiz' in request.form
        
        slides = request.form.getlist('slide_content')  # Get all slides
        
        # Process quiz if present
        quiz = None
        if has_quiz:
            questions = request.form.getlist('quiz_questions[]')
            answers = request.form.getlist('quiz_answers[]')
            if questions and answers and len(questions) == len(answers):
                quiz = {
                    'questions': questions,
                    'answers': answers,
                    'completed_by': []
                }
        
        # Create lesson document
        lesson = {
            'title': title,
            'slides': slides,
            'is_slide_format': True,
            'date_created': datetime.now(),
            'created_by': session['user_id'],
            'completed_by': [],
            'quiz': quiz
        }
        
        db.lessons.insert_one(lesson)
        flash('Lesson created successfully', 'success')
        return redirect('/lessons')
        
    return render_template('create_lesson.html', t=g.translations)

@app.route('/create_quiz', methods=['GET', 'POST'])
def create_quiz():
    if 'user_id' not in session:
        flash('Please log in to create quizzes', 'error')
        return redirect('/login')
    
    if not session.get('is_admin', False):  # Check for admin status
        flash('You do not have permission to create quizzes', 'error')
        return redirect('/dashboard')
        
    if request.method == 'POST':
        quiz_title = request.form['quiz_title']
        questions = request.form.getlist('questions')
        answers = request.form.getlist('answers')  # Correct answers
        
        # Store quiz data in MongoDB
        db.quizzes.insert_one({
            'title': quiz_title,
            'questions': questions,
            'answers': answers,
            'date_created': datetime.now()
        })
        
        flash('Quiz created successfully', 'success')
        return redirect('/dashboard')
    
    return render_template('create_quiz.html')

@app.route('/take_quiz/<quiz_id>', methods=['GET', 'POST'])
def take_quiz(quiz_id):
    quiz = db.quizzes.find_one({'_id': ObjectId(quiz_id)})
    
    if request.method == 'POST':
        user_answers = request.form.getlist('answers')
        
        # Compare user answers to the correct answers
        score = 0
        for i, user_answer in enumerate(user_answers):
            if user_answer == quiz['answers'][i]:
                score += 1
        
        # Calculate percentage
        percentage = (score / len(quiz["questions"])) * 100
        
        # Save quiz result in MongoDB
        db.quiz_results.insert_one({
            'user_id': session['user_id'],
            'quiz_id': quiz_id,
            'score': score,
            'date_taken': datetime.now()
        })
        
        # Add perfect score message for fireworks
        if percentage >= 90:
            flash(f'🎉 Outstanding! {score}/{len(quiz["questions"])} ({percentage:.1f}%)! 🎉', 'success')
        else:
            flash(f'You scored {score}/{len(quiz["questions"])} ({percentage:.1f}%)', 'success')
        return redirect('/dashboard')
    
    return render_template('take_quiz.html', quiz=quiz, t=g.translations)

@app.route('/dashboard')
def dashboard():
    if session==None or 'user_id' not in session:
        flash('Please log in to view your dashboard', 'error')
        return redirect('/login')
    
    user_id = session['user_id']
    
    completed_lessons = list(db.lessons.find({'completed_by': user_id}))
    
    # Update quiz results query to include quiz titles
    quiz_results = list(db.quiz_results.find({'user_id': user_id}))
    for result in quiz_results:
        quiz = db.quizzes.find_one({'_id': ObjectId(result['quiz_id'])})
        if quiz:
            result['quiz_title'] = quiz['title']
    
    total_lessons = db.lessons.count_documents({})
    total_quizzes = db.quizzes.count_documents({})
    
    return render_template('dashboard.html', 
                         completed_lessons=completed_lessons, 
                         quiz_results=quiz_results,
                         total_lessons=total_lessons,
                         total_quizzes=total_quizzes,
                         t=g.translations)

@app.route('/lessons')
def view_lessons():
    if 'user_id' not in session:
        flash('Please log in to view lessons', 'error')
        return redirect('/login')
    
    lessons = list(db.lessons.find())
    return render_template('lessons.html', lessons=lessons, t=g.translations)

@app.route('/view_lesson/<lesson_id>')
def view_lesson(lesson_id):
    if 'user_id' not in session:
        flash('Please log in to view lessons', 'error')
        return redirect('/login')
    
    lesson = db.lessons.find_one({'_id': ObjectId(lesson_id)})
    if not lesson:
        flash('Lesson not found', 'error')
        return redirect('/lessons')
    
    # Get the user's last quiz result for this lesson if it exists
    last_quiz_result = None
    if lesson.get('quiz') and session['user_id'] in lesson['quiz'].get('completed_by', []):
        last_quiz_result = db.lesson_quiz_results.find_one({
            'user_id': session['user_id'],
            'lesson_id': lesson_id
        }, sort=[('date_taken', -1)])
    
    return render_template('lesson_detail.html', 
                         lesson=lesson, 
                         last_quiz_result=last_quiz_result,
                         t=g.translations)

@app.route('/quizzes')
def view_quizzes():
    if 'user_id' not in session:
        flash('Please log in to view quizzes', 'error')
        return redirect('/login')
    
    quizzes = list(db.quizzes.find())
    completed_quizzes = [result['quiz_id'] for result in db.quiz_results.find({'user_id': session['user_id']})]
    
    return render_template('quizzes.html', quizzes=quizzes, completed_quizzes=completed_quizzes, t=g.translations)

@app.route('/quiz_history')
def quiz_history():
    if 'user_id' not in session:
        flash('Please log in to view your quiz history', 'error')
        return redirect('/login')
    
    # Get all quiz results for the user, sorted by date
    quiz_results = list(db.quiz_results.find(
        {'user_id': session['user_id']}
    ).sort('date_taken', -1))  # -1 for descending order
    
    # Add quiz titles to results
    for result in quiz_results:
        quiz = db.quizzes.find_one({'_id': ObjectId(result['quiz_id'])})
        if quiz:
            result['quiz_title'] = quiz['title']
            # Calculate percentage
            result['percentage'] = (result['score'] / len(quiz['questions'])) * 100
    
    return render_template('quiz_history.html', quiz_results=quiz_results, t=g.translations)

@app.route('/lesson_history')
def lesson_history():
    if 'user_id' not in session:
        flash('Please log in to view your lesson history', 'error')
        return redirect('/login')
    
    # Get all completed lessons for the user, sorted by date
    completed_lessons = list(db.lessons.find(
        {'completed_by': session['user_id']}
    ).sort('date_created', -1))  # -1 for descending order
    
    return render_template('lesson_history.html', completed_lessons=completed_lessons, t=g.translations)

@app.route('/reset_lesson/<lesson_id>')
def reset_lesson(lesson_id):
    if 'user_id' not in session:
        flash('Please log in to reset lessons', 'error')
        return redirect('/login')
    
    # Remove the user from the completed_by array for this lesson
    db.lessons.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$pull': {'completed_by': session['user_id']}}
    )
    
    flash(g.translations.lesson_reset_success, 'success')
    return redirect(url_for('view_lesson', lesson_id=lesson_id))

@socketio.on('message')
def handle_message(msg):
    emit('message', msg, broadcast=True)

def format_date(date, locale):
    months = {
        'en': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 
               'August', 'September', 'October', 'November', 'December'],
        'de': ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
               'August', 'September', 'Oktober', 'November', 'Dezember'],
        'es': ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
               'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'],
        'hi': ['जनवरी', 'फरवरी', 'मार्च', 'अप्रैल', 'मई', 'जून', 'जुलाई',
               'अगस्त', 'सितंबर', 'अक्टूबर', 'नवंबर', 'दिसंबर'],
        'fr': ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet',
               'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre'],
        'it': ['Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno', 'Luglio',
               'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre'],
        'ja': ['1月', '2月', '3月', '4月', '5月', '6月', '7月',
               '8月', '9月', '10月', '11月', '12月']
    }
    
    month_name = months[locale][date.month - 1]
    if locale == 'ja':
        return f"{date.year}年{month_name}{date.day}日"
    return f"{month_name} {date.day}, {date.year}"

@app.route('/take_lesson_quiz/<lesson_id>', methods=['POST'])
def take_lesson_quiz(lesson_id):
    if 'user_id' not in session:
        flash('Please log in to take quizzes', 'error')
        return redirect('/login')
    
    lesson = db.lessons.find_one({'_id': ObjectId(lesson_id)})
    if not lesson or not lesson.get('quiz'):
        flash('Quiz not found', 'error')
        return redirect(url_for('view_lesson', lesson_id=lesson_id))
    
    # Get user's answers
    user_answers = request.form.getlist('answers[]')
    correct_answers = lesson['quiz']['answers']
    
    # Calculate score
    score = sum(1 for ua, ca in zip(user_answers, correct_answers) 
                if ua.lower().strip() == ca.lower().strip())
    
    # Calculate percentage
    total_questions = len(correct_answers)
    percentage = (score / total_questions) * 100
    
    # Save quiz result
    quiz_result = {
        'user_id': session['user_id'],
        'lesson_id': lesson_id,
        'score': score,
        'total_questions': total_questions,
        'percentage': percentage,
        'date_taken': datetime.now()
    }
    db.lesson_quiz_results.insert_one(quiz_result)
    
    # Mark quiz as completed for this user
    db.lessons.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$addToSet': {'quiz.completed_by': session['user_id']}}
    )
    
    # Show appropriate message based on score
    if percentage == 100:
        flash(f'Outstanding! Perfect score: {score}/{total_questions}', 'success')
    else:
        flash(f'Quiz completed! Score: {score}/{total_questions}', 'success')
    
    return redirect(url_for('view_lesson', lesson_id=lesson_id))

@app.route('/reset_lesson_quiz/<lesson_id>', methods=['POST'])
def reset_lesson_quiz(lesson_id):
    if 'user_id' not in session:
        flash('Please log in to reset quizzes', 'error')
        return redirect('/login')
    
    # Remove user from completed_by array in the lesson's quiz
    db.lessons.update_one(
        {'_id': ObjectId(lesson_id)},
        {'$pull': {'quiz.completed_by': session['user_id']}}
    )
    
    flash(g.translations['quiz_reset_success'], 'success')
    return redirect(url_for('view_lesson', lesson_id=lesson_id))

@app.route('/delete_lesson/<lesson_id>', methods=['POST'])
def delete_lesson(lesson_id):
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access', 'error')
        return redirect('/lessons')
    
    try:
        # Delete the lesson
        result = db.lessons.delete_one({'_id': ObjectId(lesson_id)})
        
        if result.deleted_count == 1:
            flash('Lesson deleted successfully', 'success')
        else:
            flash('Lesson not found', 'error')
    except Exception as e:
        flash('Error deleting lesson', 'error')
        print(f"Error deleting lesson: {str(e)}")
    
    return redirect('/lessons')

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    socketio.run(app, host="0.0.0.0", port=port)