import os
from google import genai
from google.genai import types

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
API_KEY = "AIzaSyBJo5e-Zc9w7XIEcOvnFkCtP7t1L80FBwE"
OUTPUT_DIR = "./saved_images"

prompt_prefix = '''Studio photo of '''
prompt_suffix = ''' centered. Minimalist light-grey backdrop, soft warm lighting, crisp focus, subtle floor shadows. Professional educational stock style, 1:1 aspect ratio.'''

# ---------------------------------------------------------
# Script Logic
# ---------------------------------------------------------
def generate_and_save_image(prompt: str, filename: str = "output.png"):
    # 1. Initialize client
    client = genai.Client(api_key=API_KEY)

    # 2. Ensure destination folder exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Generating image for prompt: '{prompt}'...")

    try:
        # 3. Call the multimodal endpoint requesting IMAGE modality
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        # 4. Process the response payload and extract image data
        image_saved = False
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    # Convert inline bytes directly to PIL image
                    img = part.as_image()
                    filepath = os.path.join(OUTPUT_DIR, filename)
                    img.save(filepath)
                    print(f" Success! Image saved to: {filepath}")
                    image_saved = True
                    break

        if not image_saved:
            print(" No image was returned in the response payload.")

    except Exception as e:
        print(f" An error occurred: {e}")


if __name__ == "__main__":
    # Get inputs directly from user
    # user_prompt = input("Enter your image prompt: ")
    # file_name = input("Enter output file name (e.g., custom_art.png): ")

    title = 'Basic Actions - Movement'

    prompts = '''A boy eating a sandwich at a kitchen table, photorealistic, front view, bright indoor lighting
A girl drinking a glass of milk, photorealistic, side view, bright indoor lighting
A child sleeping peacefully in a bed with white sheets, photorealistic, soft lighting
A woman cooking at a stove in a kitchen, photorealistic, side view, warm lighting
A man reading a book while sitting in an armchair, photorealistic, warm indoor lighting
A girl writing in a notebook at a desk, photorealistic, overhead angle
A boy washing his hands at a sink, photorealistic, side view
A woman brushing her teeth in a bathroom, photorealistic, mirror reflection view
A man carrying grocery bags, walking on a sidewalk, photorealistic
A girl opening a door, photorealistic, side view, indoor setting
A four-panel image showing daily routine: waking up, eating breakfast, going to school, sleeping, photorealistic'''.split('\n')
    
    print(prompts)

    count = 20

    for prompt in prompts:

        # generate_and_save_image(prompt=prompt_prefix+prompt, filename=str(count)+'.jpg')
        generate_and_save_image(prompt=prompt_prefix+prompt+prompt_suffix, filename=str(count)+'.jpg')
        
        count += 1