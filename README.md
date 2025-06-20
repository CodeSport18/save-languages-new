# Kashmiri Learning Project

A web application for learning the Kashmiri language.

## Features

### Audio Support
The application now supports audio file uploads to help with pronunciation and language learning:

- **Upload Audio Files**: Support for MP3, WAV, OGG, M4A, and AAC formats
- **Record Audio**: Built-in microphone recording functionality
- **AWS S3 Integration**: All audio files are stored securely in AWS S3
- **Rich Text Editor**: Audio players can be inserted directly into lesson content
- **Preview Functionality**: Audio files can be previewed before saving

### Environment Variables Required
For audio upload functionality, you'll need to set up the following environment variables:
- `AWS_ACCESS_KEY_ID`: Your AWS access key
- `AWS_SECRET_ACCESS_KEY`: Your AWS secret access key  
- `AWS_REGION`: AWS region (defaults to 'us-east-1')
- `S3_BUCKET`: Your S3 bucket name for file storage

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
   - Set up AWS S3 credentials for audio file storage

## Running the Application

```bash
python app.py
```

The application will be available at `http://localhost:5001`

## Security Note

Never commit `password.txt` or `secret_key.txt` to version control. These files contain sensitive information and should be kept private. 