# Kashmiri Learning Project

A web application for learning the Kashmiri language.

## Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set up environment variables:
   - Copy `password.txt.template` to `password.txt`
   - Update `password.txt` with your MongoDB connection string
   - Copy `secret_key.txt.template` to `secret_key.txt`
   - Generate a secure random key for `secret_key.txt`

## Running the Application

```bash
python app.py
```

The application will be available at `http://localhost:5001`

## Security Note

Never commit `password.txt` or `secret_key.txt` to version control. These files contain sensitive information and should be kept private. 