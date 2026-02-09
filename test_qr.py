#!/usr/bin/env python3
"""Test QR code generation"""
import qrcode

# Test QR code generation
test_url = "tg://login?token=abcdef123456"

qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_L,
    box_size=10,
    border=4,
)
qr.add_data(test_url)
qr.make(fit=True)

print("\n=== Test QR Code ===\n")
qr.print_ascii(invert=True)
print("\nIf you see a QR code above, the library is working!")
print("If not, your terminal might not support ASCII art.")
