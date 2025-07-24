from openai import OpenAI
from PIL import Image
import io
import base64

def prepare_image(path):
    with Image.open(path) as img:
        img = img.convert("RGB")
        # img = img.resize((512, 512))  # Optional: reduce resolution to save tokens
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=70)  # Optional: compress
        return base64.b64encode(buffer.getvalue()).decode()

base64_image = prepare_image("./resources/example.png")

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key="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",           #llama4 
#   api_key="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",           #gemini2.5exp
)

completion = client.chat.completions.create(
  extra_headers={
    "HTTP-Referer": "<YOUR_SITE_URL>", # Optional. Site URL for rankings on openrouter.ai.
    "X-Title": "<YOUR_SITE_NAME>", # Optional. Site title for rankings on openrouter.ai.
  },
  extra_body={},
#   model="google/gemini-2.5-pro-exp-03-25:free",
    model="meta-llama/llama-4-maverick:free",
  messages=[
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Describe what each highlighted button does in the image."
        },
        {
          "type": "image_url",
          "image_url": {
            # "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg"
            "url": f"data:image/jpeg;base64,{base64_image}",
          }
        }
      ]
    }
  ]
)
try:
    print(completion.choices[0].message.content)
except Exception as e:
    print("Error:", e)
    print(completion)



# import requests
# import json

# response = requests.get(
#   url="https://openrouter.ai/api/v1/auth/key",
#   headers={
#     "Authorization": f"Bearer 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"
#   }
# )

# print(json.dumps(response.json(), indent=2))
