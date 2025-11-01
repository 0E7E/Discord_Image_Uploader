import discord
import requests
from supabase import create_client, Client
from io import BytesIO
from PIL import Image
import os
from dotenv import load_dotenv
import tempfile  
from datetime import timezone, datetime
from flask import Flask, jsonify, send_file, request
import threading
import logging

logging.basicConfig(level=logging.INFO,format="[%(asctime)s] %(levelname)s: %(message)s",datefmt="%Y-%m-%d %H:%M:%S")

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Discrod 設定
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 定数
TARGET_SIZE = (1920, 1080)
BACKGROUND_COLOR = (255, 255, 255)

# Flask設定
app = Flask(__name__)

# 状態変数
START_TIME = datetime.now(timezone.utc)
UPLOAD_COUNT = 0

# Flask root
@app.route('/')
def index():
    return jsonify({
        "start_time": START_TIME.isoformat(),
        "upload_count": UPLOAD_COUNT
    })

@app.route("/api/image")
def get_image():
    """?id=1 のようにアクセスして画像を取得"""
    try:
        id_str = request.args.get("id")
        if not id_str or not id_str.isdigit() or int(id_str) < 1:
            return jsonify({"error": "Invalid ?id parameter"}), 400

        image_id = int(id_str)

        # Supabaseのファイル一覧を取得
        files_resp = supabase.storage.from_(SUPABASE_BUCKET).list()
        files = files_resp if isinstance(files_resp, list) else files_resp.get("data", [])
        if not files:
            return jsonify({"error": "No files found in bucket"}), 404

        # 画像のみ抽出・日付順に並べ替え
        valid_ext = ["jpg", "jpeg", "png", "webp", "gif"]
        sorted_files = sorted(
            [f for f in files if f["name"].split(".")[-1].lower() in valid_ext],
            key=lambda x: x.get("updated_at", ""),
            reverse=True
        )

        if not sorted_files:
            return jsonify({"error": "No valid image files found"}), 404

        index = (image_id - 1) % len(sorted_files)
        target = sorted_files[index]

        # ダウンロード
        file_data = supabase.storage.from_(SUPABASE_BUCKET).download(target["name"])
        if not file_data:
            return jsonify({"error": "Failed to download file"}), 404

        # リサイズ
        img = Image.open(BytesIO(file_data))
        img.thumbnail(TARGET_SIZE)
        resized = Image.new("RGB", TARGET_SIZE, BACKGROUND_COLOR)
        x = (TARGET_SIZE[0] - img.width) // 2
        y = (TARGET_SIZE[1] - img.height) // 2
        resized.paste(img, (x, y))

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        resized.save(tmp, format="JPEG")
        tmp.seek(0)

        return send_file(
            tmp.name,
            mimetype="image/jpeg",
            as_attachment=False,
            download_name=target["name"]
        )
    except Exception as e:
        logging.exception("❌ Error in /image")
        return jsonify({"error": str(e)}), 500


# Discordイベント
@client.event
async def on_ready():
    logging.info(f"✅ Logged in as {client.user}")

@client.event
async def on_message(message):
    global UPLOAD_COUNT

    if message.channel.id != TARGET_CHANNEL_ID:
        return
    if message.author.bot or not message.attachments:
        return

    image_index = 1

    for attachment in message.attachments:
        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            continue

        logging.info(f"📸 {attachment.filename} を取得中...")

        response = requests.get(attachment.url)
        if response.status_code != 200:
            logging.info("❌ ダウンロード失敗")
            return

        # 画像リサイズ＋白背景
        original = Image.open(BytesIO(response.content))
        original.thumbnail(TARGET_SIZE)
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
            logging.info(f"❌ アップロード失敗: {res.error}")
        else:
            logging.info(f"✅ Supabase にアップロード成功: {res.full_path}")
            await message.channel.send(f"✅ アップロード完了！: `{file_path}`")
            UPLOAD_COUNT +=1

        image_index += 1

def run_flask():
    app.run(host="0.0.0.0", port=10000)

def run_discord():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    threading.Thread(target=run_discord, daemon=True).start()
    run_flask()

