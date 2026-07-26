import os
os.environ['HF_TOKEN'] = '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'


import os
from huggingface_hub import InferenceClient

client = InferenceClient(
    provider="auto",
    api_key=os.environ["HF_TOKEN"],
)

# prompts = []

prompts = [
    "A single ripe red tomato on a clean white background, photorealistic, studio lighting",
    "A single whole brown potato on a clean white background, photorealistic, studio lighting",
    "A single white onion on a clean white background, photorealistic, studio lighting",
    "A single red bell pepper on a clean white background, photorealistic, studio lighting",
    "A single ear of yellow corn on a clean white background, photorealistic, studio lighting",
    "A single fresh cucumber on a clean white background, photorealistic, studio lighting",
    "A single head of green lettuce on a clean white background, photorealistic, studio lighting",
    "Several fresh green peas in an open pod on a clean white background, photorealistic, studio lighting",
    "A colorful arrangement of five different vegetables on a white background: carrot, tomato, broccoli, potato, bell pepper, photorealistic"
]

count = 0

for prompt in prompts:
  # output is a PIL.Image object
  image = client.text_to_image(
      prompt,
      model="stabilityai/stable-diffusion-xl-base-1.0",
  )
  image.save(str(count)+'.png')