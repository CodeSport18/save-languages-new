from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from functools import wraps
import os
from translations import translations

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '!hUcAZCNrL-HM&-')

# User database (in-memory for simplicity)
users = {}

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
    g.locale = session['locale']
    g.t = translations[g.locale]

@app.route('/')
def homepage():
    return render_template('main.html', t=g.t)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            session['user_id'] = username
            session['is_admin'] = users[username].get('is_admin', False)
            flash('Successfully logged in!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    return render_template('login.html', t=g.t)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users:
            flash('Username already exists', 'error')
        else:
            users[username] = {'password': password, 'is_admin': False}
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html', t=g.t)

@app.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out!', 'success')
    return redirect(url_for('homepage'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', t=g.t)

@app.route('/lessons')
@login_required
def lessons():
    return render_template('lessons.html', t=g.t)

@app.route('/lesson/<int:lesson_id>')
@login_required
def lesson_detail(lesson_id):
    return render_template('lesson_detail.html', t=g.t)

@app.route('/create_lesson')
@login_required
def create_lesson():
    if not session.get('is_admin'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return render_template('create_lesson.html', t=g.t)

@app.route('/quizzes')
@login_required
def quizzes():
    return render_template('quizzes.html', t=g.t)

@app.route('/create_quiz')
@login_required
def create_quiz():
    if not session.get('is_admin'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    return render_template('create_quiz.html', t=g.t)

@app.route('/take_quiz/<int:quiz_id>')
@login_required
def take_quiz(quiz_id):
    return render_template('take_quiz.html', t=g.t)

@app.route('/lesson_history')
@login_required
def lesson_history():
    return render_template('lesson_history.html', t=g.t)

@app.route('/quiz_history')
@login_required
def quiz_history():
    return render_template('quiz_history.html', t=g.t)

@app.route('/change_language/<language>')
def change_language(language):
    if language in translations:
        session['locale'] = language
    return redirect(request.referrer or url_for('homepage'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
