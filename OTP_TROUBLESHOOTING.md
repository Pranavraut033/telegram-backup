# OTP Authentication Troubleshooting

## Your Current Issue

**Problem:** Not receiving OTP on the phone number used to create the app, but seeing it on Telegram Web.

**Root Cause:** Your number is already logged into Telegram Web, so Telegram sends the OTP as an in-app message instead of SMS.

## Immediate Solutions

### Solution 1: Use the Code from Telegram Web (Fastest)
1. Open **Telegram Web** where you're logged in
2. Look for a message from **"Telegram"** (the official service account)  
3. Copy the code from there
4. Paste it into the CLI prompt where it's waiting
5. Done! ✅

### Solution 2: Use QR Code Login (Recommended)
1. Install the new dependency:
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Logout and restart:
   ```bash
   python main.py --logout
   python main.py
   ```

3. When prompted, choose **option 2** (QR code)
4. Scan the QR code with your Telegram mobile app
   - Open Telegram app → Settings → Devices → Link Desktop Device
5. Done! ✅

### Solution 3: Wait and Retry
If you've hit the resend limit:
1. Wait 10-15 minutes
2. Run: `python main.py --logout`
3. Try authenticating again with phone number
4. Or use QR code login instead

## Why This Happens

- Telegram prioritizes sending OTP to active sessions (like Telegram Web)
- SMS is only used if you're not logged in anywhere else
- After multiple resend attempts, Telegram blocks further resends temporarily
- Other numbers work because they're not logged in elsewhere

## Best Practice Going Forward

**Use QR code login** - It bypasses all OTP issues and is faster!

```bash
python main.py
# Choose option 2 when prompted
```

## Quick Commands

```bash
# Install new dependency
source venv/bin/activate
pip install -r requirements.txt

# Clear session and restart
python main.py --logout
python main.py

# Enable debug mode to see what's happening
python main.py --debug
```
