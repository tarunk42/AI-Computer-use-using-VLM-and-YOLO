# from openai import OpenAI

# client = OpenAI()

# response = client.responses.create(
#     model="gpt-4o-mini",
#     input=[{
#         "role": "user",
#         "content": [
#             {"type": "input_text", "text": "what's in this image?"},
#             {
#                 "type": "input_image",
#                 "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg",
#             },
#         ],
#     }],
# )

# print(response.output_text)


import base64
from openai import OpenAI

# Load and encode image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

image_path = "example.png"
base64_image = encode_image(image_path)

client = OpenAI()

response = client.chat.completions.create(
    model="gpt-4o-mini",  # or gpt-4o
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What's in this image?"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        }
    ],
    max_tokens=300
)

print(response.choices[0].message.content)
