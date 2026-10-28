import os
from delivery import request_json,DeliveryError

if __name__ == '__main__':
    try:
        token=os.environ['TELEGRAM_BOT_TOKEN']
        chat=os.environ['TELEGRAM_CHAT_ID']
        if not token or not chat:
            raise DeliveryError('Add both Telegram secrets first')
        bot=request_json(f'https://api.telegram.org/bot{token}/getMe')
        destination=request_json(f'https://api.telegram.org/bot{token}/getChat','POST',{'chat_id':chat})
        if not bot.get('ok') or not destination.get('ok'):
            raise DeliveryError('Telegram connection check failed')
        print('Bot credentials and destination chat verified. No message sent.')
    except (KeyError,DeliveryError):
        raise SystemExit('Connection check failed. Verify bot token, chat ID and bot chat access in GitHub Secrets.')
