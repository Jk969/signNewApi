from telethon import TelegramClient, events
import asyncio

# 填入你申请到的信息
api_id = 27715050 
api_hash = 'a7552139040eca3cb3cef6bbea9e1cc3'
bot_username = '@wjkcbot'
checkin_text = '签到' # 替换为实际的签到指令

client = TelegramClient('session_name', api_id, api_hash)

async def main():
    print("正在启动签到任务...")
    await client.start()
    
    # 向机器人发送消息
    await client.send_message(bot_username, checkin_text)
    print(f"已向 {bot_username} 发送签到信息")
    
    # 等待几秒查看是否有回复（可选）
    await asyncio.sleep(5)
    print("任务结束。")

with client:
    client.loop.run_until_complete(main())