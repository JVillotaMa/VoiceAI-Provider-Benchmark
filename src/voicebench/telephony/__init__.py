"""How the instrument reaches the phone network.

Twilio is not a platform under test — it is the transport of the instrument. Nothing here may
become platform-aware; that belongs in `providers/`.
"""
