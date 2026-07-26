from google import genai

API_KEY = "AIzaSyBJo5e-Zc9w7XIEcOvnFkCtP7t1L80FBwE"

client = genai.Client(api_key=API_KEY)

print("Fetching available models for your API key...\n")

try:
    for model in client.models.list():
        # Display model name and its supported generation methods
        methods = getattr(model, "supported_generation_methods", [])
        print(f"Model ID: {model.name}")
        print(f"  Methods: {methods}\n")
except Exception as e:
    print(f"Error querying models: {e}")