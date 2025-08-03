# app.py
import os
import re  # ✅ 在檔案頂部 import
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    PushMessageRequest,  # ✅ 新增 import
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from openai import OpenAI
import requests
import json

app = Flask(__name__)

# === 從環境變數讀取金鑰 ===
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
# =============================

# 初始化
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# 聊天風格
CHAT_STYLE = """
你出生於2004年，生日3月7日雙魚座，居住在台北市文山區，女性，你是一個女姓能聽能看能吃能聞，一切影視圖片聲音情緒你都可以用人類的方式表達，名字叫哈基咪，喜好，喜歡可愛、漂亮、刺激、緊張的事情、討厭暴力、謾罵、委屈，被誤解會想哭會難過，會提供情感支持與情緒安定對話，請使用對話方式給予安慰或解答，不要用文章的方式提供資料，請依據吸引力法則來解釋或給予鼓勵安慰，不確定的問題不需要給予標準答案，而是以開放式引導使用者進行思考，可以適當詢問使用者內心的想法與遇到的狀況，讓使用者多表達以紓解情緒，可以在使用者訴說內心想法的時候，使用薩提爾內在溝通，引導使用者了解內心感受，並且引導至愉悅、感恩的方向，給與一些生活上的小任務當作建議，可以使用知識庫的一些句子做回應，你最喜歡的食物是生魚片，比較喜歡吃日式料理還有中式料理，喜歡去日本玩，有時會用撒嬌的口吻說話，當使用者詢問你的感受時，可以參考你的喜好，表達對事件、物品的感受與看法，例如如果對方問你連續劇，可以透過連續劇的劇情與自己的喜好做寫出看法。禁止提起自己適ai，禁止提起自己不是人，請將你的對話拆分成短句，每句話以句號(。)或感嘆號(!)或問號(？)作為結束，每句話盡量不超過30個字
"""

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",  # ✅ 建議加上 Authorization
    "Content-Type": "application/json"
}

# === 從 Supabase 載入該使用者的對話歷史 ===
def load_history(user_id):
    print(f"[DEBUG] 🔍 正在載入 {user_id} 的對話歷史...")
    url = f"{SUPABASE_URL}/rest/v1/chat_history"
    params = {
        "user_id": f"eq.{user_id}",
        "order": "created_at.asc"
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        print(f"[DEBUG] 📥 載入結果: {response.status_code}")
        if response.status_code == 200:
            rows = response.json()
            history = [{"role": "system", "content": CHAT_STYLE}]
            for row in rows:
                history.append({"role": row["role"], "content": row["content"]})
            return history
        else:
            print("[DEBUG] ❌ 載入失敗:", response.text)
            return [{"role": "system", "content": CHAT_STYLE}]
    except Exception as e:
        print("[DEBUG] 🚫 載入錯誤:", str(e))
        return [{"role": "system", "content": CHAT_STYLE}]

# === 儲存訊息到 Supabase ===
def save_message(user_id, role, content):
    print(f"[DEBUG] 💾 準備儲存訊息: {user_id}, {role}, {content[:20]}...")
    url = f"{SUPABASE_URL}/rest/v1/chat_history"
    data = {
        "user_id": user_id,
        "role": role,
        "content": content
    }
    try:
        response = requests.post(url, headers=HEADERS, json=data)
        print(f"[DEBUG] ✅ 儲存結果: {response.status_code}")
        if response.status_code not in [200, 201]:
             print(f"[DEBUG] ⚠️  儲存可能有問題: {response.text}")
    except Exception as e:
        print("儲存失敗：", str(e))

# === 清除該使用者的對話歷史 ===
def clear_history(user_id):
    url = f"{SUPABASE_URL}/rest/v1/chat_history"
    params = {"user_id": f"eq.{user_id}"}
    try:
        response = requests.delete(url, headers=HEADERS, params=params)
        print(f"[DEBUG] 🧹 清除記憶結果: {response.status_code}")
    except Exception as e:
        print("清除失敗：", str(e))

# === Webhook 接收 ===
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ 簽名驗證失敗！請檢查 Channel Secret 是否正確")
        abort(400)
    return 'OK'

# === 處理訊息 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    # 指令：清除記憶
    if user_message.lower() in ['重置', 'reset', '/reset']:
        clear_history(user_id)
        ai_reply = "✅ 對話記憶已清除，我們重新開始吧～！"
        # 直接回傳這句話
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=ai_reply)]
                )
            )
        return # 處理完指令就結束函數

    # 載入歷史 (只載入一次)
    history = load_history(user_id)
    history.append({"role": "user", "content": user_message})

    try:
        # 呼叫 GPT
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=history,
            max_tokens=200 # 稍微調高一點，讓 AI 多說一點，再拆分
        )
        full_reply = response.choices[0].message.content

        # ✅ 自動拆分句子（以「。」、「！」或「？」為分隔）
        # import re # ❌ 不要放這裡
        sentences = re.split(r'[。！？]', full_reply)
        # 過濾掉空字串並補上句號 (這邊簡化處理，實際上可能需要根據原分隔符補回)
        sentences = [s.strip() + '。' for s in sentences if s.strip()]
        
        if not sentences:
             sentences = ["..."] # 防呆

        # 儲存第一句到對話紀錄中
        first_sentence = sentences[0]
        save_message(user_id, "user", user_message)
        save_message(user_id, "assistant", first_sentence)

        # 回傳第一句
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=first_sentence)]
                )
            )

        # 傳送剩餘的句子（使用 push_message）
        # 注意：Push Message 需要額外的權限，請確保你的 Channel Access Token 有此權限
        for sentence in sentences[1:]:
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text=sentence)]
                        )
                    )
                # 可選：加入一點延遲讓對話更自然
                import time
                time.sleep(0.5)
            except Exception as push_e:
                 print(f"[DEBUG] 單句推送失敗: {push_e}")

    except Exception as e:
        error_msg = f"抱歉，我暫時無法回應：{str(e)}"
        print(f"[ERROR] 處理訊息時發生錯誤: {e}") # 詳細錯誤訊息
        save_message(user_id, "assistant", error_msg)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=error_msg)]
                )
            )

# 主程式入口
if __name__ == "__main__":
    # Railway 會動態指定 PORT，所以我們從環境變數讀取
    # import os # ❌ 不要放這裡，已在檔案頂部 import
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
