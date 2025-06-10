from telegram.ext import ApplicationBuilder, Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import os
import logging
import asyncio
from datetime import datetime
from pytz import timezone
import cloudinary
import cloudinary.uploader
import pandas as pd
import pathlib
import json
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

# ========== KONFIG ========== #
cloudinary.config(
    cloud_name="dual15ulx",
    api_key="995174629387458",
    api_secret="NLO4b5uKzc6gXdp58zDRNNkfeJs"
)

dotenv_path = pathlib.Path('.env')
load_dotenv(dotenv_path=dotenv_path)

bot_token = "7725649239:AAFW9fFALpk1IHA02X8HyvxKwyRKVeGXtco"
SHEET_ID = os.getenv("16mhxrtEhy0_SNqWUWrXuXP6ZanqxzUsMpcy3k3rSQXc")
LIMIT_PATH = pathlib.Path("./limit_rekening.json")

import json

with open("/root/telegram-bot-460011-cd82656b7a6a.json") as f:
    credentials_info = json.load(f)
credentials = service_account.Credentials.from_service_account_info(
    credentials_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
)

service = build('sheets', 'v4', credentials=credentials)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== GLOBAL ========== #
is_recording = False
batch_buffer = []
valid_banks = ["BCA", "BRI", "BNI", "MANDIRI", "CIMB", "BTN", "PERMATA", "DANAMON", "OCBC", "MUAMALAT"]

# ========== UTIL FUNC ========== #
def upload_to_cloudinary(file_path):
    result = cloudinary.uploader.upload(file_path, folder="bot-bukti", use_filename=True, unique_filename=False)
    return result['secure_url']

def load_limit_data():
    if LIMIT_PATH.exists():
        return json.loads(LIMIT_PATH.read_text())
    return {}

def save_limit_data(data):
    LIMIT_PATH.write_text(json.dumps(data, indent=2))

# ========== PARSER FUNC ========== #
def parse_line(line, photo_link, username):
    try:
        nominal = line.split()[0].replace(".", "")
        nominal = int(nominal) if nominal.isdigit() else 0

        dari_pos = line.upper().find('DARI')
        ke_pos = line.upper().find(' KE ')
        pengirim = line[dari_pos + 5:ke_pos].strip() if dari_pos != -1 and ke_pos != -1 else ''
        tujuan = line[ke_pos + 4:].strip() if ke_pos != -1 else ''

        rekening_penerima = tujuan.split('TP', 1)[1].strip() if 'TP' in tujuan else tujuan

        bank_pengirim = next((b for b in reversed(pengirim.split()) if b.upper() in valid_banks), pengirim.split()[-1])
        bank_tujuan = next((b for b in reversed(rekening_penerima.split()) if b.upper() in valid_banks), rekening_penerima.split()[-1])

        keterangan = "SESAMA BANK" if bank_pengirim.upper() == bank_tujuan.upper() else "BEDA BANK"

        paydia = nominal if 'PAYDIA' in line.upper() else ''
        netzme = nominal if 'NETZME' in line.upper() else ''
        paydia2 = nominal if 'PAYDIA2' in line.upper() else ''

        tanggal = datetime.now(timezone('Asia/Phnom_Penh')).strftime("%Y-%m-%d %H:%M:%S")
        row = [photo_link, nominal, paydia, netzme, paydia2, pengirim, tujuan, rekening_penerima, keterangan, username, tanggal]
        return row
    except Exception as e:
        logger.error(f"❌ Error parsing: {e}")
        return None

# ========== HANDLERS ========== #
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording
    if not is_recording:
        await update.message.reply_text("📴 Bot belum aktif. Gunakan /gas_catat dulu.")
        return

    username = update.message.from_user.username or update.message.from_user.first_name
    caption = update.message.caption or ""
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_path = f"{photo.file_id}.jpg"
    await file.download_to_drive(file_path)
    cloudinary_link = upload_to_cloudinary(file_path)
    os.remove(file_path)

    rows = []
    for line in caption.split("\n"):
        if "DARI" in line and " KE " in line:
            parsed = parse_line(line, cloudinary_link, username)
            if parsed:
                rows.append(parsed)
    batch_buffer.extend(rows)
    await batch_update()

