import os
from ollama import Client
import base64
from dotenv import load_dotenv
load_dotenv()

client = Client(
    host='https://ollama.com',
    headers={'Authorization': 'Bearer ' + os.environ.get('OLLAMA_API_KEY')}
)

with open(r'D:\coding\Ablatix\backend\models\image.png', 'rb') as img_file:
    img_base64 = base64.b64encode(img_file.read()).decode()


messages = [
  {
        'role': 'user',
        'content': 'What is in this image?',
        'images': [img_base64]

    }
]

for part in client.chat('qwen3.5:397b-cloud', messages=messages, stream=True):
  print(part.message.content, end='', flush=True)