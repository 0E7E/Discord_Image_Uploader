import discord
import requests
from supabase import create_client, Client
from io import BytesIO
from PIL import Image
import os
from dotenv import load_dotenv
import tempfile  
from datetime import timezone

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

TARGET_SIZE = (1920, 1080)
BACKGROUND_COLOR = (255, 255, 255)


@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.channel.id != TARGET_CHANNEL_ID:
        return
    if message.author.bot or not message.attachments:
        return

    image_index = 1

    for attachment in message.attachments:
        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            continue

        print(f"📸 {attachment.filename} を取得中...")

        response = requests.get(attachment.url)
        if response.status_code != 200:
            print("❌ ダウンロード失敗")
            return

        # 画像リサイズ＋白背景
        original = Image.open(BytesIO(response.content))
        original.thumbnail((1920, 1080))
        resized = Image.new("RGB", TARGET_SIZE, BACKGROUND_COLOR)
        x = (TARGET_SIZE[0] - original.width) // 2
        y = (TARGET_SIZE[1] - original.height) // 2
        resized.paste(original, (x, y))

        # 一時ファイルに保存（Supabaseはパスで必要）
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            resized.save(tmp, format="JPEG")
            tmp_path = tmp.name

        # ファイル名作成
        ts = message.created_at.astimezone(timezone.utc)
        timestamp_str = ts.strftime("%Y-%m-%d-%H-%M-%S")
        author_name = message.author.name.replace(" ", "_")  # スペースはアンダースコアに
        file_path = f"{timestamp_str}_{image_index}_{author_name}.jpg"

        # Supabaseにアップロード
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            file_path,
            tmp_path,  # ← 一時ファイルのパスを渡す！
            {"content-type": "image/jpeg"}
        )

        os.remove(tmp_path)  # 一時ファイル削除

        if hasattr(res, "error") and res.error is not None:
            print(f"❌ アップロード失敗: {res.error}")
        else:
            print(f"✅ Supabase にアップロード成功: {res.full_path}")

        image_index += 1

client.run(DISCORD_TOKEN)
