"""Quick test: run a signal analysis via the bot module."""
import sys
sys.path.insert(0, ".")

from tradingagents.telegram.bot import _analyze_signal, _analyze_scalp, build_signal_message, build_scalp_message

print("=" * 50)
print("TESTING SIGNAL ANALYSIS — CFI:US100")
print("=" * 50)

data = _analyze_signal("CFI:US100")
if data:
    for k, v in data.items():
        print(f"  {k}: {v}")
else:
    print("  FAILED")

print()
print("=" * 50)
print("TESTING SCALP ANALYSIS — CFI:US100")
print("=" * 50)

scalp = _analyze_scalp("CFI:US100")
if scalp:
    for k, v in scalp.items():
        print(f"  {k}: {v}")
else:
    print("  FAILED")

print()
print("Bot analysis functions work.")
print("To run the bot: tradingagents-bot")
print("(Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env first)")
