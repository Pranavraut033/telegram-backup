#!/usr/bin/env python3
"""Test actual Telegram QR login to debug the issue"""
import asyncio
import qrcode
from telethon import TelegramClient
import config

async def test_qr():
    print("Testing QR code login...")
    
    client = TelegramClient(
        'test_qr_session',
        config.API_ID,
        config.API_HASH
    )
    
    await client.connect()
    print("Connected to Telegram")
    
    try:
        qr_login = await client.qr_login()
        print(f"QR Login object created: {type(qr_login)}")
        print(f"QR Login URL: {qr_login.url}")
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        
        print("\n=== Scan this QR code with Telegram ===\n")
        qr.print_ascii(invert=True)
        print("\n")
        
        print("Waiting 60 seconds for you to scan...")
        try:
            await asyncio.wait_for(qr_login.wait(), timeout=60)
            print("QR code was scanned!")
        except asyncio.TimeoutError:
            print("Timeout - you didn't scan in time")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        # Clean up test session
        import os
        for f in ['test_qr_session.session', 'test_qr_session.session-journal']:
            if os.path.exists(f):
                os.remove(f)

if __name__ == '__main__':
    asyncio.run(test_qr())
