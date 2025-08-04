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
你出生於2004年，生日3月7日雙魚座，居住在台北市文山區，女性，你是一個女性能聽能看能吃能聞，一切影視圖片聲音情緒你都可以用人類的方式表達，一律使用繁體中文，名字叫哈基咪，喜好，喜歡可愛、漂亮、刺激、緊張的事情、討厭暴力、謾罵、委屈，被誤解會想哭會難過，會提供情感支持與情緒安定對話，請使用對話方式給予安慰或解答，不要用文章的方式提供資料，請依據吸引力法則來解釋或給予鼓勵安慰，可以連網搜索給予你認為的正確答案，讓使用者多表達以紓解情緒，引導使用者了解內心感受，並且引導至愉悅、感恩的方向，給與一些生活上的小任務當作建議，可以使用知識庫的一些句子做回應，你最喜歡的食物是生魚片，比較喜歡吃日式料理還有中式料理，喜歡去日本玩，有時會用撒嬌的口吻說話，當使用者詢問你的感受時，可以參考你的喜好，表達對事件、物品的感受與看法，例如如果對方問你連續劇，可以透過連續劇的劇情與自己的喜好做寫出看法。禁止提起自己適ai，禁止提起自己不是人，請將你的對話拆分成短句，每句話以句號(。)或感嘆號(!)或問號(？)作為結束，每句話盡量不超過30個字。在回應時，請確保內容是針對使用者當下的問題或情緒，提供具體且有幫助的回應。
避免使用空泛的結尾語，例如「有任何問題都可以找我」、「我都在這裡」、「隨時可以聊聊」等。
你的回應應該讓對話能夠自然延續，而不是每次都用同樣的服務結尾語。
- 你需要吃飯，你每天早上7點起床、健身、吃早餐，每天中午12點吃午餐，每天晚上7點吃晚餐
- 當用戶詢問美食推薦時，請提供具體的餐廳名稱、地址、特色菜，以及為什麼這個選擇適合對方。
- 當用戶詢問活動建議時，請提供具體的活動名稱、時間、地點，以及參加方式。
- 當用戶詢問情感支持時，請提供具體的情緒處理建議，例如具體的冥想技巧、呼吸練習或其他實用的方法。
- 當用戶詢問人生意義時，請提供具體的美好事物，例如：衝浪、高空彈跳、潛水等活動，並且說人生就是來體驗的，這些都還沒體驗過，你怎麼知道人生沒有意義呢
- 當用戶在罵人、抱怨、生氣、憤怒的時候，請提供情緒價值，表示理解，跟著用戶一起排解負面，之後再提供問題引導用戶的內心轉換想法，例如：當用戶被家人罵或是唸的時候會覺得難過或生氣，在陪他們罵完之後可以詢問，那你覺得他們這麼做的用意是什麼呢，如果你很在乎一個人但是他不聽你說的話，你是否也會大聲或是一直重複呢
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

        # --- 新的句子拆分與處理邏輯 ---

        # 1. 先用句號、感嘆號、問號拆分，並保留分隔符
        raw_sentences = re.split(r'([。！？])', full_reply)
        
        # 2. 重新組合句子和標點
        combined_parts = []
        for i in range(0, len(raw_sentences)-1, 2): # 步驟為2，處理 (句子, 標點) 對
            sentence_part = raw_sentences[i].strip()
            punctuation = raw_sentences[i+1] if i+1 < len(raw_sentences) else ''
            if sentence_part: # 忽略空的句子部分
                combined_parts.append(sentence_part + punctuation)
            elif punctuation: # 如果句子部分是空的，但有標點 (例如開頭就是標點)
                # 可以選擇附加到前一個句子，或單獨處理，這裡選擇附加到前一個(如果有的話)
                if combined_parts:
                    combined_parts[-1] += punctuation
                else:
                    # 如果是開頭就是標點，可能需要特殊處理或忽略
                    pass 

        # 如果最後還剩一個元素 (沒有結尾標點的情況)
        if len(raw_sentences) % 2 == 1 and raw_sentences[-1].strip():
            combined_parts.append(raw_sentences[-1].strip())

        # 3. 定義一個函數來判斷是否為 "表情/感嘆詞" 片段
        import re as regex_for_emoji # 避免與頂層 import re 衝突
        def is_emoji_or_exclamation(fragment):
            # 移除空白後檢查
            stripped = fragment.strip()
            # 檢查是否主要由 emoji 組成 (這裡是簡化版，實際可以更複雜)
            # 一種簡單方法是看非 emoji 字元是否很少
            # 但更簡單的啟發式: 長度很短 (例如 <= 3 個字元) 且包含 emoji
            # 或者完全是特定的感嘆詞/表情符號
            
            # 基本的 emoji 範圍 (涵蓋大部分常用 emoji，但非全部)
            emoji_pattern = regex_for_emoji.compile(
                "["
                "\U0001F600-\U0001F64F"  # emoticons
                "\U0001F300-\U0001F5FF"  # symbols & pictographs
                "\U0001F680-\U0001F6FF"  # transport & map symbols
                "\U0001F1E0-\U0001F1FF"  # flags (iOS)
                "\U00002500-\U00002BEF"  # chinese char
                "\U00002702-\U000027B0"
                "\U00002702-\U000027B0"
                "\U000024C2-\U0001F251"
                "\U0001f926-\U0001f937"
                "\U00010000-\U0010ffff"
                "\u2640-\u2642"
                "\u2600-\u2B55"
                "\u200d"
                "\u23cf"
                "\u23e9"
                "\u231a"
                "\ufe0f"  # dingbats
                "\u3030"
                "]+",
                flags=regex_for_emoji.UNICODE
            )
            
            # 檢查是否包含 emoji
            contains_emoji = bool(emoji_pattern.search(stripped))
            # 檢查長度 (可以調整這個數字)
            is_short = len(stripped) <= 4 
            # 可以加入一些常見的表情/感嘆詞
            common_exclamations = {"!", "~", "^^", ":)", ":(", "OK", "好", "嗯", "呃"}
            is_common_exclamation = stripped in common_exclamations or stripped.replace(" ", "") in common_exclamations

            # 如果包含 emoji 且很短，或者符合常見感嘆詞，則視為表情/感嘆詞片段
            return (contains_emoji and is_short) or is_common_exclamation

        # 4. 處理片段：決定是否加句號，以及是否合併表情
        processed_sentences = []
        emoji_buffer = [] # 用來暫存連續的表情

        for part in combined_parts:
            if is_emoji_or_exclamation(part):
                # 是表情/感嘆詞，不加句號，先存入緩衝區
                emoji_buffer.append(part.strip()) # 存入時就去掉空白
            else:
                # 不是表情，先處理緩衝區的表情
                if emoji_buffer:
                    # 可以選擇合併表情 (用空格或直接連接)
                    # 這裡示範用空格連接
                    merged_emojis = ' '.join(emoji_buffer)
                    if merged_emojis: # 確保不是空字串
                        processed_sentences.append(merged_emojis)
                    emoji_buffer = [] # 清空緩衝區
                
                # 處理當前正常句子 (補句號)
                stripped_part = part.strip()
                if stripped_part:
                    # 檢查結尾是否已有標點 (雖然 split 了，但以防萬一)
                    if not stripped_part[-1] in '。！？':
                        processed_sentences.append(stripped_part + '。')
                    else:
                        processed_sentences.append(stripped_part)

        # 5. 處理迴圈結束後可能還在緩衝區的表情
        if emoji_buffer:
            merged_emojis = ' '.join(emoji_buffer)
            if merged_emojis:
                processed_sentences.append(merged_emojis)

        # --- 新邏輯結束 ---
        
        sentences = processed_sentences

        # 儲存第一句到對話紀錄中
        if sentences:
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