async def batch_update():
    global batch_buffer
    if not batch_buffer:
        return

    values = list(batch_buffer)
    batch_buffer.clear()
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="A1:K",
        valueInputOption="USER_ENTERED",
        body={"values": values}
    ).execute()

async def gas_catat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording
    is_recording = True
    await update.message.reply_text("🚀 Mulai mencatat transaksi!")

async def stop_catat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording
    is_recording = False
    await update.message.reply_text("🛑 Stop mencatat!")

async def rekap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range="A1:K").execute()
        data = result.get("values", [])[1:]
        df = pd.DataFrame(data, columns=["LINK", "TOTAL", "PAYDIA", "NETZME", "PAYDIA2", "PENGIRIM", "TUJUAN", "REK", "KET", "USER", "TGL"])
        today = datetime.now(timezone('Asia/Phnom_Penh')).strftime("%Y-%m-%d")
        df = df[df['TGL'].str.startswith(today)]
        for col in ["PAYDIA", "NETZME", "PAYDIA2"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        total1, total2, total3 = df['PAYDIA'].sum(), df['NETZME'].sum(), df['PAYDIA2'].sum()
        pesan = f"""📊 REKAP HARI INI\n\nPAYDIA: Rp {total1:,}\nNETZME: Rp {total2:,}\nPAYDIA2: Rp {total3:,}\nTOTAL: Rp {total1+total2+total3:,}\nJumlah: {len(df)}x"""
        await update.message.reply_text(pesan)
    except Exception as e:
        await update.message.reply_text(f"❌ Error rekap: {e}")

async def rincian_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range="A1:K").execute()
        data = result.get("values", [])[1:]
        df = pd.DataFrame(data, columns=["LINK", "TOTAL", "PAYDIA", "NETZME", "PAYDIA2", "PENGIRIM", "TUJUAN", "REK", "KET", "USER", "TGL"])
        today = datetime.now(timezone('Asia/Phnom_Penh')).strftime("%Y-%m-%d")
        df = df[df['TGL'].str.startswith(today)]
        for col in ["PAYDIA", "NETZME", "PAYDIA2"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        pesan = "📋 RINCIAN PER REKENING:\n\n"
        for metode in ["PAYDIA", "NETZME", "PAYDIA2"]:
            sub = df[df[metode] > 0].groupby("REK")[metode].sum()
            pesan += f"💳 {metode}:\n" + "\n".join([f"- {r} : Rp {v:,}" for r, v in sub.items()]) + "\n\n"
        await update.message.reply_text(pesan)
    except Exception as e:
        await update.message.reply_text(f"❌ Error rincian: {e}")

async def set_limit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _, nama, bank, limit = update.message.text.split()
        data = load_limit_data()
        data[f"{nama}|{bank}"] = int(limit)
        save_limit_data(data)
        await update.message.reply_text(f"✅ Limit untuk {nama} ({bank}) diset Rp {limit}")
    except Exception as e:
        await update.message.reply_text(f"❌ Format salah. Gunakan: /set_limit [NAMA] [BANK] [NOMINAL]\nError: {e}")

# ========== MAIN ========== #
async def main():
    app = Application.builder().token(bot_token).build()
    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CommandHandler("gas_catat", gas_catat))
    app.add_handler(CommandHandler("stop_catat", stop_catat))
    app.add_handler(CommandHandler("rekap", rekap_handler))
    app.add_handler(CommandHandler("rincian", rincian_handler))
    app.add_handler(CommandHandler("set_limit", set_limit_handler))
    print("🔥 Bot siap jalan di Railway!")
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(5)
        await batch_update()

if __name__ == '__main__':
    asyncio.run(main())
