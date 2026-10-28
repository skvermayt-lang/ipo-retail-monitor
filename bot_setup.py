"""Find your chat ID without writing a bot token to command history or files."""
from getpass import getpass
from delivery import DeliveryError,request_json

if __name__=='__main__':
    print('Create a bot with @BotFather, then open your bot and send /start.')
    token=getpass('Bot token (hidden; not saved): ').strip()
    try:
        data=request_json(f'https://api.telegram.org/bot{token}/getUpdates')
        chats={}
        for update in data.get('result',[]):
            msg=update.get('message',update.get('channel_post',{}))
            chat=msg.get('chat',{})
            if chat.get('id'):
                chats[chat['id']]=chat.get('title',chat.get('first_name','chat'))
        if not chats:
            print('No chats found. Send /start and run again. An existing webhook prevents getUpdates.')
        for chat_id,name in chats.items():
            print(f'{name}: TELEGRAM_CHAT_ID = {chat_id}')
        print('Add token as TELEGRAM_BOT_TOKEN in repository Actions secrets.')
    except DeliveryError as e:
        print(str(e))
